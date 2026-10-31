"""Monthly quota arithmetic (01 §4.5). Pure: the atomic reserve, confirm and release live in konboro.services.quota.

A reservation counts as taken: two uploads at once must not get past the limit, so the warning and the
block both look at `used + reserved`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

Counter = Literal["quote", "audit"]
Purpose = Literal["quote", "audit"]

# 01 §4.5: up to 80% only the settings counter, above 80% the `quota_near` banner, at 100% `quota_reached`.
NEAR_NUMERATOR, NEAR_DENOMINATOR = 4, 5


class QuotaState(StrEnum):
    OK = "ok"
    NEAR = "quota_near"
    REACHED = "quota_reached"


@dataclass(frozen=True)
class Limits:
    """Effective monthly limits. `None` quote limit = unlimited; `None` audit limit = audits count as quotes."""

    monthly_quote_limit: int | None
    monthly_audit_limit: int | None


def effective_limits(
    plan_quote: int | None,
    plan_audit: int | None,
    override_quote: int | None = None,
    override_audit: int | None = None,
) -> Limits:
    """A tenant override wins over the plan; `None` in the override means "use the plan's value" (01 §4.3)."""
    return Limits(
        monthly_quote_limit=override_quote if override_quote is not None else plan_quote,
        monthly_audit_limit=override_audit if override_audit is not None else plan_audit,
    )


def counter_for(purpose: Purpose, limits: Limits) -> Counter:
    """Audits use their own counter only when the plan gives them a separate limit (01 §4.5, 11)."""
    if purpose == "audit" and limits.monthly_audit_limit is not None:
        return "audit"
    return "quote"


def limit_for(counter: Counter, limits: Limits) -> int | None:
    return limits.monthly_audit_limit if counter == "audit" else limits.monthly_quote_limit


def month_start(now: datetime, timezone: str) -> date:
    """The quota month is the calendar month in the tenant's timezone (01 §4.5)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(timezone)).date().replace(day=1)


@dataclass(frozen=True)
class Usage:
    limit: int | None
    used: int = 0
    reserved: int = 0
    extra: int = 0

    @property
    def capacity(self) -> int | None:
        return None if self.limit is None else self.limit + self.extra

    @property
    def taken(self) -> int:
        return self.used + self.reserved

    @property
    def remaining(self) -> int | None:
        return None if self.capacity is None else max(self.capacity - self.taken, 0)

    def can_reserve(self) -> bool:
        return self.capacity is None or self.taken < self.capacity

    @property
    def state(self) -> QuotaState:
        if self.capacity is None:
            return QuotaState.OK
        if self.taken >= self.capacity:
            return QuotaState.REACHED
        if self.taken * NEAR_DENOMINATOR > self.capacity * NEAR_NUMERATOR:
            return QuotaState.NEAR
        return QuotaState.OK
