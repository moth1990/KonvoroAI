"""Stage 1 → 2: intake and page classification (01 §6). Side flows from here (00 §5.2): context artifacts
(`legend`, `general_notes`, `bom_table`) and the title block's `designer`."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Bbox, Confidence, Contract, DrawingId, FileId, PageId, PanelId, Rotation, StageIssue, TraceId

DetectedFormat = Literal["pdf", "png", "jpg", "webp", "heic", "xlsx", "csv", "zip"]
PageKind = Literal[
    "single_line_diagram",
    "control_diagram",
    "panel_front_view",
    "legend",
    "bom_table",
    "general_notes",
    "technical_data",
    "terminal_diagram",
    "title_cover",
    "factory_template",
    "other",
]
Route = Literal["process", "context", "skip"]
InputKind = Literal["factory_drawing", "designer_plan", "bom_only", "mixed"]


class SourceFile(Contract):
    file_id: FileId
    original_name: str
    detected_format: DetectedFormat
    sha256: str
    page_count: int = Field(ge=0)


class PagePanel(Contract):
    panel_id: PanelId
    name: str
    bbox: Bbox
    confidence: Confidence


class Region(Contract):
    """An area of a page that is not a panel (01 §5.4)."""

    region_kind: Literal["panel", "notes_block", "feed_diagram", "title_block", "legend"]
    bbox: Bbox
    panel_ref: PanelId | None = None


class TitleBlock(Contract):
    project_name: str | None = None
    designer: str | None = None
    drawing_number: str | None = None
    revision: str | None = None
    date: str | None = None
    status: Literal["for_info", "for_bidding", "for_execution"] | None = None


class Page(Contract):
    page_id: PageId
    file_id: FileId
    page_no: int = Field(ge=1)
    sha256: str | None
    reused_from: PageId | None = None
    size_pt: tuple[float, float] = Field(description="Width and height in points, after rotation")
    rotation_applied: Rotation = 0
    geometry_source: Literal["vector", "raster", "mixed"] | None
    text_source: Literal["pdf_text", "ocr", "mixed"] | None
    quality: Literal["ok", "low_resolution", "blurry", "cropped"]
    page_kind: PageKind
    page_kind_confidence: Confidence
    route: Route
    panels: list[PagePanel] = []
    regions: list[Region] = []
    title_block: TitleBlock | None = None
    context_artifact_ids: list[str] = []
    classified_by: Literal["model", "user", "reused", "template"]
    model: str | None = None


class Panel(Contract):
    panel_id: PanelId
    name: str
    page_ids: list[PageId]


class ContextArtifact(Contract):
    artifact_id: str
    page_id: PageId | None
    kind: str = Field(description="legend, general_notes, bom_table, technical_data, feed_diagram, …")
    format: Literal["markdown", "json", "text"]
    content: str


class QuotaOutcome(Contract):
    """How this drawing counted against the monthly quota (01 §4.5)."""

    counted: bool
    reason: Literal["new_drawing", "revision", "reuse", "audit"]
    quota_event_id: str | None = None


class IntakeResult(Contract):
    drawing_id: DrawingId
    tenant_id: str
    project_id: str | None
    status: Literal["ready", "awaiting_confirmation", "failed"]
    created_at: datetime
    revision_of: DrawingId | None = None
    input_kind: InputKind | None = Field(None, description="A hint, set after classification (01 §4.4)")
    source_files: list[SourceFile]
    pages: list[Page]
    panels: list[Panel]
    context_artifacts: list[ContextArtifact] = []
    issues: list[StageIssue] = []
    needs_confirmation: bool = False
    quota: QuotaOutcome | None = None
    trace_id: TraceId
