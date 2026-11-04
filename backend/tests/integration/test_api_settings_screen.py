"""What the settings screen (S24, prototype `vPrefs`) reads and changes beyond S03's `/settings`: the default markup,
the two brand preferences, what the enclosure's price includes and the RCD's 30 mA default. Flags stay read-only (S03
decision), and current and poles still never get a default (05 §4.4)."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session

from .api import Api, ApiTenant, add_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seeded(api: Api, migrated_db: dict[str, Engine]) -> Api:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the attribute schemas: an RCD's residual current may default
    return api


def patch(api: Api, tenant: ApiTenant, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    r = api.client.patch("/settings", json=body, headers=api.as_(tenant))
    assert r.status_code == status, r.text
    return dict(r.json())


def defaults(api: Api, tenant: ApiTenant) -> list[m.MarginRule]:
    with tenant_session(tenant.tenant_id, api.engine) as s:
        rows = list(s.scalars(select(m.MarginRule).where(m.MarginRule.level == "default")))
        s.expunge_all()
    return rows


def test_the_markup_is_the_default_rule(seeded: Api) -> None:
    api, tenant = seeded, add_tenant(seeded.engine)
    assert api.client.get("/settings", headers=api.as_(tenant)).json()["default_markup"] is None
    assert patch(api, tenant, {"default_markup": "0.25"})["default_markup"] == "0.2500"
    assert patch(api, tenant, {"default_markup": "0.3"})["default_markup"] == "0.3000"
    [rule] = defaults(api, tenant)  # changed, not added
    assert (rule.kind, rule.value, rule.version) == ("markup", Decimal("0.3000"), 2)
    patch(api, tenant, {"default_markup": None}, status=422)
    patch(api, tenant, {"default_markup": "5.5"}, status=422)
    patch(api, tenant, {"default_markup": 0.3}, status=422)


def test_every_row_of_the_screen_round_trips(seeded: Api) -> None:
    api, tenant = seeded, add_tenant(seeded.engine)
    body = patch(
        api,
        tenant,
        {
            "brand_preferences": {"circuit_breaker": "Schneider", "rcd": "Hager"},
            "enclosure_includes_default": {"busbar": True, "n": True, "pe": False, "panels": True, "doors": False},
            "attribute_defaults": {"rcd": {"residual_ma": 30}},
        },
    )
    again = api.client.get("/settings", headers=api.as_(tenant)).json()
    assert again == body
    assert again["brand_preferences"] == {"circuit_breaker": "Schneider", "rcd": "Hager"}
    assert again["enclosure_includes_default"]["pe"] is False
    assert again["attribute_defaults"] == {"rcd": {"residual_ma": 30}}
    assert patch(api, tenant, {"attribute_defaults": {}})["attribute_defaults"] == {}  # the 30 mA toggle off


def test_flags_and_unknown_fields_cannot_be_written(seeded: Api) -> None:
    api, tenant = seeded, add_tenant(seeded.engine)
    patch(api, tenant, {"flags": {"onboarding": True}}, status=422)
    patch(api, tenant, {"data_terms_accepted": {"version": "x"}}, status=422)
    body = patch(api, tenant, {"attribute_defaults": {"circuit_breaker": {"current_a": 16}}}, status=422)
    assert body["error"]["details"][0]["type"] == "default_not_allowed"
