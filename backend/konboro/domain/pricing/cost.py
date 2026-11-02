"""Which cost enters a quote (07 §7.2, §7.2.2).

1. A supplier price in force on the quote date, in this order (07 §7.2.2):
   the supplier chosen on this line, the product's preferred supplier, the factory's preferred supplier for the
   product's family, then for its brand (family first, S18 decision 3), then the lowest cost in force.
2. The manufacturer's list price less the factory's brand discount (`discount_based`).
3. None: `missing`, the line is red with no price.

"In force" means not past `valid_until` (S18 decision 2): an expired price is skipped at every step, and a supplier
chosen on the line whose price expired falls through to the next step. `price_date` only ages a price: older than
`stale_days` on the quote date is `stale` (yellow at most), manual entries too (10 §8).

A manual entry (`manual_entry`) is superseded by a supplier price-list row of the same product with a later
`price_date` (07 §7.2, S18 decision 7).

A price is looked up for the identical product only (07 §7.2): a product's own rows, never a neighbouring rating's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from . import ONE, ZERO, money
from .fx import FxRate, FxRateMissing, convert

PriceStatus = Literal["ok", "stale", "discount_based", "missing"]
# Which step of 07 §7.2.2's order chose the supplier, for the trace.
Via = Literal["line", "product_preferred", "family_preferred", "brand_preferred", "cheapest"]


@dataclass(frozen=True)
class SupplierPrice:
    id: str
    supplier_id: str | None  # null for a cost typed in a quote with no supplier
    unit_cost: Decimal
    currency: str
    price_date: date
    valid_until: date | None = None
    preferred: bool = False
    source: str = "supplier_price_list"
    supplier_name: str | None = None


@dataclass(frozen=True)
class ProductCosts:
    """One price-list product and what its cost can come from."""

    product_id: str
    family: str
    brand: str | None
    suppliers: Sequence[SupplierPrice] = ()
    list_price: Decimal | None = None  # the master catalog's manufacturer list price
    list_currency: str | None = None


@dataclass(frozen=True)
class CostContext:
    on_date: date
    stale_days: int = 90
    currency: str = "ILS"
    brand_discounts: Mapping[str, Decimal] = field(default_factory=dict)
    # ("family", "mcb") or ("brand", "ABB") -> supplier id
    supplier_preferences: Mapping[tuple[str, str], str] = field(default_factory=dict)
    fx_rates: Sequence[FxRate] = ()


@dataclass(frozen=True)
class Cost:
    unit_cost: Decimal | None
    price_status: PriceStatus
    source: dict[str, object] | None  # 07 §6.2 `cost_source`, amounts as strings
    issue: Literal["missing_cost", "fx_rate_missing"] | None = None


def in_force(price: SupplierPrice, on_date: date) -> bool:
    return price.valid_until is None or price.valid_until >= on_date


def candidates(product: ProductCosts, on_date: date) -> list[SupplierPrice]:
    """The prices in force, without manual entries a later supplier price list replaced."""
    live = [p for p in product.suppliers if in_force(p, on_date)]
    listed = [p.price_date for p in live if p.source == "supplier_price_list"]
    newest_list = max(listed, default=None)
    return [
        p for p in live if not (p.source == "manual_entry" and newest_list is not None and newest_list > p.price_date)
    ]


def choose(product: ProductCosts, ctx: CostContext, line_supplier_id: str | None) -> tuple[SupplierPrice, Via] | None:
    """Steps 1–3 of 07 §7.2.2 by supplier; step 4 (cheapest) needs the converted costs, so it is `unit_cost`'s."""
    live = candidates(product, ctx.on_date)
    by_supplier = {p.supplier_id: p for p in live if p.supplier_id is not None}
    if line_supplier_id is not None and line_supplier_id in by_supplier:
        return by_supplier[line_supplier_id], "line"
    preferred = next((p for p in live if p.preferred), None)
    if preferred is not None:
        return preferred, "product_preferred"
    for scope, key in (("family", product.family), ("brand", product.brand)):
        supplier_id = ctx.supplier_preferences.get((scope, key)) if key else None
        if supplier_id in by_supplier:
            return by_supplier[supplier_id], "family_preferred" if scope == "family" else "brand_preferred"
    return None


def status(price: SupplierPrice, ctx: CostContext) -> PriceStatus:
    return "stale" if (ctx.on_date - price.price_date).days > ctx.stale_days else "ok"


def supplier_cost(price: SupplierPrice, via: Via, ctx: CostContext) -> Cost:
    converted = convert(price.unit_cost, price.currency, ctx.currency, ctx.fx_rates, ctx.on_date)
    source: dict[str, object] = {
        "type": price.source,
        "supplier_price_id": price.id,
        "supplier_id": price.supplier_id,
        "supplier": price.supplier_name,
        "price_date": price.price_date.isoformat(),
        "via": via,
    }
    if converted.original_currency is not None:
        source |= fx_trace(converted.original_currency, converted.original_amount, converted.fx_rate, converted.fx_date)
    return Cost(converted.amount, status(price, ctx), source)


def fx_trace(currency: str, amount: object, rate: object, rate_date: date | None) -> dict[str, object]:
    return {
        "original_currency": currency,
        "original_cost": str(amount),
        "fx_rate": str(rate),
        "fx_date": rate_date.isoformat() if rate_date else None,
    }


def cheapest(product: ProductCosts, ctx: CostContext) -> Cost | None:
    """Step 4: the lowest cost in force, compared in the quote's currency. A price whose rate is missing can't be
    compared and is left out; if every price lacks one, the line has no price."""
    priced: list[tuple[Decimal, int, str, Cost]] = []
    missing_fx = False
    for price in candidates(product, ctx.on_date):
        try:
            cost = supplier_cost(price, "cheapest", ctx)
        except FxRateMissing:
            missing_fx = True
            continue
        # ties: the newest price, then the row id, so the same price list always gives the same quote (07 §10.1)
        priced.append((cost.unit_cost or ZERO, -price.price_date.toordinal(), price.id, cost))
    if priced:
        return min(priced, key=lambda p: p[:3])[3]
    return no_price("fx_rate_missing") if missing_fx else None


def brand_discount(product: ProductCosts, ctx: CostContext) -> Cost | None:
    """07 §7.2 priority 2: the manufacturer's list price less the factory's discount for the brand."""
    pct = ctx.brand_discounts.get(product.brand) if product.brand else None
    if pct is None or product.list_price is None:
        return None
    discounted = money(product.list_price * (ONE - pct))
    try:
        converted = convert(discounted, product.list_currency or ctx.currency, ctx.currency, ctx.fx_rates, ctx.on_date)
    except FxRateMissing:
        return no_price("fx_rate_missing")
    source: dict[str, object] = {
        "type": "brand_discount",
        "list_price": str(product.list_price),
        "discount_pct": str(pct),
    }
    if converted.original_currency is not None:
        source |= fx_trace(converted.original_currency, converted.original_amount, converted.fx_rate, converted.fx_date)
    return Cost(converted.amount, "discount_based", source)


def no_price(issue: Literal["missing_cost", "fx_rate_missing"]) -> Cost:
    return Cost(None, "missing", {"type": "missing"}, issue)


def unit_cost(product: ProductCosts, ctx: CostContext, line_supplier_id: str | None = None) -> Cost:
    chosen = choose(product, ctx, line_supplier_id)
    if chosen is not None:
        try:
            return supplier_cost(*chosen, ctx)
        except FxRateMissing:
            return no_price("fx_rate_missing")
    found = cheapest(product, ctx) or brand_discount(product, ctx)
    return found or no_price("missing_cost")
