"""The audit step → the audit screen: an existing quote compared with its drawing (11 §6).

The audit step runs after stage 4 on a drawing uploaded for an audit (S15 decision 2), reads stage 1's pages and
stage 4's components, reads the quote, and writes this contract to S3 and its rows to `audits`,
`audit_quote_lines` and `audit_differences`. Every amount is a decimal string (CLAUDE.md non-negotiable 5).
"""

from typing import Annotated, Any, Literal

from pydantic import Field

from .common import (
    Bbox,
    ComponentId,
    Confidence,
    Contract,
    DecimalStr,
    DrawingId,
    InstanceId,
    QtyStr,
    TenantId,
    TraceId,
    _id,
)

AuditId = Annotated[str, _id("aud")]
DifferenceId = Annotated[str, _id("dif")]

# 11 §5.4, and `not_a_difference` for a tenant's auxiliary material (S15 decision 4)
DifferenceType = Literal[
    "missing_in_quote",
    "qty_short",
    "qty_over",
    "possible_double_count",
    "attribute_mismatch",
    "extra_in_quote",
    "arithmetic",
    "drawing_conflict",
    "not_a_difference",
]
DifferenceSeverity = Literal["high", "medium", "low", "info"]
LineStatus = Literal["matched", "quantity_differs", "attribute_differs", "not_in_drawing", "arithmetic"]
PriceSourceKind = Literal["same_signature", "same_family_poles", "this_line"]


class QuoteRef(Contract):
    number: str | None
    date: str | None
    total_before_vat: DecimalStr | None


class AuditSummary(Contract):
    quote_lines: int
    lines_matched: int
    drawing_components: int
    differences: int = Field(description="Every type but drawing_conflict and not_a_difference")
    info_notes: int = Field(description="drawing_conflict")
    missing_items: int = Field(description="Units the quote leaves out: missing_in_quote and qty_short")
    value_at_risk: DecimalStr = Field(description="Shown differences (confidence ≥ 0.6) with a price (11 §5.5)")
    missing_items_without_price: int
    over_charged: DecimalStr = Field(description="qty_over and possible_double_count, not in the value at risk")
    not_differences: int = 0
    to_check: int = Field(0, description="Differences below 0.6: shown apart (11 §5.4)")


class Evidence(Contract):
    page_no: int
    instance_ids: list[InstanceId] = []


class PriceSource(Contract):
    kind: PriceSourceKind
    line_index: int


class SuggestedLine(Contract):
    description: str
    qty: QtyStr
    unit_price: DecimalStr | None
    price_source: PriceSource | None


class Difference(Contract):
    diff_id: DifferenceId
    type: DifferenceType
    severity: DifferenceSeverity
    confidence: Confidence
    family: str | None
    designators: list[str] = []
    drawing_qty: QtyStr | None
    quote_qty: QtyStr | None
    quote_line_index: int | None
    evidence: list[Evidence] = []
    suggested_line: SuggestedLine | None = None
    message: str
    amount: DecimalStr | None = None
    status: Literal["open", "confirmed", "rejected"] = "open"
    component_ids: list[ComponentId] = []


class AuditedLine(Contract):
    """A quote line as the audit read it, signed and matched (11 §7: matched / quantity / attribute / not drawn)."""

    index: int
    text: str
    qty: QtyStr | None
    unit_price: DecimalStr | None
    total: DecimalStr | None
    confidence: Confidence
    page_no: int | None = None
    rows: list[int] = []
    bbox: Bbox | None = None
    signature: dict[str, Any]
    status: LineStatus
    component_ids: list[ComponentId] = []
    matched_qty: QtyStr | None = None


class AuditResult(Contract):
    audit_id: AuditId
    tenant_id: TenantId
    drawing_id: DrawingId
    quote_ref: QuoteRef
    input_kind: str | None
    summary: AuditSummary
    differences: list[Difference]
    lines: list[AuditedLine] = []
    issues: list[str] = []
    trace_id: TraceId
