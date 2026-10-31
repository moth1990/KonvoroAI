"""A token for tenant A never reads or writes tenant B's data, on any endpoint (00 §8.1)."""

from sqlalchemy import select

from konboro.db import models as m
from konboro.db.session import tenant_session

from .api import GATE, Api, set_tenant_flag


def test_every_read_endpoint_answers_with_the_callers_tenant_only(api: Api) -> None:
    a, b = api.as_(api.a), api.as_(api.b)
    me_a, me_b = api.client.get("/me", headers=a).json(), api.client.get("/me", headers=b).json()
    assert (me_a["tenant"]["id"], me_b["tenant"]["id"]) == (api.a.tenant_id, api.b.tenant_id)
    assert me_a["user"]["id"] == api.a.user_id
    assert (me_a["quota"]["counters"][0]["used"], me_b["quota"]["counters"][0]["used"]) == (12, 3)
    assert api.client.get("/quota", headers=a).json()["counters"][0]["used"] == 12
    assert api.client.get("/quota", headers=b).json()["counters"][0]["used"] == 3


def test_settings_patch_by_a_never_touches_b(api: Api) -> None:
    before = api.client.get("/settings", headers=api.as_(api.b)).json()
    response = api.client.patch("/settings", headers=api.as_(api.a), json={"brand_preferences": {"mcb": "Hager"}})
    assert response.status_code == 200
    assert api.client.get("/settings", headers=api.as_(api.b)).json() == before
    with tenant_session(api.b.tenant_id, api.engine) as s:
        assert s.scalar(select(m.TenantSettings.brand_preferences)) == before["brand_preferences"]


def test_a_flag_for_a_is_not_a_flag_for_b(api: Api) -> None:
    set_tenant_flag(api.engine, api.a.tenant_id, GATE, True)
    try:
        assert api.client.get("/__test__/gate", headers=api.as_(api.a)).status_code == 200
        set_tenant_flag(api.engine, api.b.tenant_id, GATE, False)
        assert api.client.get("/__test__/gate", headers=api.as_(api.b)).status_code == 404
    finally:
        set_tenant_flag(api.engine, api.a.tenant_id, GATE, False)
