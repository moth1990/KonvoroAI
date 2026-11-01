"""GET /quotes/{id}: the review screen's quote (09 §4), tenant-scoped and behind `review_screen` (S09)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery

from .api import Api, set_tenant_flag

FLAG = "review_screen"


@pytest.fixture(scope="module")
def quote_id(api: Api, migrated_db: dict[str, Engine]) -> Iterator[str]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    with tenant_session(api.a.tenant_id, api.engine) as s:
        qid = seed_nursery(s, api.a.tenant_id)
    assert qid is not None
    for t in (api.a, api.b):
        set_tenant_flag(api.engine, t.tenant_id, FLAG, True)
    yield qid


def test_the_fixture_comes_back_with_money_as_strings(api: Api, quote_id: str) -> None:
    r = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["drawing_number"], body["status"], body["version"]) == ("NURSERY", "26/952", "draft", 1)
    totals = body["totals"]
    assert totals["net_total"] == "4674.0000"
    assert (totals["vat"], totals["gross_total"]) == ("841.32", "5515.3200")
    assert totals["line_counts"] == {"green": 9, "yellow": 0, "red": 5}
    assert (totals["unpriced_count"], totals["uncosted_count"], body["coverage_pct"]) == (5, 1, 62)

    (panel,) = body["panels"]
    assert panel["totals"]["price_total"] == "4674.0000"
    lines = panel["lines"]
    assert len(lines) == 14
    for line in lines:
        for k in ("qty", "unit_price", "unit_cost", "line_total", "line_cost", "margin_pct"):
            assert line[k] is None or isinstance(line[k], str), (k, line[k])
    assert sum(Decimal(ln["line_total"]) for ln in lines if ln["line_total"]) == Decimal("4674")
    f1 = next(ln for ln in lines if ln["designators"][:1] == ["F1"])
    assert (f1["qty"], f1["unit_price"], f1["line_total"]) == ("17.000", "130.0000", "2210.0000")
    assert f1["price_source"] == {"kind": "fixed", "source": "quote_import", "quotes": ["10288"], "value": None}
    assert f1["cost_source"]["supplier"] == "ספק א׳ · מפיץ ABB"
    assert body["findings"][0]["code"] == "MISSING_PRICE"


def test_another_tenants_quote_is_not_found(api: Api, quote_id: str) -> None:
    r = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.b))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_an_unknown_or_malformed_id(api: Api, quote_id: str) -> None:
    assert api.client.get("/quotes/quo_01JD0000000000000000000000", headers=api.as_(api.a)).status_code == 404
    assert api.client.get("/quotes/not-an-id", headers=api.as_(api.a)).status_code == 422


def test_with_the_flag_off_the_route_does_not_exist(api: Api, quote_id: str) -> None:
    set_tenant_flag(api.engine, api.a.tenant_id, FLAG, False)
    try:
        r = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a))
        assert r.status_code == 404
    finally:
        set_tenant_flag(api.engine, api.a.tenant_id, FLAG, True)


def test_without_a_token(api: Api, quote_id: str) -> None:
    assert api.client.get(f"/quotes/{quote_id}").status_code == 401
