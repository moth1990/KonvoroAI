"""The factory's price list (07 §7.2–7.3): products with their suppliers, brand discounts, margin rules and supplier
preferences, and the history of every change (07 §7.2.1 `history[]`, §12).

Runs inside `tenant_session`, so RLS already limits every query to the tenant; the explicit `tenant_id` filters are
a second guard, as in `services.quotes`. Pricing decisions are `konboro.domain.pricing`'s: this module loads rows into
its dataclasses and stores what the user changed.

- Every change writes `price_history`: the field, the value before and after (JSON, amounts as strings), who, and the
  quote it was made from, if any. A change that is not to a product names what it changed in `subject`.
- A product has at most one preferred supplier, and at most one cost with no supplier (S18 decision 7).
- A cost typed by hand (`manual_entry`) is checked against the list price, similar products and the previous cost
  (10 §8); the result is kept in `products.sanity` and returned, and never stops the save.
- A product's cost and price "today" are worked out on read, with the tenant's own rules, for the price-list screen.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.models.pricing import PRICE_SOURCES
from konboro.domain import totals
from konboro.domain.pricing import ONE, ZERO
from konboro.domain.pricing import cost as pc
from konboro.domain.pricing import margin as pm
from konboro.domain.pricing.fx import MAX_AGE_DAYS, FxRate, FxRateMissing, convert
from konboro.domain.pricing.sanity import check_cost
from konboro.services.quotes import store_totals

MAX_MONEY = Decimal("10000000000")  # numeric(14,4)
PRODUCT_FIELDS = (
    "display_name",
    "manufacturer_sku",
    "brand",
    "family",
    "unit",
    "sale_mode",
    "fixed_price",
    "includes",
    "consumable",
    "catalog_item_id",
)
SUPPLIER_FIELDS = (
    "supplier_id",
    "supplier_sku",
    "unit_cost",
    "currency",
    "lead_days",
    "price_date",
    "valid_until",
    "preferred",
    "source",
)
Filter = Literal["all", "nocost", "multi", "low"]


class PriceListError(Exception):
    """A request the price list refuses: `status` 404, 409 or 422, `code` from `api.errors.MESSAGES`, and where."""

    def __init__(self, status: int, code: str, loc: Sequence[str | int] = (), kind: str | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.details = [{"loc": ["body", *loc], "type": kind or code}] if loc else None


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    user_id: str | None


# --- input ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierPriceIn:
    """One supplier's price. `id` keeps an existing row; `supplier_name` finds or adds the supplier (09 §7.13);
    neither `supplier_id` nor `supplier_name` is a cost with no supplier."""

    unit_cost: Decimal
    price_date: date
    id: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    supplier_sku: str | None = None
    currency: str = "ILS"
    lead_days: int | None = None
    valid_until: date | None = None
    preferred: bool = False
    source: str = "supplier_price_list"


@dataclass(frozen=True)
class ProductIn:
    display_name: str
    family: str
    source: str
    manufacturer_sku: str | None = None
    brand: str | None = None
    unit: str = "unit"
    sale_mode: str = "rule"
    fixed_price: Decimal | None = None
    includes: dict[str, Any] | None = None
    consumable: bool = False
    catalog_item_id: str | None = None
    suppliers: Sequence[SupplierPriceIn] = ()


# --- output ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierPriceView:
    id: str
    supplier_id: str | None
    supplier_name: str | None
    supplier_sku: str | None
    unit_cost: Decimal
    currency: str
    lead_days: int | None
    price_date: date
    valid_until: date | None
    preferred: bool
    source: str
    in_force: bool


@dataclass(frozen=True)
class HistoryView:
    id: str
    field: str
    old: dict[str, Any] | None
    new: dict[str, Any] | None
    quote_id: str | None
    changed_by: str | None
    changed_at: datetime


@dataclass(frozen=True)
class ProductView:
    id: str
    display_name: str
    manufacturer_sku: str | None
    brand: str | None
    family: str
    unit: str
    sale_mode: str
    fixed_price: Decimal | None
    includes: dict[str, Any] | None
    consumable: bool
    source: str
    catalog_item_id: str | None
    list_price: Decimal | None
    list_currency: str | None
    entered_in_quote: str | None
    entered_by: str | None
    entered_at: datetime | None
    sanity: dict[str, Any] | None
    suppliers: list[SupplierPriceView]
    # today, by the tenant's rules (07 §7.2.2, §7.3), for a new quote with no customer
    unit_cost: Decimal | None
    price_status: str
    cost_source: dict[str, Any] | None
    unit_price: Decimal | None
    margin_rule: dict[str, Any] | None
    margin_pct: Decimal | None
    below_margin_floor: bool
    history: list[HistoryView] = field(default_factory=list)


# --- context --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """What pricing needs from the tenant and the shared layer, loaded once per request (or per quote, S22)."""

    cost: pc.CostContext
    rules: list[pm.Rule]
    min_line_margin: Decimal | None


def load_context(session: Session, tenant_id: str, on_date: date) -> Context:
    settings = session.get(m.TenantSettings, tenant_id)
    tenant = session.get_one(m.Tenant, tenant_id)
    discounts = {
        d.brand: d.discount_pct
        for d in session.scalars(select(m.BrandDiscount).where(m.BrandDiscount.tenant_id == tenant_id))
    }
    prefs = {
        (p.scope, p.key): p.supplier_id
        for p in session.scalars(select(m.SupplierPreference).where(m.SupplierPreference.tenant_id == tenant_id))
    }
    since = on_date - timedelta(days=MAX_AGE_DAYS)
    rates = [
        FxRate(r.currency, r.rate_date, r.rate)
        for r in session.scalars(select(m.FxRate).where(m.FxRate.rate_date <= on_date, m.FxRate.rate_date >= since))
    ]
    rules = [rule(r) for r in session.scalars(select(m.MarginRule).where(m.MarginRule.tenant_id == tenant_id))]
    return Context(
        pc.CostContext(
            on_date=on_date,
            stale_days=settings.stale_days if settings else 90,
            currency=tenant.currency,
            brand_discounts=discounts,
            supplier_preferences=prefs,
            fx_rates=rates,
        ),
        rules,
        settings.min_line_margin if settings else None,
    )


def rule(r: m.MarginRule) -> pm.Rule:
    return pm.Rule(
        id=r.id,
        level=r.level,  # type: ignore[arg-type]
        kind=r.kind,  # type: ignore[arg-type]
        value=r.value,
        fixed_price=r.fixed_price,
        target=r.target,
        customer_id=r.customer_id,
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        version=r.version,
    )


def subject(product: m.Product, customer_id: str | None = None) -> pm.Subject:
    return pm.Subject(
        product_id=product.id,
        family=product.family,
        brand=product.brand,
        sale_mode=product.sale_mode,  # type: ignore[arg-type]
        fixed_price=product.fixed_price,
        customer_id=customer_id,
    )


def product_costs(
    product: m.Product, rows: Sequence[m.ProductSupplier], names: dict[str, str], item: m.CatalogItem | None
) -> pc.ProductCosts:
    return pc.ProductCosts(
        product_id=product.id,
        family=product.family,
        brand=product.brand,
        suppliers=[
            pc.SupplierPrice(
                id=r.id,
                supplier_id=r.supplier_id,
                unit_cost=r.unit_cost,
                currency=r.currency,
                price_date=r.price_date,
                valid_until=r.valid_until,
                preferred=r.preferred,
                source=r.source,
                supplier_name=names.get(r.supplier_id) if r.supplier_id else None,
            )
            for r in rows
        ],
        list_price=item.list_price if item else None,
        list_currency=item.list_currency if item else None,
    )


# --- read -----------------------------------------------------------------------------------------------------------


@dataclass
class Loaded:
    """Products with their supplier rows, the tenant's supplier names and the linked catalog items."""

    products: list[m.Product]
    rows: dict[str, list[m.ProductSupplier]]
    names: dict[str, str]
    items: dict[str, m.CatalogItem]


def load(session: Session, tenant_id: str, products: list[m.Product]) -> Loaded:
    ids = [p.id for p in products]
    rows: dict[str, list[m.ProductSupplier]] = {i: [] for i in ids}
    if ids:
        for r in session.scalars(
            select(m.ProductSupplier)
            .where(m.ProductSupplier.tenant_id == tenant_id, m.ProductSupplier.product_id.in_(ids))
            .order_by(m.ProductSupplier.preferred.desc(), m.ProductSupplier.unit_cost, m.ProductSupplier.id)
        ):
            rows[r.product_id].append(r)
    names = dict(session.execute(select(m.Supplier.id, m.Supplier.name).where(m.Supplier.tenant_id == tenant_id)).all())
    item_ids = {p.catalog_item_id for p in products if p.catalog_item_id}
    items = (
        {i.id: i for i in session.scalars(select(m.CatalogItem).where(m.CatalogItem.id.in_(item_ids)))}
        if item_ids
        else {}
    )
    return Loaded(products, rows, names, items)


def view(loaded: Loaded, product: m.Product, ctx: Context, history: Sequence[HistoryView] = ()) -> ProductView:
    rows = loaded.rows.get(product.id, [])
    item = loaded.items.get(product.catalog_item_id) if product.catalog_item_id else None
    cost = pc.unit_cost(product_costs(product, rows, loaded.names, item), ctx.cost)
    sale = pm.sale_price(cost.unit_cost, ctx.rules, subject(product), ctx.cost.on_date)
    return ProductView(
        id=product.id,
        display_name=product.display_name,
        manufacturer_sku=product.manufacturer_sku,
        brand=product.brand,
        family=product.family,
        unit=product.unit,
        sale_mode=product.sale_mode,
        fixed_price=product.fixed_price,
        includes=product.includes,
        consumable=product.consumable,
        source=product.source,
        catalog_item_id=product.catalog_item_id,
        list_price=item.list_price if item else None,
        list_currency=item.list_currency if item else None,
        entered_in_quote=product.entered_in_quote,
        entered_by=product.entered_by,
        entered_at=product.entered_at,
        sanity=product.sanity,
        suppliers=[
            SupplierPriceView(
                id=r.id,
                supplier_id=r.supplier_id,
                supplier_name=loaded.names.get(r.supplier_id) if r.supplier_id else None,
                supplier_sku=r.supplier_sku,
                unit_cost=r.unit_cost,
                currency=r.currency,
                lead_days=r.lead_days,
                price_date=r.price_date,
                valid_until=r.valid_until,
                preferred=r.preferred,
                source=r.source,
                in_force=r.valid_until is None or r.valid_until >= ctx.cost.on_date,
            )
            for r in rows
        ],
        unit_cost=cost.unit_cost,
        price_status=cost.price_status,
        cost_source=cost.source,
        unit_price=sale.unit_price_raw,
        margin_rule=sale.rule,
        margin_pct=totals.margin_ratio(sale.unit_price_raw, cost.unit_cost),
        below_margin_floor=pm.line_floor(sale.unit_price_raw, cost.unit_cost, ctx.min_line_margin) is not None,
        history=list(history),
    )


def today(session: Session, tenant_id: str) -> date:
    tz = session.scalar(select(m.Tenant.timezone).where(m.Tenant.id == tenant_id))
    return datetime.now(UTC).astimezone(ZoneInfo(tz or "Asia/Jerusalem")).date()


def list_products(
    session: Session,
    tenant_id: str,
    *,
    q: str | None = None,
    family: str | None = None,
    brand: str | None = None,
    which: Filter = "all",
    on_date: date | None = None,
) -> list[ProductView]:
    """The price-list table (prototype vPrices): search over the name, skus, brand and suppliers, and the filters
    "בלי עלות" (no supplier and not a consumable), "כמה ספקים" and "רווח נמוך" (below the line margin floor)."""
    query = select(m.Product).where(m.Product.tenant_id == tenant_id)
    if family:
        query = query.where(m.Product.family == family)
    if brand:
        query = query.where(m.Product.brand == brand)
    if q:
        like = f"%{q.strip()}%"
        by_supplier = (
            select(m.ProductSupplier.product_id)
            .outerjoin(
                m.Supplier,
                (m.Supplier.tenant_id == m.ProductSupplier.tenant_id)
                & (m.Supplier.id == m.ProductSupplier.supplier_id),
            )
            .where(
                m.ProductSupplier.tenant_id == tenant_id,
                m.Supplier.name.ilike(like) | m.ProductSupplier.supplier_sku.ilike(like),
            )
        )
        query = query.where(
            m.Product.display_name.ilike(like)
            | m.Product.manufacturer_sku.ilike(like)
            | m.Product.brand.ilike(like)
            | m.Product.id.in_(by_supplier)
        )
    products = list(session.scalars(query.order_by(m.Product.family, m.Product.display_name, m.Product.id)))
    loaded = load(session, tenant_id, products)
    ctx = load_context(session, tenant_id, on_date or today(session, tenant_id))
    views = [view(loaded, p, ctx) for p in products]
    match which:
        case "nocost":
            return [v for v in views if not v.suppliers and not v.consumable]
        case "multi":
            return [v for v in views if len(v.suppliers) > 1]
        case "low":
            return [v for v in views if v.below_margin_floor]
        case _:
            return views


def history(session: Session, tenant_id: str, product_id: str) -> list[HistoryView]:
    return [
        HistoryView(h.id, h.field, h.old, h.new, h.quote_id, h.changed_by, h.created_at)
        for h in session.scalars(
            select(m.PriceHistory)
            .where(m.PriceHistory.tenant_id == tenant_id, m.PriceHistory.product_id == product_id)
            .order_by(m.PriceHistory.created_at.desc(), m.PriceHistory.id.desc())
        )
    ]


def get_product(session: Session, tenant_id: str, product_id: str, on_date: date | None = None) -> ProductView:
    product = _product(session, tenant_id, product_id)
    loaded = load(session, tenant_id, [product])
    ctx = load_context(session, tenant_id, on_date or today(session, tenant_id))
    return view(loaded, product, ctx, history(session, tenant_id, product_id))


def _product(session: Session, tenant_id: str, product_id: str) -> m.Product:
    product = session.scalar(select(m.Product).where(m.Product.tenant_id == tenant_id, m.Product.id == product_id))
    if product is None:
        raise PriceListError(404, "not_found")
    return product


# --- history --------------------------------------------------------------------------------------------------------


def as_json(value: Any) -> Any:
    """A value for `price_history.old` / `new`: amounts and dates as strings, never a JSON number for money."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")  # 185.0000 from the database and 185 from a request are one value
    if isinstance(value, date):
        return value.isoformat()
    return value


def wrap(value: Any) -> dict[str, Any] | None:
    """A snapshot is kept as is; a single value as `{"value": …}`, the shape every history row has."""
    if value is None or isinstance(value, dict):
        return value
    return {"value": as_json(value)}


def log(
    session: Session,
    actor: Actor,
    field_name: str,
    old: Any,
    new: Any,
    *,
    product_id: str | None = None,
    subject_key: str | None = None,
    quote_id: str | None = None,
) -> None:
    session.add(
        m.PriceHistory(
            id=new_id("prh"),
            tenant_id=actor.tenant_id,
            product_id=product_id,
            subject=subject_key,
            field=field_name,
            old=wrap(old),
            new=wrap(new),
            quote_id=quote_id,
            changed_by=actor.user_id,
        )
    )


def supplier_snapshot(r: m.ProductSupplier) -> dict[str, Any]:
    return {"id": r.id} | {f: as_json(getattr(r, f)) for f in SUPPLIER_FIELDS}


def product_snapshot(p: m.Product) -> dict[str, Any]:
    return {f: as_json(getattr(p, f)) for f in (*PRODUCT_FIELDS, "source")}


# --- products -------------------------------------------------------------------------------------------------------

SALE_MODES = ("rule", "fixed")
ROW_SOURCES = ("supplier_price_list", "manual_entry", "quote_import")  # a supplier row is never a brand discount


def in_range(value: Decimal, upper: Decimal) -> bool:
    """Zero or more, below `upper`, with at most 4 decimal places: what numeric(…,4) stores exactly."""
    return value.is_finite() and ZERO <= value < upper and -value.as_tuple().exponent <= 4  # type: ignore[operator]


def check_money(value: Decimal | None, loc: Sequence[str | int]) -> None:
    if value is None:
        return
    if not in_range(value, MAX_MONEY):
        raise PriceListError(422, "validation_error", loc, "invalid_amount")


def check_product(session: Session, tenant_id: str, values: dict[str, Any], product_id: str | None) -> None:
    for name in ("display_name", "family", "unit"):
        if name in values and not (values[name] or "").strip():
            raise PriceListError(422, "validation_error", (name,), "missing")
    if values.get("sale_mode", "rule") not in SALE_MODES:
        raise PriceListError(422, "validation_error", ("sale_mode",), "invalid")
    if "source" in values and values["source"] not in PRICE_SOURCES:
        raise PriceListError(422, "validation_error", ("source",), "invalid")
    check_money(values.get("fixed_price"), ("fixed_price",))
    sku = values.get("manufacturer_sku")
    if sku:
        clash = session.scalar(
            select(m.Product.id).where(
                m.Product.tenant_id == tenant_id, m.Product.manufacturer_sku == sku, m.Product.id != (product_id or "")
            )
        )
        if clash is not None:
            raise PriceListError(409, "sku_exists", ("manufacturer_sku",))
    item = values.get("catalog_item_id")
    if item and session.get(m.CatalogItem, item) is None:
        raise PriceListError(422, "validation_error", ("catalog_item_id",), "not_found")


def check_fixed(product: m.Product) -> None:
    """07 §7.2.1: `fixed` needs its sale price (the database checks it too)."""
    if product.sale_mode == "fixed" and product.fixed_price is None:
        raise PriceListError(422, "validation_error", ("fixed_price",), "missing")


def create_product(session: Session, actor: Actor, data: ProductIn, quote_id: str | None = None) -> ProductView:
    values = {f: getattr(data, f) for f in (*PRODUCT_FIELDS, "source")}
    check_product(session, actor.tenant_id, values, None)
    product = m.Product(id=new_id("prd"), tenant_id=actor.tenant_id, **values)
    if data.source == "manual_entry":
        product.entered_in_quote, product.entered_by, product.entered_at = quote_id, actor.user_id, datetime.now(UTC)
    check_fixed(product)
    session.add(product)
    session.flush()
    log(session, actor, "created", None, product_snapshot(product), product_id=product.id, quote_id=quote_id)
    set_suppliers(session, actor, product, data.suppliers, quote_id)
    return reread(session, actor.tenant_id, product.id)


def update_product(
    session: Session,
    actor: Actor,
    product_id: str,
    changes: dict[str, Any],
    suppliers: Sequence[SupplierPriceIn] | None = None,
    quote_id: str | None = None,
) -> ProductView:
    """`changes` holds only the fields the caller sent. `suppliers`, when given, is the product's whole supplier list:
    a row with an `id` is kept and updated, one without is added, and a row left out is removed."""
    product = _product(session, actor.tenant_id, product_id)
    unknown = set(changes) - set(PRODUCT_FIELDS)
    if unknown:
        raise PriceListError(422, "validation_error", (sorted(unknown)[0],), "unknown_field")
    check_product(session, actor.tenant_id, changes, product_id)
    for name, new in changes.items():
        old = getattr(product, name)
        if old != new:
            setattr(product, name, new)
            log(session, actor, name, old, new, product_id=product.id, quote_id=quote_id)
    check_fixed(product)
    session.flush()
    if suppliers is not None:
        set_suppliers(session, actor, product, suppliers, quote_id)
    return reread(session, actor.tenant_id, product.id)


def reread(session: Session, tenant_id: str, product_id: str) -> ProductView:
    """The product as stored: amounts at their column's scale ("130.0000"), as every read returns them."""
    session.flush()
    session.expire_all()
    return get_product(session, tenant_id, product_id)


# --- suppliers of a product -----------------------------------------------------------------------------------------


def supplier_id_for(session: Session, actor: Actor, row: SupplierPriceIn, i: int) -> str | None:
    if row.supplier_id is not None:
        found = session.scalar(
            select(m.Supplier.id).where(m.Supplier.tenant_id == actor.tenant_id, m.Supplier.id == row.supplier_id)
        )
        if found is None:
            raise PriceListError(422, "validation_error", ("suppliers", i, "supplier_id"), "not_found")
        return found
    if row.supplier_name is not None and row.supplier_name.strip():
        return supplier_by_name(session, actor, row.supplier_name.strip()).id
    return None


def check_rows(rows: Sequence[SupplierPriceIn]) -> None:
    if sum(r.preferred for r in rows) > 1:
        raise PriceListError(422, "validation_error", ("suppliers",), "one_preferred")
    for i, r in enumerate(rows):
        check_money(r.unit_cost, ("suppliers", i, "unit_cost"))
        if len(r.currency) != 3 or not r.currency.isupper():
            raise PriceListError(422, "validation_error", ("suppliers", i, "currency"), "invalid")
        if r.source not in ROW_SOURCES:
            raise PriceListError(422, "validation_error", ("suppliers", i, "source"), "invalid")
        if r.valid_until is not None and r.valid_until < r.price_date:
            raise PriceListError(422, "validation_error", ("suppliers", i, "valid_until"), "before_price_date")
        if r.lead_days is not None and r.lead_days < 0:
            raise PriceListError(422, "validation_error", ("suppliers", i, "lead_days"), "invalid")


def set_suppliers(
    session: Session, actor: Actor, product: m.Product, incoming: Sequence[SupplierPriceIn], quote_id: str | None
) -> None:
    check_rows(incoming)
    existing = {
        r.id: r
        for r in session.scalars(
            select(m.ProductSupplier).where(
                m.ProductSupplier.tenant_id == actor.tenant_id, m.ProductSupplier.product_id == product.id
            )
        )
    }
    resolved = [replace(r, supplier_id=supplier_id_for(session, actor, r, i)) for i, r in enumerate(incoming)]
    for i, r in enumerate(resolved):
        if r.id is not None and r.id not in existing:
            raise PriceListError(422, "validation_error", ("suppliers", i, "id"), "not_found")
    ids = [r.supplier_id for r in resolved]
    if len(ids) != len(set(ids)):  # one row per supplier, and one with none (S18 decision 7)
        raise PriceListError(422, "validation_error", ("suppliers",), "duplicate_supplier")

    before = pc.unit_cost(_costs_of(session, actor.tenant_id, product), _ctx(session, actor.tenant_id).cost)
    originals = {row_id: supplier_snapshot(row) for row_id, row in existing.items()}
    kept = {r.id for r in resolved if r.id is not None}
    for row_id, row in list(existing.items()):
        if row_id not in kept:
            log(session, actor, "supplier", supplier_snapshot(row), None, product_id=product.id, quote_id=quote_id)
            session.delete(row)
        elif row.preferred:
            row.preferred = False  # the one preferred is set again below; the index allows one at a time
    session.flush()

    checked: list[tuple[SupplierPriceIn, Decimal | None, date | None]] = []
    for r in resolved:
        found = existing.get(r.id) if r.id else None
        old = originals[found.id] if found is not None else None
        previous = (found.unit_cost, found.price_date) if found is not None else None
        row = found or m.ProductSupplier(id=new_id("psp"), tenant_id=actor.tenant_id, product_id=product.id)
        if found is None:
            session.add(row)
        for f in SUPPLIER_FIELDS:
            setattr(row, f, getattr(r, f))
        session.flush()
        new = supplier_snapshot(row)
        if old != new:
            log(session, actor, "supplier", old, new, product_id=product.id, quote_id=quote_id)
            if r.source == "manual_entry" and (old is None or old["unit_cost"] != new["unit_cost"]):
                checked.append((r, previous[0] if previous else before.unit_cost, previous[1] if previous else None))
    if checked:
        r, prev_cost, prev_date = checked[-1]
        product.sanity = sanity_for(session, actor.tenant_id, product, r, prev_cost, prev_date)
    session.flush()


def _ctx(session: Session, tenant_id: str) -> Context:
    return load_context(session, tenant_id, today(session, tenant_id))


def _costs_of(session: Session, tenant_id: str, product: m.Product) -> pc.ProductCosts:
    loaded = load(session, tenant_id, [product])
    item = loaded.items.get(product.catalog_item_id) if product.catalog_item_id else None
    return product_costs(product, loaded.rows[product.id], loaded.names, item)


def sanity_for(
    session: Session,
    tenant_id: str,
    product: m.Product,
    row: SupplierPriceIn,
    previous: Decimal | None,
    previous_date: date | None,
) -> dict[str, Any]:
    """10 §8, in the tenant's currency: the list price, the same family, brand and current, and the previous cost."""
    ctx = _ctx(session, tenant_id)

    def local(amount: Decimal | None, currency: str | None) -> Decimal | None:
        if amount is None:
            return None
        try:
            return convert(
                amount, currency or ctx.cost.currency, ctx.cost.currency, ctx.cost.fx_rates, ctx.cost.on_date
            ).amount
        except FxRateMissing:
            return None

    cost = local(row.unit_cost, row.currency)
    if cost is None:
        return {"warning_shown": False, "warnings": [], "list_price": None, "ratio_to_list": None}
    item = session.get(m.CatalogItem, product.catalog_item_id) if product.catalog_item_id else None
    current = (item.attributes or {}).get("current_a") if item else None
    similar: list[Decimal] = []
    if current is not None:
        others = list(
            session.scalars(
                select(m.Product).where(
                    m.Product.tenant_id == tenant_id,
                    m.Product.id != product.id,
                    m.Product.family == product.family,
                    m.Product.brand == product.brand,
                    m.Product.catalog_item_id.is_not(None),
                )
            )
        )
        loaded = load(session, tenant_id, others)
        for other in others:
            other_item = loaded.items[other.catalog_item_id]  # type: ignore[index]
            if (other_item.attributes or {}).get("current_a") != current:
                continue
            other_cost = pc.unit_cost(product_costs(other, loaded.rows[other.id], loaded.names, other_item), ctx.cost)
            if other_cost.unit_cost is not None and other_cost.price_status != "discount_based":
                similar.append(other_cost.unit_cost)
    result = check_cost(
        cost,
        list_price=local(item.list_price, item.list_currency) if item else None,
        similar_costs=similar,
        previous=(previous, previous_date or row.price_date) if previous is not None else None,
    )
    return result.as_json()


# --- suppliers ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierView:
    id: str
    name: str
    product_count: int


def supplier_by_name(session: Session, actor: Actor, name: str) -> m.Supplier:
    found = session.scalar(select(m.Supplier).where(m.Supplier.tenant_id == actor.tenant_id, m.Supplier.name == name))
    if found is None:
        found = m.Supplier(id=new_id("sup"), tenant_id=actor.tenant_id, name=name)
        session.add(found)
        session.flush()
    return found


def list_suppliers(session: Session, tenant_id: str) -> list[SupplierView]:
    counts = dict(
        session.execute(
            select(m.ProductSupplier.supplier_id, func.count())
            .where(m.ProductSupplier.tenant_id == tenant_id, m.ProductSupplier.supplier_id.is_not(None))
            .group_by(m.ProductSupplier.supplier_id)
        ).all()
    )
    return [
        SupplierView(s.id, s.name, counts.get(s.id, 0))
        for s in session.scalars(select(m.Supplier).where(m.Supplier.tenant_id == tenant_id).order_by(m.Supplier.name))
    ]


def create_supplier(session: Session, actor: Actor, name: str) -> SupplierView:
    name = name.strip()
    if not name:
        raise PriceListError(422, "validation_error", ("name",), "missing")
    if session.scalar(select(m.Supplier.id).where(m.Supplier.tenant_id == actor.tenant_id, m.Supplier.name == name)):
        raise PriceListError(409, "supplier_exists", ("name",))
    supplier = supplier_by_name(session, actor, name)
    return SupplierView(supplier.id, supplier.name, 0)


# --- brand discounts (07 §7.2 priority 2; 09 §7.13 "הזנה מרוכזת לפי מותג") ----------------------------------------


@dataclass(frozen=True)
class BrandDiscountView:
    brand: str
    discount_pct: Decimal
    priced_products: int  # the brand's products priced by this discount today (no supplier price in force)


def brand_discount_view(session: Session, tenant_id: str, brand: str, pct: Decimal) -> BrandDiscountView:
    products = list(
        session.scalars(select(m.Product).where(m.Product.tenant_id == tenant_id, m.Product.brand == brand))
    )
    loaded = load(session, tenant_id, products)
    ctx = _ctx(session, tenant_id)
    priced = sum(1 for p in products if view(loaded, p, ctx).price_status == "discount_based")
    return BrandDiscountView(brand, pct, priced)


def list_brand_discounts(session: Session, tenant_id: str) -> list[BrandDiscountView]:
    rows = session.scalars(
        select(m.BrandDiscount).where(m.BrandDiscount.tenant_id == tenant_id).order_by(m.BrandDiscount.brand)
    )
    return [brand_discount_view(session, tenant_id, r.brand, r.discount_pct) for r in rows]


def set_brand_discount(
    session: Session, actor: Actor, brand: str, pct: Decimal, quote_id: str | None = None
) -> BrandDiscountView:
    """ "כל המוצרים של שניידר: מחירון יצרן פחות 32%": every product of the brand with no supplier price in force is
    priced from its list price, `discount_based` (yellow at most) until a supplier price arrives."""
    brand = brand.strip()
    if not brand:
        raise PriceListError(422, "validation_error", ("brand",), "missing")
    if not in_range(pct, ONE):
        raise PriceListError(422, "validation_error", ("discount_pct",), "invalid")
    row = session.get(m.BrandDiscount, (actor.tenant_id, brand))
    old = row.discount_pct if row else None
    if row is None:
        row = m.BrandDiscount(tenant_id=actor.tenant_id, brand=brand, discount_pct=pct)
        session.add(row)
    else:
        row.discount_pct = pct
    if old != pct:
        log(session, actor, "discount_pct", old, pct, subject_key=f"brand_discount:{brand}", quote_id=quote_id)
    session.flush()
    session.refresh(row)
    return brand_discount_view(session, actor.tenant_id, brand, row.discount_pct)


def delete_brand_discount(session: Session, actor: Actor, brand: str) -> None:
    row = session.get(m.BrandDiscount, (actor.tenant_id, brand))
    if row is None:
        raise PriceListError(404, "not_found")
    log(session, actor, "discount_pct", row.discount_pct, None, subject_key=f"brand_discount:{brand}")
    session.delete(row)
    session.flush()


# --- margin rules (07 §7.3) -----------------------------------------------------------------------------------------

RULE_FIELDS = ("level", "target", "customer_id", "kind", "value", "fixed_price", "valid_from", "valid_to")
MAX_RATE = Decimal("1000")  # numeric(7,4)


@dataclass(frozen=True)
class MarginRuleView:
    id: str
    level: str
    target: str | None
    customer_id: str | None
    kind: str
    value: Decimal | None
    fixed_price: Decimal | None
    valid_from: date | None
    valid_to: date | None
    version: int


def rule_view(r: m.MarginRule) -> MarginRuleView:
    return MarginRuleView(
        r.id, r.level, r.target, r.customer_id, r.kind, r.value, r.fixed_price, r.valid_from, r.valid_to, r.version
    )


def list_margin_rules(session: Session, tenant_id: str) -> list[MarginRuleView]:
    order: dict[str, int] = {level: i for i, level in enumerate(pm.LEVELS)}
    rows = session.scalars(select(m.MarginRule).where(m.MarginRule.tenant_id == tenant_id))
    return [rule_view(r) for r in sorted(rows, key=lambda r: (order[r.level], r.target or "", r.id))]


def check_rule(session: Session, tenant_id: str, values: dict[str, Any]) -> None:
    """What a rule is for must match its level, and point at a real product or customer of the tenant."""
    level = values.get("level")
    if level not in pm.LEVELS:
        raise PriceListError(422, "validation_error", ("level",), "invalid")
    if values.get("kind") not in ("markup", "margin"):
        raise PriceListError(422, "validation_error", ("kind",), "invalid")
    target, customer = values.get("target"), values.get("customer_id")
    needs_target = level in ("customer_sku", "sku", "family", "brand")
    needs_customer = level in ("customer_sku", "customer")
    if bool(target) != needs_target:
        raise PriceListError(422, "validation_error", ("target",), "missing" if needs_target else "not_allowed")
    if bool(customer) != needs_customer:
        raise PriceListError(422, "validation_error", ("customer_id",), "missing" if needs_customer else "not_allowed")
    if (
        level in ("customer_sku", "sku")
        and session.scalar(select(m.Product.id).where(m.Product.tenant_id == tenant_id, m.Product.id == target)) is None
    ):
        raise PriceListError(422, "validation_error", ("target",), "not_found")
    if (
        needs_customer
        and session.scalar(select(m.Customer.id).where(m.Customer.tenant_id == tenant_id, m.Customer.id == customer))
        is None
    ):
        raise PriceListError(422, "validation_error", ("customer_id",), "not_found")
    value, fixed = values.get("value"), values.get("fixed_price")
    try:
        pm.check(pm.Rule("new", level, values["kind"], value, fixed))
    except pm.InvalidRule as e:
        raise PriceListError(
            422, "validation_error", ("value",), "margin_below_100" if "100%" in str(e) else "value_or_fixed"
        ) from e
    if value is not None and not in_range(value, MAX_RATE):
        raise PriceListError(422, "validation_error", ("value",), "invalid")
    check_money(fixed, ("fixed_price",))
    start, end = values.get("valid_from"), values.get("valid_to")
    if start is not None and end is not None and end < start:
        raise PriceListError(422, "validation_error", ("valid_to",), "before_valid_from")


def rule_snapshot(r: m.MarginRule) -> dict[str, Any]:
    return {f: as_json(getattr(r, f)) for f in (*RULE_FIELDS, "version")}


def create_margin_rule(session: Session, actor: Actor, values: dict[str, Any]) -> MarginRuleView:
    values = {f: values.get(f) for f in RULE_FIELDS} | {"kind": values.get("kind") or "markup"}
    check_rule(session, actor.tenant_id, values)
    row = m.MarginRule(id=new_id("mr"), tenant_id=actor.tenant_id, **values)
    session.add(row)
    session.flush()
    log(session, actor, "margin_rule", None, rule_snapshot(row), subject_key=row.id)
    session.flush()
    session.refresh(row)
    return rule_view(row)


def _rule(session: Session, tenant_id: str, rule_id: str) -> m.MarginRule:
    row = session.scalar(select(m.MarginRule).where(m.MarginRule.tenant_id == tenant_id, m.MarginRule.id == rule_id))
    if row is None:
        raise PriceListError(404, "not_found")
    return row


def update_margin_rule(session: Session, actor: Actor, rule_id: str, changes: dict[str, Any]) -> MarginRuleView:
    """A changed rule gets the next version, so a quote's snapshot can say which one priced it (07 §7.7)."""
    row = _rule(session, actor.tenant_id, rule_id)
    values = {f: getattr(row, f) for f in RULE_FIELDS} | {k: v for k, v in changes.items() if k in RULE_FIELDS}
    check_rule(session, actor.tenant_id, values)
    old = rule_snapshot(row)
    for f in RULE_FIELDS:
        setattr(row, f, values[f])
    if rule_snapshot(row) | {"version": old["version"]} != old:
        row.version += 1
        session.flush()
        log(session, actor, "margin_rule", old, rule_snapshot(row), subject_key=row.id)
    session.flush()
    session.refresh(row)
    return rule_view(row)


def delete_margin_rule(session: Session, actor: Actor, rule_id: str) -> None:
    """The last `default` rule stays: without it a line with a cost has no price (07 §8 `no_margin_rule`)."""
    row = _rule(session, actor.tenant_id, rule_id)
    if row.level == "default":
        defaults = session.scalar(
            select(func.count()).where(m.MarginRule.tenant_id == actor.tenant_id, m.MarginRule.level == "default")
        )
        if defaults == 1:
            raise PriceListError(409, "default_rule_required")
    log(session, actor, "margin_rule", rule_snapshot(row), None, subject_key=row.id)
    session.delete(row)
    session.flush()


# --- supplier preferences (07 §7.2.2 item 3; S18 decision 3) --------------------------------------------------------


@dataclass(frozen=True)
class SupplierPreferenceView:
    scope: str
    key: str
    supplier_id: str
    supplier_name: str


def list_supplier_preferences(session: Session, tenant_id: str) -> list[SupplierPreferenceView]:
    rows = session.execute(
        select(m.SupplierPreference, m.Supplier.name)
        .join(
            m.Supplier,
            (m.Supplier.tenant_id == m.SupplierPreference.tenant_id)
            & (m.Supplier.id == m.SupplierPreference.supplier_id),
        )
        .where(m.SupplierPreference.tenant_id == tenant_id)
        .order_by(m.SupplierPreference.scope.desc(), m.SupplierPreference.key)  # family first, as they apply
    ).all()
    return [SupplierPreferenceView(p.scope, p.key, p.supplier_id, name) for p, name in rows]


def set_supplier_preference(
    session: Session, actor: Actor, scope: str, key: str, supplier_id: str
) -> SupplierPreferenceView:
    if scope not in ("brand", "family"):
        raise PriceListError(422, "validation_error", ("scope",), "invalid")
    key = key.strip()
    if not key:
        raise PriceListError(422, "validation_error", ("key",), "missing")
    supplier = session.scalar(
        select(m.Supplier).where(m.Supplier.tenant_id == actor.tenant_id, m.Supplier.id == supplier_id)
    )
    if supplier is None:
        raise PriceListError(422, "validation_error", ("supplier_id",), "not_found")
    row = session.scalar(
        select(m.SupplierPreference).where(
            m.SupplierPreference.tenant_id == actor.tenant_id,
            m.SupplierPreference.scope == scope,
            m.SupplierPreference.key == key,
        )
    )
    old = row.supplier_id if row else None
    if row is None:
        row = m.SupplierPreference(id=new_id("spf"), tenant_id=actor.tenant_id, scope=scope, key=key)
        session.add(row)
    row.supplier_id = supplier_id
    if old != supplier_id:
        log(session, actor, "preferred_supplier", old, supplier_id, subject_key=f"supplier_preference:{scope}:{key}")
    session.flush()
    return SupplierPreferenceView(scope, key, supplier_id, supplier.name)


def delete_supplier_preference(session: Session, actor: Actor, scope: str, key: str) -> None:
    row = session.scalar(
        select(m.SupplierPreference).where(
            m.SupplierPreference.tenant_id == actor.tenant_id,
            m.SupplierPreference.scope == scope,
            m.SupplierPreference.key == key,
        )
    )
    if row is None:
        raise PriceListError(404, "not_found")
    log(session, actor, "preferred_supplier", row.supplier_id, None, subject_key=f"supplier_preference:{scope}:{key}")
    session.delete(row)
    session.flush()


# --- a price change from a quote (07 §7.2.3; 09 §7.14) --------------------------------------------------------------


def change_line_price(
    session: Session,
    actor: Actor,
    quote_id: str,
    line_id: str,
    unit_price: Decimal,
    scope: Literal["quote", "catalog"],
) -> None:
    """ "רק בהצעה הזו": the line gets an override tagged "מחיר להצעה הזו", and nothing else changes. "גם במחירון": the
    line, and its product becomes `fixed` at the new price, with the quote in the product's history.

    Either way other quotes are untouched: a sent one never changes (07 §7.7), and a draft gets "מחיר חדש במחירון"
    from stage 7 (S22), never a silent new amount. The line's color is stage 7's, so it stays.
    """
    row = session.execute(
        select(m.QuoteLine, m.QuoteVersion)
        .join(
            m.QuoteVersion,
            (m.QuoteVersion.tenant_id == m.QuoteLine.tenant_id) & (m.QuoteVersion.id == m.QuoteLine.quote_version_id),
        )
        .where(
            m.QuoteLine.tenant_id == actor.tenant_id,
            m.QuoteLine.id == line_id,
            m.QuoteLine.deleted_at.is_(None),
            m.QuoteVersion.quote_id == quote_id,
        )
    ).first()
    if row is None:
        raise PriceListError(404, "not_found")
    line, version = row
    if version.status == "sent":
        raise PriceListError(409, "quote_sent")
    check_money(unit_price, ("unit_price",))
    if scope == "catalog" and line.product_id is None:
        raise PriceListError(422, "validation_error", ("scope",), "no_product")

    before = {"unit_price": as_json(line.unit_price), "override": line.override}
    if scope == "catalog":
        update_product(
            session,
            actor,
            line.product_id,  # type: ignore[arg-type]
            {"sale_mode": "fixed", "fixed_price": unit_price},
            quote_id=quote_id,
        )
        line.override = None  # the line now has the price list's price
        line.margin_rule = {"kind": "fixed", "source": "manual_entry", "quotes": [], "value": None}
    else:
        line.override = {
            "scope": "quote",
            "unit_price": as_json(unit_price),
            "previous_price": as_json(line.unit_price),
            "by": actor.user_id,
            "at": datetime.now(UTC).isoformat(),
        }
        line.margin_rule = {"kind": "override", "source": "quote", "quotes": [], "value": None}
    line.unit_price = line.unit_price_raw = unit_price
    amounts = totals.line_amounts(line.qty, unit_price, line.unit_cost)
    line.line_total, line.line_cost, line.margin_pct = amounts.line_total, amounts.line_cost, amounts.margin_pct
    session.add(
        m.CorrectionEvent(
            id=new_id("evt"),
            tenant_id=actor.tenant_id,
            quote_id=quote_id,
            quote_version=version.version,
            user_id=actor.user_id,
            source="review_screen",
            type="price_changed",
            line_id=line.id,
            before=before,
            after={"unit_price": as_json(unit_price), "scope": scope},  # 09 §7.14: scope quote or catalog
        )
    )
    session.flush()
    store_totals(session, version)
