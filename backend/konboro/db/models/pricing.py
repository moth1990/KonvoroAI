"""Tenant layer: the price list, suppliers, margin and derived-item rules (docs/db-schema.md §6.2, 07 §7.2–7.4)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Money, Rate, TenantScoped, Timestamps, one_of, pk, tenant_fk, tenant_unique

PRICE_SOURCES = ("supplier_price_list", "manual_entry", "quote_import", "brand_discount")


class Product(Base, TenantScoped, Timestamps):
    """One record per product, with any number of suppliers (07 §7.2.1)."""

    __tablename__ = "products"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("entered_in_quote", "quotes"),
        tenant_fk("entered_by", "users"),
        one_of("sale_mode", ("rule", "fixed")),
        one_of("source", PRICE_SOURCES),
        CheckConstraint("sale_mode <> 'fixed' OR fixed_price IS NOT NULL", name="fixed_needs_price"),
        Index(
            "uq_products_tenant_sku",
            "tenant_id",
            "manufacturer_sku",
            unique=True,
            postgresql_where="manufacturer_sku IS NOT NULL",
        ),
        Index(None, "tenant_id", "family"),
        Index(None, "tenant_id", "brand"),
    )

    id: Mapped[str] = pk()
    catalog_item_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_items.id"))
    display_name: Mapped[str]
    manufacturer_sku: Mapped[str | None]
    brand: Mapped[str | None]
    family: Mapped[str]
    unit: Mapped[str] = mapped_column(server_default="unit")
    sale_mode: Mapped[str] = mapped_column(server_default="rule")
    fixed_price: Mapped[Decimal | None] = mapped_column(Money)
    includes: Mapped[dict[str, Any] | None]
    consumable: Mapped[bool] = mapped_column(server_default="false")
    source: Mapped[str]
    entered_in_quote: Mapped[str | None]
    entered_by: Mapped[str | None]
    entered_at: Mapped[datetime | None]
    sanity: Mapped[dict[str, Any] | None]


class Supplier(Base, TenantScoped, Created):
    __tablename__ = "suppliers"
    __table_args__ = (tenant_unique(), UniqueConstraint("tenant_id", "name"))

    id: Mapped[str] = pk()
    name: Mapped[str]


class ProductSupplier(Base, TenantScoped, Timestamps):
    """A supplier's price for a product (07 §7.2.2). At most one preferred supplier per product."""

    __tablename__ = "product_suppliers"
    __table_args__ = (
        tenant_unique(),
        UniqueConstraint("tenant_id", "product_id", "supplier_id"),
        tenant_fk("product_id", "products", ondelete="CASCADE"),
        tenant_fk("supplier_id", "suppliers"),
        one_of("source", PRICE_SOURCES),
        CheckConstraint("unit_cost >= 0", name="unit_cost"),
        Index(
            "uq_product_suppliers_one_preferred",
            "tenant_id",
            "product_id",
            unique=True,
            postgresql_where="preferred",
        ),
    )

    id: Mapped[str] = pk()
    product_id: Mapped[str]
    supplier_id: Mapped[str]
    supplier_sku: Mapped[str | None]
    unit_cost: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(server_default="ILS")
    lead_days: Mapped[int | None]
    price_date: Mapped[date]
    valid_until: Mapped[date | None]
    preferred: Mapped[bool] = mapped_column(server_default="false")
    source: Mapped[str] = mapped_column(server_default="supplier_price_list")


class PriceHistory(Base, TenantScoped, Created):
    __tablename__ = "price_history"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("product_id", "products", ondelete="CASCADE"),
        tenant_fk("quote_id", "quotes"),
        tenant_fk("changed_by", "users"),
    )

    id: Mapped[str] = pk()
    product_id: Mapped[str]
    field: Mapped[str]
    old: Mapped[dict[str, Any] | None]
    new: Mapped[dict[str, Any] | None]
    quote_id: Mapped[str | None]
    changed_by: Mapped[str | None]


class BrandDiscount(Base, TenantScoped, Timestamps):
    """Manufacturer list price minus this discount (07 §7.2, priority 2)."""

    __tablename__ = "brand_discounts"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    brand: Mapped[str] = mapped_column(primary_key=True)
    discount_pct: Mapped[Decimal] = mapped_column(Rate)


class MarginRule(Base, TenantScoped, Timestamps):
    """07 §7.3. Priority: customer_sku > customer > sku > family > brand > default."""

    __tablename__ = "margin_rules"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("customer_id", "customers"),
        one_of("level", ("customer_sku", "customer", "sku", "family", "brand", "default")),
        one_of("kind", ("markup", "margin")),
        CheckConstraint("(value IS NULL) <> (fixed_price IS NULL)", name="value_or_fixed"),
        CheckConstraint("kind <> 'margin' OR value < 1", name="margin_below_one"),
    )

    id: Mapped[str] = pk()
    level: Mapped[str]
    target: Mapped[str | None]
    customer_id: Mapped[str | None]
    kind: Mapped[str] = mapped_column(server_default="markup")
    value: Mapped[Decimal | None] = mapped_column(Rate)
    fixed_price: Mapped[Decimal | None] = mapped_column(Money)
    valid_from: Mapped[date | None]
    valid_to: Mapped[date | None]
    version: Mapped[int] = mapped_column(server_default="1")


class DerivedItemRule(Base, TenantScoped, Timestamps):
    """07 §7.4: items that are not drawn but go into the panel. A new tenant gets a copy of the starter rules."""

    __tablename__ = "derived_item_rules"
    __table_args__ = (tenant_unique(), one_of("scope", ("panel", "quote")))

    id: Mapped[str] = pk()
    scope: Mapped[str]
    trigger: Mapped[dict[str, Any]]
    quantity_formula: Mapped[str]
    item: Mapped[dict[str, Any]]
    explanation_he: Mapped[str]
    enabled: Mapped[bool] = mapped_column(server_default="true")
    version: Mapped[int] = mapped_column(server_default="1")


__all__ = [
    "BrandDiscount",
    "DerivedItemRule",
    "MarginRule",
    "PriceHistory",
    "Product",
    "ProductSupplier",
    "Supplier",
]
