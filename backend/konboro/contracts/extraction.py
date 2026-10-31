"""Stage 2 → 3: extraction and tiling, per page (02 §6). Side flow (00 §5.2): `wire_graph` → stage 6.
Heavy data (renders, paths, the wire graph, tiles) lives in S3; these models hold the keys."""

from typing import Any, Literal

from pydantic import Field

from .common import (
    Bbox,
    BlockId,
    Confidence,
    Contract,
    DrawingId,
    PageId,
    PanelId,
    Point,
    Rotation,
    SpanId,
    StageIssue,
    TileId,
    TraceId,
)


class Render(Contract):
    dpi: int
    px_per_pt: float
    width_px: int
    height_px: int
    image_uri: str


class TextSpan(Contract):
    span_id: SpanId
    text: str = Field(description="After normalization")
    raw_text: str = Field(description="Exactly as extracted")
    bbox: Bbox
    rotation: Rotation = 0
    font_size_pt: float | None = None
    source: Literal["pdf_text", "ocr", "cad_text", "cad_attrib"]
    confidence: Confidence
    layer: str | None = None
    tags: dict[str, Any] = Field(default={}, description="current_a, poles, curve, breaking_capacity_ka, residual_ma")
    corrections: list[dict[str, Any]] = []
    block_id: BlockId | None = None
    merged_from: list[SpanId] = []


class CadBlock(Contract):
    block_id: BlockId
    block_name: str
    bbox: Bbox
    insert_point: Point
    rotation: float = 0
    scale: tuple[float, float] = (1.0, 1.0)
    layer: str
    attributes: dict[str, str] = {}
    attribute_span_ids: list[SpanId] = []
    mapped_symbol_class: str | None = None
    mapping_source: Literal["designer", "tenant", "global"] | None = None
    mapping_confidence: Confidence | None = None


class PreDetection(Contract):
    pre_det_id: str
    block_id: BlockId | None
    symbol_class: str
    bbox: Bbox
    confidence: Confidence


class Layer(Contract):
    name: str
    visible: bool


class Vector(Contract):
    paths_uri: str
    path_count: int
    layers: list[Layer] = []


class WireGraph(Contract):
    uri: str | None
    node_count: int = 0
    edge_count: int = 0
    block_links: int = 0
    status: Literal["built", "partial", "unavailable"]


class Tile(Contract):
    tile_id: TileId
    row: int
    col: int
    bbox_pt: Bbox
    bbox_px: tuple[int, int, int, int]
    image_uri: str
    padding_px: tuple[int, int, int, int] = Field((0, 0, 0, 0), description="top, right, bottom, left")
    panel_ids: list[PanelId] = []
    is_blank: bool = False
    span_ids: list[SpanId] = []
    pre_detection_ids: list[str] = []


class ExtractionStats(Contract):
    span_count: int = 0
    ocr_span_count: int = 0
    corrected_span_count: int = 0
    low_confidence_span_count: int = 0
    tile_count: int = 0
    blank_tile_count: int = 0
    mapped_block_ratio: float = 0


class PageExtraction(Contract):
    page_id: PageId
    drawing_id: DrawingId
    render: Render | None
    text_spans: list[TextSpan] = []
    cad_blocks: list[CadBlock] = []
    pre_detections: list[PreDetection] = []
    vector: Vector | None = None
    wire_graph: WireGraph | None = None
    tiles: list[Tile] = []
    stats: ExtractionStats = ExtractionStats()
    issues: list[StageIssue] = []
    trace_id: TraceId


class ExtractionResult(Contract):
    """Stage 2's output for the drawing: one entry per `process` page."""

    drawing_id: DrawingId
    pages: list[PageExtraction]
    trace_id: TraceId
