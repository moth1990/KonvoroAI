"""A new factory's entry (10 §5.1, §5.2, §9.1, S24): the two questions and the data terms before the first upload, what
they write, the counters, and the first-quote banner. All behind `onboarding`: off, nothing waits."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global, seed_price_list
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery
from konboro.services.queue import Queue

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_api_upload import pdf, upload

pytestmark = pytest.mark.integration

FLAG = "onboarding"


@pytest.fixture(scope="module")
def seeded(api: Api, migrated_db: dict[str, Engine]) -> Api:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the flags and the sample catalog
    return api


def new_factory(api: Api, *, flag: bool = True) -> ApiTenant:
    tenant = add_tenant(api.engine)
    set_tenant_flag(api.engine, tenant.tenant_id, FLAG, flag)
    return tenant


def answer(api: Api, tenant: ApiTenant, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    r = api.client.post("/onboarding", json=body, headers=api.as_(tenant))
    assert r.status_code == status, r.text
    return dict(r.json())


def settings_row(api: Api, tenant: ApiTenant) -> m.TenantSettings:
    with tenant_session(tenant.tenant_id, api.engine) as s:
        row = s.get_one(m.TenantSettings, tenant.tenant_id)
        s.expunge(row)
    return row


def default_rules(api: Api, tenant: ApiTenant) -> list[m.MarginRule]:
    with tenant_session(tenant.tenant_id, api.engine) as s:
        rows = list(s.scalars(select(m.MarginRule).where(m.MarginRule.level == "default")))
        s.expunge_all()
    return rows


ANSWER = {"markup": "0.30", "brands": {"circuit_breaker": "Schneider", "rcd": None}, "accept_terms": True}


def test_a_new_factory_answers_before_its_first_upload(seeded: Api, clean_queue: Queue) -> None:
    api, tenant = seeded, new_factory(seeded)
    me = api.client.get("/me", headers=api.as_(tenant)).json()
    assert me["onboarding_required"] is True
    state = api.client.get("/onboarding", headers=api.as_(tenant)).json()
    assert state == {
        "required": True,
        "terms_version": "2026-10",
        "terms_accepted_at": None,
        "markup": None,
        "brands": {"circuit_breaker": None, "rcd": None},
    }

    refused = upload(api, tenant, [("a.pdf", pdf(1))])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "data_terms_required"
    refused = api.client.post(
        "/audits",
        headers=api.as_(tenant),
        files=[("files", ("a.pdf", pdf(1), "application/pdf")), ("quote", ("q.pdf", pdf(1), "application/pdf"))],
    )
    assert refused.status_code in (404, 409)  # 404 when the audit's own flag is off for the tenant

    done = answer(api, tenant, ANSWER)
    assert done["required"] is False
    assert done["markup"] == "0.3000"
    assert done["brands"] == {"circuit_breaker": "Schneider", "rcd": None}
    assert api.client.get("/me", headers=api.as_(tenant)).json()["onboarding_required"] is False

    row = settings_row(api, tenant)
    assert row.data_terms_accepted is not None
    assert row.data_terms_accepted["version"] == "2026-10"
    assert row.data_terms_accepted["by"] == tenant.user_id
    # a skipped family sets none; another family's preference (add_tenant's) stays
    assert row.brand_preferences == {"mcb": "ABB", "circuit_breaker": "Schneider"}
    assert row.onboarding["markup_source"] == "onboarding_question"
    assert row.onboarding["first_drawing_at"] is None
    [rule] = default_rules(api, tenant)
    assert (rule.kind, rule.value) == ("markup", Decimal("0.3000"))

    accepted = upload(api, tenant, [("a.pdf", pdf(1))])
    assert accepted.status_code == 201, accepted.text
    assert settings_row(api, tenant).onboarding["first_drawing_at"] is not None


def test_the_terms_must_be_accepted_and_the_answers_valid(seeded: Api) -> None:
    api, tenant = seeded, new_factory(seeded)
    body = answer(api, tenant, {**ANSWER, "accept_terms": False}, status=422)
    assert body["error"]["details"][0]["loc"] == ["body", "accept_terms"]
    answer(api, tenant, {**ANSWER, "markup": "6"}, status=422)  # 600% is a typing mistake
    answer(api, tenant, {**ANSWER, "markup": "-0.1"}, status=422)
    answer(api, tenant, {**ANSWER, "markup": 0.25}, status=422)  # money and rates are strings
    answer(api, tenant, {**ANSWER, "brands": {"contactor": "ABB"}}, status=422)
    answer(api, tenant, {**ANSWER, "brands": {"rcd": "Siemens"}}, status=422)
    assert settings_row(api, tenant).data_terms_accepted is None
    assert default_rules(api, tenant) == []


def test_other_sets_no_preference_and_an_existing_default_rule_is_changed(seeded: Api) -> None:
    api, tenant = seeded, new_factory(seeded)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        s.add(m.MarginRule(id=new_id("mr"), tenant_id=tenant.tenant_id, level="default", value=Decimal("0.25")))
    done = answer(
        api, tenant, {"markup": "0.4", "brands": {"circuit_breaker": "other", "rcd": "Hager"}, "accept_terms": True}
    )
    assert done["brands"] == {"circuit_breaker": "other", "rcd": "Hager"}
    assert settings_row(api, tenant).brand_preferences == {"mcb": "ABB", "rcd": "Hager"}
    [rule] = default_rules(api, tenant)
    assert (rule.value, rule.version) == (Decimal("0.4000"), 2)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        logged = s.scalars(select(m.PriceHistory.field).where(m.PriceHistory.subject == rule.id)).all()
    assert "margin_rule" in logged


def test_with_the_flag_off_nothing_waits(seeded: Api, clean_queue: Queue) -> None:
    api, tenant = seeded, new_factory(seeded, flag=False)
    assert api.client.get("/onboarding", headers=api.as_(tenant)).status_code == 404
    assert api.client.post("/onboarding", json=ANSWER, headers=api.as_(tenant)).status_code == 404
    assert api.client.get("/me", headers=api.as_(tenant)).json()["onboarding_required"] is False
    assert upload(api, tenant, [("a.pdf", pdf(1))]).status_code == 201


def test_the_first_quote_banner_and_the_counters(seeded: Api) -> None:
    """10 §5.2: until the factory sends its first quote; sending counts it, with its price coverage (§9.1)."""
    api, tenant = seeded, new_factory(seeded)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        seed_price_list(s, tenant.tenant_id)
        s.add(m.MarginRule(id=new_id("mr"), tenant_id=tenant.tenant_id, level="default", value=Decimal("0.25")))
        s.flush()
        qid = seed_nursery(s, tenant.tenant_id)
    answer(api, tenant, ANSWER)
    headers = api.as_(tenant)
    assert api.client.get(f"/quotes/{qid}", headers=headers).json()["first_quote"] is True

    sent = api.client.post(f"/quotes/{qid}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    counters = settings_row(api, tenant).onboarding
    assert counters["quotes_sent"] == 1
    assert counters["first_quote_sent_at"] is not None
    assert 0 < counters["price_coverage_last"] < 1  # NURSERY-1 has lines with no price

    opened = api.client.post(f"/quotes/{qid}/versions", headers=headers)
    assert opened.status_code in (200, 201), opened.text
    assert api.client.get(f"/quotes/{qid}", headers=headers).json()["first_quote"] is False

    set_tenant_flag(api.engine, tenant.tenant_id, FLAG, False)
    assert api.client.get(f"/quotes/{qid}", headers=headers).json()["first_quote"] is False
