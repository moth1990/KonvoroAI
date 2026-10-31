"""Request and response models. Field names are the API contract; `make gen-client` turns them into TS types.

Money and rates are strings in JSON, never numbers (CLAUDE.md non-negotiable 5).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, WithJsonSchema, model_validator

from konboro.domain.quota import QuotaState


def _decimal_from_string(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise ValueError('a decimal must be sent as a string, e.g. "0.15"')
    try:
        return Decimal(value)
    except InvalidOperation as e:
        raise ValueError("not a decimal") from e


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_string),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["0.15"]}),
]

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
