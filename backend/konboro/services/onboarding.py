"""A new factory's entry (10 §5.1, §9.1, S24): two questions and the data terms, then the onboarding counters.

Nothing is required before the first drawing but the two questions and the terms (10 §1, principle 1). The markup
answer is the factory's `default` `markup` margin rule (07 §7.3); the brands are its brand preference per family
(05 §5.4, priority 4), and a skipped family, or "אחר", sets none (S24 decision 7: stage 5 cannot prefer a brand
with no name). The terms are recorded with their version, the user and the time (00 §11).

Behind the `onboarding` flag: when it is off, nothing here gates an upload. Runs inside `tenant_session`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.domain.flags import is_enabled
from konboro.services import flags
from konboro.services import price_list as pl

FLAG = "onboarding"
TERMS_VERSION = "2026-10"  # 10 §9.1
BRAND_FAMILIES = ("circuit_breaker", "rcd")  # 10 §5.1 question 2: breakers and RCDs
BRANDS = ("Schneider", "ABB", "Hager")  # the question's options; "אחר" is `other`
OTHER = "other"
MAX_MARKUP = Decimal("5")  # 500%: anything above is a typing mistake, not a markup

COUNTERS: dict[str, Any] = {
    "first_drawing_at": None,
    "first_quote_sent_at": None,
    "quotes_sent": 0,
    "price_coverage_last": 0.0,
    "accelerators_offered": [],
    "accelerators_used": [],
}


class OnboardingError(Exception):
    def __init__(self, status: int, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.field = field


def enabled(session: Session, tenant_id: str) -> bool:
    return is_enabled(flags.tenant_flags(session, tenant_id), FLAG)


def _settings(session: Session, tenant_id: str) -> m.TenantSettings:
    row = session.get(m.TenantSettings, tenant_id)
    if row is None:
        row = m.TenantSettings(tenant_id=tenant_id)
        session.add(row)
        session.flush()
        session.refresh(row)
    return row


def terms_accepted(session: Session, tenant_id: str) -> bool:
    row = session.get(m.TenantSettings, tenant_id)
    return bool(row and row.data_terms_accepted)


def required(session: Session, tenant_id: str) -> bool:
    """The flag is on and the terms are not accepted: the onboarding page comes first, and uploads wait."""
    return enabled(session, tenant_id) and not terms_accepted(session, tenant_id)


def default_rule(session: Session, tenant_id: str) -> m.MarginRule | None:
    """The factory's `default` rule, the one the markup question and the settings screen set (07 §7.3)."""
    return session.scalar(
        select(m.MarginRule)
        .where(m.MarginRule.tenant_id == tenant_id, m.MarginRule.level == "default")
        .order_by(m.MarginRule.created_at, m.MarginRule.id)
        .limit(1)
    )


def default_markup(session: Session, tenant_id: str) -> Decimal | None:
    rule = default_rule(session, tenant_id)
    return rule.value if rule is not None and rule.kind == "markup" else None


def check_markup(value: Decimal) -> None:
    if not value.is_finite() or value < 0 or value > MAX_MARKUP:
        raise OnboardingError(422, "validation_error", "markup")


def set_default_markup(session: Session, tenant_id: str, user_id: str | None, value: Decimal) -> None:
    """Changes the `default` rule to a markup of `value`, or creates it; the price list's history logs it."""
    check_markup(value)
    actor = pl.Actor(tenant_id=tenant_id, user_id=user_id)
    rule = default_rule(session, tenant_id)
    if rule is None:
        pl.create_margin_rule(session, actor, {"level": "default", "kind": "markup", "value": value})
    else:
        pl.update_margin_rule(session, actor, rule.id, {"kind": "markup", "value": value, "fixed_price": None})


def check_brands(brands: dict[str, str | None]) -> None:
    for family, brand in brands.items():
        if family not in BRAND_FAMILIES:
            raise OnboardingError(422, "validation_error", f"brands.{family}")
        if brand is not None and brand not in (*BRANDS, OTHER):
            raise OnboardingError(422, "validation_error", f"brands.{family}")


def set_brands(row: m.TenantSettings, brands: dict[str, str | None]) -> None:
    """A brand sets the family's preference; none, or "אחר", removes it. Other families are left alone."""
    check_brands(brands)
    prefs = dict(row.brand_preferences or {})
    for family, brand in brands.items():
        if brand in BRANDS:
            prefs[family] = brand
        else:
            prefs.pop(family, None)
    row.brand_preferences = prefs


@dataclass(frozen=True)
class OnboardingState:
    required: bool
    terms_version: str
    terms_accepted_at: str | None
    markup: Decimal | None
    brands: dict[str, str | None]


def state(session: Session, tenant_id: str) -> OnboardingState:
    row = _settings(session, tenant_id)
    prefs = row.brand_preferences or {}
    answers = (row.onboarding or {}).get("brands") or {}
    terms = row.data_terms_accepted or {}
    return OnboardingState(
        required=enabled(session, tenant_id) and not terms,
        terms_version=TERMS_VERSION,
        terms_accepted_at=terms.get("at"),
        markup=default_markup(session, tenant_id),
        brands={f: prefs.get(f) or (OTHER if answers.get(f) == OTHER else None) for f in BRAND_FAMILIES},
    )


def answer(
    session: Session,
    tenant_id: str,
    user_id: str,
    *,
    markup: Decimal,
    brands: dict[str, str | None],
    accept_terms: bool,
) -> OnboardingState:
    """The two questions and the terms, in one step (10 §5.1). The terms must be accepted to finish."""
    if not accept_terms:
        raise OnboardingError(422, "terms_required", "accept_terms")
    check_markup(markup)
    check_brands(brands)
    row = _settings(session, tenant_id)
    set_default_markup(session, tenant_id, user_id, markup)
    set_brands(row, brands)
    now = datetime.now(UTC).isoformat()
    row.data_terms_accepted = {"version": TERMS_VERSION, "by": user_id, "at": now}
    row.onboarding = {
        **COUNTERS,
        **(row.onboarding or {}),
        "answered_at": now,
        "markup_source": "onboarding_question",  # 10 §9.1 default_margin_rule.source
        "brands": {f: brands.get(f) for f in BRAND_FAMILIES},
    }
    session.flush()
    return state(session, tenant_id)


def _counters(row: m.TenantSettings) -> dict[str, Any]:
    return {**COUNTERS, **(row.onboarding or {})}


def note_drawing(session: Session, tenant_id: str) -> None:
    """The first drawing's time (10 §7.2: from signup to the first drawing)."""
    row = _settings(session, tenant_id)
    counters = _counters(row)
    if counters["first_drawing_at"] is None:
        row.onboarding = {**counters, "first_drawing_at": datetime.now(UTC).isoformat()}
        session.flush()


def note_quote_sent(session: Session, tenant_id: str, coverage_pct: int | None) -> None:
    """A sent quote counts; its price coverage is the last one (10 §7.1, §9.1)."""
    row = _settings(session, tenant_id)
    counters = _counters(row)
    now = datetime.now(UTC).isoformat()
    row.onboarding = {
        **counters,
        "first_quote_sent_at": counters["first_quote_sent_at"] or now,
        "quotes_sent": int(counters["quotes_sent"] or 0) + 1,
        "price_coverage_last": round((coverage_pct or 0) / 100, 4),
    }
    session.flush()


def first_quote(session: Session, tenant_id: str) -> bool:
    """The factory has sent no quote yet: the review screen says its prices are an investment (10 §5.2)."""
    if not enabled(session, tenant_id):
        return False
    row = session.get(m.TenantSettings, tenant_id)
    return int(_counters(row)["quotes_sent"] or 0) == 0 if row is not None else True
