"""What the price-list screen (S19) reads beyond S18's API: 10 §8's check on a cost before it is saved, the drafts
that use a product, the quote a product was entered in, and the brands the bulk discount offers. Another tenant's
products are never compared or shown."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery

from .api import Api, ApiTenant, set_tenant_flag

pytestmark = pytest.mark.integration

FLAG = "price_list"
TODAY = date.today()
F1 = 'מא"ז ABB SN201M 1P+N ‏10A'  # NURSERY-1's F1 … F17 (devtools/fixtures/nursery.py)
F1_TO_F17 = ", ".join(f"F{i}" for i in range(1, 18))


@pytest.fixture(scope="module")
def pl(api: Api, migrated_db: dict[str, Engine]) -> Api:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the flag, the FX rates and the sample catalog
    for t in (api.a, api.b):
        set_tenant_flag(api.engine, t.tenant_id, FLAG, True)
        with tenant_session(t.tenant_id, api.engine) as s:
            s.add(m.MarginRule(id=new_id("mr"), tenant_id=t.tenant_id, level="default", value=Decimal("0.25")))
    return api


def catalog_item(pl: Api, sku: str) -> str:
    with Session(pl.engine) as s:
        found = s.scalar(select(m.CatalogItem.id).where(m.CatalogItem.sku == sku))
    assert found is not None
    return found


def post(pl: Api, tenant: ApiTenant, body: dict[str, Any]) -> dict[str, Any]:
    r = pl.client.post("/price-list/products", json=body, headers=pl.as_(tenant))
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def check(pl: Api, tenant: ApiTenant, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
    r = pl.client.post("/price-list/products/check-cost", json=body, headers=pl.as_(tenant))
    assert r.status_code == expect, r.text
    return r.json()  # type: ignore[no-any-return]


def codes(result: dict[str, Any]) -> list[str]:
    return [w["code"] for w in result["warnings"]]


def linked(pl: Api, tenant: ApiTenant, name: str, sku: str, cost: str, when: date = TODAY) -> dict[str, Any]:
    return post(
        pl,
        tenant,
        {
            "display_name": name,
            "family": "circuit_breaker",
            "brand": "ABB",
            "catalog_item_id": catalog_item(pl, sku),
            "source": "supplier_price_list",
            "suppliers": [{"supplier_name": "ספק א׳", "unit_cost": cost, "price_date": when.isoformat()}],
        },
    )


def test_a_cost_is_checked_before_it_is_saved(pl: Api) -> None:
    """10 §8: against the catalog's list price (S203M-C16: 210) and the row's previous cost. Nothing is written."""
    then = TODAY - timedelta(days=30)
    product = linked(pl, pl.a, 'מא"ז 3X16A', "S203M-C16", "138", then)
    row = product["suppliers"][0]["id"]
    with tenant_session(pl.a.tenant_id, pl.engine) as s:
        before = s.scalar(select(func.count()).select_from(m.PriceHistory))

    typo = check(pl, pl.a, {"unit_cost": "1380", "product_id": product["id"], "row_id": row})
    assert codes(typo) == ["far_from_list", "jump_from_previous"]
    assert (typo["list_price"], typo["ratio_to_list"]) == ("210.0000", "6.57")
    assert typo["warnings"][1] == {"code": "jump_from_previous", "reference": "138.0000", "reference_date": str(then)}

    fine = check(pl, pl.a, {"unit_cost": "140", "product_id": product["id"], "row_id": row})
    assert fine["warnings"] == [] and fine["ratio_to_list"] == "0.67"

    # a new row compares with the cost the product has today, and when it was set
    new_row = check(pl, pl.a, {"unit_cost": "30", "product_id": product["id"]})
    assert codes(new_row) == ["far_from_list", "jump_from_previous"]
    assert new_row["warnings"][1]["reference_date"] == str(then)

    with tenant_session(pl.a.tenant_id, pl.engine) as s:
        assert s.scalar(select(func.count()).select_from(m.PriceHistory)) == before
        assert s.get_one(m.Product, product["id"]).sanity is None


def test_saving_anyway_is_recorded(pl: Api) -> None:
    """S19 decision 4: the warning doesn't stop the save, and `sanity` keeps that it was shown."""
    product = linked(pl, pl.a, 'מא"ז 3X25A', "S203M-C25", "145")
    row = product["suppliers"][0]
    typed = {k: v for k, v in row.items() if k not in ("supplier_name", "in_force")}
    typed |= {"unit_cost": "1450", "source": "manual_entry"}
    r = pl.client.patch(f"/price-list/products/{product['id']}", json={"suppliers": [typed]}, headers=pl.as_(pl.a))
    assert r.status_code == 200, r.text
    assert r.json()["unit_cost"] == "1450.0000"
    sanity = r.json()["sanity"]
    assert sanity["warning_shown"] is True and "jump_from_previous" in [w["code"] for w in sanity["warnings"]]


def test_a_new_product_has_only_what_it_was_given(pl: Api) -> None:
    """No catalog link and no previous cost: no check can fire. A family is needed without a product."""
    assert check(pl, pl.a, {"unit_cost": "99999", "family": "relay", "brand": None})["warnings"] == []
    r = pl.client.post("/price-list/products/check-cost", json={"unit_cost": "5"}, headers=pl.as_(pl.a))
    assert r.status_code == 422


def test_another_tenants_products_are_never_compared(pl: Api) -> None:
    """10 §8, §11: tenant a has ABB 16A breakers at about 31; tenant b's 200 is compared with nothing of a's."""
    for sku, cost in (("S201M-C16", "31.5"), ("SN201M-C16", "30")):
        linked(pl, pl.a, f"a {sku}", sku, cost)
    mine = linked(pl, pl.a, "a S203M-C16 again", "S203M-C16", "138")
    theirs = linked(pl, pl.b, "b S203M-C16", "S203M-C16", "138")

    assert "far_from_similar" in codes(check(pl, pl.a, {"unit_cost": "200", "product_id": mine["id"]}))
    assert "far_from_similar" not in codes(check(pl, pl.b, {"unit_cost": "200", "product_id": theirs["id"]}))
    # and tenant a's product is not found from tenant b
    r = pl.client.post(
        "/price-list/products/check-cost", json={"unit_cost": "1", "product_id": mine["id"]}, headers=pl.as_(pl.b)
    )
    assert r.status_code == 404


def test_the_flag_off_answers_404(pl: Api) -> None:
    set_tenant_flag(pl.engine, pl.a.tenant_id, FLAG, False)
    try:
        r = pl.client.post(
            "/price-list/products/check-cost", json={"unit_cost": "1", "family": "relay"}, headers=pl.as_(pl.a)
        )
        assert r.status_code == 404
        assert pl.client.get("/price-list/brands", headers=pl.as_(pl.a)).status_code == 404
    finally:
        set_tenant_flag(pl.engine, pl.a.tenant_id, FLAG, True)


def test_the_drafts_that_use_a_product(pl: Api) -> None:
    """The editor's note (prototype openEditor): NURSERY's lines with the product, by designators; a sent quote is not
    listed, and neither is anything from another tenant."""
    product = post(
        pl, pl.a, {"display_name": F1, "family": "circuit_breaker", "sale_mode": "fixed", "fixed_price": "130"}
    )
    with tenant_session(pl.a.tenant_id, pl.engine) as s:
        quote_id = seed_nursery(s, pl.a.tenant_id)
    assert quote_id is not None

    out = pl.client.get(f"/price-list/products/{product['id']}", headers=pl.as_(pl.a)).json()
    assert out["used_in_drafts"] == [{"quote_id": quote_id, "quote_name": "NURSERY", "lines": [F1_TO_F17], "fresh": 0}]
    listed = pl.client.get("/price-list/products", headers=pl.as_(pl.a)).json()
    assert all(p["used_in_drafts"] == [] for p in listed)  # only on GET of one product

    with tenant_session(pl.a.tenant_id, pl.engine) as s:
        version = s.scalar(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote_id))
        assert version is not None
        version.status = "sent"
    out = pl.client.get(f"/price-list/products/{product['id']}", headers=pl.as_(pl.a)).json()
    assert out["used_in_drafts"] == []


def test_the_quote_a_product_was_entered_in(pl: Api) -> None:
    quote_id = new_id("quo")
    with tenant_session(pl.a.tenant_id, pl.engine) as s:
        s.add(m.Quote(id=quote_id, tenant_id=pl.a.tenant_id, name="הצעה 10271"))
    body = {
        "display_name": "ממסר חוסר מתח",
        "family": "relay",
        "source": "manual_entry",
        "quote_id": quote_id,
        "suppliers": [{"unit_cost": "250", "price_date": TODAY.isoformat(), "source": "manual_entry"}],
    }
    out = post(pl, pl.a, body)
    assert (out["entered_in_quote"], out["entered_in_quote_name"]) == (quote_id, "הצעה 10271")
    assert out["last_changed_at"] is not None
    listed = {p["id"]: p for p in pl.client.get("/price-list/products?q=חוסר", headers=pl.as_(pl.a)).json()}
    assert listed[out["id"]]["entered_in_quote_name"] == "הצעה 10271"


def test_the_brands_the_bulk_discount_offers(pl: Api) -> None:
    """Catalog brands with a list price, and any brand the tenant already discounts; not another tenant's."""
    r = pl.client.put("/price-list/brand-discounts/Hager", json={"discount_pct": "0.3"}, headers=pl.as_(pl.b))
    assert r.status_code == 200, r.text
    mine = pl.client.get("/price-list/brands", headers=pl.as_(pl.a)).json()
    theirs = pl.client.get("/price-list/brands", headers=pl.as_(pl.b)).json()
    assert "ABB" in mine and "Hager" not in mine
    assert "ABB" in theirs and "Hager" in theirs
