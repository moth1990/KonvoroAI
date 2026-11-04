"""The canonical schema (dev-strategy §6): one shape for every golden label file, and for what the pipeline
produced, so each metric is written once.

A golden drawing has:
- `pages[{no, kind, route}]` and `input_kind` (stage 1, 01 §10);
- `panels[{name, components[{family, attributes, designators, qty}]}]` (stage 4, 04 §10);
- `audit{matched, differences[{type, item, designators, value_at_risk}]}` (11 §10), from `actual_quote.json`;
- `quote_total`: the real quote's total before VAT (07 §10.2 backtest).
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from konboro.contracts.intake import InputKind, PageKind, Route

SupplyScope = Literal["in_panel", "other_location", "prepare_only", "by_others"]
DifferenceType = Literal[
    "missing_in_quote",
    "quantity_mismatch",
    "extra_in_quote",
    "possible_double_count",
    "attribute_mismatch",
    "arithmetic",
]


class Canon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonPage(Canon):
    no: int
    kind: PageKind
    route: Route | None  # None only when nothing tells us; the normalizer fills it from the kind when it can


class CanonComponent(Canon):
    family: str
    designators: tuple[str, ...] = ()
    attributes: dict[str, Any] = {}  # current_a, poles, … as numbers; only what the label (or the stage) states
    qty: int
    supply_scope: SupplyScope = "in_panel"
    label: str = ""  # the product name in the label, for the report only
    pages: tuple[int, ...] = ()  # where the label says it is drawn, when it says (stage 2's designator recall)
    ref: str | None = None  # predictions only: the component's id, to find its stage-5 match

    @property
    def current_a(self) -> float | None:
        value = self.attributes.get("current_a")
        return float(value) if isinstance(value, int | float) else None

    @property
    def poles(self) -> int | None:
        value = self.attributes.get("poles")
        return int(value) if isinstance(value, int | float) else None


class CanonMatch(Canon):
    """Stage 5's match of one component (05 §6), as the metrics read it. On labelled input (05 §10) `label` holds the
    labelled current, poles and neutral the match was asked for, and `in_catalog` whether the catalog has an active
    item of the family with them."""

    ref: str
    family: str
    status: str
    sku: str | None = None
    item: dict[str, Any] = {}  # the chosen item's attributes
    method: str | None = None
    signature: str | None = None
    label: dict[str, Any] = {}
    in_catalog: bool | None = None


class CanonPanel(Canon):
    name: str
    components: tuple[CanonComponent, ...]
    verified: bool = True  # a labelled panel nobody checked (25.26.100's sub-panel): counted as a panel, not scored


class CanonDifference(Canon):
    type: DifferenceType
    item: str
    designators: tuple[str, ...] = ()
    value_at_risk: Decimal | None = None
    confidence: float | None = None  # predictions only: 11 §10 scores the differences shown at ≥ 0.6


class CanonAudit(Canon):
    matched: int | None  # quote lines that match the drawing
    differences: tuple[CanonDifference, ...]  # factory-confirmed only


class Checksums(Canon):
    """The counts a label file documents about itself, for the normalizer tests (S06 acceptance)."""

    products: int
    units: int


class GoldenDrawing(Canon):
    id: str  # the golden folder name
    file: str
    input_kind: InputKind
    pages: tuple[CanonPage, ...]  # empty when the label has no page list (a photo of a BOM)
    panels: tuple[CanonPanel, ...]
    audit: CanonAudit | None = None
    quote_total: Decimal | None = None
    checksums: Checksums | None = None  # when the label file documents its own counts
    title_block: dict[str, str] = {}  # only the fields the label states (01 §10: accuracy per field)

    @property
    def products(self) -> int:
        return sum(len(p.components) for p in self.panels)

    @property
    def units(self) -> int:
        return sum(c.qty for p in self.panels for c in p.components)


class CanonDetection(Canon):
    """One of stage 3's detections, as the metrics read it (S12)."""

    page_no: int
    family: str
    role: str
    designator: str | None
    bbox: tuple[float, float, float, float]
    billable: bool


class CanonFinding(Canon):
    """One of stage 6's issues (06 §6.2), as the metrics read it (S21)."""

    rule_id: str
    severity: str
    source: str
    category: str
    designators: tuple[str, ...] = ()
    bug_net: bool = False  # a category-D safety net that should never fire (06 §6.2)


class CanonInjected(Canon):
    """One error put into a correct quote (06 §10.1, S21 decision 3) and whether the rules caught it."""

    kind: str
    target: str  # what was changed, for the report
    applicable: bool  # the drawing has the data a rule needs to see it (a main device, a front view, a BOM)
    caught: bool
    rule_ids: tuple[str, ...] = ()  # the new findings on what was changed


class Prediction(Canon):
    """What one pipeline run produced, in the same shape. `None` = the stage produced nothing to score."""

    pages: tuple[CanonPage, ...]
    input_kind: InputKind | None
    panels: tuple[CanonPanel, ...]
    audit: tuple[CanonDifference, ...] | None = None  # the audit's differences, when the drawing has a quote (S15)
    quote_total: Decimal | None = None
    # the backtest (07 §10.2, `eval/backtest.py`): own-quote and leave-one-out totals and coverage, decimal strings
    backtest: dict[str, str | None] = {}
    title_block: dict[str, str | None] = {}
    needs_confirmation: bool | None = None
    span_texts: tuple[str, ...] | None = None  # stage 2's normalized text on the process pages
    extraction: dict[str, int] = {}  # stage 2's counts, reported, not scored
    detections: tuple[CanonDetection, ...] | None = None  # stage 3's, on the process pages
    detection: dict[str, int] = {}  # stage 3's counts: detections, orphan texts, disambiguation calls
    merge: dict[str, int] = {}  # stage 4's counts: agent tiles, cited values, mismatches, values with no evidence
    matches: tuple[CanonMatch, ...] | None = None  # stage 5's, end to end
    matching: dict[str, int] = {}  # stage 5's counts: signatures, the agent's, by status and method
    labelled_matches: tuple[CanonMatch, ...] | None = None  # stage 5 on the labelled attributes (05 §10)
    findings: tuple[CanonFinding, ...] | None = None  # stage 6's, end to end
    validation: dict[str, int] = {}  # stage 6's counts: agent calls, checks run and skipped
    labelled_findings: tuple[CanonFinding, ...] | None = None  # stage 6 on the labelled (correct) quote, rules only
    injected: tuple[CanonInjected, ...] | None = None  # the injected-error set (06 §10.1)
