"""Plan limits that are not the monthly quota (01 §4.3): the plan's value, unless the tenant has an override."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from konboro.db.models import Plan, Tenant, TenantPlanOverride


def max_pages_per_file(session: Session, tenant_id: str) -> int:
    value = session.scalar(
        select(func.coalesce(TenantPlanOverride.max_pages_per_file, Plan.max_pages_per_file))
        .select_from(Tenant)
        .join(Plan, Plan.id == Tenant.plan_id)
        .outerjoin(TenantPlanOverride, TenantPlanOverride.tenant_id == Tenant.id)
        .where(Tenant.id == tenant_id)
    )
    if value is None:
        raise LookupError(f"no plan for tenant {tenant_id}")
    return int(value)
