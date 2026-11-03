"""The factory's price book for one quote, and one product's price in it (07 §7.2–7.3, §7.6).

Pure: `load.py` reads the rows into these dataclasses, so the same book always gives the same quote to the agora
(07 §10.1) and the eval can price a run again with another book (S22 decision 1).

A price is looked up for the identical product only (07 §7.2): the price-list product linked to the catalog item
stage 5 chose, else the one with the same manufacturer SKU. A neighbouring rating is another product, so NURSERY-1's
3X20A stays without a price even when 3X16A and 3X25A have one.

`price_status` follows the cost only when the sale price comes from it: a fixed product price (07 §7.2.1) is a price
whatever its cost, and a missing or stale cost only leaves its margin unknown or old.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property
from typing import Any

from konboro.domain.pricing import cost as pc
from konboro.domain.pricing import margin as pm
from konboro.domain.pricing.rounding import Rounding, round_price


@dataclass(frozen=True)
class Product:
    """One price-list product (07 §7.2.1) and what its cost can come from."""

    product_id: str
    name: str
    family: str
    brand: str | None = None
    manufacturer_sku: str | None = None
    catalog_item_id: str | None = None
    unit: str = "unit"
    sale_mode: str = "rule"
    fixed_price: Decimal | None = None
    includes: Mapping[str, bool] = field(default_factory=dict)
    consumable: bool = False
    suppliers: Sequence[pc.SupplierPrice] = ()
    list_price: Decimal | None = None
    list_currency: str | None = None

    @property
    def costs(self) -> pc.ProductCosts:
        return pc.ProductCosts(
            self.product_id, self.family, self.brand, self.suppliers, self.list_price, self.list_currency
        )


@dataclass(frozen=True)
class Item:
    """A master catalog item, for the derived items' queries (07 §7.4) and the module count."""

    id: str
    sku: str
    brand: str
    family: str
    description: str
    series: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    module_width: Decimal | None = None
    list_price: Decimal | None = None
    list_currency: str | None = None


def sku_key(sku: str) -> str:
    return sku.replace(" ", "").upper()


@dataclass(frozen=True)
class Book:
    cost: pc.CostContext
    products: Sequence[Product] = ()
    rules: Sequence[pm.Rule] = ()
    customer_id: str | None = None
    rounding: Rounding = "agora"
    min_line_margin: Decimal | None = None
    min_quote_margin: Decimal | None = None
    items: Sequence[Item] = ()  # the catalog items the quote points at, and the derived items' candidates

    @cached_property
    def _by_item(self) -> dict[str, Product]:
        return {p.catalog_item_id: p for p in self.products if p.catalog_item_id}

    @cached_property
    def _by_sku(self) -> dict[str, Product]:
        return {sku_key(p.manufacturer_sku): p for p in self.products if p.manufacturer_sku}

    @cached_property
    def _items(self) -> dict[str, Item]:
        return {i.id: i for i in self.items}

    @cached_property
    def _items_by_sku(self) -> dict[tuple[str, str], Item]:
        return {(i.brand.upper(), sku_key(i.sku)): i for i in self.items}

    def product(self, catalog_item_id: str | None, sku: str | None) -> Product | None:
        if catalog_item_id and catalog_item_id in self._by_item:
            return self._by_item[catalog_item_id]
        return self._by_sku.get(sku_key(sku)) if sku else None

    def item(self, catalog_item_id: str | None) -> Item | None:
        return self._items.get(catalog_item_id) if catalog_item_id else None

    def item_by_sku(self, brand: str | None, sku: str) -> Item | None:
        return self._items_by_sku.get(((brand or "").upper(), sku_key(sku)))

    def of_family(self, family: str) -> list[Item]:
        return [i for i in self.items if i.family == family]

    def unlinked(self, family: str) -> list[Product]:
        """The factory's own products of a family with no catalog item (a label, a consumable it buys locally)."""
        return [p for p in self.products if p.family == family and not p.catalog_item_id]


@dataclass(frozen=True)
class Priced:
    """One unit's price and its trace (07 §6.2)."""

    unit_cost: Decimal | None
    cost_source: dict[str, Any] | None
    price_status: str
    margin_rule: dict[str, Any] | None
    unit_price_raw: Decimal | None
    unit_price: Decimal | None
    rounding: str | None
    issues: tuple[str, ...] = ()  # pricing issue codes (07 §8)
    floor: Decimal | None = None  # the line's margin floor, when its margin is below it


NO_PRODUCT = Priced(None, {"type": "missing"}, "missing", None, None, None, None, ("missing_cost",))
INCLUDED = Priced(None, None, "ok", {"kind": "included"}, Decimal("0"), Decimal("0.00"), None)


def price(product: Product | None, book: Book, line_supplier_id: str | None = None) -> Priced:
    if product is None:
        return NO_PRODUCT
    cost = pc.unit_cost(product.costs, book.cost, line_supplier_id)
    subject = pm.Subject(
        product.product_id,
        product.family,
        product.brand,
        product.sale_mode,  # type: ignore[arg-type]  # the database allows rule or fixed only
        product.fixed_price,
        book.customer_id,
    )
    sale = pm.sale_price(cost.unit_cost, book.rules, subject, book.cost.on_date)
    issues: tuple[str, ...] = tuple(i for i in (cost.issue, sale.issue) if i)
    if sale.unit_price_raw is None:  # no rule, or a rule and no cost to apply it to (`cost.issue` says which)
        return Priced(cost.unit_cost, cost.source, "missing", sale.rule, None, None, None, issues)
    from_cost = sale.rule is not None and sale.rule["kind"] != "fixed"
    status = cost.price_status if from_cost else "ok"
    rounded = round_price(sale.unit_price_raw, book.rounding)
    floor = pm.line_floor(rounded, cost.unit_cost, book.min_line_margin)
    if floor is not None:
        issues += ("below_margin_floor",)
    if status == "stale":
        issues += ("stale_price",)
    return Priced(
        cost.unit_cost,
        cost.source,
        status,
        sale.rule,
        sale.unit_price_raw,
        rounded,
        book.rounding,
        tuple(i for i in issues if i != "missing_cost"),
        floor.floor if floor else None,
    )
