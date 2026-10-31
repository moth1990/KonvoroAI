"""API test setup: an app on the konboro_test DB, tenants with an owner, tokens, and test flags."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from konboro.api.app import create_app
from konboro.api.deps import Actor, require, require_flag
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.domain.permissions import Permission
from konboro.domain.quota import month_start
from konboro.services import auth
from konboro.settings import Settings

from .factory import GLOBAL_PLAN

DEV_PASSWORD = "s03-test-password"

# Test-only flags: gate on, child depends on gate. Global rows, inserted once by the owner.
GATE, CHILD = "s03_gate", "s03_child"


# Flag-gated routes that exist only in the test app (13 §3.1: the API checks the flag on every call).
gated = APIRouter(prefix="/__test__")


@gated.get("/gate", dependencies=[Depends(require_flag(GATE))])
def gate_route(actor: Annotated[Actor, Depends(require(Permission.ACCOUNT_READ))]) -> dict[str, str]:
    return {"tenant_id": actor.tenant_id}


@gated.get("/child", dependencies=[Depends(require_flag(CHILD))])
def child_route(actor: Annotated[Actor, Depends(require(Permission.ACCOUNT_READ))]) -> dict[str, str]:
    return {"tenant_id": actor.tenant_id}


@dataclass(frozen=True)
class ApiTenant:
    tenant_id: str
    user_id: str
    email: str


def add_tenant(engine: Engine, *, limit: int | None = 50, used: int = 0, status: str = "active") -> ApiTenant:
    tid, uid = new_id("tnt"), new_id("usr")
    email = f"owner@{tid[-8:].lower()}.test"
    with tenant_session(tid, engine) as s:
        s.add(m.Tenant(id=tid, name=f"מפעל {tid[-4:]}", plan_id=GLOBAL_PLAN, status=status))
        s.flush()
        s.add(m.User(id=uid, tenant_id=tid, email=email, display_name="בעלים"))
        s.add(m.TenantSettings(tenant_id=tid, brand_preferences={"mcb": "ABB"}))
        s.add(m.TenantPlanOverride(tenant_id=tid, monthly_quote_limit=limit))
        if used:
            month = month_start(datetime.now(UTC), "Asia/Jerusalem")
            s.add(m.QuotaUsage(tenant_id=tid, month=month, used=used))
    return ApiTenant(tid, uid, email)


def set_tenant_flag(engine: Engine, tenant_id: str, key: str, enabled: bool) -> None:
    with tenant_session(tenant_id, engine) as s:
        s.execute(
            text(
                "INSERT INTO tenant_feature_overrides (tenant_id, flag_key, enabled, reason) "
                "VALUES (:t, :k, :e, 'test') "
                "ON CONFLICT (tenant_id, flag_key) DO UPDATE SET enabled = excluded.enabled"
            ),
            {"t": tenant_id, "k": key, "e": enabled},
        )


def api_settings(directory: list[ApiTenant]) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,  # hermetic: never read a developer's .env
        env="test",
        dev_password=SecretStr(DEV_PASSWORD),
        dev_users=",".join(f"{t.email}={t.tenant_id}" for t in directory),
        flag_cache_seconds=0,  # a flag change is visible on the next request
    )


def token_for(settings: Settings, tenant: ApiTenant, engine: Engine) -> str:
    with tenant_session(tenant.tenant_id, engine) as s:
        user = s.get_one(m.User, tenant.user_id)
        s.expunge(user)
    return auth.dev_tokens(settings).issue(user)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Api:
    app: FastAPI
    client: TestClient
    settings: Settings
    engine: Engine
    a: ApiTenant
    b: ApiTenant

    def as_(self, tenant: ApiTenant) -> dict[str, str]:
        return bearer(token_for(self.settings, tenant, self.engine))


@pytest.fixture(scope="module")
def api(migrated_db: dict[str, Engine]) -> Iterator[Api]:
    with migrated_db["owner"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO feature_flags (key, description, depends_on) VALUES "
                "(:g, 'test gate', '{}'), (:c, 'test child', ARRAY[:g]) ON CONFLICT DO NOTHING"
            ),
            {"g": GATE, "c": CHILD},
        )
    engine = migrated_db["app"]
    a, b = add_tenant(engine, used=12), add_tenant(engine, used=3)
    settings = api_settings([a, b])
    app = create_app(settings, engine=engine)
    app.include_router(gated)
    with TestClient(app) as client:
        yield Api(app, client, settings, engine, a, b)
