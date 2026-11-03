"""Pricing a drawing's quote in the database: stage 7, a rerun of stages 2–7, and a recalculation (07 §7.7).

Which version is priced:
- no quote yet: a quote and version 1, `draft`;
- the current version is a draft: it is priced again in place, and what the user did on it is carried (S22
  decision 5);
- the current version was sent: it never changes (the trigger enforces it); version N+1 is made as a draft, carrying
  what the user did on N, with `diff_from_previous` against N (07 §7.7).

The version keeps a snapshot of what priced it: the price-list rows its lines used, the margin rules and their
versions, the derived rules' version, the FX rates and the VAT rate (07 §7.7). The drawing's stage-6 findings move to
the version priced (S21 decision 1), each pointing at its lines; pricing's own are made anew for it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import (
    CostSource,
    Derived,
    Line,
    LineCounts,
    MarginRule,
    PanelTotals,
    PricingIssue,
    QuotePanel,
    QuoteVersionResult,
    Snapshot,
    StatusReason,
)
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain import totals as t
from konboro.services import quotes as qs
from konboro.services.storage import Storage

from . import load
from .diff import LineSnap, diff
from .engine import PricedQuote, QuoteInput, amounts, price_quote
from .lines import Draft

STAGE6_SOURCES = ("rule", "bom_crosscheck", "agent")


@dataclass(frozen=True)
class Outputs:
    intake: IntakeResult
    merge: MergeResult
    matching: MatchingResult
    validation: ValidationResult


@dataclass
class Priced:
    quote: m.Quote
    version: m.QuoteVersion
    priced: PricedQuote
    line_ids: dict[str, str]  # line key → line id
    snapshot: dict[str, Any]
    diff: dict[str, Any]  # against the sent version it follows, else against the draft as it was before


def today() -> date:
    return datetime.now(UTC).date()


def target(
    session: Session, tenant_id: str, drawing: m.Drawing, name: str
) -> tuple[m.Quote, m.QuoteVersion, m.QuoteVersion | None]:
    """The quote and the version to price, and the sent version it follows when there is one."""
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == tenant_id, m.Quote.drawing_id == drawing.id))
    project = session.get(m.Project, drawing.project_id) if drawing.project_id else None
    if quote is None:
        quote = m.Quote(
            id=new_id("quo"),
            tenant_id=tenant_id,
            drawing_id=drawing.id,
            project_id=project.id if project else None,
            customer_id=project.customer_id if project else None,
            name=name,
        )
        session.add(quote)
        session.flush()
    current = session.scalar(
        select(m.QuoteVersion).where(
            m.QuoteVersion.tenant_id == tenant_id,
            m.QuoteVersion.quote_id == quote.id,
            m.QuoteVersion.version == quote.current_version,
        )
    )
    if current is not None and current.status == "draft":
        return quote, current, None
    customer = session.get(m.Customer, quote.customer_id) if quote.customer_id else None
    version = m.QuoteVersion(
        id=new_id("qv"),
        tenant_id=tenant_id,
        quote_id=quote.id,
        version=current.version + 1 if current else 1,
        quote_date=today(),
        discount_pct=current.discount_pct if current else customer.discount_pct if customer else None,
    )
    session.add(version)
    session.flush()
    quote.current_version = version.version
    session.flush()
    return quote, version, current


def snapshot_of(session: Session, version: m.QuoteVersion) -> list[LineSnap]:
    rows = session.scalars(
        select(m.QuoteLine).where(
            m.QuoteLine.tenant_id == version.tenant_id,
            m.QuoteLine.quote_version_id == version.id,
            m.QuoteLine.deleted_at.is_(None),
        )
    )
    return [
        LineSnap(
            key=r.line_key or r.id,
            panel_id=r.panel_id,
            description=r.description,
            sku=r.sku,
            qty=r.qty,
            unit_price=r.unit_price,
            line_total=r.line_total,
            unit_cost=r.unit_cost,
            cost_ref=_cost_ref(r.cost_source),
            rule_ref=_rule_ref(r.margin_rule),
        )
        for r in rows
    ]


def _cost_ref(source: dict[str, Any] | None) -> str | None:
    if not source:
        return None
    return str(source.get("supplier_price_id") or source.get("type"))


def _rule_ref(rule: dict[str, Any] | None) -> str | None:
    if not rule:
        return None
    return str(rule.get("rule_id") or rule.get("kind"))


def snap_drafts(priced: PricedQuote) -> list[LineSnap]:
    return [
        LineSnap(
            key=ln.key,
            panel_id=ln.panel_id,
            description=ln.description,
            sku=ln.sku,
            qty=ln.qty,
            unit_price=ln.priced.unit_price,
            line_total=amounts(ln).line_total,
            unit_cost=ln.priced.unit_cost,
            cost_ref=_cost_ref(ln.priced.cost_source),
            rule_ref=_rule_ref(ln.priced.margin_rule),
        )
        for ln in priced.lines
    ]


def price_drawing(
    session: Session,
    tenant_id: str,
    drawing: m.Drawing,
    out: Outputs,
    name: str,
    keep: frozenset[str] | None = None,
) -> Priced:
    """`keep`, after a review action on the draft: the keys of the lines the action touched. Every other line keeps
    its stored price (07 §7.2.3), and the quote date stays."""
    quote, version, previous = target(session, tenant_id, drawing, name)
    carried = load.carry(session, previous or version, keep)
    load.ensure_rules(session, tenant_id)
    rules = load.derived_rules(session, tenant_id)
    settings = session.get(m.TenantSettings, tenant_id)
    if keep is None or version.quote_date is None:
        version.quote_date = today()
    chosen = [
        (e.replaced.manufacturer or "", e.replaced.sku) for e in carried.edits.values() if e.replaced and e.replaced.sku
    ]
    book, row_ids = load.book(session, tenant_id, version.quote_date, out.matching, quote.customer_id, chosen)
    vat = session.execute(
        select(m.VatRate.id, m.VatRate.rate)
        .where(m.VatRate.valid_from <= version.quote_date)
        .order_by(m.VatRate.valid_from.desc())
        .limit(1)
    ).first()
    inp = QuoteInput(
        tenant_id=tenant_id,
        quote_date=version.quote_date,
        panels=[(p.panel_id, p.name) for p in out.intake.panels],
        merge=out.merge,
        matching=out.matching,
        validation=out.validation,
        book=book,
        rules=rules,
        labor=load.labor(settings),
        requirements=load.requirements(out.intake),
        includes_default={k: bool(v) for k, v in (settings.enclosure_includes_default if settings else {}).items()},
        discount_pct=version.discount_pct,
        vat_rate=vat[1] if vat else Decimal(0),
        carry=carried,
        scope=version.id,
    )
    priced = price_quote(inp)
    was = previous or version
    before = snapshot_of(session, was)
    was_net = Decimal(str((was.totals or {}).get("net_total", "0")))
    line_ids = write(session, version, drawing.id, priced)
    used = {
        str(ln.priced.cost_source.get("supplier_price_id"))
        for ln in priced.lines
        if ln.priced.cost_source and ln.priced.cost_source.get("supplier_price_id")
    }
    fx = sorted(
        {
            (str(s["original_currency"]), str(s.get("fx_date")), str(s["fx_rate"]))
            for ln in priced.lines
            if (s := ln.priced.cost_source) and s.get("original_currency")
        }
    )
    snapshot = {
        "price_list_ids": sorted(i for i in row_ids if i in used),
        "products": sorted({ln.product_id for ln in priced.lines if ln.product_id}),
        "margin_rules_version": f"{tenant_id}-mr-" + ",".join(sorted(f"{r.id}@{r.version}" for r in book.rules)),
        "derived_rules_version": load.rules_version(rules, tenant_id),
        "fx_rates": [{"currency": c, "rate_date": d, "rate": r} for c, d, r in fx],
        "vat_rate_id": vat[0] if vat else None,
        "rounding": book.rounding,
        "notes": {p.panel_id: p.notes for p in priced.panels if p.notes},
        "deleted_line_keys": sorted(carried.deleted),  # carried into the versions that follow (S22 decision 5)
    }
    version.snapshot = snapshot
    sums = qs.store_totals(session, version)
    changes = diff(before, snap_drafts(priced), was.version, was_net, sums.net_total)
    if previous is not None:
        version.diff_from_previous = changes
    version.revision += 1
    session.flush()
    return Priced(quote, version, priced, line_ids, snapshot, changes)


def read_outputs(session: Session, storage: Storage, tenant_id: str, drawing_id: str) -> Outputs:
    """Stages 1, 4, 5 and 6 as they last wrote them, for a recalculation outside the pipeline (07 §7.7)."""
    keys: dict[int, str | None] = dict(
        session.execute(
            select(m.StageRun.stage, m.StageRun.output_key).where(
                m.StageRun.tenant_id == tenant_id,
                m.StageRun.drawing_id == drawing_id,
                m.StageRun.stage.in_((1, 4, 5, 6)),
            )
        ).all()
    )
    if any(not keys.get(n) for n in (1, 4, 5, 6)):
        raise LookupError(f"drawing {drawing_id} has not been through stages 1–6")

    def get(n: int, model: type[Any]) -> Any:
        return model.model_validate_json(storage.get(tenant_id, str(keys[n])))

    return Outputs(get(1, IntakeResult), get(4, MergeResult), get(5, MatchingResult), get(6, ValidationResult))


def line_in(ln: Draft) -> qs.LineIn:
    return qs.LineIn(
        key=ln.key,
        description=ln.description,
        qty=ln.qty,
        status=ln.status,
        line_type=ln.line_type,
        line_group=ln.line_group,
        parent=ln.parent,
        component_id=ln.component_id,
        product_id=ln.product_id,
        sku=ln.sku,
        manufacturer=ln.manufacturer,
        unit_cost=ln.priced.unit_cost,
        cost_source=ln.priced.cost_source,
        unit_price=ln.priced.unit_price,
        unit_price_raw=ln.priced.unit_price_raw,
        price_status=ln.priced.price_status,
        margin_rule=ln.priced.margin_rule,
        rounding=ln.priced.rounding,
        status_reasons=ln.status_reasons,
        issue_ids=ln.issue_ids,
        alternatives=ln.alternatives,
        explanation=ln.explanation,
        derived=ln.derived,
        unit=ln.unit,
        catalog_item_id=ln.catalog_item_id,
        line_key=ln.key,
        override=ln.override,
        edits=dict(ln.edits),  # applied to the draft already; the row keeps them for the next recalculation
        approved_at=ln.approved_at,
    )


def write(session: Session, version: m.QuoteVersion, drawing_id: str, priced: PricedQuote) -> dict[str, str]:
    """The version's live lines and its findings, replaced whole. A line the user deleted stays, soft-deleted: undo
    can bring it back (09 §7.11), and its key keeps the rule from making it again."""
    tid = version.tenant_id
    # a line keeps its id across a recalculation, by its key: the review screen's selection and undo name it
    reuse = {
        key: line_id
        for key, line_id in session.execute(
            select(m.QuoteLine.line_key, m.QuoteLine.id).where(
                m.QuoteLine.tenant_id == tid,
                m.QuoteLine.quote_version_id == version.id,
                m.QuoteLine.deleted_at.is_(None),
            )
        )
        if key
    }
    session.execute(
        delete(m.QuoteLine).where(
            m.QuoteLine.tenant_id == tid, m.QuoteLine.quote_version_id == version.id, m.QuoteLine.deleted_at.is_(None)
        )
    )
    ids: dict[str, str] = {}
    for p in priced.panels:
        ids |= qs.write_lines(session, version, p.panel_id, [line_in(ln) for ln in p.lines], reuse)
    by_component: dict[str, list[str]] = {}
    for p in priced.panels:
        for ln in p.lines:
            if ln.component_id and ln.parent is None:
                by_component.setdefault(ln.component_id, []).append(ids[ln.key])
    for row in session.scalars(
        select(m.Finding).where(
            m.Finding.tenant_id == tid, m.Finding.drawing_id == drawing_id, m.Finding.source.in_(STAGE6_SOURCES)
        )
    ):
        row.quote_version_id = version.id
        row.line_ids = [i for c in row.component_ids for i in by_component.get(c, [])]
    session.execute(
        delete(m.Finding).where(
            m.Finding.tenant_id == tid, m.Finding.quote_version_id == version.id, m.Finding.source == "pricing"
        )
    )
    panels = {p.panel_id for p in priced.panels}
    for f in priced.findings:
        session.add(
            m.Finding(
                id=f.finding_id(version.id),
                tenant_id=tid,
                quote_version_id=version.id,
                drawing_id=drawing_id,
                source="pricing",
                rule_id=f.code,
                severity=f.severity,
                code=f.code,
                panel_id=f.panel_id if f.panel_id in panels else None,
                component_ids=list(f.component_ids),
                line_ids=[ids[k] for k in f.line_keys if k in ids],
                message=f.message,
                values={**f.values, "title": f.title},
            )
        )
    session.flush()
    return ids


# --- the contract (07 §6) -------------------------------------------------------------------------------------------


def contract(p: Priced, drawing_id: str, trace_id: str) -> QuoteVersionResult:
    ids = p.line_ids
    panels = []
    for panel in p.priced.panels:
        lines = []
        for ln in panel.lines:
            a = amounts(ln)
            pr = ln.priced
            lines.append(
                Line(
                    line_id=ids[ln.key],
                    line_type=ln.line_type,  # type: ignore[arg-type]  # one of 07 §6.2's
                    component_id=ln.component_id,
                    sku=ln.sku,
                    description=ln.description,
                    manufacturer=ln.manufacturer,
                    qty=ln.qty,
                    unit_cost=pr.unit_cost,
                    cost_source=_cost_source(pr.cost_source),
                    price_status=pr.price_status,  # type: ignore[arg-type]
                    margin_rule=_margin_rule(pr.margin_rule),
                    unit_price_raw=pr.unit_price_raw,
                    unit_price=pr.unit_price,
                    rounding=pr.rounding,
                    line_cost=a.line_cost,
                    line_total=a.line_total,
                    margin_pct=a.margin_pct,
                    parent_line_id=ids.get(ln.parent) if ln.parent else None,
                    is_derived=ln.line_type in ("derived", "labor"),
                    derived=Derived.model_validate(ln.derived) if ln.derived else None,
                    status=ln.status,  # type: ignore[arg-type]
                    status_reasons=[StatusReason.model_validate(r) for r in ln.status_reasons],
                    issue_ids=ln.issue_ids,
                    override=ln.override,
                )
            )
        s = panel.sums
        panels.append(
            QuotePanel(
                panel_id=panel.panel_id,
                name=panel.name,
                lines=lines,
                totals=PanelTotals(
                    cost_total=s.cost_total,
                    price_total=s.price_total,
                    line_counts=LineCounts(**s.line_counts),
                    unpriced_count=s.unpriced_count,
                ),
            )
        )
    v = p.version
    return QuoteVersionResult(
        quote_id=p.quote.id,
        version=v.version,
        status=v.status,  # type: ignore[arg-type]
        drawing_id=drawing_id,
        tenant_id=v.tenant_id,
        customer_id=p.quote.customer_id,
        currency=v.currency,
        quote_date=v.quote_date,
        panels=panels,
        totals=qs.totals_contract(
            t.quote_sums(t.merge(x.sums for x in p.priced.panels), v.discount_pct, p.priced.totals.vat_rate)
        ),
        pricing_issues=[
            PricingIssue(code=f.code, line_id=ids.get(f.line_keys[0]) if f.line_keys else None, message=f.message)
            for f in p.priced.findings
        ],
        snapshot=Snapshot(
            price_list_ids=p.snapshot["price_list_ids"],
            margin_rules_version=p.snapshot["margin_rules_version"],
            derived_rules_version=p.snapshot["derived_rules_version"],
            fx_rates=p.snapshot["fx_rates"],
            vat_rate_id=p.snapshot["vat_rate_id"],
        ),
        trace_id=trace_id,
    )


def _cost_source(source: dict[str, Any] | None) -> CostSource | None:
    if not source:
        return None
    s = dict(source)
    s["price_list_id"] = s.pop("supplier_price_id", None)
    return CostSource.model_validate(s)


def _margin_rule(rule: dict[str, Any] | None) -> MarginRule | None:
    """A rule or a fixed price; an override and an included kit part have none (`override`, the line's price)."""
    if not rule or rule.get("kind") not in ("markup", "margin", "fixed"):
        return None
    return MarginRule(
        rule_id=str(rule["rule_id"]),
        level=str(rule["level"]),
        kind=rule["kind"],
        value=rule.get("value"),
        fixed_price=rule.get("fixed_price"),
    )
