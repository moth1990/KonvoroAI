"""Stage 7 → review screen: the priced quote version (07 §6). Every amount is a decimal string (07 §6.1)."""

from datetime import date
from typing import Any, Literal

from pydantic import Field

from .common import ComponentId, Contract, DecimalStr, DrawingId, IssueId, LineId, PanelId, QtyStr, QuoteId, TraceId

LineStatus = Literal["green", "yellow", "red"]


class CostSource(Contract):
    """07 §7.2: where the cost came from. `price_list_id` is the price-list row (`product_suppliers`); `via` is which
    step of 07 §7.2.2's order chose it (S22)."""

    type: str
    price_list_id: str | None = None
    supplier: str | None = None
    supplier_id: str | None = None
    via: str | None = None
    price_date: date | None = None
    original_currency: str | None = None
    original_cost: DecimalStr | None = None
    fx_rate: DecimalStr | None = None
    fx_date: date | None = None
    list_price: DecimalStr | None = None  # `brand_discount`: the manufacturer's list price and the discount
    discount_pct: DecimalStr | None = None


class MarginRule(Contract):
    """07 §7.3: the rule that set the sale price; `fixed` for a product's fixed price (07 §7.2.1, S18 decision 6)."""

    rule_id: str
    level: str
    kind: Literal["markup", "margin", "fixed"]
    value: DecimalStr | None = None
    fixed_price: DecimalStr | None = None


class Derived(Contract):
    rule_id: str
    rule_key: str | None = None  # the starter rule it copies (`enclosure`, `labor`…), stable across tenants
    from_component_ids: list[ComponentId] = []
    explanation: str
    hours: dict[str, DecimalStr] | None = None  # labor: hours per family (07 §7.4)
    service: bool = False  # a required service from the notes: yellow, no price (07 §7.4)


class StatusReason(Contract):
    source: Literal["confidence", "match", "validator", "price", "missing", "user"]
    status: LineStatus
    value: Any = None
    issue_id: IssueId | None = None
    # S23: the price's pricing issues and the margin floor it fell under (07 §8), and, on a line the estimator
    # approved, the colour the reason had before (09 §7.2)
    issues: list[str] = []
    floor: DecimalStr | None = None
    was: LineStatus | None = None


class Line(Contract):
    line_id: LineId
    line_type: Literal["component", "derived", "labor", "manual", "missing"]
    component_id: ComponentId | None
    component_ids: list[ComponentId] = []  # a merged line's components (07 §6.2, S27b)
    pending: bool = False  # waiting for a decision: no product (07 §7.1, S27b)
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
