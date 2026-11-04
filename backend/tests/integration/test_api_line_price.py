"""A line's price changed in the review screen (07 §7.2.3, 09 §7.14; S18 decision 8), on the NURSERY-1 fixture: for
this quote only, or in the price list too; a sent quote refused; another tenant's line not found."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery

from .api import Api

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def quote_id(api: Api, migrated_db: dict[str, Engine]) -> Iterator[str]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    with tenant_session(api.a.tenant_id, api.engine) as s:
        qid = seed_nursery(s, api.a.tenant_id)
    assert qid is not None
    yield qid


def lines(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A quote, or an action's answer (S23: `ActionOut` holds the quote)."""
    body = body.get("quote", body)
    return {ln["designators"][0] if ln["designators"] else ln["description"]: ln for ln in body["panels"][0]["lines"]}


def change(api: Api, quote_id: str, line_id: str, body: dict[str, Any], tenant: Any = None) -> Any:
    return api.client.post(f"/quotes/{quote_id}/lines/{line_id}/price", json=body, headers=api.as_(tenant or api.a))


def test_only_in_this_quote(api: Api, quote_id: str) -> None:
    before = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a)).json()
    f1 = lines(before)["F1"]
    assert (f1["qty"], f1["unit_price"]) == ("17.000", "130.0000")
    r = change(api, quote_id, f1["line_id"], {"unit_price": "125", "scope": "quote"})
    assert r.status_code == 200, r.text
    after = lines(r.json())["F1"]
    assert (after["unit_price"], after["line_total"], after["price_source"]["kind"]) == (
        "125.0000",
        "2125.0000",
        "override",
    )
    assert Decimal(r.json()["quote"]["totals"]["net_total"]) == Decimal(before["totals"]["net_total"]) - 85
    with tenant_session(api.a.tenant_id, api.engine) as s:
        line = s.get_one(m.QuoteLine, f1["line_id"])
        assert line.override and (line.override["scope"], line.override["previous_price"]) == ("quote", "130")
        event = s.scalar(select(m.CorrectionEvent).where(m.CorrectionEvent.type == "price_changed"))
        assert event is not None
        assert (event.after, event.before["unit_price"], event.user_id) == (
            {"unit_price": "125", "scope": "quote"},
            "130",
            api.a.user_id,
        )


def test_in_the_price_list_too(api: Api, quote_id: str) -> None:
    body = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a)).json()
    f1 = lines(body)["F1"]
    with tenant_session(api.a.tenant_id, api.engine) as s:
        product_id = new_id("prd")
        s.add(
            m.Product(
                id=product_id,
                tenant_id=api.a.tenant_id,
                display_name='מא"ז ABB SN201M 1P+N ‏16A',
                family="circuit_breaker",
                sale_mode="rule",
                source="supplier_price_list",
            )
        )
        s.flush()
        s.execute(update(m.QuoteLine).where(m.QuoteLine.id == f1["line_id"]).values(product_id=product_id))
    r = change(api, quote_id, f1["line_id"], {"unit_price": "135", "scope": "catalog"})
    assert r.status_code == 200, r.text
    assert lines(r.json())["F1"]["unit_price"] == "135.0000"
    with tenant_session(api.a.tenant_id, api.engine) as s:
        product = s.get_one(m.Product, product_id)
        assert (product.sale_mode, str(product.fixed_price)) == ("fixed", "135.0000")
        history = {h.field: h for h in s.scalars(select(m.PriceHistory).where(m.PriceHistory.product_id == product_id))}
        assert set(history) == {"sale_mode", "fixed_price"}
        assert {h.quote_id for h in history.values()} == {quote_id}
        assert history["fixed_price"].new == {"value": "135"} and history["fixed_price"].changed_by == api.a.user_id
        assert s.get_one(m.QuoteLine, f1["line_id"]).override is None  # the line has the price list's price now


def test_refusals(api: Api, quote_id: str) -> None:
    body = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a)).json()
    no_product = next(ln for ln in body["panels"][0]["lines"] if ln["unit_price"] and ln["designators"][:1] != ["F1"])
    r = change(api, quote_id, no_product["line_id"], {"unit_price": "10", "scope": "catalog"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "no_product"
    assert change(api, quote_id, no_product["line_id"], {"unit_price": "-1", "scope": "quote"}).status_code == 422
    assert change(api, quote_id, no_product["line_id"], {"unit_price": 10, "scope": "quote"}).status_code == 422
    assert change(api, quote_id, no_product["line_id"], {"unit_price": "10", "scope": "x"}).status_code == 422
    # another tenant's quote and line: not found, as if they don't exist
    assert (
        change(api, quote_id, no_product["line_id"], {"unit_price": "10", "scope": "quote"}, api.b).status_code == 404
    )


def test_a_sent_quote_never_changes(api: Api, quote_id: str) -> None:
    """07 §7.7. Runs last: it sends the fixture's only version."""
    body = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a)).json()
    f1 = lines(body)["F1"]
    with tenant_session(api.a.tenant_id, api.engine) as s:
        s.execute(update(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote_id).values(status="sent"))
    r = change(api, quote_id, f1["line_id"], {"unit_price": "1", "scope": "quote"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_sent"
    after = api.client.get(f"/quotes/{quote_id}", headers=api.as_(api.a)).json()
    assert lines(after)["F1"]["unit_price"] == f1["unit_price"]
