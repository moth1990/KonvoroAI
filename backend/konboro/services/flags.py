"""Loads a tenant's flag inputs from the DB and evaluates them (13 §2–3), with a short in-process cache."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db.models import FeatureFlag, PlanFeatureFlag, Tenant, TenantFeatureOverride
from konboro.domain.flags import FlagDef, FlagInputs, TTLCache, evaluate

DEFAULT_TTL_SECONDS = 30.0

# tenant_id -> evaluated flags. A change to a flag reaches every process within the TTL.
cache: TTLCache[str, dict[str, bool]] = TTLCache(DEFAULT_TTL_SECONDS)


def load_inputs(session: Session, tenant_id: str) -> FlagInputs:
    """`session` must be a tenant_session for `tenant_id`: RLS limits the overrides to that tenant."""
    defs = {
        f.key: FlagDef(f.key, f.default_on, tuple(f.depends_on)) for f in session.scalars(select(FeatureFlag)).all()
    }
    plan_id = session.scalar(select(Tenant.plan_id).where(Tenant.id == tenant_id))
    plan = {
        row.flag_key: row.enabled
        for row in session.scalars(select(PlanFeatureFlag).where(PlanFeatureFlag.plan_id == plan_id)).all()
    }
    tenant = {
        row.flag_key: row.enabled
        for row in session.scalars(
            select(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id)
        ).all()
    }
    return FlagInputs(defs=defs, plan=plan, tenant=tenant)


def tenant_flags(session: Session, tenant_id: str) -> dict[str, bool]:
    cached = cache.get(tenant_id)
    if cached is not None:
        return cached
    evaluated = evaluate(load_inputs(session, tenant_id))
    cache.put(tenant_id, evaluated)
    return evaluated
