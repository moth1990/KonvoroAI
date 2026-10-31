"""Tenant layer: account, users, settings, plan overrides, flags, quota, LLM cost (docs/db-schema.md §4)."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Rate, TenantScoped, Timestamps, one_of, pk, tenant_fk, tenant_unique


class Tenant(Base, Timestamps):
    """A factory. Its RLS policy compares `id` instead of `tenant_id`."""

    __tablename__ = "tenants"
    __table_args__ = (one_of("status", ("active", "suspended")),)

    id: Mapped[str] = pk()
    name: Mapped[str]
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    timezone: Mapped[str] = mapped_column(server_default="Asia/Jerusalem")
    currency: Mapped[str] = mapped_column(server_default="ILS")
    status: Mapped[str] = mapped_column(server_default="active")


class User(Base, TenantScoped, Timestamps):
    """One user per tenant in v1.0, but every action still checks the role (00 §14.1)."""

    __tablename__ = "users"
    __table_args__ = (
        tenant_unique(),
        UniqueConstraint("tenant_id", "email"),
        UniqueConstraint("auth_subject"),
        one_of("role", ("owner",)),
    )

    id: Mapped[str] = pk()
    email: Mapped[str]
    auth_subject: Mapped[str | None]
    display_name: Mapped[str | None]
    role: Mapped[str] = mapped_column(server_default="owner")


class TenantSettings(Base, TenantScoped):
    """10 §9.1 plus the prototype settings screen. One row per tenant."""

    __tablename__ = "tenant_settings"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    brand_preferences: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    attribute_defaults: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    enclosure_includes_default: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    min_line_margin: Mapped[Decimal | None] = mapped_column(Rate)
    min_quote_margin: Mapped[Decimal | None] = mapped_column(Rate)
    stale_days: Mapped[int] = mapped_column(server_default="90")
    labor: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    rounding: Mapped[str] = mapped_column(server_default="agora")
    data_terms_accepted: Mapped[dict[str, Any] | None]
    onboarding: Mapped[dict[str, Any]] = mapped_column(server_default="{}")


class TenantPlanOverride(Base, TenantScoped, Timestamps):
    """`null` = use the plan's value (01 §4.3)."""

    __tablename__ = "tenant_plan_overrides"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    monthly_quote_limit: Mapped[int | None]
    monthly_audit_limit: Mapped[int | None]
    max_pages_per_file: Mapped[int | None]
    reason: Mapped[str | None]


class TenantFeatureOverride(Base, TenantScoped, Created):
    __tablename__ = "tenant_feature_overrides"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    flag_key: Mapped[str] = mapped_column(ForeignKey("feature_flags.key"), primary_key=True)
    enabled: Mapped[bool]
    reason: Mapped[str | None]


QUOTA_COUNTERS = ("quote", "audit")


class QuotaUsage(Base, TenantScoped, Timestamps):
    """01 §4.5. `month` is the first day of the month in the tenant's timezone.

    The audit counter is used only when the plan has a separate monthly_audit_limit.
    """

    __tablename__ = "quota_usage"
    __table_args__ = (
        one_of("counter", QUOTA_COUNTERS),
        CheckConstraint("used >= 0 AND reserved >= 0 AND extra >= 0", name="non_negative"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    month: Mapped[date] = mapped_column(primary_key=True)
    counter: Mapped[str] = mapped_column(primary_key=True, server_default="quote")
    used: Mapped[int] = mapped_column(server_default="0")
    reserved: Mapped[int] = mapped_column(server_default="0")
    extra: Mapped[int] = mapped_column(server_default="0")


QUOTA_CLOSING_KINDS = ("confirm", "release")


class QuotaEvent(Base, TenantScoped, Created):
    """Every quota change with its reason: answers "why was this counted?" (01 §4.5).

    A `reserve` event is a reservation. Its `confirm` or `release` points back at it through
    `reservation_id`, and the partial unique index allows only one of them, so a reservation
    can never be closed twice (e.g. a confirm racing the 24 h expiry).
    """

    __tablename__ = "quota_events"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings"),
        tenant_fk("created_by", "users"),
        tenant_fk("reservation_id", "quota_events"),
        one_of("counter", QUOTA_COUNTERS),
        one_of("kind", ("reserve", "confirm", "release", "manual_add")),
        CheckConstraint(
            "(reservation_id IS NOT NULL) = (kind IN ('confirm', 'release'))", name="closing_has_reservation"
        ),
        Index(
            "uq_quota_events_one_closing",
            "tenant_id",
            "reservation_id",
            unique=True,
            postgresql_where=text("kind IN ('confirm', 'release')"),
        ),
    )

    id: Mapped[str] = pk()
    month: Mapped[date]
    counter: Mapped[str] = mapped_column(server_default="quote")
    drawing_id: Mapped[str | None]
    kind: Mapped[str]
    amount: Mapped[int] = mapped_column(server_default="1")
    reason: Mapped[str | None]
    created_by: Mapped[str | None]
    reservation_id: Mapped[str | None]


class LlmCall(Base, TenantScoped, Created):
    """One row per konboro_llm call: cost per tenant and stage (00 §7.2, 12 §7). A log, so no foreign keys."""

    __tablename__ = "llm_calls"
    __table_args__ = (tenant_unique(), Index(None, "tenant_id", "created_at"))

    id: Mapped[str] = pk()
    stage: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    latency_ms: Mapped[int]
    attempts: Mapped[int] = mapped_column(SmallInteger)
    drawing_id: Mapped[str | None]
    quote_id: Mapped[str | None]


__all__ = [
    "QUOTA_CLOSING_KINDS",
    "QUOTA_COUNTERS",
    "LlmCall",
    "QuotaEvent",
    "QuotaUsage",
    "Tenant",
    "TenantFeatureOverride",
    "TenantPlanOverride",
    "TenantSettings",
    "User",
]
