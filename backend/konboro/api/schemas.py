"""Request and response models. Field names are the API contract; `make gen-client` turns them into TS types.

Money and rates are strings in JSON, never numbers (CLAUDE.md non-negotiable 5).
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from konboro.contracts.common import DecimalStr
from konboro.contracts.intake import PageKind
from konboro.domain.quota import QuotaState

Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- auth ---------------------------------------------------------------------------------------


class LoginIn(Strict):
    email: Email
    password: Annotated[str, Field(min_length=1, max_length=256)]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (the OAuth token type, not a secret)
    expires_in: int = Field(description="Seconds until the token expires")


class PasswordResetIn(Strict):
    email: Email


# --- account ------------------------------------------------------------------------------------


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str


class TenantOut(BaseModel):
    id: str
    name: str
    timezone: str
    currency: str


class PlanOut(BaseModel):
    """The tenant's effective limits: plan values with the tenant's overrides applied (01 §4.3)."""

    id: str
    name_he: str
    monthly_quote_limit: int | None = Field(description="null = unlimited")
    monthly_audit_limit: int | None = Field(description="null = audits count against the quote limit")
    max_pages_per_file: int


class QuotaCounterOut(BaseModel):
    counter: Literal["quote", "audit"]
    limit: int | None = Field(description="null = unlimited")
    used: int
    reserved: int
    extra: int
    remaining: int | None
    state: QuotaState


class QuotaOut(BaseModel):
    month: date = Field(description="First day of the quota month, in the tenant's timezone")
    counters: list[QuotaCounterOut]


class MeOut(BaseModel):
    user: UserOut
    tenant: TenantOut
    plan: PlanOut
    flags: dict[str, bool] = Field(description="Every flag, evaluated on the server (13 §3.1)")
    quota: QuotaOut


# --- quotes and home ----------------------------------------------------------------------------


class QuoteListItem(BaseModel):
    id: str
    name: str
    version: int = Field(description="The quote's current version number")
    version_status: Literal["draft", "sent"]
    missing_prices: int = Field(description="Live lines of the current version that have no unit price")
    updated_at: datetime


class QuoteList(BaseModel):
    items: list[QuoteListItem]


class MissingPricesItem(BaseModel):
    quote_id: str
    quote_name: str
    count: int


class AuditOmissionsItem(BaseModel):
    audit_id: str
    quote_number: str | None = Field(description="The audited quote's number, from its header (11 §5)")
    count: int
    amount_at_risk: DecimalStr | None = Field(description="Sum of the priced omissions; null when none is priced")


class HomeSummaryOut(BaseModel):
    """The home screen's "waiting for you" card (prototype `vHome`)."""

    queue_pending: int = Field(description="Approval-queue items waiting for a decision")
    missing_prices: list[MissingPricesItem]
    audit_omissions: list[AuditOmissionsItem]


# --- quote review (09 §6, 07 §6) ------------------------------------------------------------------


class SourceOut(BaseModel):
    """Where one attribute's value came from (09 §6.4). `source` is 04 §6.2 / 05 §6.2's, plus `series`, `memory`,
    `circuit` (inferred from the circuit) and `missing`; the screen words each one."""

    attribute: str
    value: str | None
    source: str
    detail: str | None = Field(description="What the source points at, e.g. 'עמוד 1' or 'F22–F25 (3X16A)'")
    confidence: float | None


class StatusReasonOut(BaseModel):
    """One reason for the line's color (07 §7.5). Every reason is shown, not only the worst (09 §9)."""

    source: str
    status: Literal["green", "yellow", "red"]
    value: Any = None
    issue_id: str | None = None


class PriceSourceOut(BaseModel):
    """Where the sale price comes from: a fixed price (and the quotes it was imported from) or a margin rule."""

    kind: str
    source: str | None = None
    quotes: list[str] = []
    value: DecimalStr | None = None


class CostSourceOut(BaseModel):
    type: str
    supplier: str | None = None
    price_date: date | None = None


class AlternativeOut(BaseModel):
    description: str


class DerivedOut(BaseModel):
    """How an accessory line was worked out (07 §7.4): "איך חושב"."""

    rule_id: str | None = None
    explanation: str


class BoxOut(BaseModel):
    """One instance on the drawing: PDF points, origin top left (00 §6.2)."""

    page_id: str
    bbox: list[float] = Field(min_length=4, max_length=4, description="x0, y0, x1, y1")


class LineOut(BaseModel):
    """A quote line (07 §6.2) with what the review screen shows of its component (09 §6.3–6.4)."""

    line_id: str
    line_type: Literal["component", "derived", "labor", "manual", "missing"]
    section: Literal["items", "missing", "extras"] = Field(description="09 §6.3: lines, missing lines, accessories")
    line_group: str | None = Field(description="feed, outputs, control or enclosure (db-schema `line_group`)")
    parent_line_id: str | None
    included: bool = Field(description="A kit add-on whose price is in its parent line's")
    sku: str | None
    description: str
    manufacturer: str | None
    qty: DecimalStr
    unit: str
    unit_price: DecimalStr | None
    unit_cost: DecimalStr | None
    line_total: DecimalStr | None
    line_cost: DecimalStr | None
    margin_pct: DecimalStr | None
    unit_margin: DecimalStr | None = Field(description="Unit price minus unit cost, in shekels")
    price_status: Literal["ok", "stale", "discount_based", "missing"] | None
    price_source: PriceSourceOut | None
    cost_source: CostSourceOut | None
    status: Literal["green", "yellow", "red"]
    status_reasons: list[StatusReasonOut]
    issue_ids: list[str]
    designators: list[str]
    raw_text: list[str] = Field(description="The text read beside the component, line by line")
    sources: list[SourceOut]
    note: str | None = Field(description="The circuit's load, as written in the drawing")
    explanation: str | None = Field(description="Why this product, when it needs saying")
    alternatives: list[AlternativeOut]
    derived: DerivedOut | None
    approved: bool
    boxes: list[BoxOut] = Field(description="Every instance of the line's component, for the drawing (09 §6.5)")


class LineCountsOut(BaseModel):
    green: int
    yellow: int
    red: int


class PanelTotalsOut(BaseModel):
    cost_total: DecimalStr
    price_total: DecimalStr
    line_counts: LineCountsOut
    unpriced_count: int
    uncosted_count: int = Field(description="Priced lines with no cost, left out of the margin (09 §6.3)")


class PanelOut(BaseModel):
    panel_id: str | None
    name: str
    lines: list[LineOut] = Field(description="In the review screen's order (09 §6.3); a child follows its parent")
    totals: PanelTotalsOut


class QuoteTotalsOut(PanelTotalsOut):
    """07 §7.6, summed on the server from the live lines."""

    discount_pct: DecimalStr | None
    discount: DecimalStr | None
    net_total: DecimalStr = Field(description="Before VAT")
    margin_abs: DecimalStr
    margin_pct: DecimalStr | None
    vat_rate: DecimalStr
    vat: DecimalStr
    gross_total: DecimalStr


class FindingOut(BaseModel):
    finding_id: str
    severity: Literal["error", "warning", "info"]
    code: str
    title: str | None
    message: str
    line_ids: list[str]
    page_no: int | None
    page_id: str | None
    bbox: list[float] | None = Field(description='Where the finding is on the page, for "בשרטוט"')


class PagePanelOut(BaseModel):
    panel_id: str
    name: str
    bbox: list[float] | None = Field(description="The panel's area on this page, if the classifier boxed it")


class PageOut(BaseModel):
    """One page of the quote's drawing, for the drawing pane (09 §6.5)."""

    page_id: str
    page_no: int
    sheet: str | None = Field(description="The page's own drawing number, e.g. E-104")
    page_kind: str | None
    page_kind_confidence: float | None
    classified_by: Literal["model", "user", "reused", "template"] | None
    route: Literal["process", "context", "skip"] | None
    quality: str | None
    geometry_source: str | None = Field(description="vector or raster")
    width_pt: float | None
    height_pt: float | None
    panels: list[PagePanelOut]
    thumbnail_url: str | None = Field(None, description="Short-lived; load it, don't store it")
    has_viewer: bool = Field(description="GET /pages/{page_id}/dz/page.dzi serves the page's pyramid")
    red_count: int = Field(description="Red lines with an instance on the page")
    yellow_count: int


class QuoteOut(BaseModel):
    """The review screen's quote (09 §4): its current version, panels, lines, findings and totals."""

    quote_id: str
    name: str
    drawing_id: str | None
    drawing_number: str | None
    input_kind: Literal["factory_drawing", "designer_plan", "bom_only", "mixed"] | None
    version: int
    status: Literal["draft", "sent"]
    revision: int
    quote_date: date | None
    currency: str
    coverage_pct: int | None = Field(description="Share of the lines that have a price (09 §6.1, 10 §7)")
    panels: list[PanelOut]
    findings: list[FindingOut] = Field(description="Open findings, errors first")
    totals: QuoteTotalsOut
    pages: list[PageOut] = Field(description="The drawing's pages, in order")


# --- drawings (01 §4, §4.6) ----------------------------------------------------------------------------


class UploadedFileOut(BaseModel):
    """One file of an upload. A rejected upload lists every file, each with its own error (01 §4.3)."""

    name: str
    size_bytes: int
    detected_format: str | None
    page_count: int | None
    error: str | None = Field(None, description="01 §8 code, e.g. cad_not_supported")
    message: str | None = Field(None, description="Hebrew, ready to show next to the file")


class UploadOut(BaseModel):
    drawing_id: str
    status: str
    files: list[UploadedFileOut]
    counted_as: Literal["new_drawing", "revision"] = Field(
        description="new_drawing: counts once stage 1 succeeds; revision: never counts (S05)"
    )


class StageOut(BaseModel):
    stage: int
    name: str = Field(description="Hebrew, as on the new-quote screen")
    status: Literal["queued", "running", "done", "failed", "skipped"]
    summary: str | None = Field(None, description="A short Hebrew summary once the stage is done")


class ProgressFileOut(BaseModel):
    name: str
    page_count: int | None


class ProgressPageOut(BaseModel):
    page_id: str
    page_no: int
    file_name: str
    route: Literal["process", "context", "skip"] | None
    page_kind: PageKind | None
    page_kind_confidence: float | None = None
    classified_by: Literal["model", "user", "reused", "template"] | None = None
    unsure: bool = Field(False, description="Below the confirmation threshold and not settled by the user (01 §5.6)")
    thumbnail_url: str | None = Field(None, description="Short-lived; load it, don't store it")


class NoticeOut(BaseModel):
    """A stage-1 issue for the user (01 §6.5, §8): Hebrew, ready to show."""

    code: str
    severity: Literal["info", "warning", "error"]
    page_id: str | None = None
    message: str


class PageKindIn(BaseModel):
    page_kind: PageKind


class ProgressSummaryOut(BaseModel):
    """The done step's grid (01 §4.6 "סיום"). Products, prices and findings stay 0 until stages 4–7 are real."""

    input_kind: str | None
    panels: list[str]
    page_count: int
    pages_by_route: dict[str, int]
    products: int
    priced: int
    findings: int


class ProgressOut(BaseModel):
    drawing_id: str
    name: str = Field(description="The project's name, or else the first file's")
    status: Literal["uploaded", "processing", "awaiting_confirmation", "ready", "failed", "cancelled"]
    current_stage: int | None
    progress: float = Field(ge=0, le=1)
    counted_as: Literal["new_drawing", "revision", "reuse"]
    counted: bool = Field(description="Whether this upload is counted in the quota right now")
    files: list[ProgressFileOut]
    stages: list[StageOut]
    quote_id: str | None
    error: str | None = Field(None, description="Hebrew, when the pipeline failed")
    summary: ProgressSummaryOut | None = None
    pages: list[ProgressPageOut] = Field([], description="Once stage 1 is done: when ready, or awaiting confirmation")
    confirmation_reasons: list[Literal["low_confidence", "no_diagram_pages", "panel_count_mismatch"]] = Field(
        [], description="Why the pages need the user's confirmation (01 §5.6); empty when they don't"
    )
    notices: list[NoticeOut] = []


class RevisableOut(BaseModel):
    """A finished drawing a new version can follow (01 §4.6 item 1)."""

    drawing_id: str
    name: str
    version: int
    updated_at: datetime


# --- settings -----------------------------------------------------------------------------------

EnclosurePart = Literal["busbar", "n", "pe", "panels", "doors"]
AttributeValue = str | int | bool
Margin = Annotated[DecimalStr, Field(ge=0, lt=1)]


class SettingsOut(BaseModel):
    brand_preferences: dict[str, str]
    attribute_defaults: dict[str, dict[str, AttributeValue]]
    enclosure_includes_default: dict[EnclosurePart, bool]
    min_line_margin: DecimalStr | None
    min_quote_margin: DecimalStr | None
    stale_days: int
    labor: dict[str, Any]
    rounding: str


class SettingsPatch(Strict):
    """Only the fields sent are changed. A dict field is replaced as a whole. Flags are not here (S03 decision).

    `null` clears a margin floor; the other fields cannot be null.
    """

    brand_preferences: dict[str, str] | None = None
    attribute_defaults: dict[str, dict[str, AttributeValue]] | None = None
    enclosure_includes_default: dict[EnclosurePart, bool] | None = None
    min_line_margin: Margin | None = None
    min_quote_margin: Margin | None = None
    stale_days: Annotated[int, Field(ge=1, le=3650)] | None = None

    @model_validator(mode="after")
    def _only_margins_may_be_null(self) -> "SettingsPatch":
        for name in self.model_fields_set - {"min_line_margin", "min_quote_margin"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
