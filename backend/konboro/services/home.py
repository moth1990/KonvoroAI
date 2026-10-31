"""Read models for the home screen: recent quotes and the "waiting for you" counts.

Runs inside `tenant_session`, so RLS already limits every query to the tenant. The explicit `tenant_id`
filters are a second guard and let Postgres use the `(tenant_id, …)` indexes.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Subquery, and_, func, select
from sqlalchemy.orm import Session

from konboro.db.models import Audit, AuditDifference, KnowledgeCandidate, Quote, QuoteLine, QuoteVersion

# 11 §5.2: the difference types the home card counts as omissions.
OMISSION_TYPES = ("missing_in_quote",)


@dataclass(frozen=True)
class RecentQuote:
    id: str
    name: str
    version: int
    version_status: str
    missing_prices: int
    updated_at: datetime


@dataclass(frozen=True)
class MissingPrices:
    quote_id: str
    quote_name: str
    count: int


@dataclass(frozen=True)
class AuditOmissions:
    audit_id: str
    quote_number: str | None
    count: int
    amount_at_risk: Decimal | None


@dataclass(frozen=True)
class Summary:
    queue_pending: int
    missing_prices: list[MissingPrices]
    audit_omissions: list[AuditOmissions]


def _missing_prices_by_version(tenant_id: str) -> Subquery:
    """Live lines with no unit price, per quote version. Pricing (S22) may narrow what counts."""
    return (
        select(QuoteLine.quote_version_id, func.count().label("n"))
        .where(QuoteLine.tenant_id == tenant_id, QuoteLine.deleted_at.is_(None), QuoteLine.unit_price.is_(None))
        .group_by(QuoteLine.quote_version_id)
        .subquery()
    )


def recent_quotes(session: Session, tenant_id: str, limit: int) -> list[RecentQuote]:
    missing = _missing_prices_by_version(tenant_id)
    rows = session.execute(
        select(Quote, QuoteVersion.status, func.coalesce(missing.c.n, 0))
        .join(
            QuoteVersion,
            and_(
                QuoteVersion.tenant_id == Quote.tenant_id,
                QuoteVersion.quote_id == Quote.id,
                QuoteVersion.version == Quote.current_version,
            ),
        )
        .outerjoin(missing, missing.c.quote_version_id == QuoteVersion.id)
        .where(Quote.tenant_id == tenant_id)
        .order_by(Quote.updated_at.desc(), Quote.id.desc())
        .limit(limit)
    ).all()
    return [RecentQuote(q.id, q.name, q.current_version, status, int(n), q.updated_at) for q, status, n in rows]


def summary(session: Session, tenant_id: str) -> Summary:
    queue = session.scalar(
        select(func.count())
        .select_from(KnowledgeCandidate)
        .where(KnowledgeCandidate.tenant_id == tenant_id, KnowledgeCandidate.status == "pending")
    )
    missing = _missing_prices_by_version(tenant_id)
    prices = session.execute(
        select(Quote.id, Quote.name, missing.c.n)
        .join(
            QuoteVersion,
            and_(
                QuoteVersion.tenant_id == Quote.tenant_id,
                QuoteVersion.quote_id == Quote.id,
                QuoteVersion.version == Quote.current_version,
                QuoteVersion.status == "draft",  # a sent version is final; its gaps are history
            ),
        )
        .join(missing, missing.c.quote_version_id == QuoteVersion.id)
        .where(Quote.tenant_id == tenant_id)
        .order_by(Quote.updated_at.desc(), Quote.id.desc())
    ).all()
    omissions = session.execute(
        select(Audit.id, Audit.quote_ref["number"].astext, func.count(), func.sum(AuditDifference.amount))
        .join(
            AuditDifference,
            and_(AuditDifference.tenant_id == Audit.tenant_id, AuditDifference.audit_id == Audit.id),
        )
        .where(
            Audit.tenant_id == tenant_id,
            Audit.status == "ready",
            AuditDifference.type.in_(OMISSION_TYPES),
            AuditDifference.status != "rejected",
        )
        .group_by(Audit.id)
        .order_by(func.max(Audit.updated_at).desc(), Audit.id.desc())
    ).all()
    return Summary(
        queue_pending=queue or 0,
        missing_prices=[MissingPrices(qid, name, int(n)) for qid, name, n in prices],
        audit_omissions=[AuditOmissions(aid, number, int(n), amount) for aid, number, n, amount in omissions],
    )
