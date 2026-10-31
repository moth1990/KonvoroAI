"""The monthly quota in the DB (01 §4.5, docs/db-schema.md §4): reserve, confirm, release, expiry.

Every function takes a tenant_session for `tenant_id`. Each change is one atomic statement plus a
`quota_events` row, so 20 uploads at once against a limit of 10 give exactly 10 reservations:
the reservation is `UPDATE … WHERE used + reserved < limit + extra`, and Postgres re-checks that
condition on the locked row for every waiting transaction.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from konboro.db.ids import new_id
from konboro.db.models import Plan, QuotaEvent, QuotaUsage, Tenant, TenantPlanOverride
from konboro.domain.quota import (
    Counter,
    Limits,
    Purpose,
    QuotaState,
    Usage,
    counter_for,
    effective_limits,
    limit_for,
    month_start,
)

RESERVATION_TTL = timedelta(hours=24)
_CLOSING = text("kind IN ('confirm', 'release')")


class QuotaReachedError(Exception):
    """The month's quota is used up (01 §4.5, `quota_reached`)."""


class ReservationClosedError(Exception):
    """The reservation was already confirmed or released (e.g. it expired after 24 h)."""


@dataclass(frozen=True)
class TenantQuota:
    timezone: str
    limits: Limits


@dataclass(frozen=True)
class CounterSummary:
    counter: Counter
    usage: Usage

    @property
    def state(self) -> QuotaState:
        return self.usage.state


@dataclass(frozen=True)
class QuotaSummary:
    month: date
    counters: list[CounterSummary]


def tenant_quota(session: Session, tenant_id: str) -> TenantQuota:
    row = session.execute(
        select(
            Tenant.timezone,
            Plan.monthly_quote_limit,
            Plan.monthly_audit_limit,
            TenantPlanOverride.monthly_quote_limit,
            TenantPlanOverride.monthly_audit_limit,
        )
        .join(Plan, Plan.id == Tenant.plan_id)
        .outerjoin(TenantPlanOverride, TenantPlanOverride.tenant_id == Tenant.id)
        .where(Tenant.id == tenant_id)
    ).one()
    return TenantQuota(timezone=row[0], limits=effective_limits(row[1], row[2], row[3], row[4]))


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def _ensure_usage_row(session: Session, tenant_id: str, month: date, counter: Counter) -> None:
    session.execute(
        insert(QuotaUsage)
        .values(tenant_id=tenant_id, month=month, counter=counter)
        .on_conflict_do_nothing(index_elements=["tenant_id", "month", "counter"])
    )


def reserve(
    session: Session,
    tenant_id: str,
    purpose: Purpose = "quote",
    *,
    created_by: str | None = None,
    now: datetime | None = None,
) -> str:
    """Hold one slot when the user starts a new quote. Returns the reservation id (a `qev_` id)."""
    now = _now(now)
    expire_stale(session, tenant_id, now=now)
    quota = tenant_quota(session, tenant_id)
    counter = counter_for(purpose, quota.limits)
    limit = limit_for(counter, quota.limits)
    month = month_start(now, quota.timezone)
    _ensure_usage_row(session, tenant_id, month, counter)

    condition = [QuotaUsage.tenant_id == tenant_id, QuotaUsage.month == month, QuotaUsage.counter == counter]
    if limit is not None:
        condition.append(QuotaUsage.used + QuotaUsage.reserved < limit + QuotaUsage.extra)
    taken = session.execute(
        update(QuotaUsage).where(*condition).values(reserved=QuotaUsage.reserved + 1).returning(QuotaUsage.month)
    ).first()
    if taken is None:
        raise QuotaReachedError(counter)

    reservation_id = new_id("qev")
    session.add(
        QuotaEvent(
            id=reservation_id,
            tenant_id=tenant_id,
            month=month,
            counter=counter,
            kind="reserve",
            reason=purpose,
            created_by=created_by,
        )
    )
    session.flush()
    return reservation_id


def _close(
    session: Session,
    tenant_id: str,
    reservation: QuotaEvent,
    kind: str,
    *,
    reason: str | None,
    drawing_id: str | None = None,
    created_by: str | None = None,
) -> bool:
    """Write the one closing event, then move the slot. False if the reservation was already closed."""
    closed = session.execute(
        insert(QuotaEvent)
        .values(
            id=new_id("qev"),
            tenant_id=tenant_id,
            month=reservation.month,
            counter=reservation.counter,
            kind=kind,
            amount=reservation.amount,
            reason=reason,
            drawing_id=drawing_id,
            created_by=created_by,
            reservation_id=reservation.id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "reservation_id"], index_where=_CLOSING)
        .returning(QuotaEvent.id)
    ).first()
    if closed is None:
        return False
    values = {"reserved": QuotaUsage.reserved - reservation.amount}
    if kind == "confirm":
        values["used"] = QuotaUsage.used + reservation.amount
    session.execute(
        update(QuotaUsage)
        .where(
            QuotaUsage.tenant_id == tenant_id,
            QuotaUsage.month == reservation.month,
            QuotaUsage.counter == reservation.counter,
        )
        .values(values)
    )
    return True


def _reservation(session: Session, tenant_id: str, reservation_id: str) -> QuotaEvent:
    reservation = session.scalar(
        select(QuotaEvent).where(
            QuotaEvent.tenant_id == tenant_id, QuotaEvent.id == reservation_id, QuotaEvent.kind == "reserve"
        )
    )
    if reservation is None:
        raise LookupError(f"no reservation {reservation_id}")
    return reservation


def confirm(
    session: Session,
    tenant_id: str,
    reservation_id: str,
    *,
    drawing_id: str | None = None,
    created_by: str | None = None,
) -> None:
    """Stage 1 succeeded: the reserved slot becomes used (01 §4.5 step 2). Counted in the reservation's month."""
    reservation = _reservation(session, tenant_id, reservation_id)
    if not _close(
        session,
        tenant_id,
        reservation,
        "confirm",
        reason="intake_succeeded",
        drawing_id=drawing_id,
        created_by=created_by,
    ):
        raise ReservationClosedError(reservation_id)


def release(
    session: Session,
    tenant_id: str,
    reservation_id: str,
    reason: str,
    *,
    drawing_id: str | None = None,
    created_by: str | None = None,
) -> bool:
    """Rejected, failed or cancelled upload (01 §4.5 step 3). Idempotent: False if already closed."""
    reservation = _reservation(session, tenant_id, reservation_id)
    return _close(
        session, tenant_id, reservation, "release", reason=reason, drawing_id=drawing_id, created_by=created_by
    )


def _is_open() -> ColumnElement[bool]:
    """A reserve event with no confirm or release pointing at it."""
    closing = aliased(QuotaEvent)
    return and_(
        QuotaEvent.kind == "reserve",
        ~exists().where(closing.tenant_id == QuotaEvent.tenant_id, closing.reservation_id == QuotaEvent.id),
    )


def expire_stale(session: Session, tenant_id: str, *, now: datetime | None = None) -> int:
    """Release reservations older than 24 h with no closing event. Returns how many were released."""
    cutoff = _now(now) - RESERVATION_TTL
    stale = session.scalars(
        select(QuotaEvent).where(QuotaEvent.tenant_id == tenant_id, QuotaEvent.created_at < cutoff, _is_open())
    ).all()
    return sum(_close(session, tenant_id, r, "release", reason="expired") for r in stale)


def summary(session: Session, tenant_id: str, *, now: datetime | None = None) -> QuotaSummary:
    """This month's counters. The audit counter appears only when the plan gives audits their own limit."""
    now = _now(now)
    expire_stale(session, tenant_id, now=now)
    quota = tenant_quota(session, tenant_id)
    month = month_start(now, quota.timezone)
    counters: list[Counter] = ["quote"] if quota.limits.monthly_audit_limit is None else ["quote", "audit"]
    rows = {
        row.counter: row
        for row in session.scalars(
            select(QuotaUsage).where(QuotaUsage.tenant_id == tenant_id, QuotaUsage.month == month)
        ).all()
    }
    result = []
    for counter in counters:
        row = rows.get(counter)
        usage = Usage(
            limit=limit_for(counter, quota.limits),
            used=row.used if row else 0,
            reserved=row.reserved if row else 0,
            extra=row.extra if row else 0,
        )
        result.append(CounterSummary(counter=counter, usage=usage))
    return QuotaSummary(month=month, counters=result)


def open_reservations(session: Session, tenant_id: str) -> int:
    """For tests and diagnostics: reservations without a closing event."""
    query = select(func.count()).select_from(QuotaEvent).where(QuotaEvent.tenant_id == tenant_id, _is_open())
    return int(session.scalar(query) or 0)
