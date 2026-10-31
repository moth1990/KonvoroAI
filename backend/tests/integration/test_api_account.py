"""/me, /quota, /settings and flag gating (00 §14.1, 01 §4.5, 13 §3)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select

from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.domain.quota import month_start
from konboro.services import quota

from .api import CHILD, GATE, Api, add_tenant, set_tenant_flag
from .factory import GLOBAL_FLAG, GLOBAL_PLAN


def test_me_returns_the_tenant_flags_and_quota(api: Api) -> None:
    response = api.client.get("/me", headers=api.as_(api.a))
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": api.a.user_id, "email": api.a.email, "display_name": "בעלים", "role": "owner"}
    assert body["tenant"]["id"] == api.a.tenant_id
    assert body["tenant"]["timezone"] == "Asia/Jerusalem"
    assert body["plan"] == {
        "id": GLOBAL_PLAN,
        "name_he": "בדיקה",
        "monthly_quote_limit": 50,  # the tenant override wins over the plan's null
        "monthly_audit_limit": None,
        "max_pages_per_file": 30,
    }
    # Every known flag is listed, evaluated. Nothing turned on for this tenant.
    assert {GLOBAL_FLAG, GATE, CHILD} <= set(body["flags"])
    assert not any(body["flags"].values())
    month = month_start(datetime.now(UTC), "Asia/Jerusalem")
    assert body["quota"] == {
        "month": month.isoformat(),
        "counters": [
            {
                "counter": "quote",
                "limit": 50,
                "used": 12,
                "reserved": 0,
                "extra": 0,
                "remaining": 38,
                "state": "ok",
            }
        ],
    }


def test_quota_states_reach_the_client(api: Api, migrated_db: dict[str, Engine]) -> None:
    near, full = add_tenant(migrated_db["app"], limit=10, used=9), add_tenant(migrated_db["app"], limit=10, used=10)
    assert api.client.get("/quota", headers=api.as_(near)).json()["counters"][0]["state"] == "quota_near"
    body = api.client.get("/quota", headers=api.as_(full)).json()["counters"][0]
    assert (body["state"], body["remaining"]) == ("quota_reached", 0)


def test_quota_read_releases_stale_reservations(api: Api, migrated_db: dict[str, Engine]) -> None:
    tenant = add_tenant(migrated_db["app"], limit=10)
    with tenant_session(tenant.tenant_id, migrated_db["app"]) as s:
        rid = quota.reserve(s, tenant.tenant_id)
        s.execute(
            m.QuotaEvent.__table__.update()
            .where(m.QuotaEvent.id == rid)
            .values(created_at=datetime(2020, 1, 1, tzinfo=UTC))
        )
    body = api.client.get("/quota", headers=api.as_(tenant)).json()["counters"][0]
    assert body["reserved"] == 0


def test_flag_off_is_404_and_on_works(api: Api) -> None:
    t = api.b
    set_tenant_flag(api.engine, t.tenant_id, GATE, False)
    off = api.client.get("/__test__/gate", headers=api.as_(t))
    assert off.status_code == 404
    assert off.json()["error"]["code"] == "not_found"

    set_tenant_flag(api.engine, t.tenant_id, GATE, True)
    on = api.client.get("/__test__/gate", headers=api.as_(t))
    assert on.status_code == 200
    assert on.json() == {"tenant_id": t.tenant_id}
    assert api.client.get("/me", headers=api.as_(t)).json()["flags"][GATE] is True

    set_tenant_flag(api.engine, t.tenant_id, GATE, False)
    assert api.client.get("/__test__/gate", headers=api.as_(t)).status_code == 404


def test_flag_dependency_is_enforced_by_the_api(api: Api, migrated_db: dict[str, Engine]) -> None:
    t = add_tenant(migrated_db["app"])
    set_tenant_flag(api.engine, t.tenant_id, CHILD, True)  # child on, gate off
    assert api.client.get("/__test__/child", headers=api.as_(t)).status_code == 404
    assert api.client.get("/me", headers=api.as_(t)).json()["flags"][CHILD] is False
    set_tenant_flag(api.engine, t.tenant_id, GATE, True)
    assert api.client.get("/__test__/child", headers=api.as_(t)).status_code == 200


def test_flag_gate_still_needs_a_token(api: Api) -> None:
    assert api.client.get("/__test__/gate").status_code == 401


def test_settings_get_and_patch(api: Api, migrated_db: dict[str, Engine]) -> None:
    t = add_tenant(migrated_db["app"])
    headers = api.as_(t)
    got = api.client.get("/settings", headers=headers).json()
    assert got["brand_preferences"] == {"mcb": "ABB"}
    assert got["min_line_margin"] is None

    patched = api.client.patch(
        "/settings",
        headers=headers,
        json={
            "min_line_margin": "0.15",
            "enclosure_includes_default": {"busbar": True, "doors": False},
            "attribute_defaults": {"rcd": {"residual_ma": 30}},
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["min_line_margin"] == "0.1500"  # a string, never a float
    assert body["enclosure_includes_default"] == {"busbar": True, "doors": False}
    assert body["brand_preferences"] == {"mcb": "ABB"}  # untouched
    with tenant_session(t.tenant_id, migrated_db["app"]) as s:
        stored = s.scalar(select(m.TenantSettings.min_line_margin))
    assert stored == Decimal("0.15")

    cleared = api.client.patch("/settings", headers=headers, json={"min_line_margin": None})
    assert cleared.json()["min_line_margin"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"min_line_margin": 0.15},  # money and rates are strings, never floats
        {"min_line_margin": "1"},  # a margin is below 100%
        {"min_line_margin": "-0.1"},
        {"min_line_margin": "abc"},
        {"stale_days": 0},
        {"stale_days": None},
        {"brand_preferences": None},
        {"enclosure_includes_default": {"roof": True}},
        {"attribute_defaults": {"mcb": {"current_a": 16}}},  # current never gets a default (05 §4.4)
        {"attribute_defaults": {"mcb": {"poles": 3}}},  # nor poles
        {"rounding": "shekel"},  # not patchable here
        {"flags": {"voice_input": True}},  # flags are read-only to the owner (S03 decision)
    ],
)
def test_settings_patch_rejects(api: Api, body: dict[str, object]) -> None:
    response = api.client.patch("/settings", headers=api.as_(api.a), json=body)
    assert response.status_code == 422, body
    assert response.json()["error"]["code"] == "validation_error"


def test_settings_patch_respects_attribute_schemas(api: Api, migrated_db: dict[str, Engine]) -> None:
    with migrated_db["owner"].begin() as conn:
        conn.execute(
            m.AttributeSchema.__table__.insert().values(
                family="s03_rcd",
                attributes=[
                    {"name": "residual_ma", "required": False, "match_mode": "exact", "default_allowed": True},
                    {"name": "frame", "required": False, "match_mode": "exact", "default_allowed": False},
                ],
            )
        )
    ok = api.client.patch(
        "/settings", headers=api.as_(api.b), json={"attribute_defaults": {"s03_rcd": {"residual_ma": 30}}}
    )
    assert ok.status_code == 200
    bad = api.client.patch(
        "/settings", headers=api.as_(api.b), json={"attribute_defaults": {"s03_rcd": {"frame": "x"}}}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["details"][0]["loc"] == ["body", "attribute_defaults", "s03_rcd", "frame"]
