"""Quota arithmetic (01 §4.5): the 80% warning, the 100% block, release, unlimited plans, the tenant's month."""

from datetime import UTC, date, datetime

import pytest

from konboro.domain.permissions import Permission, allowed
from konboro.domain.quota import Limits, QuotaState, Usage, counter_for, effective_limits, limit_for, month_start


@pytest.mark.parametrize(
    ("used", "reserved", "state"),
    [
        (0, 0, QuotaState.OK),
        (12, 0, QuotaState.OK),  # the prototype's "12 of 50"
        (40, 0, QuotaState.OK),  # exactly 80%: still only the counter
        (41, 0, QuotaState.NEAR),  # above 80%: "8 left" banner
        (40, 1, QuotaState.NEAR),  # a reservation counts
        (49, 0, QuotaState.NEAR),
        (50, 0, QuotaState.REACHED),
        (49, 1, QuotaState.REACHED),
        (60, 0, QuotaState.REACHED),  # over the limit after a plan downgrade
    ],
)
def test_state_thresholds(used: int, reserved: int, state: QuotaState) -> None:
    assert Usage(limit=50, used=used, reserved=reserved).state is state


def test_near_banner_counts_what_is_left() -> None:
    usage = Usage(limit=50, used=42)
    assert usage.state is QuotaState.NEAR
    assert usage.remaining == 8


def test_block_at_100_percent() -> None:
    assert Usage(limit=50, used=49).can_reserve()
    assert not Usage(limit=50, used=50).can_reserve()
    assert not Usage(limit=50, used=49, reserved=1).can_reserve()


def test_release_frees_the_slot() -> None:
    held = Usage(limit=10, used=9, reserved=1)
    assert not held.can_reserve()
    released = Usage(limit=10, used=9, reserved=0)
    assert released.can_reserve()
    assert released.remaining == 1


def test_extra_raises_the_capacity() -> None:
    usage = Usage(limit=10, used=10, extra=2)
    assert usage.capacity == 12
    assert usage.can_reserve()
    assert usage.remaining == 2


def test_remaining_never_negative() -> None:
    assert Usage(limit=10, used=12).remaining == 0


def test_unlimited() -> None:
    usage = Usage(limit=None, used=10_000, reserved=5)
    assert usage.can_reserve()
    assert usage.state is QuotaState.OK
    assert usage.capacity is None
    assert usage.remaining is None


def test_zero_limit_is_reached_immediately() -> None:
    usage = Usage(limit=0)
    assert usage.state is QuotaState.REACHED
    assert not usage.can_reserve()


def test_override_wins_and_none_falls_back_to_plan() -> None:
    assert effective_limits(50, None, 5, None) == Limits(5, None)
    assert effective_limits(50, 10, None, None) == Limits(50, 10)
    assert effective_limits(50, 10, None, 3) == Limits(50, 3)


def test_audits_use_the_quote_counter_without_their_own_limit() -> None:
    shared = Limits(monthly_quote_limit=50, monthly_audit_limit=None)
    separate = Limits(monthly_quote_limit=50, monthly_audit_limit=10)
    assert counter_for("audit", shared) == "quote"
    assert counter_for("audit", separate) == "audit"
    assert counter_for("quote", separate) == "quote"
    assert limit_for("audit", separate) == 10
    assert limit_for("quote", separate) == 50


def test_month_is_in_the_tenant_timezone() -> None:
    # 22:30 UTC on Oct 31 is already Nov 1 in Jerusalem (UTC+2 in winter).
    late = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
    assert month_start(late, "Asia/Jerusalem") == date(2026, 11, 1)
    assert month_start(late, "UTC") == date(2026, 10, 1)


def test_month_needs_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_start(datetime(2026, 10, 1), "UTC")


def test_owner_has_every_permission_and_unknown_roles_none() -> None:
    assert all(allowed("owner", p) for p in Permission)
    assert not any(allowed("viewer", p) for p in Permission)
