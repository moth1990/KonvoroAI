"""The factory's price list (07 §7.2–7.3): products and their suppliers, suppliers, brand discounts, margin rules and
supplier preferences. Every route is behind `price_list` (S18 decision 5) until S19's screen is complete.

Money is a string in every request and response (non-negotiable 5). Every change is logged in `price_history` with
who made it and the quote it came from (07 §12).
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel

from konboro.domain.permissions import Permission
from konboro.services import price_list as pl

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import (
    BrandDiscountIn,
    BrandDiscountOut,
    MarginRuleIn,
    MarginRuleOut,
    MarginRulePatch,
    ProductIn,
    ProductOut,
    ProductPatch,
    SupplierIn,
    SupplierOut,
    SupplierPreferenceIn,
    SupplierPreferenceOut,
    SupplierPriceIn,
)

FLAG = "price_list"

router = APIRouter(
    prefix="/price-list", tags=["price-list"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(FLAG))]
)

Reader = Annotated[Actor, Depends(require(Permission.PRICE_LIST_READ))]
Writer = Annotated[Actor, Depends(require(Permission.PRICE_LIST_WRITE))]
ProductId = Annotated[str, Path(pattern=r"^prd_[0-9A-Z]{26}$")]
RuleId = Annotated[str, Path(pattern=r"^mr_[0-9A-Z]{26}$")]
Brand = Annotated[str, Path(min_length=1, max_length=100)]
Scope = Annotated[Literal["brand", "family"], Path()]
Key = Annotated[str, Path(min_length=1, max_length=100)]


def who(actor: Actor) -> pl.Actor:
    return pl.Actor(actor.tenant_id, actor.user_id)


def api_error(e: pl.PriceListError) -> ApiError:
    return ApiError(e.status, e.code, e.details)


def values(body: BaseModel, *, sent_only: bool = False, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """The body's fields as Python values. Not `model_dump()`: it turns a DecimalStr back into its JSON string."""
    names = body.model_fields_set if sent_only else type(body).model_fields
    return {n: getattr(body, n) for n in names if n not in exclude}


def rows_in(rows: list[SupplierPriceIn]) -> list[pl.SupplierPriceIn]:
    return [pl.SupplierPriceIn(**values(r)) for r in rows]


def product_out(v: pl.ProductView) -> ProductOut:
    return ProductOut.model_validate(v, from_attributes=True)


# --- products -------------------------------------------------------------------------------------------------------


@router.get("/products")
def list_products(
    actor: Reader,
    q: Annotated[str | None, Query(max_length=100, description="Name, skus, brand or supplier")] = None,
    family: Annotated[str | None, Query(max_length=64)] = None,
    brand: Annotated[str | None, Query(max_length=100)] = None,
    filter: Annotated[pl.Filter, Query(description="The screen's filters (prototype vPrices)")] = "all",
) -> list[ProductOut]:
    views = pl.list_products(actor.session, actor.tenant_id, q=q, family=family, brand=brand, which=filter)
    return [product_out(v) for v in views]


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(body: ProductIn, actor: Writer) -> ProductOut:
    data = values(body, exclude=("suppliers", "quote_id"))
    try:
        view = pl.create_product(
            actor.session, who(actor), pl.ProductIn(**data, suppliers=rows_in(body.suppliers)), body.quote_id
        )
    except pl.PriceListError as e:
        raise api_error(e) from e
    return product_out(view)


@router.get("/products/{product_id}")
def get_product(product_id: ProductId, actor: Reader) -> ProductOut:
    try:
        return product_out(pl.get_product(actor.session, actor.tenant_id, product_id))
    except pl.PriceListError as e:
        raise api_error(e) from e


@router.patch("/products/{product_id}")
def update_product(product_id: ProductId, body: ProductPatch, actor: Writer) -> ProductOut:
    changes = values(body, sent_only=True, exclude=("suppliers", "quote_id"))
    suppliers = rows_in(body.suppliers) if body.suppliers is not None else None
    try:
        view = pl.update_product(actor.session, who(actor), product_id, changes, suppliers, body.quote_id)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return product_out(view)


# --- suppliers ------------------------------------------------------------------------------------------------------


@router.get("/suppliers")
def list_suppliers(actor: Reader) -> list[SupplierOut]:
    return [
        SupplierOut.model_validate(s, from_attributes=True) for s in pl.list_suppliers(actor.session, actor.tenant_id)
    ]


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
def create_supplier(body: SupplierIn, actor: Writer) -> SupplierOut:
    try:
        return SupplierOut.model_validate(
            pl.create_supplier(actor.session, who(actor), body.name), from_attributes=True
        )
    except pl.PriceListError as e:
        raise api_error(e) from e


# --- brand discounts ------------------------------------------------------------------------------------------------


@router.get("/brand-discounts")
def list_brand_discounts(actor: Reader) -> list[BrandDiscountOut]:
    rows = pl.list_brand_discounts(actor.session, actor.tenant_id)
    return [BrandDiscountOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/brand-discounts/{brand}")
def set_brand_discount(brand: Brand, body: BrandDiscountIn, actor: Writer) -> BrandDiscountOut:
    """09 §7.13's "כל המוצרים של שניידר: מחירון יצרן פחות 32%" (07 §7.2, priority 2)."""
    try:
        row = pl.set_brand_discount(actor.session, who(actor), brand, body.discount_pct, body.quote_id)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return BrandDiscountOut.model_validate(row, from_attributes=True)


@router.delete("/brand-discounts/{brand}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand_discount(brand: Brand, actor: Writer) -> Response:
    try:
        pl.delete_brand_discount(actor.session, who(actor), brand)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- margin rules ---------------------------------------------------------------------------------------------------


@router.get("/margin-rules")
def list_margin_rules(actor: Reader) -> list[MarginRuleOut]:
    rows = pl.list_margin_rules(actor.session, actor.tenant_id)
    return [MarginRuleOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/margin-rules", status_code=status.HTTP_201_CREATED)
def create_margin_rule(body: MarginRuleIn, actor: Writer) -> MarginRuleOut:
    try:
        row = pl.create_margin_rule(actor.session, who(actor), values(body))
    except pl.PriceListError as e:
        raise api_error(e) from e
    return MarginRuleOut.model_validate(row, from_attributes=True)


@router.patch("/margin-rules/{rule_id}")
def update_margin_rule(rule_id: RuleId, body: MarginRulePatch, actor: Writer) -> MarginRuleOut:
    try:
        row = pl.update_margin_rule(actor.session, who(actor), rule_id, values(body, sent_only=True))
    except pl.PriceListError as e:
        raise api_error(e) from e
    return MarginRuleOut.model_validate(row, from_attributes=True)


@router.delete("/margin-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_margin_rule(rule_id: RuleId, actor: Writer) -> Response:
    try:
        pl.delete_margin_rule(actor.session, who(actor), rule_id)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- supplier preferences -------------------------------------------------------------------------------------------


@router.get("/supplier-preferences")
def list_supplier_preferences(actor: Reader) -> list[SupplierPreferenceOut]:
    rows = pl.list_supplier_preferences(actor.session, actor.tenant_id)
    return [SupplierPreferenceOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/supplier-preferences/{scope}/{key}")
def set_supplier_preference(scope: Scope, key: Key, body: SupplierPreferenceIn, actor: Writer) -> SupplierPreferenceOut:
    """The preferred supplier for a family or a brand (07 §7.2.2 item 3); the family's applies first."""
    try:
        row = pl.set_supplier_preference(actor.session, who(actor), scope, key, body.supplier_id)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return SupplierPreferenceOut.model_validate(row, from_attributes=True)


@router.delete("/supplier-preferences/{scope}/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier_preference(scope: Scope, key: Key, actor: Writer) -> Response:
    try:
        pl.delete_supplier_preference(actor.session, who(actor), scope, key)
    except pl.PriceListError as e:
        raise api_error(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)
