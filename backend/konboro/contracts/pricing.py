"""Stage 7 → review screen: the priced quote version (07 §6). Every amount is a decimal string (07 §6.1)."""

from datetime import date
from typing import Any, Literal

from pydantic import Field

from .common import ComponentId, Contract, DecimalStr, DrawingId, IssueId, LineId, PanelId, QtyStr, QuoteId, TraceId

LineStatus = Literal["green", "yellow", "red"]


class CostSource(Contract):
    type: str
    price_list_id: str | None = None
    supplier: str | None = None
    price_date: date | None = None
    original_currency: str | None = None
    fx_rate: DecimalStr | None = None


class MarginRule(Contract):
    rule_id: str
    level: str
    kind: Literal["markup", "margin"]
    value: DecimalStr


class Derived(Contract):
    rule_id: str
    from_component_ids: list[ComponentId] = []
    explanation: str


class StatusReason(Contract):
    source: Literal["confidence", "match", "validator", "price", "missing", "user"]
    status: LineStatus
    value: Any = None
    issue_id: IssueId | None = None


class Line(Contract):
    line_id: LineId
    line_type: Literal["component", "derived", "labor", "manual", "missing"]
    component_id: ComponentId | None
    sku: str | None
    description: str
    manufacturer: str | None
    qty: QtyStr = Field(description="numeric(12,3): products sold by the metre can be fractional")
    unit_cost: DecimalStr | None
    cost_source: CostSource | None = None
    price_status: Literal["ok", "stale", "discount_based", "missing"]
    margin_rule: MarginRule | None = None
    unit_price_raw: DecimalStr | None
    unit_price: DecimalStr | None
    rounding: str | None = None
    line_cost: DecimalStr | None
    line_total: DecimalStr | None
    margin_pct: DecimalStr | None
    parent_line_id: LineId | None = None
    is_derived: bool = False
    derived: Derived | None = None
    status: LineStatus
    status_reasons: list[StatusReason] = []
    issue_ids: list[IssueId] = []
    override: dict[str, Any] | None = None


class LineCounts(Contract):
    green: int = 0
    yellow: int = 0
    red: int = 0


class PanelTotals(Contract):
    cost_total: DecimalStr
    price_total: DecimalStr
    line_counts: LineCounts = LineCounts()
    unpriced_count: int = 0


class QuotePanel(Contract):
    panel_id: PanelId
    name: str
    lines: list[Line] = []
    totals: PanelTotals


class Discount(Contract):
    pct: DecimalStr
    amount: DecimalStr


class QuoteTotals(Contract):
    cost_total: DecimalStr
    price_total: DecimalStr
    discount: Discount | None = None
    net_total: DecimalStr
    margin_abs: DecimalStr
    margin_pct: DecimalStr | None
    vat_rate: DecimalStr
    vat: DecimalStr
    gross_total: DecimalStr
    line_counts: LineCounts = LineCounts()
    unpriced_count: int = 0


class PricingIssue(Contract):
    code: str
    line_id: LineId | None = None
    message: str


class Snapshot(Contract):
    price_list_ids: list[str] = []
    margin_rules_version: str | None = None
    derived_rules_version: str | None = None
    fx_rates: list[dict[str, Any]] = []
    vat_rate_id: str | None = None


class QuoteVersionResult(Contract):
    quote_id: QuoteId
    version: int = Field(ge=1)
    status: Literal["draft", "sent"]
    drawing_id: DrawingId | None
    tenant_id: str
    customer_id: str | None = None
    currency: str = "ILS"
    quote_date: date | None = None
    panels: list[QuotePanel] = []
    totals: QuoteTotals
    pricing_issues: list[PricingIssue] = []
    snapshot: Snapshot = Snapshot()
    trace_id: TraceId
