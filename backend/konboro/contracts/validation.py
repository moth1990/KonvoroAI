"""Stage 6 → 7: validation (06 §6)."""

from typing import Any, Literal

from .common import Bbox, ComponentId, Confidence, Contract, DrawingId, InstanceId, IssueId, PanelId, Severity, TraceId


class Issue(Contract):
    issue_id: IssueId
    source: Literal["rule", "bom_crosscheck", "agent"]
    rule_id: str
    rule_version: int
    category: Literal["A", "B", "C", "D", "E"]
    severity: Severity
    panel_id: PanelId | None
    component_ids: list[ComponentId] = []
    instance_ids: list[InstanceId] = []
    bbox: Bbox | None = None
    message: str
    values: dict[str, Any] = {}
    confidence: Confidence = 1.0
    status: Literal["open", "resolved", "dismissed"] = "open"


class RowStatusCap(Contract):
    component_id: ComponentId
    max_status: Literal["green", "yellow", "red"]
    issue_ids: list[IssueId]


class PanelSummary(Contract):
    panel_id: PanelId
    hierarchy_available: bool
    main_device_component_id: ComponentId | None = None
    issue_counts: dict[str, int] = {}


class QtyDiff(Contract):
    signature: str
    bom_qty: float
    quote_qty: float


class BomCrosscheck(Contract):
    available: bool
    matched_signatures: int = 0
    missing_in_quote: list[str] = []
    extra_in_quote: list[str] = []
    qty_diffs: list[QtyDiff] = []


class SkippedCheck(Contract):
    rule_id: str
    panel_id: PanelId | None
    reason: str


class ValidationResult(Contract):
    drawing_id: DrawingId
    rules_version: str | None = None
    tenant_rules_version: str | None = None
    issues: list[Issue] = []
    row_status_caps: list[RowStatusCap] = []
    panel_summaries: list[PanelSummary] = []
    bom_crosscheck: BomCrosscheck = BomCrosscheck(available=False)
    checks_run: list[str] = []
    checks_skipped: list[SkippedCheck] = []
    agent_calls: int = 0
    trace_id: TraceId
