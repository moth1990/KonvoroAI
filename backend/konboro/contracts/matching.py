"""Stage 5 → 6: catalog matching, per component (05 §6)."""

from typing import Any, Literal

from .common import ComponentId, Confidence, Contract, DrawingId, StageIssue, TraceId

# Stage 5 adds these to the "read from the drawing" sources of stage 4 (04 §6.2).
UsedSource = Literal[
    "drawing",
    "cad_attrib",
    "graphic",
    "shared_label",
    "bom",
    "notes",
    "circuit",
    "tenant_default",
    "system_default",
    "user",
]


class CatalogItemSnapshot(Contract):
    sku: str
    manufacturer: str | None
    series: str | None = None
    description: str
    attributes: dict[str, Any] = {}


class UsedAttribute(Contract):
    value: Any
    source: UsedSource


class BrandDecision(Contract):
    brand: str | None
    source: str


class Substitution(Contract):
    requested_brand: str | None
    chosen_brand: str | None
    reason: str


class Alternative(Contract):
    sku: str
    manufacturer: str | None
    diff: str
    has_cost_price: bool


class ComponentMatch(Contract):
    component_id: ComponentId
    status: Literal["matched", "ambiguous", "unmatched", "conflict"]
    chosen_sku: str | None
    catalog_item: CatalogItemSnapshot | None
    method: Literal["explicit_sku", "explicit_series", "memory", "rules_unique", "rules_ranked", "llm", "user"] | None
    match_confidence: Confidence
    confidence: Confidence
    attributes_used: dict[str, UsedAttribute] = {}
    defaulted_attributes: list[str] = []
    brand_decision: BrandDecision | None = None
    substitution: Substitution | None = None
    relaxations: list[str] = []
    has_cost_price: bool = False
    alternatives: list[Alternative] = []
    reason: str = ""
    missing_attributes: list[str] = []
    warnings: list[str] = []
    signature: str | None = None
    llm_decision: dict[str, Any] | None = None


class MatchingResult(Contract):
    """Stage 5's output for the drawing: one match per component."""

    drawing_id: DrawingId
    matches: list[ComponentMatch]
    issues: list[StageIssue] = []
    trace_id: TraceId
