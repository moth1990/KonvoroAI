"""Tenant layer: quotes, versions, lines, findings, correction events (docs/db-schema.md §6.1)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Money, Qty, Rate, TenantScoped, Timestamps, one_of, pk, tenant_fk, tenant_unique

LINE_STATUS = ("green", "yellow", "red")


class Quote(Base, TenantScoped, Timestamps):
    __tablename__ = "quotes"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings"),
        tenant_fk("customer_id", "customers"),
        tenant_fk("project_id", "projects"),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str | None]  # null for a quote built in chat or by hand
    customer_id: Mapped[str | None]
    project_id: Mapped[str | None]
    name: Mapped[str]
    current_version: Mapped[int] = mapped_column(server_default="1")


class QuoteVersion(Base, TenantScoped, Timestamps):
    """07 §7.7. A `sent` version never changes: a trigger in the migration rejects updates."""

    __tablename__ = "quote_versions"
    __table_args__ = (
        tenant_unique(),
        UniqueConstraint("tenant_id", "quote_id", "version"),
        tenant_fk("quote_id", "quotes"),
        tenant_fk("sent_by", "users"),
        one_of("status", ("draft", "sent")),
    )

    id: Mapped[str] = pk()
    quote_id: Mapped[str]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(server_default="draft")
    revision: Mapped[int] = mapped_column(server_default="0")  # optimistic check (09 §11), proposal expiry (08 §7.5)
    quote_date: Mapped[date | None]
    currency: Mapped[str] = mapped_column(server_default="ILS")
    discount_pct: Mapped[Decimal | None] = mapped_column(Rate)
    totals: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    snapshot: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    diff_from_previous: Mapped[dict[str, Any] | None]
    sent_at: Mapped[datetime | None]
    sent_by: Mapped[str | None]


class QuoteLine(Base, TenantScoped, Timestamps):
    """07 §6.2. Money columns are null while the line has no price. Only stage 7 writes `status`."""

    __tablename__ = "quote_lines"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("quote_version_id", "quote_versions"),
        tenant_fk("panel_id", "panels"),
        tenant_fk("component_id", "components"),
        tenant_fk("parent_line_id", "quote_lines"),
        tenant_fk("product_id", "products"),
        one_of("line_type", ("component", "derived", "labor", "manual", "missing")),
        CheckConstraint(
            "price_status IS NULL OR price_status IN ('ok', 'stale', 'discount_based', 'missing')",
            name="price_status",
        ),
        one_of("status", LINE_STATUS),
        CheckConstraint("qty >= 0", name="qty"),
        Index(None, "tenant_id", "quote_version_id", "position"),
        Index(
            "ix_quote_lines_live",
            "tenant_id",
            "quote_version_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    id: Mapped[str] = pk()
    quote_version_id: Mapped[str]
    panel_id: Mapped[str | None]
    position: Mapped[int]
    line_group: Mapped[str | None]
    line_type: Mapped[str] = mapped_column(server_default="component")
    component_id: Mapped[str | None]
    parent_line_id: Mapped[str | None]
    catalog_item_id: Mapped[str | None]  # global table: plain reference, checked by the app
    product_id: Mapped[str | None]
    sku: Mapped[str | None]
    description: Mapped[str]
    manufacturer: Mapped[str | None]
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(server_default="unit")
    unit_cost: Mapped[Decimal | None] = mapped_column(Money)
    cost_source: Mapped[dict[str, Any] | None]
    price_status: Mapped[str | None]
    margin_rule: Mapped[dict[str, Any] | None]
    unit_price_raw: Mapped[Decimal | None] = mapped_column(Money)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    rounding: Mapped[str | None]
    line_cost: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    margin_pct: Mapped[Decimal | None] = mapped_column(Rate)
    derived: Mapped[dict[str, Any] | None]
    alternatives: Mapped[list[Any]] = mapped_column(server_default="[]")
    explanation: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="red")
    status_reasons: Mapped[list[Any]] = mapped_column(server_default="[]")
    issue_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    override: Mapped[dict[str, Any] | None]
    approved_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]  # soft delete: undo must restore the row (09 §7.6, §7.11)


class Finding(Base, TenantScoped, Timestamps):
    """Issues from the validator and from pricing (06 §6.2)."""

    __tablename__ = "findings"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("quote_version_id", "quote_versions"),
        tenant_fk("drawing_id", "drawings"),
        tenant_fk("panel_id", "panels"),
        tenant_fk("page_id", "pages"),
        one_of("source", ("rule", "bom_crosscheck", "agent", "pricing")),
        one_of("severity", ("error", "warning", "info")),
        one_of("status", ("open", "resolved", "dismissed")),
        Index(None, "tenant_id", "quote_version_id", "status"),
    )

    id: Mapped[str] = pk()
    quote_version_id: Mapped[str | None]
    drawing_id: Mapped[str | None]
    source: Mapped[str]
    rule_id: Mapped[str | None]
    rule_version: Mapped[int | None]
    category: Mapped[str | None]
    severity: Mapped[str]
    code: Mapped[str]
    panel_id: Mapped[str | None]
    component_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    instance_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    line_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    page_id: Mapped[str | None]
    bbox: Mapped[list[Any] | None]
    message: Mapped[str]
    values: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    confidence: Mapped[float] = mapped_column(server_default="1")
    status: Mapped[str] = mapped_column(server_default="open")


CORRECTION_TYPES = (
    "row_confirmed",
    "sku_replaced",
    "attribute_changed",
    "quantity_changed",
    "row_deleted",
    "derived_removed",
    "derived_restored",
    "issue_dismissed",
    "missing_resolved",
    "component_marked",
    "page_reclassified",
    "page_reuploaded",
    "price_entered",
    "brand_discount_set",
    "undo",
    "quote_sent",
    # 09 §7.14-7.15; missing from the 09 §10 table (CLAUDE.md, known inconsistencies)
    "price_changed",
    "supplier_selected",
)


class CorrectionEvent(Base, TenantScoped, Created):
    """09 §10. Append-only: a trigger allows updating `undone` and nothing else, and no deletes."""

    __tablename__ = "correction_events"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("quote_id", "quotes"),
        tenant_fk("user_id", "users"),
        one_of("source", ("review_screen", "chat", "price_list")),
        one_of("type", CORRECTION_TYPES),
        Index(None, "tenant_id", "quote_id", "created_at"),
    )

    id: Mapped[str] = pk()
    quote_id: Mapped[str | None]
    quote_version: Mapped[int | None]
    user_id: Mapped[str | None]
    source: Mapped[str]
    type: Mapped[str]
    line_id: Mapped[str | None]
    component_id: Mapped[str | None]
    instance_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    page_id: Mapped[str | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    reason: Mapped[str | None]
    undone: Mapped[bool] = mapped_column(server_default="false")


__all__ = ["CorrectionEvent", "Finding", "Quote", "QuoteLine", "QuoteVersion"]
