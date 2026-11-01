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
