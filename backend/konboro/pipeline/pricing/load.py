"""What stage 7 reads from the database, as the engine's dataclasses (`book.py`, `derived.py`, `engine.py`).

Runs inside `tenant_session`, so RLS limits every tenant row to the tenant; the explicit `tenant_id` filters are a
second guard (07 §12: one factory's prices never serve another, not even as a default). The master catalog is global
and read-only, and holds no factory price.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain.pricing.rounding import mode
from konboro.pipeline.matching import text
from konboro.services import price_list as pl

from .book import Book, Item, Priced, Product, sku_key
from .derived import DerivedRule, Labor, Requirement, starter_pack
from .engine import Carry
from .lines import Draft

DERIVED_FAMILIES = ("enclosure", "din_rail", "busbar", "terminal", "label")


# --- derived rules --------------------------------------------------------------------------------------------------


def ensure_rules(session: Session, tenant_id: str) -> None:
    """A tenant with no derived rules gets a copy of the starter pack (07 §7.4, db-schema §6.2). A tenant that has
    rows keeps them as they are: a rule it turned off or tuned stays so."""
    have = session.scalar(select(m.DerivedItemRule.id).where(m.DerivedItemRule.tenant_id == tenant_id).limit(1))
    if have is not None:
        return
    version, rules = starter_pack()
    for r in rules:
        session.execute(
            insert(m.DerivedItemRule)
            .values(
                id=new_id("dr"),
                tenant_id=tenant_id,
                rule_key=r["key"],
                scope=r["scope"],
                trigger={},
                quantity_formula=r["kind"],
                item=r["item"],
                params=r["params"],
                explanation_he=r["explanation_he"],
                enabled=r["enabled"],
                version=version,
                approval=r.get("approval"),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "rule_key"])
        )
    session.flush()


def derived_rules(session: Session, tenant_id: str) -> list[DerivedRule]:
    rows = session.scalars(
        select(m.DerivedItemRule).where(m.DerivedItemRule.tenant_id == tenant_id).order_by(m.DerivedItemRule.rule_key)
    )
    return [
        DerivedRule(
            id=r.id,
            key=r.rule_key,
            kind=r.quantity_formula,
            explanation_he=r.explanation_he,
            scope=r.scope,
            item=r.item,
            params=r.params,
            enabled=r.enabled,
            version=r.version,
        )
        for r in rows
    ]


def rules_version(rules: Sequence[DerivedRule], tenant_id: str) -> str:
    on = sorted(f"{r.key}@{r.version}" for r in rules if r.enabled)
    return f"{tenant_id}-dr-" + ",".join(on)


def labor(settings: m.TenantSettings | None) -> Labor | None:
    raw = settings.labor if settings else {}
    rate = raw.get("hourly_rate")
    if rate in (None, "", 0, "0"):
        return None
    return Labor(Decimal(str(rate)), {k: Decimal(str(v)) for k, v in (raw.get("hours") or {}).items()})


# --- the book -------------------------------------------------------------------------------------------------------


def _n(v: Any) -> str:
    return format(Decimal(str(v)).normalize(), "f")


def describe(r: m.CatalogItem) -> str:
    """A derived item as a factory writes it ("ארון Schneider 1200×800×300 IP55"); stage 5's wording for the rest."""
    a = r.attributes
    if r.family == "enclosure":
        size = "×".join(_n(a[k]) for k in ("height_mm", "width_mm", "depth_mm") if a.get(k) is not None)
        parts = ["ארון", r.brand, size, a.get("ip") or "", f"{_n(a['modules'])} מודולים" if a.get("modules") else ""]
        return " ".join(p for p in parts if p)
    if r.family == "din_rail":
        return f"מסילת DIN ‏{_n(a['length_mm'])} מ״מ" if a.get("length_mm") else "מסילת DIN"
    if r.family == "busbar":
        return f"פס צבירה {_n(a['current_a'])}A" if a.get("current_a") else "פס צבירה"
    if r.family == "terminal":
        return f"מהדק {r.brand} {_n(a['cross_section_mm2'])} ממ״ר" if a.get("cross_section_mm2") else "מהדק"
    if r.family == "label":
        return "שלט חרוט"
    return text.describe(r.family, r.symbol_class, r.brand, r.model_code, a)


def item_of(r: m.CatalogItem) -> Item:
    return Item(
        id=r.id,
        sku=r.sku,
        brand=r.brand,
        family=r.family,
        description=describe(r),
        series=r.series,
        attributes=r.attributes,
        module_width=r.module_width,
        list_price=r.list_price,
        list_currency=r.list_currency,
    )


def catalog_items(session: Session, matching: MatchingResult, families: Iterable[str]) -> list[Item]:
    """The items stage 5 chose (and their kits' parts), and every item of the derived items' families."""
    wanted: set[tuple[str, str]] = set()
    for x in matching.matches:
        if x.catalog_item is not None:
            wanted.add(((x.catalog_item.manufacturer or ""), x.catalog_item.sku))
        wanted |= {((b.manufacturer or ""), b.sku) for b in x.bundle_lines}
    skus = {sku for _, sku in wanted}
    rows = session.scalars(
        select(m.CatalogItem).where(or_(m.CatalogItem.sku.in_(skus), m.CatalogItem.family.in_(list(families))))
    )
    return [item_of(r) for r in rows if r.family in families or (r.brand, r.sku) in wanted]


def products(session: Session, tenant_id: str, items: Sequence[Item], skus: set[str]) -> list[Product]:
    item_ids = [i.id for i in items]
    keys = {sku_key(s) for s in skus} | {sku_key(i.sku) for i in items}
    rows = list(
        session.scalars(
            select(m.Product).where(
                m.Product.tenant_id == tenant_id,
                or_(
                    m.Product.catalog_item_id.in_(item_ids),
                    m.Product.manufacturer_sku.is_not(None),
                    m.Product.family.in_(DERIVED_FAMILIES),
                ),
            )
        )
    )
    rows = [
        p
        for p in rows
        if p.catalog_item_id in item_ids
        or (p.manufacturer_sku and sku_key(p.manufacturer_sku) in keys)
        or (p.family in DERIVED_FAMILIES and not p.catalog_item_id)
    ]
    loaded = pl.load(session, tenant_id, rows)
    by_item = {i.id: i for i in items}
    out = []
    for p in rows:
        costs = pl.product_costs(p, loaded.rows[p.id], loaded.names, loaded.items.get(p.catalog_item_id or ""))
        item = by_item.get(p.catalog_item_id or "")
        out.append(
            Product(
                product_id=p.id,
                name=p.display_name,
                family=p.family,
                brand=p.brand,
                manufacturer_sku=p.manufacturer_sku or (item.sku if item else None),
                catalog_item_id=p.catalog_item_id,
                unit=p.unit,
                sale_mode=p.sale_mode,
                fixed_price=p.fixed_price,
                includes={str(k): bool(v) for k, v in (p.includes or {}).items()},
                consumable=p.consumable,
                suppliers=costs.suppliers,
                list_price=costs.list_price,
                list_currency=costs.list_currency,
            )
        )
    return out


def book(
    session: Session, tenant_id: str, on_date: date, matching: MatchingResult, customer_id: str | None
) -> tuple[Book, list[str]]:
    """The book, and the ids of the price-list rows it holds (for the version's snapshot, 07 §7.7)."""
    ctx = pl.load_context(session, tenant_id, on_date)
    settings = session.get(m.TenantSettings, tenant_id)
    items = catalog_items(session, matching, DERIVED_FAMILIES)
    skus = {x.chosen_sku for x in matching.matches if x.chosen_sku} | {
        b.sku for x in matching.matches for b in x.bundle_lines
    }
    found = products(session, tenant_id, items, skus)
    return (
        Book(
            cost=ctx.cost,
            products=found,
            rules=ctx.rules,
            customer_id=customer_id,
            rounding=mode(settings.rounding if settings else None),
            min_line_margin=settings.min_line_margin if settings else None,
            min_quote_margin=settings.min_quote_margin if settings else None,
            items=items,
        ),
        sorted(s.id for p in found for s in p.suppliers),
    )


# --- the drawing ----------------------------------------------------------------------------------------------------


def requirements(intake: IntakeResult) -> dict[str | None, Requirement]:
    """01 §5.5–5.5.1: a panel's notes block (key: the panel), and the drawing's data page (key None)."""
    page_no = {p.page_id: p.page_no for p in intake.pages}
    out: dict[str | None, Requirement] = {}
    for a in intake.context_artifacts:
        if a.kind not in ("technical_data", "notes_block") or a.format != "json":
            continue
        try:
            content = json.loads(a.content)
        except ValueError:
            continue
        key = content.get("panel_id") if a.kind == "notes_block" else None
        if a.kind == "notes_block" and key is None:
            continue
        where = (
            "הערות הלוח"
            if a.kind == "notes_block"
            else f"עמוד הנתונים (עמ׳ {page_no[a.page_id]})"
            if a.page_id in page_no
            else "עמוד הנתונים"
        )
        enc = content.get("enclosure") or {}

        def n(v: Any) -> float | None:
            return float(v) if isinstance(v, int | float) and v > 0 else None

        out[key] = Requirement(
            source=where,
            height_mm=n(enc.get("height_mm")),
            width_mm=n(enc.get("width_mm")),
            depth_mm=n(enc.get("depth_mm")),
            ip=enc.get("ip") or None,
            spare_pct=n(content.get("spare_space_pct")),
            services=tuple(str(s) for s in content.get("required_services") or ()),
        )
    return out


# --- what the user did on the draft ---------------------------------------------------------------------------------


def priced_as_stored(ln: m.QuoteLine) -> Priced:
    status = ln.price_status or ("ok" if ln.unit_price is not None else "missing")
    return Priced(ln.unit_cost, ln.cost_source, status, ln.margin_rule, ln.unit_price_raw, ln.unit_price, ln.rounding)


def carry(session: Session, version: m.QuoteVersion | None) -> Carry:
    """S22 decision 5: what a rerun keeps from the draft it replaces."""
    if version is None:
        return Carry()
    rows = list(
        session.scalars(
            select(m.QuoteLine).where(
                m.QuoteLine.tenant_id == version.tenant_id, m.QuoteLine.quote_version_id == version.id
            )
        )
    )
    deleted = frozenset(r.line_key for r in rows if r.deleted_at is not None and r.line_key) | frozenset(
        (version.snapshot or {}).get("deleted_line_keys", ())
    )
    overrides = {r.line_key: r.override for r in rows if r.override and r.line_key and r.deleted_at is None}
    manual = [
        Draft(
            key=r.line_key or f"u:{r.id}",
            panel_id=r.panel_id,
            line_type="manual",
            description=r.description,
            qty=r.qty,
            priced=priced_as_stored(r),
            line_group=r.line_group,
            product_id=r.product_id,
            catalog_item_id=r.catalog_item_id,
            sku=r.sku,
            manufacturer=r.manufacturer,
            unit=r.unit,
            explanation=r.explanation,
        )
        for r in rows
        if r.line_type == "manual" and r.deleted_at is None
    ]
    return Carry(deleted, overrides, manual)
