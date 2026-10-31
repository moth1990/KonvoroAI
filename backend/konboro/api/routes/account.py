"""The signed-in user's account: who, which tenant and plan, evaluated flags, quota (00 §14.1, 13 §3, 01 §4.5)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from konboro.db.models import Plan, Tenant, TenantPlanOverride, User
from konboro.domain.permissions import Permission
from konboro.services import quota

from ..deps import Actor, require
from ..errors import ERROR_RESPONSES
from ..schemas import MeOut, PlanOut, QuotaCounterOut, QuotaOut, TenantOut, UserOut

router = APIRouter(tags=["account"], responses=ERROR_RESPONSES)


def quota_out(actor: Actor) -> QuotaOut:
    result = quota.summary(actor.session, actor.tenant_id)
    return QuotaOut(
        month=result.month,
        counters=[
            QuotaCounterOut(
                counter=c.counter,
                limit=c.usage.limit,
                used=c.usage.used,
                reserved=c.usage.reserved,
                extra=c.usage.extra,
                remaining=c.usage.remaining,
                state=c.state,
            )
            for c in result.counters
        ],
    )


@router.get("/me")
def me(actor: Annotated[Actor, Depends(require(Permission.ACCOUNT_READ))]) -> MeOut:
    s = actor.session
    user = s.get_one(User, actor.user_id)
    tenant = s.get_one(Tenant, actor.tenant_id)
    plan = s.get_one(Plan, tenant.plan_id)
    override = s.scalar(select(TenantPlanOverride).where(TenantPlanOverride.tenant_id == actor.tenant_id))
    limits = quota.tenant_quota(s, actor.tenant_id).limits
    pages = override.max_pages_per_file if override and override.max_pages_per_file is not None else None
    return MeOut(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role),
        tenant=TenantOut(id=tenant.id, name=tenant.name, timezone=tenant.timezone, currency=tenant.currency),
        plan=PlanOut(
            id=plan.id,
            name_he=plan.name_he,
            monthly_quote_limit=limits.monthly_quote_limit,
            monthly_audit_limit=limits.monthly_audit_limit,
            max_pages_per_file=pages if pages is not None else plan.max_pages_per_file,
        ),
        flags=actor.flags,
        quota=quota_out(actor),
    )


@router.get("/quota")
def get_quota(actor: Annotated[Actor, Depends(require(Permission.QUOTA_READ))]) -> QuotaOut:
    """Also releases reservations older than 24 h (01 §4.5), so the numbers are current."""
    return quota_out(actor)
