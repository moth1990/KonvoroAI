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
    counted_as: Literal["new_drawing", "revision", "audit"] = Field(
        description="new_drawing: counts once stage 1 succeeds; revision: never counts (S05); audit: POST /audits"
    )


class StageOut(BaseModel):
    stage: int
    name: str = Field(description="Hebrew, as on the new-quote screen")
    status: Literal["queued", "running", "done", "failed", "skipped"]
    summary: str | None = Field(None, description="A short Hebrew summary once the stage is done")


class ProgressFileOut(BaseModel):
    name: str
    page_count: int | None


BomRole = Literal["item", "quantity", "panel", "model", "brand", "unit", "row_number", "price", "other"]


class BomColumnOut(BaseModel):
    index: int
    letter: str = Field(description="The column as Excel names it: A, B, …")
    header: str | None
    role: BomRole
    by: Literal["code", "model", "user"] = Field(description="Who gave the role")
    samples: list[str] = Field(description="The first cells below the header, for the user to recognise the column")


class BomTableOut(BaseModel):
    """A BOM page's table (01 §5.8): its columns and how they were mapped (S14 decision 1)."""

    source: Literal["spreadsheet", "image"]
    sheet: str | None
    mapping_sure: bool = Field(description="False: the user should check the roles before decoding goes on")
    columns: list[BomColumnOut]
    rows: int = Field(description="Product rows, after the row rules")


class BomColumnRoleIn(BaseModel):
    index: int = Field(ge=0)
    role: BomRole


class BomColumnsIn(BaseModel):
    columns: list[BomColumnRoleIn] = Field(min_length=1)


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
    bom: BomTableOut | None = Field(None, description="A BOM page's table, once stage 1 read it")


class NoticeOut(BaseModel):
    """A stage-1 issue for the user (01 §6.5, §8): Hebrew, ready to show."""

    code: str
    severity: Literal["info", "warning", "error"]
    page_id: str | None = None
    message: str


class PageKindIn(BaseModel):
    page_kind: PageKind


class ProgressSummaryOut(BaseModel):
    """The done step's grid (01 §4.6 "סיום"): the products stage 7 priced and how many have a price (S22), and the
    drawing's open findings, stage 6's and pricing's."""

    input_kind: str | None
    panels: list[str]
    page_count: int
    pages_by_route: dict[str, int]
    products: int
    priced: int
    findings: int


ConfirmationReason = Literal["low_confidence", "no_diagram_pages", "panel_count_mismatch", "bom_mapping"]


class ProgressOut(BaseModel):
    drawing_id: str
    name: str = Field(description="The project's name, or else the first file's")
    status: Literal["uploaded", "processing", "awaiting_confirmation", "ready", "failed", "cancelled"]
    current_stage: int | None
    progress: float = Field(ge=0, le=1)
    counted_as: Literal["new_drawing", "revision", "reuse", "audit"]
    counted: bool = Field(description="Whether this upload is counted in the quota right now")
    files: list[ProgressFileOut]
    stages: list[StageOut] = Field(description="Stages 1–7; an audit drawing's are 1–4 and the audit step, 8 (11 §5.1)")
    quote_id: str | None
    audit_id: str | None = Field(None, description="An audit drawing's audit (POST /audits); its results once ready")
    error: str | None = Field(None, description="Hebrew, when the pipeline failed")
    summary: ProgressSummaryOut | None = None
    pages: list[ProgressPageOut] = Field([], description="Once stage 1 is done: when ready, or awaiting confirmation")
    confirmation_reasons: list[ConfirmationReason] = Field(
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
    auxiliary_families: list[str] = Field(description="The audit shows these as not a difference (11 §5.4, S15)")


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
    auxiliary_families: (
        Annotated[list[Annotated[str, Field(pattern=r"^[a-z_]{2,40}$")]], Field(max_length=40)] | None
    ) = None

    @model_validator(mode="after")
    def _only_margins_may_be_null(self) -> "SettingsPatch":
        for name in self.model_fields_set - {"min_line_margin", "min_quote_margin"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"


# --- quote audit (11 §6–8) ----------------------------------------------------------------------

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
RejectReason = Literal["included_elsewhere", "customer_supplies", "system_error", "other"]


class AuditUploadOut(BaseModel):
    audit_id: str
    drawing_id: str
    status: str
    files: list[UploadedFileOut]
    quote_file: UploadedFileOut
    counted_as: Literal["audit"] = Field(
        description="An audit counts once stage 1 succeeds, on the audit counter when the plan has one (11 §4)"
    )


class AuditQuoteRefOut(BaseModel):
    number: str | None
    date: str | None
    total_before_vat: DecimalStr | None


class AuditSummaryOut(BaseModel):
    quote_lines: int
    lines_matched: int
    drawing_components: int
    differences: int
    info_notes: int
    missing_items: int
    value_at_risk: DecimalStr
    missing_items_without_price: int
    over_charged: DecimalStr
    not_differences: int
    to_check: int = Field(description="Differences below 0.6 confidence, shown apart (11 §5.4)")


class AuditEvidenceOut(BaseModel):
    page_no: int
    instance_ids: list[str]


class AuditPriceSourceOut(BaseModel):
    kind: Literal["same_signature", "same_family_poles", "this_line"]
    line_index: int


class AuditSuggestedLineOut(BaseModel):
    description: str
    qty: DecimalStr
    unit_price: DecimalStr | None
    price_source: AuditPriceSourceOut | None


class AuditDifferenceOut(BaseModel):
    diff_id: str
    type: DifferenceType
    severity: Literal["high", "medium", "low", "info"]
    confidence: float
    shown: bool = Field(description="confidence ≥ 0.6; the rest are shown apart, as maybe the system's mistake")
    family: str | None
    designators: list[str]
    drawing_qty: DecimalStr | None
    quote_qty: DecimalStr | None
    quote_line_index: int | None
    evidence: list[AuditEvidenceOut]
    suggested_line: AuditSuggestedLineOut | None
    message: str = Field(description="Hebrew, ready to show")
    amount: DecimalStr | None = Field(description="Money at risk; negative for an over-charge")
    status: Literal["open", "confirmed", "rejected"]
    reject_reason: RejectReason | None
    reject_note: str | None
    component_ids: list[str]
    boxes: list[BoxOut] = Field(description='The evidence on the drawing, for "הצג בשרטוט" (11 §7, S16)')


class AuditLineOut(BaseModel):
    index: int
    description: str
    qty: DecimalStr | None
    unit_price: DecimalStr | None
    total: DecimalStr | None
    confidence: float
    page_no: int | None
    status: Literal["matched", "quantity_differs", "attribute_differs", "not_in_drawing", "arithmetic"]
    includes: list[str] = Field(description='What the line says it includes ("כולל", "+"), 11 §5.2 item 6')
    component_ids: list[str]
    designators: list[str] = Field(description="The matched components' tags on the drawing (S16)")
    matched_qty: DecimalStr | None


class AuditOut(BaseModel):
    audit_id: str
    drawing_id: str
    status: Literal["processing", "ready", "failed"]
    drawing_status: str
    drawing_name: str
    drawing_file_name: str | None
    drawing_number: str | None = Field(description="From the drawing's title block (01 §5.4)")
    quote_file_name: str | None
    input_kind: str | None
    quote_ref: AuditQuoteRefOut | None
    summary: AuditSummaryOut | None
    issues: list[str]
    lines: list[AuditLineOut]
    differences: list[AuditDifferenceOut]
    corrected_quote_id: str | None
    pages: list[PageOut] = Field(description="The audit drawing's pages, for the drawing pane (S16 decision 1)")


class AuditDecisionIn(Strict):
    """11 §7: "נכון, זה הבדל" / "לא נכון" with a reason, or back to open."""

    status: Literal["open", "confirmed", "rejected"]
    reject_reason: RejectReason | None = None
    note: Annotated[str, Field(max_length=500)] | None = None

    @model_validator(mode="after")
    def _reason_when_rejected(self) -> "AuditDecisionIn":
        if self.status == "rejected" and self.reject_reason is None:
            raise ValueError("a rejected difference needs a reason")
        return self


class CorrectedQuoteOut(BaseModel):
    quote_id: str
    created: bool = Field(description="false: the audit already had its corrected quote")


# --- price list (07 §7.2–7.3; S18) --------------------------------------------------------------------------------

PriceSource = Literal["supplier_price_list", "manual_entry", "quote_import", "brand_discount"]
RowSource = Literal["supplier_price_list", "manual_entry", "quote_import"]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class SupplierPriceOut(BaseModel):
    id: str
    supplier_id: str | None = Field(description="null: a cost typed in a quote with no supplier")
    supplier_name: str | None
    supplier_sku: str | None
    unit_cost: DecimalStr
    currency: str
    lead_days: int | None
    price_date: date
    valid_until: date | None
    preferred: bool
    source: str
    in_force: bool = Field(description="Not past `valid_until` today (07 §7.2)")


class PriceHistoryOut(BaseModel):
    id: str
    field: str
    old: dict[str, Any] | None = Field(description='`{"value": …}`, or a whole supplier row; amounts as strings')
    new: dict[str, Any] | None
    quote_id: str | None = Field(description="The quote the change was made from, if any")
    changed_by: str | None
    changed_at: datetime


class DraftUseOut(BaseModel):
    quote_id: str
    quote_name: str
    lines: list[str] = Field(description="Each line's designators, or its description when it has none")


class ProductOut(BaseModel):
    """A price-list product (07 §7.2.1), with its cost and price today by the tenant's rules (07 §7.2.2, §7.3)."""

    id: str
    display_name: str
    manufacturer_sku: str | None
    brand: str | None
    family: str
    unit: str
    sale_mode: Literal["rule", "fixed"]
    fixed_price: DecimalStr | None
    includes: dict[str, Any] | None
    consumable: bool
    source: str
    catalog_item_id: str | None
    list_price: DecimalStr | None = Field(description="The master catalog's manufacturer list price")
    list_currency: str | None
    entered_in_quote: str | None
    entered_by: str | None
    entered_at: datetime | None
    sanity: dict[str, Any] | None = Field(description="10 §8's checks on the last cost typed by hand (10 §9.2)")
    suppliers: list[SupplierPriceOut]
    unit_cost: DecimalStr | None
    price_status: Literal["ok", "stale", "discount_based", "missing"]
    cost_source: dict[str, Any] | None
    unit_price: DecimalStr | None = Field(description="Before 07 §7.6's rounding")
    margin_rule: dict[str, Any] | None
    margin_pct: DecimalStr | None
    below_margin_floor: bool
    entered_in_quote_name: str | None = Field(description="The name of the quote in `entered_in_quote`")
    last_changed_at: datetime | None = Field(description="The newest history row")
    history: list[PriceHistoryOut] = Field(description="Newest first; only on GET of one product")
    used_in_drafts: list[DraftUseOut] = Field(
        description="Drafts whose current version has lines with the product (07 §7.2.3); only on GET of one product"
    )


class SupplierPriceIn(Strict):
    id: str | None = Field(default=None, description="Keep and update this row; without it, a new row")
    supplier_id: str | None = None
    supplier_name: ShortText | None = Field(default=None, description="Finds the supplier by name, or adds it")
    supplier_sku: Annotated[str, Field(max_length=100)] | None = None
    unit_cost: DecimalStr
    currency: Currency = "ILS"
    lead_days: Annotated[int, Field(ge=0, le=3650)] | None = None
    price_date: date
    valid_until: date | None = None
    preferred: bool = False
    source: RowSource = "supplier_price_list"


class ProductIn(Strict):
    display_name: ShortText
    family: Annotated[str, Field(min_length=1, max_length=64)]
    source: PriceSource = "manual_entry"
    manufacturer_sku: Annotated[str, Field(max_length=100)] | None = None
    brand: Annotated[str, Field(max_length=100)] | None = None
    unit: Annotated[str, Field(min_length=1, max_length=20)] = "unit"
    sale_mode: Literal["rule", "fixed"] = "rule"
    fixed_price: DecimalStr | None = None
    includes: dict[str, Any] | None = None
    consumable: bool = False
    catalog_item_id: str | None = None
    suppliers: list[SupplierPriceIn] = Field(default_factory=list, max_length=50)
    quote_id: str | None = Field(default=None, description="The quote the product was entered from (07 §7.2)")


class ProductPatch(Strict):
    """Only the fields sent change. `suppliers`, when sent, is the whole list: rows left out are removed."""

    display_name: ShortText | None = None
    family: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    manufacturer_sku: Annotated[str, Field(max_length=100)] | None = None
    brand: Annotated[str, Field(max_length=100)] | None = None
    unit: Annotated[str, Field(min_length=1, max_length=20)] | None = None
    sale_mode: Literal["rule", "fixed"] | None = None
    fixed_price: DecimalStr | None = None
    includes: dict[str, Any] | None = None
    consumable: bool | None = None
    catalog_item_id: str | None = None
    suppliers: list[SupplierPriceIn] | None = Field(default=None, max_length=50)
    quote_id: str | None = None


class CostCheckIn(Strict):
    """A cost the editor has not saved yet (10 §8, S19 decision 4). With `product_id`, the product's catalog link and
    its previous cost (the row's own with `row_id`); `family` and `brand` are the editor's, sent together."""

    unit_cost: DecimalStr
    currency: Currency = "ILS"
    product_id: str | None = None
    row_id: str | None = Field(default=None, description="The supplier row being edited, if it is saved")
    family: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    brand: Annotated[str, Field(max_length=100)] | None = None


class SanityWarningOut(BaseModel):
    code: Literal["far_from_list", "far_from_similar", "jump_from_previous"]
    reference: DecimalStr = Field(description="The price it was compared with, in the tenant's currency")
    reference_date: date | None = Field(description="When the previous cost was set (`jump_from_previous`)")


class CostCheckOut(BaseModel):
    list_price: DecimalStr | None
    ratio_to_list: DecimalStr | None
    warnings: list[SanityWarningOut] = Field(description="Warnings only: the user can save anyway")


class SupplierOut(BaseModel):
    id: str
    name: str
    product_count: int


class SupplierIn(Strict):
    name: ShortText


class BrandDiscountOut(BaseModel):
    brand: str
    discount_pct: DecimalStr = Field(description="Off the manufacturer's list price: 0.32 is 32%")
    priced_products: int = Field(description="The brand's products this discount prices today")


class BrandDiscountIn(Strict):
    discount_pct: DecimalStr
    quote_id: str | None = Field(default=None, description="The quote it was entered from (09 §7.13)")


RuleLevel = Literal["customer_sku", "customer", "sku", "family", "brand", "default"]


class MarginRuleOut(BaseModel):
    id: str
    level: RuleLevel
    target: str | None = Field(description="The product id (sku levels), the family or the brand")
    customer_id: str | None
    kind: Literal["markup", "margin"]
    value: DecimalStr | None
    fixed_price: DecimalStr | None
    valid_from: date | None
    valid_to: date | None
    version: int


class MarginRuleIn(Strict):
    level: RuleLevel
    kind: Literal["markup", "margin"] = Field(description="Required: a markup and a margin give different prices")
    value: DecimalStr | None = None
    fixed_price: DecimalStr | None = None
    target: str | None = None
    customer_id: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class MarginRulePatch(Strict):
    kind: Literal["markup", "margin"] | None = None
    value: DecimalStr | None = None
    fixed_price: DecimalStr | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class SupplierPreferenceOut(BaseModel):
    scope: Literal["brand", "family"]
    key: str
    supplier_id: str
    supplier_name: str


class SupplierPreferenceIn(Strict):
    supplier_id: str


class LinePriceIn(Strict):
    """09 §7.14: the new sale price per unit, and "רק בהצעה הזו" (`quote`) or "עדכן גם במחירון" (`catalog`)."""

    unit_price: DecimalStr
    scope: Literal["quote", "catalog"]
