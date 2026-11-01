"""Quote lines in and out: the write path stage 7 uses (S22, and the S09 fixture), and the review screen's read model.

Runs inside `tenant_session`, so RLS already limits every query to the tenant. The explicit `tenant_id` filters are
a second guard and let Postgres use the `(tenant_id, …)` indexes.

- Writing: the caller decides prices and colors (stage 7 alone sets `status`, 00 §6.3). This module only stores
  them, works out each line's amounts and the version's totals (07 §7.6), and keeps them in `quote_versions.totals`.
- Reading: lines come back in the review screen's order (09 §6.3), and totals are summed again from the live lines,
  so a soft-deleted line never counts. The screen shows these numbers and computes none of its own (09 principle 7).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from konboro.contracts.pricing import Discount, LineCounts, QuoteTotals
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain import totals as t
from konboro.services.storage import drawing_key

# 09 §6.3: component lines by group (db-schema `line_group`), then missing lines, then accessories and labor.
GROUP_ORDER = ("feed", "outputs", "control", "enclosure")
SECTIONS = {"component": "items", "manual": "items", "missing": "missing", "derived": "extras", "labor": "extras"}
SECTION_ORDER = ("items", "missing", "extras")
SEVERITY_ORDER = ("error", "warning", "info")


# --- write ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineIn:
    """One line as stage 7 decided it. `key` is the caller's handle, so a child line can name its parent."""

    key: str
    description: str
    qty: Decimal
    status: str
    line_type: str = "component"
    line_group: str | None = None
    parent: str | None = None
    component_id: str | None = None
    product_id: str | None = None
    sku: str | None = None
    manufacturer: str | None = None
    unit_cost: Decimal | None = None
    cost_source: dict[str, Any] | None = None
    unit_price: Decimal | None = None
    price_status: str | None = None
    margin_rule: dict[str, Any] | None = None
    rounding: str | None = None
    status_reasons: list[dict[str, Any]] = field(default_factory=list)
    issue_ids: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    explanation: str | None = None
    derived: dict[str, Any] | None = None


def write_lines(
    session: Session, version: m.QuoteVersion, panel_id: str | None, lines: Sequence[LineIn]
) -> dict[str, str]:
    """Appends the lines to a draft version, in order. Returns `key → line_id`."""
    start = session.scalar(
        select(m.QuoteLine.position)
        .where(m.QuoteLine.tenant_id == version.tenant_id, m.QuoteLine.quote_version_id == version.id)
        .order_by(m.QuoteLine.position.desc())
        .limit(1)
    )
    ids: dict[str, str] = {}
    for position, line in enumerate(lines, start=(start or 0) + 1):
        ids[line.key] = new_id("ln")
        amounts = t.line_amounts(line.qty, line.unit_price, line.unit_cost)
        session.add(
            m.QuoteLine(
                id=ids[line.key],
                tenant_id=version.tenant_id,
                quote_version_id=version.id,
                panel_id=panel_id,
                position=position,
                line_group=line.line_group,
                line_type=line.line_type,
                component_id=line.component_id,
                parent_line_id=ids[line.parent] if line.parent else None,
                product_id=line.product_id,
                sku=line.sku,
                description=line.description,
                manufacturer=line.manufacturer,
                qty=line.qty,
                unit_cost=line.unit_cost,
                cost_source=line.cost_source,
                price_status=line.price_status,
                margin_rule=line.margin_rule,
                unit_price_raw=line.unit_price,
                unit_price=line.unit_price,
                rounding=line.rounding,
                line_cost=amounts.line_cost,
                line_total=amounts.line_total,
                margin_pct=amounts.margin_pct,
                derived=line.derived,
                alternatives=line.alternatives,
                explanation=line.explanation,
                status=line.status,
                status_reasons=line.status_reasons,
                issue_ids=line.issue_ids,
            )
        )
        session.flush()  # a child line's foreign key needs its parent's row
    return ids


def vat_rate_on(session: Session, day: date) -> Decimal:
    rate = session.scalar(
        select(m.VatRate.rate).where(m.VatRate.valid_from <= day).order_by(m.VatRate.valid_from.desc()).limit(1)
    )
    return rate if rate is not None else t.ZERO


def store_totals(session: Session, version: m.QuoteVersion) -> t.QuoteSums:
    """Sums the version's live lines into `quote_versions.totals` (07 §6.1 shape, decimal strings)."""
    vat = vat_rate_on(session, version.quote_date) if version.quote_date else t.ZERO
    sums = t.quote_sums(t.sum_lines(_figures(_live_lines(session, version))), version.discount_pct, vat)
    version.totals = totals_contract(sums).model_dump(mode="json")
    session.flush()
    return sums


def totals_contract(q: t.QuoteSums) -> QuoteTotals:
    return QuoteTotals(
        cost_total=q.sums.cost_total,
        price_total=q.sums.price_total,
        discount=Discount(pct=q.discount_pct, amount=q.discount) if q.discount_pct and q.discount else None,
        net_total=q.net_total,
        margin_abs=q.margin_abs,
        margin_pct=q.margin_pct,
        vat_rate=q.vat_rate,
        vat=q.vat,
        gross_total=q.gross_total,
        line_counts=LineCounts(**q.sums.line_counts),
        unpriced_count=q.sums.unpriced_count,
    )


# --- read ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceView:
    """Where one attribute's value came from (09 §6.4, "מאיפה כל ערך")."""

    attribute: str
    value: str | None
    source: str
    detail: str | None
    confidence: float | None


@dataclass(frozen=True)
class BoxView:
    """One instance on the drawing (04 §6.2): its page and bbox in PDF points, origin top left (00 §6.2)."""

    page_id: str
    bbox: list[float]


@dataclass(frozen=True)
class LineView:
    line_id: str
    line_type: str
    section: str
    line_group: str | None
    parent_line_id: str | None
    included: bool  # a kit add-on whose price is in its parent's (05 §5.9.1)
    sku: str | None
    description: str
    manufacturer: str | None
    qty: Decimal
    unit: str
    unit_price: Decimal | None
    unit_cost: Decimal | None
    line_total: Decimal | None
    line_cost: Decimal | None
    margin_pct: Decimal | None
    unit_margin: Decimal | None  # per unit, in shekels; the screen does no money arithmetic (09 principle 7)
    price_status: str | None
    price_source: dict[str, Any] | None
    cost_source: dict[str, Any] | None
    status: str
    status_reasons: list[dict[str, Any]]
    issue_ids: list[str]
    designators: list[str]
    raw_text: list[str]
    sources: list[SourceView]
    note: str | None
    explanation: str | None
    alternatives: list[dict[str, Any]]
    derived: dict[str, Any] | None
    approved: bool
    boxes: list[BoxView]  # every instance of the line's component, for the drawing pane (09 §6.5)


@dataclass(frozen=True)
class PanelView:
    panel_id: str | None
    name: str
    lines: list[LineView]
    sums: t.Sums


@dataclass(frozen=True)
class FindingView:
    finding_id: str
    severity: str
    code: str
    title: str | None
    message: str
    line_ids: list[str]
    page_no: int | None
    page_id: str | None
    bbox: list[float] | None  # "בשרטוט" (prototype `f-show`)


def _panel_box(boxes: list[list[float]] | None) -> list[float] | None:
    """Stage 1 keeps a panel's boxes on a page as a list (`panels.bboxes`, S08); the review screen draws one, around
    them all (BUG-026)."""
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


@dataclass(frozen=True)
class PagePanelView:
    panel_id: str
    name: str
    bbox: list[float] | None  # the panel's area on the page, when the page holds more than one (09 §6.5)


@dataclass(frozen=True)
class PageView:
    """One page of the drawing for the drawing pane's strip and viewer (09 §6.5, 01 §6)."""

    page_id: str
    page_no: int
    sheet: str | None  # the page's own drawing number, when its title block has one ("E-104")
    page_kind: str | None
    page_kind_confidence: float | None
    classified_by: str | None
    route: str | None
    quality: str | None
    geometry_source: str | None
    width_pt: float | None
    height_pt: float | None
    panels: list[PagePanelView]
    thumbnail_key: str | None  # stage 1's thumbnail, once the page was read
    has_viewer: bool  # stage 2 wrote the page's pyramid
    red_count: int  # lines with an instance on the page (09 §6.5, the strip's counter)
    yellow_count: int


@dataclass(frozen=True)
class QuoteView:
    quote_id: str
    name: str
    drawing_id: str | None
    drawing_number: str | None
    input_kind: str | None
    version: int
    status: str
    revision: int
    quote_date: date | None
    currency: str
    coverage_pct: int | None  # share of lines with a price (09 §6.1, 10 §7), shown while under 100
    panels: list[PanelView]
    findings: list[FindingView]
    totals: t.QuoteSums
    pages: list[PageView]


def read_quote(session: Session, tenant_id: str, quote_id: str) -> QuoteView | None:
    """The quote's current version, or None when the tenant has no such quote (the API answers 404)."""
    row = session.execute(
        select(m.Quote, m.QuoteVersion)
        .join(
            m.QuoteVersion,
            and_(
                m.QuoteVersion.tenant_id == m.Quote.tenant_id,
                m.QuoteVersion.quote_id == m.Quote.id,
                m.QuoteVersion.version == m.Quote.current_version,
            ),
        )
        .where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id)
    ).first()
    if row is None:
        return None
    quote, version = row
    drawing = session.get(m.Drawing, quote.drawing_id) if quote.drawing_id else None
    lines = _live_lines(session, version)
    components = _by_id(session, m.Component, tenant_id, {ln.component_id for ln in lines if ln.component_id})
    panels = _by_id(session, m.Panel, tenant_id, {ln.panel_id for ln in lines if ln.panel_id})

    by_panel: dict[str | None, list[m.QuoteLine]] = {}
    for ln in lines:
        by_panel.setdefault(ln.panel_id, []).append(ln)
    panel_views = [
        PanelView(
            panel_id=pid,
            name=panels[pid].name if pid in panels else quote.name,
            lines=[_line_view(ln, components.get(ln.component_id or "")) for ln in display_order(group)],
            sums=t.sum_lines(_figures(group)),
        )
        for pid, group in sorted(by_panel.items(), key=lambda kv: min(ln.position for ln in kv[1]))
    ]
    vat = Decimal(version.totals["vat_rate"]) if "vat_rate" in version.totals else t.ZERO
    sums = t.quote_sums(t.merge(p.sums for p in panel_views), version.discount_pct, vat)
    return QuoteView(
        quote_id=quote.id,
        name=quote.name,
        drawing_id=quote.drawing_id,
        drawing_number=(drawing.title_block or {}).get("drawing_number") if drawing else None,
        input_kind=drawing.input_kind if drawing else None,
        version=version.version,
        status=version.status,
        revision=version.revision,
        quote_date=version.quote_date,
        currency=version.currency,
        coverage_pct=coverage_pct(lines),
        panels=panel_views,
        findings=_findings(session, version),
        totals=sums,
        pages=_pages(session, drawing, [ln for p in panel_views for ln in p.lines]) if drawing else [],
    )


def display_order(lines: Sequence[m.QuoteLine]) -> list[m.QuoteLine]:
    """09 §6.3 within one panel: section, then group, then pipeline position. A child line follows its parent."""

    def key(ln: m.QuoteLine) -> tuple[int, int, int]:
        section = SECTION_ORDER.index(SECTIONS[ln.line_type])
        group = GROUP_ORDER.index(ln.line_group) if ln.line_group in GROUP_ORDER else len(GROUP_ORDER)
        return section, group, ln.position

    ids = {ln.id for ln in lines}
    children: dict[str, list[m.QuoteLine]] = {}
    for ln in lines:
        if ln.parent_line_id in ids:
            children.setdefault(ln.parent_line_id or "", []).append(ln)
    out: list[m.QuoteLine] = []

    def visit(ln: m.QuoteLine) -> None:
        out.append(ln)
        for child in sorted(children.get(ln.id, []), key=lambda c: c.position):
            visit(child)

    for ln in sorted((ln for ln in lines if ln.parent_line_id not in ids), key=key):
        visit(ln)
    return out


def coverage_pct(lines: Sequence[m.QuoteLine]) -> int | None:
    """Lines with a price, out of the lines that need one (a kit add-on priced in its parent doesn't)."""
    counted = [ln for ln in lines if not _included(ln)]
    if not counted:
        return None
    share = Decimal(100 * sum(ln.unit_price is not None for ln in counted)) / len(counted)
    return int(share.quantize(Decimal(1), ROUND_HALF_UP))


def _included(ln: m.QuoteLine) -> bool:
    return ln.parent_line_id is not None and ln.unit_price is not None and ln.unit_price == t.ZERO


def _live_lines(session: Session, version: m.QuoteVersion) -> list[m.QuoteLine]:
    return list(
        session.scalars(
            select(m.QuoteLine)
            .where(
                m.QuoteLine.tenant_id == version.tenant_id,
                m.QuoteLine.quote_version_id == version.id,
                m.QuoteLine.deleted_at.is_(None),
            )
            .order_by(m.QuoteLine.position)
        )
    )


def _figures(lines: Sequence[m.QuoteLine]) -> list[t.LineFigures]:
    return [t.LineFigures(ln.status, ln.line_total, ln.line_cost) for ln in lines]


def _by_id(session: Session, model: type[Any], tenant_id: str, ids: set[str]) -> dict[str, Any]:
    if not ids:
        return {}
    rows = session.scalars(select(model).where(model.tenant_id == tenant_id, model.id.in_(ids)))
    return {r.id: r for r in rows}


# Attribute keys that are not a family attribute: the circuit's load is shown beside the tags, not as a source.
NOTE_ATTRIBUTE = "load"


def _line_view(ln: m.QuoteLine, cmp: m.Component | None) -> LineView:
    attributes: dict[str, Any] = cmp.attributes if cmp else {}
    sources = [
        SourceView(
            attribute=name,
            value=None if a.get("value") is None else str(a["value"]),
            source=a.get("source") or "missing",
            detail=a.get("detail"),
            confidence=a.get("confidence"),
        )
        for name, a in attributes.items()
        if name != NOTE_ATTRIBUTE
    ]
    note = attributes.get(NOTE_ATTRIBUTE, {}).get("value")
    return LineView(
        line_id=ln.id,
        line_type=ln.line_type,
        section=SECTIONS[ln.line_type],
        line_group=ln.line_group,
        parent_line_id=ln.parent_line_id,
        included=_included(ln),
        sku=ln.sku,
        description=ln.description,
        manufacturer=ln.manufacturer,
        qty=ln.qty,
        unit=ln.unit,
        unit_price=ln.unit_price,
        unit_cost=ln.unit_cost,
        line_total=ln.line_total,
        line_cost=ln.line_cost,
        margin_pct=ln.margin_pct,
        unit_margin=ln.unit_price - ln.unit_cost if ln.unit_price is not None and ln.unit_cost is not None else None,
        price_status=ln.price_status,
        price_source=ln.margin_rule,
        cost_source=ln.cost_source,
        status=ln.status,
        status_reasons=list(ln.status_reasons),
        issue_ids=list(ln.issue_ids),
        designators=list(cmp.designators) if cmp else [],
        raw_text=[str(x) for x in cmp.explicit_texts] if cmp else [],
        sources=sources,
        note=str(note) if note is not None else None,
        explanation=ln.explanation,
        alternatives=list(ln.alternatives),
        derived=ln.derived,
        approved=ln.approved_at is not None,
        boxes=[BoxView(i["page_id"], list(i["bbox"])) for i in (cmp.instances if cmp else []) if i.get("bbox")],
    )


def _findings(session: Session, version: m.QuoteVersion) -> list[FindingView]:
    rows = session.execute(
        select(m.Finding, m.Page.page_no)
        .outerjoin(m.Page, and_(m.Page.tenant_id == m.Finding.tenant_id, m.Page.id == m.Finding.page_id))
        .where(
            m.Finding.tenant_id == version.tenant_id,
            m.Finding.quote_version_id == version.id,
            m.Finding.status == "open",
        )
    ).all()
    # Findings written in one run share `created_at`; the code breaks the tie, so the order never depends on an id's
    # random bits (it did, between two E2E databases).
    rows = sorted(rows, key=lambda r: (SEVERITY_ORDER.index(r[0].severity), r[0].created_at, r[0].code, r[0].id))
    return [
        FindingView(
            f.id,
            f.severity,
            f.code,
            f.values.get("title"),
            f.message,
            list(f.line_ids),
            page_no,
            f.page_id,
            list(f.bbox) if f.bbox else None,
        )
        for f, page_no in rows
    ]


def _pages(session: Session, drawing: m.Drawing, lines: Sequence[LineView]) -> list[PageView]:
    pages = session.scalars(
        select(m.Page)
        .where(m.Page.tenant_id == drawing.tenant_id, m.Page.drawing_id == drawing.id)
        .order_by(m.Page.page_no)
    ).all()
    panels = session.scalars(
        select(m.Panel)
        .where(m.Panel.tenant_id == drawing.tenant_id, m.Panel.drawing_id == drawing.id)
        .order_by(m.Panel.name)
    ).all()
    counts: dict[tuple[str, str], int] = {}
    for ln in lines:
        if ln.status != "green":
            for page_id in {b.page_id for b in ln.boxes}:
                counts[page_id, ln.status] = counts.get((page_id, ln.status), 0) + 1
    return [
        PageView(
            page_id=p.id,
            page_no=p.page_no,
            sheet=(p.title_block or {}).get("drawing_number"),
            page_kind=p.page_kind,
            page_kind_confidence=p.page_kind_confidence,
            classified_by=p.classified_by,
            route=p.route,
            quality=p.quality,
            geometry_source=p.geometry_source,
            width_pt=p.width_pt,
            height_pt=p.height_pt,
            panels=[
                PagePanelView(pn.id, pn.name, _panel_box(pn.bboxes.get(p.id)))
                for pn in panels
                if p.id in (pn.page_ids or [])
            ],
            # Stage 1 points `render_key` at its thumbnail and stage 2 at the full render; the thumbnail stays.
            thumbnail_key=drawing_key(drawing.tenant_id, drawing.id, "pages", p.id, "thumb.png")
            if p.render_key
            else None,
            has_viewer=p.tiles_prefix is not None,
            red_count=counts.get((p.id, "red"), 0),
            yellow_count=counts.get((p.id, "yellow"), 0),
        )
        for p in pages
    ]
