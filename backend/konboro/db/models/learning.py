"""Tenant layer: match memory, tenant knowledge, approval queue, chat and audit (docs/db-schema.md §6.3)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Money, Qty, TenantScoped, Timestamps, one_of, pk, tenant_fk, tenant_unique


class MatchMemory(Base, TenantScoped, Timestamps):
    """05 §11: signature + context -> the SKU the user chose. Deterministic and immediate."""

    __tablename__ = "match_memory"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("customer_id", "customers"),
        # One memory per (customer or all customers, signature, brand context). NULL means "any", so coalesce.
        Index(
            "uq_match_memory_key",
            "tenant_id",
            text("coalesce(customer_id, '')"),
            "signature",
            text("coalesce(brand_context, '')"),
            unique=True,
        ),
        Index(None, "tenant_id", "signature"),
    )

    id: Mapped[str] = pk()
    customer_id: Mapped[str | None]
    signature: Mapped[str]
    brand_context: Mapped[str | None]
    sku: Mapped[str]
    approved_count: Mapped[int] = mapped_column(server_default="1")
    last_used_at: Mapped[datetime | None]


class TenantAbbreviation(Base, TenantScoped, Created):
    """The tenant's and its designers' abbreviation dictionary (03 §4.6)."""

    __tablename__ = "tenant_abbreviations"
    __table_args__ = (tenant_unique(), one_of("scope", ("tenant", "designer")))

    id: Mapped[str] = pk()
    scope: Mapped[str] = mapped_column(server_default="tenant")
    designer: Mapped[str | None]
    text: Mapped[str]
    symbol_class: Mapped[str | None] = mapped_column(ForeignKey("symbol_classes.id"))
    family: Mapped[str | None]


class TenantReferenceCrop(Base, TenantScoped, Created):
    """Reference crops in tenant, designer or drawing scope (03 §4.3). Never visible to another tenant."""

    __tablename__ = "tenant_reference_crops"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        one_of("scope", ("tenant", "designer", "drawing")),
        one_of("source", ("user_correction", "legend")),
    )

    id: Mapped[str] = pk()
    symbol_class: Mapped[str] = mapped_column(ForeignKey("symbol_classes.id"))
    scope: Mapped[str]
    designer: Mapped[str | None]
    drawing_id: Mapped[str | None]
    image_key: Mapped[str]
    source: Mapped[str]
    approved_count: Mapped[int] = mapped_column(server_default="0")


class TenantRuleOverride(Base, TenantScoped, Timestamps):
    """Per-tenant enable/params for a global validator rule (06 §6.2)."""

    __tablename__ = "tenant_rule_overrides"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    rule_id: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool | None]
    params: Mapped[dict[str, Any]] = mapped_column(server_default="{}")


class KnowledgeCandidate(Base, TenantScoped, Timestamps):
    """The pilot approval queue (00 §14.2). Approval never writes the global layer directly:
    a promotion job, running as the owner role, copies the record with source='pilot_engineer'."""

    __tablename__ = "knowledge_candidates"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("decided_by", "users"),
        one_of("kind", ("symbol", "abbreviation", "spelling", "catalog_item", "catalog_attribute")),
        one_of("status", ("pending", "approved", "rejected")),
        Index(None, "tenant_id", "status"),
    )

    id: Mapped[str] = pk()
    kind: Mapped[str]
    payload: Mapped[dict[str, Any]]
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    status: Mapped[str] = mapped_column(server_default="pending")
    decided_by: Mapped[str | None]
    decided_at: Mapped[datetime | None]
    reason: Mapped[str | None]


class ChatConversation(Base, TenantScoped, Timestamps):
    """08 §5.2.1. One active conversation per quote. The summary never contains money (08 §5.4)."""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("quote_id", "quotes"),
        one_of("status", ("active", "closed")),
        Index(
            "uq_chat_conversations_one_active",
            "tenant_id",
            "quote_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[str] = pk()
    quote_id: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="active")
    summary: Mapped[str | None]


class ChatMessage(Base, TenantScoped, Created):
    __tablename__ = "chat_messages"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("conversation_id", "chat_conversations", ondelete="CASCADE"),
        one_of("role", ("user", "assistant", "tool")),
    )

    id: Mapped[str] = pk()
    conversation_id: Mapped[str]
    role: Mapped[str]
    content: Mapped[dict[str, Any]]
    tokens: Mapped[int | None]


class ChatProposal(Base, TenantScoped, Timestamps):
    """08 §7.1. Expires when the quote's revision moves past base_revision."""

    __tablename__ = "chat_proposals"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("quote_id", "quotes"),
        tenant_fk("conversation_id", "chat_conversations"),
        one_of("status", ("pending", "applied", "dismissed", "expired")),
        one_of("remember_default", ("quote_only", "customer", "tenant")),
    )

    id: Mapped[str] = pk()
    quote_id: Mapped[str]
    conversation_id: Mapped[str | None]
    base_version: Mapped[int]
    base_revision: Mapped[int]
    summary_he: Mapped[str]
    changes: Mapped[list[Any]]
    diff: Mapped[dict[str, Any]]
    remember_default: Mapped[str] = mapped_column(server_default="quote_only")
    status: Mapped[str] = mapped_column(server_default="pending")
    resolved_at: Mapped[datetime | None]


class Audit(Base, TenantScoped, Timestamps):
    """Audit of an existing quote (11 §6)."""

    __tablename__ = "audits"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings"),
        tenant_fk("quote_file_id", "drawing_files"),
        tenant_fk("corrected_quote_id", "quotes"),
        one_of("status", ("processing", "ready", "failed")),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    quote_file_id: Mapped[str | None]
    quote_ref: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    input_kind: Mapped[str | None]
    summary: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    status: Mapped[str] = mapped_column(server_default="processing")
    corrected_quote_id: Mapped[str | None]


class AuditDifference(Base, TenantScoped, Timestamps):
    __tablename__ = "audit_differences"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("audit_id", "audits", ondelete="CASCADE"),
        one_of("severity", ("high", "medium", "low")),
        one_of("status", ("open", "confirmed", "rejected")),
    )

    id: Mapped[str] = pk()
    audit_id: Mapped[str]
    type: Mapped[str]
    severity: Mapped[str]
    confidence: Mapped[float]
    family: Mapped[str | None]
    designators: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    drawing_qty: Mapped[Decimal | None] = mapped_column(Qty)
    quote_qty: Mapped[Decimal | None] = mapped_column(Qty)
    quote_line_index: Mapped[int | None]
    evidence: Mapped[list[Any]] = mapped_column(server_default="[]")
    suggested_line: Mapped[dict[str, Any] | None]
    message: Mapped[str]
    amount: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(server_default="open")
    reject_reason: Mapped[str | None]


__all__ = [
    "Audit",
    "AuditDifference",
    "ChatConversation",
    "ChatMessage",
    "ChatProposal",
    "KnowledgeCandidate",
    "MatchMemory",
    "TenantAbbreviation",
    "TenantReferenceCrop",
    "TenantRuleOverride",
]
