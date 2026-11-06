"""Stage 5 → 6: catalog matching, per component (05 §6)."""

from typing import Any, Literal

from pydantic import Field

from .common import ComponentId, Confidence, Contract, DrawingId, StageIssue, TraceId

# Stage 5 adds these to the "read from the drawing" sources of stage 4 (04 §6.2): `series` (fixed by the model code,
# 05 §5.2.1), `notes` / `tenant_default` / `system_default` (filled in, 05 §5.5), `inferred` (from the circuit,
# 05 §5.5.1), `user` (the review screen).
UsedSource = Literal[
    "drawing",
    "cad_attrib",
    "graphic",
    "shared_label",
    "bom",
    "series",
    "notes",
    "inferred",
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
    note: str | None = None  # why, when it was not read: "נבחר לפי F1 (16A)" (05 §5.5.1)


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


class Nearest(Contract):
    """05 §5.9.2 (S27b): a product near a component nothing matched. A suggestion for the user, never a choice."""

    sku: str
    manufacturer: str | None
    description: str
    diff: str  # 05 §5.9's wording: "20A במקום 16A"
    differs: list[str] = []  # the attributes that differ
    catalog_item_id: str | None = None
    product_id: str | None = None  # a factory product (05 §5.6)
    has_cost_price: bool = False


class BundleLine(Contract):
    """A kit's part that the main item needs (05 §5.9.1): the RCD module of "XT1C … משולב פחת". Stage 7 shows it
    as a child line under the device's line."""

    sku: str
    manufacturer: str | None
    description: str
    quantity: int = Field(ge=1)
    reason: str
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
    bundle_lines: list[BundleLine] = []
    reason: str = ""
    missing_attributes: list[str] = []
    warnings: list[str] = []
    signature: str | None = None
    # the match memory's context for a memory written for this match (05 §5.3, §11, 08 §7.4): the customer's brand when
    # the customer's preference chose it, else null (a brand the drawing or its notes name wins over memory anyway)
    brand_context: str | None = None
    llm_decision: dict[str, Any] | None = None
    product_id: str | None = None  # a factory product made in "מוצר חדש" was chosen (05 §5.6, S27b)
    nearest: list[Nearest] = []  # no candidate at all: up to 3 products near it (05 §5.9.2, S27b)


class MatchStats(Contract):
    components: int = 0
    signatures: int = 0  # distinct signatures in a panel and brand context: each matched once (05 §5, §9)
    by_status: dict[str, int] = {}
    by_method: dict[str, int] = {}
    llm_signatures: int = 0  # signatures the agent decided (05 §5.8, target < 15%)
    auxiliary: int = 0


class MatchingResult(Contract):
    """Stage 5's output for the drawing: one match per component, except the components of the tenant's auxiliary
    families (terminals by default), which get no SKU and are listed apart for stage 7 to count (S20 decision 3)."""

    drawing_id: DrawingId
    matches: list[ComponentMatch]
    auxiliary: list[ComponentId] = []
    stats: MatchStats = MatchStats()
    issues: list[StageIssue] = []
    trace_id: TraceId
