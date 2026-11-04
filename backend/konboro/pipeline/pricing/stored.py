"""Stage 7 again on a quote's stored lines, for a quote with no stage outputs to price from: the review fixture, and a
quote built by hand or in chat (S23).

The lines come back as stage 7's drafts, priced as stored, and go through what a drawing's quote goes through after a
review action (`edits.py`): the estimator's edits, the dismissed findings, a price set on the line, the colour (07
§7.5), pricing's findings (07 §8) and the totals. `reprice` names the lines whose price comes from the list again;
every other line keeps its own (07 §7.2.3). Derived items stay as stored: there are no components to count.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.domain import totals as t
from konboro.services import quotes as qs

from . import load
from .book import Book
from .edits import Kept, apply_all, price_line, stored_reasons
from .engine import PricedPanel, attach, figures, line_findings, override
from .lines import Draft
from .status import finalize


def key_of(row: m.QuoteLine) -> str:
    return row.line_key or row.id


def draft_of(row: m.QuoteLine, keys: dict[str, str]) -> Draft:
    """`keys`: line id → key, for the parent."""
    return Draft(
        key=key_of(row),
        panel_id=row.panel_id,
        line_type=row.line_type,
        description=row.description,
        qty=row.qty,
        priced=load.priced_as_stored(row),
        line_group=row.line_group,
        component_id=row.component_id,
        signature=row.signature,
        brand_context=row.brand_context,
        parent=keys.get(row.parent_line_id or ""),
        product_id=row.product_id,
        catalog_item_id=row.catalog_item_id,
        sku=row.sku,
        manufacturer=row.manufacturer,
        unit=row.unit,
        derived=row.derived,
        explanation=row.explanation,
        alternatives=list(row.alternatives),
        reasons=stored_reasons(row.status_reasons),
        issue_ids=list(row.issue_ids),
        override=row.override,
        boxes=list(row.boxes),
        query_failed=any(r.get("source") == "match" and r.get("value") == "unmatched" for r in row.status_reasons)
        and row.line_type in ("derived", "labor"),
    )


def book_for(
    session: Session,
    version: m.QuoteVersion,
    quote: m.Quote,
    rows: Sequence[m.QuoteLine],
    also: Iterable[str] = (),
) -> Book:
    """The products the lines point at, by id or SKU, and the alternatives chosen on them; `also`: more products,
    by id."""
    skus = {r.sku for r in rows if r.sku}
    picked = set(also)
    for r in rows:
        for edit in ("replaced", "match"):
            x = (r.edits or {}).get(edit) or {}
            if x.get("sku"):
                skus.add(str(x["sku"]))
            if x.get("product_id"):
                picked.add(str(x["product_id"]))
    items = load.catalog_items_by_sku(session, skus)
    found = load.products(
        session, version.tenant_id, items, skus, {r.product_id for r in rows if r.product_id} | picked
    )
    on = version.quote_date or date.today()
    return load.book_of(session, version.tenant_id, on, quote.customer_id, items, found)[0]


def reprice(session: Session, quote: m.Quote, version: m.QuoteVersion, fresh: frozenset[str]) -> None:
    """`fresh`: the keys of the lines priced from the list again."""
    tid = version.tenant_id
    rows = list(
        session.scalars(
            select(m.QuoteLine)
            .where(
                m.QuoteLine.tenant_id == tid,
                m.QuoteLine.quote_version_id == version.id,
                m.QuoteLine.deleted_at.is_(None),
            )
            .order_by(m.QuoteLine.position)
        )
    )
    book = book_for(session, version, quote, rows)
    keys = {r.id: key_of(r) for r in rows}
    edits = {key_of(r): e for r in rows if not (e := load.edits_of(r)).empty}
    kept: dict[str, Kept] = {}
    drafts = []
    for r in rows:
        d = draft_of(r, keys)
        if d.key in fresh:
            d = replace(d, priced=price_line(d, book, (r.edits or {}).get("supplier_id")))
        else:
            kept[d.key] = Kept(r.product_id, r.sku, d.priced)
        drafts.append(d)
    drafts = apply_all(drafts, edits, book, load.dismissed(session, version), kept)
    by_key = {key_of(r): r for r in rows}
    panels: dict[str | None, list[Draft]] = {}
    for i, d in enumerate(drafts):
        if d.override and d.override.get("unit_price") is not None and not d.included:
            d = drafts[i] = override(d, d.override)
        finalize(d)
        panels.setdefault(d.panel_id, []).append(d)
        _write_back(by_key[d.key], d)
    session.flush()
    priced = [PricedPanel(pid or "", "", lines, [], t.sum_lines(figures(lines))) for pid, lines in panels.items()]
    found = line_findings(priced)
    old = _pricing_ids(session, version)
    for d in drafts:  # pricing's findings are made anew (07 §8); the others stay on the line
        d.issue_ids = [i for i in d.issue_ids if i not in old]
    attach(priced, found, version.id)
    _write_findings(session, version, quote, found, {key_of(r): r.id for r in rows})
    for d in drafts:
        by_key[d.key].issue_ids = list(dict.fromkeys(d.issue_ids))
    qs.store_totals(session, version)
    version.revision += 1
    session.flush()


def _pricing_ids(session: Session, version: m.QuoteVersion) -> set[str]:
    return set(
        session.scalars(
            select(m.Finding.id).where(
                m.Finding.tenant_id == version.tenant_id,
                m.Finding.quote_version_id == version.id,
                m.Finding.source == "pricing",
            )
        )
    )


def _write_back(row: m.QuoteLine, d: Draft) -> None:
    p = d.priced
    a = t.line_amounts(d.qty, p.unit_price, p.unit_cost)
    values: dict[str, Any] = {
        "line_type": d.line_type,  # a missing line the user resolved is a component line (09 §7.8)
        "qty": d.qty,
        "sku": d.sku,
        "description": d.description,
        "manufacturer": d.manufacturer,
        "catalog_item_id": d.catalog_item_id,
        "product_id": d.product_id,
        "unit": d.unit,
        "alternatives": d.alternatives,
        "unit_cost": p.unit_cost,
        "cost_source": p.cost_source,
        "price_status": p.price_status,
        "margin_rule": p.margin_rule,
        "unit_price_raw": p.unit_price_raw,
        "unit_price": p.unit_price,
        "rounding": p.rounding,
        "line_cost": a.line_cost,
        "line_total": a.line_total,
        "margin_pct": a.margin_pct,
        "status": d.status,
        "status_reasons": d.status_reasons,
    }
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)


def _write_findings(
    session: Session, version: m.QuoteVersion, quote: m.Quote, found: Sequence[Any], ids: dict[str, str]
) -> None:
    session.execute(
        delete(m.Finding).where(
            m.Finding.tenant_id == version.tenant_id,
            m.Finding.quote_version_id == version.id,
            m.Finding.source == "pricing",
        )
    )
    for f in found:
        session.add(
            m.Finding(
                id=f.finding_id(version.id),
                tenant_id=version.tenant_id,
                quote_version_id=version.id,
                drawing_id=quote.drawing_id,
                source="pricing",
                rule_id=f.code,
                severity=f.severity,
                code=f.code,
                panel_id=f.panel_id or None,
                component_ids=list(f.component_ids),
                line_ids=[ids[k] for k in f.line_keys if k in ids],
                message=f.message,
                values={**f.values, "title": f.title},
            )
        )
    session.flush()
