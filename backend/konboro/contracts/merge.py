"""Stage 4 → 5: text association and merge (04 §6). `components[]` is the contract with stage 5 (04 §6.3).
Side flows (00 §5.2): `context_elements` → stages 6 and 7, `missing[]` → stage 7.

Every attribute keeps its evidence: a value not written in the drawing is `null` here, and stage 5 fills it in
(00 §5.3, CLAUDE.md non-negotiable 3).
"""

from typing import Any, Literal

from pydantic import Field

from .common import (
    Bbox,
    ComponentId,
    Confidence,
    Contract,
    DetId,
    DrawingId,
    InstanceId,
    PageId,
    PanelId,
    SpanId,
    StageIssue,
    TraceId,
)

AttributeSource = Literal["drawing", "cad_attrib", "graphic", "shared_label", "bom"]


class AttributeValue(Contract):
    value: Any
    source: AttributeSource | None
    confidence: Confidence | None
    span_ids: list[SpanId] = []


class Instance(Contract):
    instance_id: InstanceId
    det_id: DetId
    page_id: PageId
    panel_id: PanelId | None
    bbox: Bbox
    family: str
    symbol_class: str
    attributes: dict[str, AttributeValue] = {}
    multiplicity: int = Field(1, ge=1)
    explicit_texts: list[str] = []
    brand_hint: str | None = None
    method: Literal["cad_attrib", "geometric", "agent", "fallback_geometric"]
    status: Literal["accepted", "uncertain", "missing"]
    confidence: Confidence
    component_id: ComponentId | None = None
    issues: list[StageIssue] = []


class Cable(Contract):
    cores: int | None = None
    cross_section_mm2: float | None = None
    raw: str | None = None


class CircuitContext(Contract):
    upstream_designator: str | None = None
    upstream_component_id: ComponentId | None = None
    load_current_a: float | None = None
    cable: Cable | None = None
    circuit_numbers: list[str] = []
    outputs: list[str] = []


class Component(Contract):
    component_id: ComponentId
    drawing_id: DrawingId
    panel_id: PanelId
    family: str
    symbol_class: str
    attributes: dict[str, AttributeValue] = {}
    explicit_texts: list[str] = []
    brand_hint: str | None = None
    quantity: int = Field(ge=0)
    designators: list[str] = []
    parent_designators: list[str] = []
    circuit_context: CircuitContext | None = None
    multiplicity_inherited: bool = False
    supply_scope: Literal["in_panel", "other_location", "prepare_only", "by_others"] = "in_panel"
    source_det_ids: list[DetId] = []
    instance_ids: list[InstanceId] = []
    confidence: Confidence
    status: Literal["accepted", "uncertain"]


class MissingInstance(Contract):
    instance_id: InstanceId
    page_id: PageId
    panel_id: PanelId | None
    bbox: Bbox
    family: str
    attributes: dict[str, AttributeValue] = {}
    origin: str
    confidence: Confidence
    status: Literal["missing"] = "missing"


class ContextElement(Contract):
    det_id: DetId
    family: str
    panel_id: PanelId | None
    bbox: Bbox


class MergeStats(Contract):
    instance_count: int = 0
    component_count: int = 0
    missing_count: int = 0
    tiles_total: int = 0
    tiles_with_agent: int = 0
    by_method: dict[str, int] = {}
    citation_mismatches: int = 0
    shared_labels: int = 0


class MergeResult(Contract):
    drawing_id: DrawingId
    instances: list[Instance] = []
    components: list[Component] = []
    missing: list[MissingInstance] = []
    context_elements: list[ContextElement] = []
    stats: MergeStats = MergeStats()
    issues: list[StageIssue] = []
    trace_id: TraceId
