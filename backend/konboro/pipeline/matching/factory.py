"""The factory's side of matching (05 §4.3): brand and series preferences, the customer's, attribute defaults, the
settings of 05 §5.6–5.7 and §13 item 1, the match memory (05 §11), how often each item was quoted, and, per catalog
item, whether the factory has an active cost price for it.

A cost is reduced here to a yes or no (`priced`), and kept as an amount only for the factory that breaks ties by
price (05 §12). Neither ever reaches a model: the agent sees `has_cost_price` at most, and only as part of the
ranking it is not shown.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.domain.pricing import cost as pc
from konboro.pipeline.detection.library import prefix_table
from konboro.services import price_list

from .catalog import Catalog, Item
from .config import TIE_BREAKS

ANY = "*"  # a preference for every family


@dataclass(frozen=True)
class Memory:
    customer_id: str | None
    signature: str
    brand_context: str | None
    sku: str
    approved_count: int = 0


@dataclass
class Factory:
    customer_id: str | None = None
    brand_preferences: dict[str, str] = field(default_factory=dict)  # family (or "*") → brand
    customer_brands: dict[str, str] = field(default_factory=dict)  # the customer's, the same shape (05 §5.4 item 3)
    attribute_defaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    series: dict[str, str] = field(default_factory=dict)  # family → preferred series
    alternate_brands: dict[str, list[str]] = field(default_factory=dict)  # family (or "*") → allowed instead
    tie_break: str = "frequency"
    inference_off: frozenset[str] = frozenset()
    # a designator's letters → the classes they may name, the factory's rows on top (BUG-070, BUG-077)
    designator_prefixes: dict[str, tuple[str, ...]] = field(default_factory=prefix_table)
    auxiliary_families: frozenset[str] = frozenset({"terminal"})
    priced: frozenset[str] = frozenset()  # catalog item ids with an active cost price
    costs: dict[str, Decimal] = field(default_factory=dict)  # catalog item id → unit cost, for `tie_break` = price
    usage: dict[str, int] = field(default_factory=dict)  # catalog item id → quote lines that used it
    memory: list[Memory] = field(default_factory=list)

    def has_cost(self, item: Item) -> bool:
        return item.id in self.priced

    def priced_brands(self, catalog: Catalog) -> frozenset[str]:
        return frozenset(catalog.items[i].brand for i in self.priced if i in catalog.items)

    @staticmethod
    def _pick(prefs: dict[str, Any], family: str) -> Any:
        return prefs.get(family, prefs.get(ANY))

    def preferred_brand(self, family: str) -> str | None:
        return self._pick(self.brand_preferences, family)  # type: ignore[no-any-return]

    def customer_brand(self, family: str) -> str | None:
        return self._pick(self.customer_brands, family)  # type: ignore[no-any-return]

    def alternates(self, family: str) -> list[str]:
        return list(self._pick(self.alternate_brands, family) or [])

    def recall(self, signature: str, brand_context: str | None) -> Memory | None:
        """05 §5.3: this customer's memory first, then the factory's."""
        found = [r for r in self.memory if r.signature == signature and r.brand_context == brand_context]
        mine = [r for r in found if self.customer_id and r.customer_id == self.customer_id]
        theirs = [r for r in found if r.customer_id is None]
        best = mine or theirs
        return max(best, key=lambda r: r.approved_count) if best else None


def _priced(
    session: Session, tenant_id: str, catalog: Catalog, on_date: date
) -> tuple[frozenset[str], dict[str, Decimal]]:
    """Each catalog item the factory can cost: its own product's cost (07 §7.2.2, the identical product only), or the
    manufacturer's list price less the factory's brand discount (07 §7.2 priority 2)."""
    ctx = price_list.load_context(session, tenant_id, on_date).cost
    products = list(session.scalars(select(m.Product).where(m.Product.tenant_id == tenant_id)))
    loaded = price_list.load(session, tenant_id, products)
    by_sku = {(i.brand, i.sku): i.id for i in catalog.items.values()}
    rows = {i.id: i for i in session.scalars(select(m.CatalogItem).where(m.CatalogItem.list_price.is_not(None)))}
    priced: set[str] = set()
    costs: dict[str, Decimal] = {}
    linked: set[str] = set()
    for p in products:
        item_id = p.catalog_item_id or by_sku.get((p.brand or "", p.manufacturer_sku or ""))
        if item_id is None:
            continue
        linked.add(item_id)
        found = pc.unit_cost(price_list.product_costs(p, loaded.rows[p.id], loaded.names, rows.get(item_id)), ctx)
        if found.unit_cost is not None:
            priced.add(item_id)
            costs[item_id] = min(costs.get(item_id, found.unit_cost), found.unit_cost)
    for item_id, row in rows.items():
        if item_id in linked:
            continue
        product = pc.ProductCosts(item_id, row.family, row.brand, (), row.list_price, row.list_currency)
        discounted = pc.brand_discount(product, ctx)
        if discounted is not None and discounted.unit_cost is not None:
            priced.add(item_id)
            costs[item_id] = discounted.unit_cost
    return frozenset(priced), costs


def load(
    session: Session, tenant_id: str, catalog: Catalog, customer_id: str | None, on_date: date | None = None
) -> Factory:
    settings = session.get(m.TenantSettings, tenant_id)
    customer = session.get(m.Customer, customer_id) if customer_id else None
    matching: dict[str, Any] = dict(settings.matching or {}) if settings else {}
    tie_break = matching.get("tie_break", "frequency")
    priced, costs = _priced(session, tenant_id, catalog, on_date or price_list.today(session, tenant_id))
    # The factory's habit is what it sent, not stage 7's own drafts: counting those would let the system's guesses
    # vote for themselves, and one drawing sway the next (BUG-047, S22).
    sent = select(m.QuoteVersion.id).where(m.QuoteVersion.tenant_id == tenant_id, m.QuoteVersion.status == "sent")
    usage = dict(
        session.execute(
            select(m.QuoteLine.catalog_item_id, func.count())
            .where(
                m.QuoteLine.tenant_id == tenant_id,
                m.QuoteLine.catalog_item_id.is_not(None),
                m.QuoteLine.deleted_at.is_(None),
                m.QuoteLine.quote_version_id.in_(sent),
            )
            .group_by(m.QuoteLine.catalog_item_id)
        ).all()
    )
    memory = [
        Memory(r.customer_id, r.signature, r.brand_context, r.sku, r.approved_count)
        for r in session.scalars(select(m.MatchMemory).where(m.MatchMemory.tenant_id == tenant_id))
    ]
    return Factory(
        customer_id=customer_id,
        brand_preferences=dict(settings.brand_preferences or {}) if settings else {},
        customer_brands=dict(customer.brand_preferences or {}) if customer else {},
        attribute_defaults=dict(settings.attribute_defaults or {}) if settings else {},
        series=dict(matching.get("series") or {}),
        alternate_brands={k: list(v) for k, v in (matching.get("alternate_brands") or {}).items()},
        tie_break=tie_break if tie_break in TIE_BREAKS else "frequency",
        inference_off=frozenset(matching.get("inference_off") or ()),
        designator_prefixes=prefix_table(matching.get("designator_prefixes")),
        auxiliary_families=frozenset(settings.auxiliary_families or ()) if settings else frozenset({"terminal"}),
        priced=priced,
        costs=costs,
        usage={k: int(v) for k, v in usage.items() if k},
        memory=memory,
    )
