"""Quota in the DB (01 §4.5): atomic reservations, confirm and release, 24 h expiry, the events log."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.domain.quota import QuotaState
from konboro.services import quota

from .db import database_dsn
from .factory import GLOBAL_PLAN

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
MONTH = date(2026, 10, 1)


def make_tenant(engine: Engine, limit: int | None, audit_limit: int | None = None) -> str:
    tid = new_id("tnt")
    with tenant_session(tid, engine) as s:
        s.add(m.Tenant(id=tid, name="מפעל מכסה", plan_id=GLOBAL_PLAN))
        s.flush()
        s.add(m.TenantPlanOverride(tenant_id=tid, monthly_quote_limit=limit, monthly_audit_limit=audit_limit))
    return tid


def usage(engine: Engine, tid: str, counter: str = "quote") -> tuple[int, int]:
    with tenant_session(tid, engine) as s:
        row = s.scalars(select(m.QuotaUsage).where(m.QuotaUsage.counter == counter)).one()
        return row.used, row.reserved


def events(engine: Engine, tid: str) -> list[str]:
    with tenant_session(tid, engine) as s:
        return [e.kind for e in s.scalars(select(m.QuotaEvent).order_by(m.QuotaEvent.id)).all()]


@pytest.fixture
def app_engine(migrated_db: dict[str, Engine]) -> Engine:
    return migrated_db["app"]


def test_twenty_concurrent_reserves_against_ten_give_exactly_ten(migrated_db: dict[str, Engine]) -> None:
    engine = create_engine(database_dsn("konboro_test", role="app"), pool_size=20, max_overflow=0)
    tid = make_tenant(migrated_db["app"], limit=10)

    def attempt(_: int) -> bool:
        try:
            with tenant_session(tid, engine) as s:
                quota.reserve(s, tid, now=NOW)
            return True
        except quota.QuotaReachedError:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))
    engine.dispose()

    assert results.count(True) == 10
    assert usage(migrated_db["app"], tid) == (0, 10)
    assert events(migrated_db["app"], tid).count("reserve") == 10


def test_confirm_moves_reserved_to_used_and_logs_it(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=5)
    with tenant_session(tid, app_engine) as s:
        rid = quota.reserve(s, tid, now=NOW)
    with tenant_session(tid, app_engine) as s:
        quota.confirm(s, tid, rid)
    assert usage(app_engine, tid) == (1, 0)
    assert events(app_engine, tid) == ["reserve", "confirm"]


def test_release_frees_the_slot_and_is_idempotent(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=1)
    with tenant_session(tid, app_engine) as s:
        rid = quota.reserve(s, tid, now=NOW)
    with tenant_session(tid, app_engine) as s, pytest.raises(quota.QuotaReachedError):
        quota.reserve(s, tid, now=NOW)
    with tenant_session(tid, app_engine) as s:
        assert quota.release(s, tid, rid, "upload_rejected") is True
        assert quota.release(s, tid, rid, "upload_rejected") is False
    assert usage(app_engine, tid) == (0, 0)
    with tenant_session(tid, app_engine) as s:
        quota.reserve(s, tid, now=NOW)  # the slot is free again


def test_confirm_after_release_is_refused(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=5)
    with tenant_session(tid, app_engine) as s:
        rid = quota.reserve(s, tid, now=NOW)
        quota.release(s, tid, rid, "cancelled")
    with tenant_session(tid, app_engine) as s, pytest.raises(quota.ReservationClosedError):
        quota.confirm(s, tid, rid)
    assert usage(app_engine, tid) == (0, 0)


def test_a_reservation_can_only_be_closed_once_in_the_db(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=5)
    with tenant_session(tid, app_engine) as s:
        rid = quota.reserve(s, tid, now=NOW)
        quota.confirm(s, tid, rid)
    with tenant_session(tid, app_engine) as s, pytest.raises(IntegrityError):
        s.add(m.QuotaEvent(id=new_id("qev"), tenant_id=tid, month=MONTH, kind="release", reservation_id=rid))
        s.flush()


def test_closing_event_needs_a_reservation(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=5)
    with tenant_session(tid, app_engine) as s, pytest.raises(IntegrityError):
        s.add(m.QuotaEvent(id=new_id("qev"), tenant_id=tid, month=MONTH, kind="confirm"))
        s.flush()


def test_stale_reservations_expire_after_24_hours(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=2)
    with tenant_session(tid, app_engine) as s:
        old = quota.reserve(s, tid, now=NOW)
        fresh = quota.reserve(s, tid, now=NOW)
        s.execute(
            text("UPDATE quota_events SET created_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(hours=25), "id": old},
        )
        s.execute(
            text("UPDATE quota_events SET created_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(hours=23), "id": fresh},
        )
    # Full until the next reserve looks at the clock: it releases the old one first, then takes its place.
    with tenant_session(tid, app_engine) as s:
        quota.reserve(s, tid, now=NOW)
        assert quota.open_reservations(s, tid) == 2
    with tenant_session(tid, app_engine) as s:
        reasons = s.scalars(select(m.QuotaEvent.reason).where(m.QuotaEvent.kind == "release")).all()
        assert reasons == ["expired"]
        with pytest.raises(quota.ReservationClosedError):
            quota.confirm(s, tid, old)
    with tenant_session(tid, app_engine) as s:
        quota.confirm(s, tid, fresh)  # 23 h old: still valid
    assert usage(app_engine, tid) == (1, 1)


def test_summary_states_and_unlimited(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=10)
    with tenant_session(tid, app_engine) as s:
        s.add(m.QuotaUsage(tenant_id=tid, month=MONTH, used=9))
    with tenant_session(tid, app_engine) as s:
        result = quota.summary(s, tid, now=NOW)
    assert result.month == MONTH
    [quote] = result.counters
    assert (quote.counter, quote.usage.used, quote.usage.remaining, quote.state) == ("quote", 9, 1, QuotaState.NEAR)

    unlimited = make_tenant(app_engine, limit=None)
    with tenant_session(unlimited, app_engine) as s:
        for _ in range(3):
            quota.reserve(s, unlimited, now=NOW)
        [counter] = quota.summary(s, unlimited, now=NOW).counters
    assert counter.usage.reserved == 3
    assert counter.usage.limit is None
    assert counter.state is QuotaState.OK


def test_audit_counter_only_with_its_own_limit(app_engine: Engine) -> None:
    shared = make_tenant(app_engine, limit=5)
    with tenant_session(shared, app_engine) as s:
        quota.reserve(s, shared, "audit", now=NOW)
        assert [c.counter for c in quota.summary(s, shared, now=NOW).counters] == ["quote"]
    assert usage(app_engine, shared, "quote") == (0, 1)

    separate = make_tenant(app_engine, limit=5, audit_limit=1)
    with tenant_session(separate, app_engine) as s:
        quota.reserve(s, separate, "audit", now=NOW)
        with pytest.raises(quota.QuotaReachedError):
            quota.reserve(s, separate, "audit", now=NOW)
        quota.reserve(s, separate, "quote", now=NOW)  # the quote counter is separate
        assert [c.counter for c in quota.summary(s, separate, now=NOW).counters] == ["quote", "audit"]


def test_the_month_follows_the_tenant_timezone(app_engine: Engine) -> None:
    tid = make_tenant(app_engine, limit=5)
    with tenant_session(tid, app_engine) as s:
        quota.reserve(s, tid, now=datetime(2026, 10, 31, 22, 30, tzinfo=UTC))  # Nov 1 in Jerusalem
        month = s.scalars(select(m.QuotaUsage.month)).one()
    assert month == date(2026, 11, 1)
