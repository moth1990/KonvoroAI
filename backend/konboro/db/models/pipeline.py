"""Tenant layer: customers, projects, drawings and pipeline outputs (docs/db-schema.md §5)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Qty, Rate, TenantScoped, Timestamps, one_of, pk, tenant_fk, tenant_unique


class Customer(Base, TenantScoped, Timestamps):
    __tablename__ = "customers"
    __table_args__ = (tenant_unique(),)

    id: Mapped[str] = pk()
    name: Mapped[str]
    discount_pct: Mapped[Decimal | None] = mapped_column(Rate)
    brand_preferences: Mapped[dict[str, Any]] = mapped_column(server_default="{}")


class Project(Base, TenantScoped, Timestamps):
    __tablename__ = "projects"
    __table_args__ = (tenant_unique(), tenant_fk("customer_id", "customers"))

    id: Mapped[str] = pk()
    customer_id: Mapped[str | None]
    name: Mapped[str]


class Drawing(Base, TenantScoped, Timestamps):
    """01 §6.2."""

    __tablename__ = "drawings"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("project_id", "projects"),
        tenant_fk("revision_of", "drawings"),
        tenant_fk("created_by", "users"),
        one_of("purpose", ("quote", "audit")),
        one_of("status", ("uploaded", "processing", "awaiting_confirmation", "ready", "failed", "cancelled")),
        CheckConstraint(
            "input_kind IS NULL OR input_kind IN ('factory_drawing', 'designer_plan', 'bom_only', 'mixed')",
            name="input_kind",
        ),
        CheckConstraint("current_stage IS NULL OR current_stage BETWEEN 1 AND 7", name="current_stage"),
        Index(None, "tenant_id", "created_at"),
    )

    id: Mapped[str] = pk()
    project_id: Mapped[str | None]
    revision_of: Mapped[str | None]
    purpose: Mapped[str] = mapped_column(server_default="quote")
    status: Mapped[str] = mapped_column(server_default="uploaded")
    input_kind: Mapped[str | None]
    current_stage: Mapped[int | None] = mapped_column(SmallInteger)
    progress: Mapped[float] = mapped_column(server_default="0")
    needs_confirmation: Mapped[bool] = mapped_column(server_default="false")
    title_block: Mapped[dict[str, Any] | None]  # read once per drawing (S08 decision), 01 §5.4
    quota: Mapped[dict[str, Any] | None]
    issues: Mapped[list[Any]] = mapped_column(server_default="[]")
    trace_id: Mapped[str | None]
    created_by: Mapped[str | None]


class DrawingFile(Base, TenantScoped, Created):
    __tablename__ = "drawing_files"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        Index(None, "tenant_id", "sha256"),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    original_name: Mapped[str]
    detected_format: Mapped[str]
    sha256: Mapped[str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None]
    storage_key: Mapped[str]


class Page(Base, TenantScoped, Timestamps):
    """01 §6.3."""

    __tablename__ = "pages"
    __table_args__ = (
        tenant_unique(),
        UniqueConstraint("tenant_id", "file_id", "page_no"),
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        tenant_fk("file_id", "drawing_files", ondelete="CASCADE"),
        tenant_fk("reused_from", "pages"),
        one_of("rotation_applied", (0, 90, 180, 270)),
        CheckConstraint("geometry_source IS NULL OR geometry_source IN ('vector', 'raster', 'mixed')", name="geom"),
        CheckConstraint("text_source IS NULL OR text_source IN ('pdf_text', 'ocr', 'mixed')", name="text_source"),
        CheckConstraint(
            "component_labels IS NULL"
            " OR component_labels IN ('tags_and_models', 'tags_only', 'none', 'not_applicable')",
            name="component_labels",
        ),
        CheckConstraint(
            "quality IS NULL OR quality IN ('ok', 'low_resolution', 'blurry', 'cropped')",
            name="quality",
        ),
        CheckConstraint("route IS NULL OR route IN ('process', 'context', 'skip')", name="route"),
        CheckConstraint("tile_count IS NULL OR tile_count >= 0", name="tile_count"),
        CheckConstraint(
            "classified_by IS NULL OR classified_by IN ('model', 'user', 'reused', 'template')",
            name="classified_by",
        ),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    file_id: Mapped[str]
    page_no: Mapped[int]
    sha256: Mapped[str | None]
    reused_from: Mapped[str | None]
    width_pt: Mapped[float | None]
    height_pt: Mapped[float | None]
    rotation_applied: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    geometry_source: Mapped[str | None]
    text_source: Mapped[str | None]
    quality: Mapped[str | None]
    page_kind: Mapped[str | None]
    page_kind_confidence: Mapped[float | None]
    route: Mapped[str | None]
    classified_by: Mapped[str | None]
    model: Mapped[str | None]
    component_labels: Mapped[str | None]  # the classifier's, for input_kind on reuse (BUG-015)
    title_block: Mapped[dict[str, Any] | None]
    regions: Mapped[list[Any]] = mapped_column(server_default="[]")
    render_key: Mapped[str | None]
    tiles_prefix: Mapped[str | None]
    tile_count: Mapped[int | None]  # tiles that are not blank, for the run step (migration 0007)


class Panel(Base, TenantScoped, Created):
    __tablename__ = "panels"
    __table_args__ = (tenant_unique(), tenant_fk("drawing_id", "drawings", ondelete="CASCADE"))

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    name: Mapped[str]
    page_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    bboxes: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    confidence: Mapped[float | None]


class ContextArtifact(Base, TenantScoped, Created):
    """Context pulled from non-drawing pages: notes, BOM tables, legend (01 §5.5)."""

    __tablename__ = "context_artifacts"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        tenant_fk("page_id", "pages", ondelete="CASCADE"),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    page_id: Mapped[str | None]
    kind: Mapped[str]
    format: Mapped[str]
    content: Mapped[str]


class PageTemplate(Base, TenantScoped, Created):
    """A factory's fixed page (01 §5.7): a fingerprint with the title block masked. A new page that matches it is
    classified without a model call, but only for the same producer as the page it came from."""

    __tablename__ = "page_templates"
    __table_args__ = (
        tenant_unique(),
        Index(None, "tenant_id", "producer"),
    )

    id: Mapped[str] = pk()
    producer: Mapped[str | None]  # normalized title-block `designer`; None when the page had none
    page_kind: Mapped[str]
    fingerprint: Mapped[str]  # hex, see pipeline/intake/templates.py
    mask: Mapped[list[float] | None] = mapped_column(ARRAY(Float))  # title block, [x0, y0, x1, y1] as 0..1
    source_page_id: Mapped[str | None]  # for the audit trail only: no FK, the template outlives its drawing


class StageRun(Base, TenantScoped):
    """Progress, retries and the S3 key of each stage's contract output (00 §5)."""

    __tablename__ = "stage_runs"
    __table_args__ = (
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        CheckConstraint("stage BETWEEN 1 AND 7", name="stage"),
        one_of("status", ("queued", "running", "done", "failed", "skipped")),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    drawing_id: Mapped[str] = mapped_column(primary_key=True)
    stage: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[str] = mapped_column(server_default="queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    output_key: Mapped[str | None]
    error: Mapped[dict[str, Any] | None]
    # When this stage's message was last sent. The worker re-sends one that no worker claimed (migration 0004).
    sent_at: Mapped[datetime | None]


class Component(Base, TenantScoped, Created):
    """Stage 4 output (04 §6.3). Kept in the DB because quote lines and audits point at it."""

    __tablename__ = "components"
    __table_args__ = (
        tenant_unique(),
        tenant_fk("drawing_id", "drawings", ondelete="CASCADE"),
        tenant_fk("panel_id", "panels", ondelete="CASCADE"),
        one_of("supply_scope", ("in_panel", "outside_panel", "prep_only", "not_in_scope")),
    )

    id: Mapped[str] = pk()
    drawing_id: Mapped[str]
    panel_id: Mapped[str | None]
    family: Mapped[str]
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    quantity: Mapped[Decimal] = mapped_column(Qty)
    designators: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    instances: Mapped[list[Any]] = mapped_column(server_default="[]")
    confidence: Mapped[float | None]
    brand_hint: Mapped[str | None]
    explicit_texts: Mapped[list[Any]] = mapped_column(server_default="[]")
    supply_scope: Mapped[str] = mapped_column(server_default="in_panel")


__all__ = [
    "Component",
    "ContextArtifact",
    "Customer",
    "Drawing",
    "DrawingFile",
    "Page",
    "PageTemplate",
    "Panel",
    "Project",
    "StageRun",
]
