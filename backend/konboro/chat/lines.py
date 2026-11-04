"""The open quote's lines as the chat reads them, and the filter `query_lines` and `propose_change` share (08 §6.2,
§6.7 `target`). Built from the review screen's own view (`services.quotes.read_quote`), so the chat and the screen
never disagree about a line; the family comes from the line's component or catalog item.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.services import quotes
from konboro_llm.stages.chat_command import LineFilter

from .state import ChatState

NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ChatLine:
    line_id: str
    key: str  # stage 7's line key, the same in version N+1 (a sent version's lines get new ids there)
    panel_id: str | None
    panel_name: str
    line_type: str
    family: str | None
    description: str
    sku: str | None
    manufacturer: str | None
    qty: Decimal
    status: str
    approved: bool
    parent_line_id: str | None
    issue_ids: tuple[str, ...]
    sources: tuple[quotes.SourceView, ...]
    unit_price: Decimal | None
    line_total: Decimal | None
    unit_cost: Decimal | None
    margin_pct: Decimal | None
    removed: bool = False
    view: quotes.LineView | None = field(default=None, compare=False, repr=False)

    def attribute(self, name: str) -> str | None:
        found = next((s for s in self.sources if s.attribute == name), None)
        return found.value if found else None


@dataclass
class QuoteLines:
    view: quotes.QuoteView
    lines: list[ChatLine]  # live, in screen order
    removed: list[ChatLine]  # derived lines the estimator removed (09 §6.3), for `restore_derived`

    def by_id(self, line_id: str) -> ChatLine | None:
        return next((ln for ln in [*self.lines, *self.removed] if ln.line_id == line_id), None)

    def panels(self) -> list[tuple[str | None, str]]:
        return [(p.panel_id, p.name) for p in self.view.panels]


def _families(session: Session, tenant_id: str, rows: Iterable[m.QuoteLine]) -> dict[str, str | None]:
    rows = list(rows)
    cmp_ids = {r.component_id for r in rows if r.component_id}
    item_ids = {r.catalog_item_id for r in rows if r.catalog_item_id}
    cmps: dict[str, str | None] = (
        {
            i: f
            for i, f in session.execute(
                select(m.Component.id, m.Component.family).where(
                    m.Component.tenant_id == tenant_id, m.Component.id.in_(cmp_ids)
                )
            )
        }
        if cmp_ids
        else {}
    )
    items: dict[str, str | None] = (
        {
            i: f
            for i, f in session.execute(
                select(m.CatalogItem.id, m.CatalogItem.family).where(m.CatalogItem.id.in_(item_ids))
            )
        }
        if item_ids
        else {}
    )
    return {r.id: items.get(r.catalog_item_id or "") or cmps.get(r.component_id or "") for r in rows}


def load(session: Session, tenant_id: str, quote_id: str) -> QuoteLines | None:
    view = quotes.read_quote(session, tenant_id, quote_id)
    if view is None:
        return None
    version = session.scalar(
        select(m.QuoteVersion).where(
            m.QuoteVersion.tenant_id == tenant_id,
            m.QuoteVersion.quote_id == quote_id,
            m.QuoteVersion.version == view.version,
        )
    )
    assert version is not None  # noqa: S101 (read_quote found it)
    rows = list(
        session.scalars(
            select(m.QuoteLine).where(m.QuoteLine.tenant_id == tenant_id, m.QuoteLine.quote_version_id == version.id)
        )
    )
    family = _families(session, tenant_id, rows)
    keys = {r.id: r.line_key or f"pos:{r.position}" for r in rows}
    lines = [
        ChatLine(
            line_id=ln.line_id,
            key=keys[ln.line_id],
            panel_id=p.panel_id,
            panel_name=p.name,
            line_type=ln.line_type,
            family=family.get(ln.line_id),
            description=ln.description,
            sku=ln.sku,
            manufacturer=ln.manufacturer,
            qty=ln.qty,
            status=ln.status,
            approved=ln.approved,
            parent_line_id=ln.parent_line_id,
            issue_ids=tuple(ln.issue_ids),
            sources=tuple(ln.sources),
            unit_price=ln.unit_price,
            line_total=ln.line_total,
            unit_cost=ln.unit_cost,
            margin_pct=ln.margin_pct,
            view=ln,
        )
        for p in view.panels
        for ln in p.lines
    ]
    names = {p.panel_id: p.name for p in view.panels}
    removed = [
        ChatLine(
            line_id=r.id,
            key=keys[r.id],
            panel_id=r.panel_id,
            panel_name=names.get(r.panel_id, view.name),
            line_type=r.line_type,
            family=family.get(r.id),
            description=r.description,
            sku=r.sku,
            manufacturer=r.manufacturer,
            qty=r.qty,
            status=r.status,
            approved=False,
            parent_line_id=r.parent_line_id,
            issue_ids=(),
            sources=(),
            unit_price=None,
            line_total=None,
            unit_cost=None,
            margin_pct=None,
            removed=True,
        )
        for r in sorted(rows, key=lambda r: r.position)
        if r.deleted_at is not None and r.line_type in ("derived", "labor")
    ]
    return QuoteLines(view, lines, removed)


def _same_value(have: str | None, want: str) -> bool:
    if have is None:
        return False
    if have.strip().casefold() == want.strip().casefold():
        return True
    a, b = NUMBER.search(have), NUMBER.search(want)
    return a is not None and b is not None and Decimal(a.group()) == Decimal(b.group())


def matches(ln: ChatLine, f: LineFilter, state: ChatState, issue_lines: set[str]) -> bool:
    if f.lines and ln.line_id not in {state.real(a, "line") for a in f.lines}:
        return False
    if f.panels and ln.panel_id not in {state.real(a, "panel") for a in f.panels}:
        return False
    if f.families and (ln.family or "") not in set(f.families):
        return False
    if f.manufacturers and (ln.manufacturer or "").casefold() not in {x.casefold() for x in f.manufacturers}:
        return False
    if f.statuses and ln.status not in set(f.statuses):
        return False
    if f.line_types and ln.line_type not in set(f.line_types):
        return False
    if f.has_issue is not None and (ln.line_id in issue_lines or bool(ln.issue_ids)) != f.has_issue:
        return False
    if f.attribute_source and all(s.source != f.attribute_source for s in ln.sources):
        return False
    if any(not _same_value(ln.attribute(a.name), a.value) for a in f.attributes):
        return False
    if f.text:
        tags = " ".join(ln.view.designators) if ln.view else ""  # "Q0", "F22": the drawing's tags (S25b)
        hay = f"{ln.description} {ln.sku or ''} {ln.manufacturer or ''} {tags}".casefold()
        if not all(w in hay for w in f.text.casefold().split()):
            return False
    return True


def select_lines(ql: QuoteLines, f: LineFilter, state: ChatState, include_removed: bool = False) -> list[ChatLine]:
    """The lines a filter names. A kit's add-on follows its device, so it is not a target of its own unless named."""
    issue_lines = {i for fv in ql.view.findings for i in fv.line_ids}
    pool = [*ql.lines, *(ql.removed if include_removed else [])]
    named = {state.real(a, "line") for a in f.lines}
    return [
        ln for ln in pool if matches(ln, f, state, issue_lines) and (ln.parent_line_id is None or ln.line_id in named)
    ]


def as_dict(ln: ChatLine, state: ChatState, costs: bool) -> dict[str, Any]:
    """One line for the model: names and references, never an id or an amount."""
    out: dict[str, Any] = {
        "line": state.name("line", ln.line_id),
        "panel": state.name("panel", ln.panel_id) if ln.panel_id else None,
        "line_type": ln.line_type,
        "family": ln.family,
        "description": ln.description,
        "sku": ln.sku,
        "manufacturer": ln.manufacturer,
        "qty": int(ln.qty) if ln.qty == ln.qty.to_integral_value() else float(ln.qty),
        "status": ln.status,
        "approved": ln.approved,
        "attributes": {s.attribute: s.value for s in ln.sources if s.value is not None},
        "unit_price": state.ref(ln.unit_price),
        "line_total": state.ref(ln.line_total),
    }
    if ln.removed:
        out["removed"] = True
    if costs:
        out["unit_cost"] = state.ref(ln.unit_cost)
        out["margin_pct"] = state.ref(ln.margin_pct, "pct")
    if ln.parent_line_id:
        out["part_of"] = state.name("line", ln.parent_line_id)
    if ln.line_type == "missing":  # what was read on the drawing, not a catalog wording (08 §10)
        out["drawing_content"] = {"description": out.pop("description")}
    return out
