"""Stage 3 → 4: symbol detection, per page (03 §6)."""

from typing import Any, Literal

from .common import (
    Bbox,
    BlockId,
    Confidence,
    Contract,
    DetId,
    DrawingId,
    PageId,
    PanelId,
    Rotation,
    SpanId,
    StageIssue,
    TileId,
    TraceId,
)


class ClassCandidate(Contract):
    symbol_class: str
    score: Confidence


class Detection(Contract):
    det_id: DetId
    page_id: PageId
    bbox: Bbox
    orientation: Rotation = 0
    family: str
    symbol_class: str
    billable: bool
    method: Literal["cad_block", "detector_knn", "detector_llm", "orphan_recovery"]
    detector_score: Confidence | None
    class_score: Confidence
    confidence: Confidence
    class_candidates: list[ClassCandidate] = []
    status: Literal["accepted", "uncertain", "unknown"]
    owner_tile_id: TileId
    seen_in_tile_ids: list[TileId] = []
    block_id: BlockId | None = None
    panel_id: PanelId | None = None
    designator: str | None = None
    designator_span_id: SpanId | None = None
    role: Literal["device", "power_contact", "coil", "relay_contact", "aux_contact", "front_view"] = "device"
    linked_designator: str | None = None
    crop_uri: str | None = None
    llm_decision: dict[str, Any] | None = None


class OrphanText(Contract):
    span_id: SpanId
    text: str
    bbox: Bbox
    recovery_attempted: bool


class DetectionStats(Contract):
    detection_count: int = 0
    by_method: dict[str, int] = {}
    by_status: dict[str, int] = {}
    duplicates_removed: int = 0
    orphan_text_count: int = 0
    llm_calls: int = 0


class PageDetections(Contract):
    page_id: PageId
    drawing_id: DrawingId
    detector_model: str | None = None
    embedding_model: str | None = None
    library_version: str | None = None
    detections: list[Detection] = []
    orphan_texts: list[OrphanText] = []
    stats: DetectionStats = DetectionStats()
    issues: list[StageIssue] = []
    trace_id: TraceId


class DetectionResult(Contract):
    """Stage 3's output for the drawing: one entry per `process` page."""

    drawing_id: DrawingId
    pages: list[PageDetections]
    trace_id: TraceId
