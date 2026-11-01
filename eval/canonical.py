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
DifferenceType = Literal["missing_in_quote", "quantity_mismatch", "extra_in_quote", "possible_double_count"]


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

    @property
    def current_a(self) -> float | None:
        value = self.attributes.get("current_a")
        return float(value) if isinstance(value, int | float) else None

    @property
    def poles(self) -> int | None:
        value = self.attributes.get("poles")
        return int(value) if isinstance(value, int | float) else None


class CanonPanel(Canon):
    name: str
    components: tuple[CanonComponent, ...]


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


class Prediction(Canon):
    """What one pipeline run produced, in the same shape. `None` = the stage produced nothing to score."""

    pages: tuple[CanonPage, ...]
    input_kind: InputKind | None
    panels: tuple[CanonPanel, ...]
    audit: tuple[CanonDifference, ...] | None = None  # the audit flow (11) isn't built yet
    quote_total: Decimal | None = None
    title_block: dict[str, str | None] = {}
    needs_confirmation: bool | None = None
    span_texts: tuple[str, ...] | None = None  # stage 2's normalized text on the process pages
    extraction: dict[str, int] = {}  # stage 2's counts, reported, not scored
