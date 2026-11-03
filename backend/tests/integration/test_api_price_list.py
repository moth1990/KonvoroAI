"""The price-list API (07 §7.2–7.3, S18): products with their suppliers, history, brand discounts, margin rules,
supplier preferences, the flag, and another tenant. Money is a string everywhere (non-negotiable 5)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session

from .api import Api, ApiTenant, set_tenant_flag

pytestmark = pytest.mark.integration

FLAG = "price_list"
TODAY = date.today()


@pytest.fixture(scope="module")
def pl(api: Api, migrated_db: dict[str, Engine]) -> Api:
    """Tenants a and b with the price list on and the one default rule a new factory gets (10 §5.1)."""
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the flag, the FX rates and the sample catalog
    for t in (api.a, api.b):
        set_tenant_flag(api.engine, t.tenant_id, FLAG, True)
        with tenant_session(t.tenant_id, api.engine) as s:
            if not s.scalar(select(m.MarginRule.id).where(m.MarginRule.level == "default")):
                s.add(m.MarginRule(id=new_id("mr"), tenant_id=t.tenant_id, level="default", value=Decimal("0.25")))
            s.get_one(m.TenantSettings, t.tenant_id).min_line_margin = Decimal("0.15")
    return api


def floats(value: Any, path: str = "$") -> list[str]:
    """Every JSON number with a fraction in a response: there must be none (money and rates are strings)."""
    if isinstance(value, float):
        return [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in floats(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in floats(v, f"{path}[{i}]")]
    return []


def post(api: Api, tenant: ApiTenant, body: dict[str, Any], expect: int = 201) -> dict[str, Any]:
    r = api.client.post("/price-list/products", json=body, headers=api.as_(tenant))
    assert r.status_code == expect, r.text
    return r.json()  # type: ignore[no-any-return]


def supplier(name: str, cost: str, **kw: Any) -> dict[str, Any]:
    return {"supplier_name": name, "unit_cost": cost, "price_date": TODAY.isoformat(), **kw}


def a_quote(api: Api, tenant: ApiTenant) -> str:
    quote_id = new_id("quo")
    with tenant_session(tenant.tenant_id, api.engine) as s:
        s.add(m.Quote(id=quote_id, tenant_id=tenant.tenant_id, name="הצעה"))
    return quote_id


def test_the_flag_off_answers_404(pl: Api) -> None:
    set_tenant_flag(pl.engine, pl.a.tenant_id, FLAG, False)
    try:
        for path in ("/price-list/products", "/price-list/suppliers", "/price-list/margin-rules"):
            assert pl.client.get(path, headers=pl.as_(pl.a)).status_code == 404
        body = {"display_name": "x", "family": "relay"}
        assert pl.client.post("/price-list/products", json=body, headers=pl.as_(pl.a)).status_code == 404
    finally:
        set_tenant_flag(pl.engine, pl.a.tenant_id, FLAG, True)


def test_a_product_with_two_suppliers(pl: Api) -> None:
    body = {
        "display_name": 'מא"ז ABB S203M 3P ‏16A',
        "manufacturer_sku": "T-S203M-C16",
        "brand": "ABB",
        "family": "circuit_breaker",
        "source": "supplier_price_list",
        "suppliers": [
            supplier("ספק א׳", "138", preferred=True, supplier_sku="A-4471", lead_days=2),
            supplier("ספק ב׳", "131", supplier_sku="B-20316", lead_days=10),
        ],
    }
    out = post(pl, pl.a, body)
    assert floats(out) == []
    assert [(s["supplier_name"], s["unit_cost"], s["preferred"]) for s in out["suppliers"]] == [
        ("ספק א׳", "138.0000", True),
        ("ספק ב׳", "131.0000", False),
    ]
    # 07 §7.2.2: the preferred supplier, not the cheapest; the default markup of 25% on it
    assert (out["unit_cost"], out["price_status"], out["unit_price"]) == ("138.0000", "ok", "172.50")
    assert out["cost_source"]["via"] == "product_preferred" and out["margin_rule"]["level"] == "default"
    assert out["margin_pct"] == "0.2000"

    one = pl.client.get(f"/price-list/products/{out['id']}", headers=pl.as_(pl.a)).json()
    fields = sorted(h["field"] for h in one["history"])
    assert fields == ["created", "supplier", "supplier"]
    assert {h["changed_by"] for h in one["history"]} == {pl.a.user_id}
    names = {s["name"] for s in pl.client.get("/price-list/suppliers", headers=pl.as_(pl.a)).json()}
    assert {"ספק א׳", "ספק ב׳"} <= names


def test_one_preferred_and_one_cost_without_a_supplier(pl: Api) -> None:
    base = {"display_name": "x", "family": "relay"}
    two = [supplier("ספק א׳", "1", preferred=True), supplier("ספק ב׳", "2", preferred=True)]
    out = post(pl, pl.a, base | {"suppliers": two}, 422)
    assert out["error"]["details"][0]["type"] == "one_preferred"
    bare = [{"unit_cost": "1", "price_date": TODAY.isoformat()}] * 2
    assert post(pl, pl.a, base | {"suppliers": bare}, 422)["error"]["details"][0]["type"] == "duplicate_supplier"
    assert post(pl, pl.a, base | {"sale_mode": "fixed"}, 422)["error"]["details"][0]["loc"] == ["body", "fixed_price"]


def test_money_is_never_a_json_number(pl: Api) -> None:
    body = {"display_name": "x", "family": "relay", "sale_mode": "fixed", "fixed_price": 185.5}
    r = pl.client.post("/price-list/products", json=body, headers=pl.as_(pl.a))
    assert r.status_code == 422
    neg = {"display_name": "x", "family": "relay", "suppliers": [supplier("ספק א׳", "-1")]}
    assert post(pl, pl.a, neg, 422)["error"]["details"][0]["type"] == "invalid_amount"
    tiny = {"display_name": "x", "family": "relay", "sale_mode": "fixed", "fixed_price": "1.00001"}
    assert post(pl, pl.a, tiny, 422)["error"]["details"][0]["type"] == "invalid_amount"


def test_another_tenant_sees_nothing(pl: Api) -> None:
    out = post(pl, pl.a, {"display_name": "פרטי", "family": "relay", "suppliers": [supplier("ספק פרטי", "10")]})
    b = pl.as_(pl.b)
    assert pl.client.get(f"/price-list/products/{out['id']}", headers=b).status_code == 404
    assert pl.client.patch(f"/price-list/products/{out['id']}", json={"unit": "set"}, headers=b).status_code == 404
    assert out["id"] not in {p["id"] for p in pl.client.get("/price-list/products", headers=b).json()}
    assert "ספק פרטי" not in {s["name"] for s in pl.client.get("/price-list/suppliers", headers=b).json()}
    foreign = {
        "display_name": "x",
        "family": "relay",
        "suppliers": [{**supplier("", "1"), "supplier_id": out["suppliers"][0]["supplier_id"], "supplier_name": None}],
    }
    assert post(pl, pl.b, foreign, 422)["error"]["details"][0]["loc"] == ["body", "suppliers", 0, "supplier_id"]


def test_history_shows_every_change_with_who_and_the_quote(pl: Api) -> None:
    out = post(
        pl, pl.a, {"display_name": "בורר 1-0-2", "family": "selector_switch", "suppliers": [supplier("ספק ג׳", "62")]}
    )
    quote = a_quote(pl, pl.a)
    row = out["suppliers"][0]
    patch = {
        "sale_mode": "fixed",
        "fixed_price": "130",
        "quote_id": quote,
        "suppliers": [{**row, "unit_cost": "64", "supplier_name": None}],
    }
    patch["suppliers"][0].pop("supplier_name")
    patch["suppliers"][0].pop("in_force")
    r = pl.client.patch(f"/price-list/products/{out['id']}", json=patch, headers=pl.as_(pl.a))
    assert r.status_code == 200, r.text
    after = pl.client.get(f"/price-list/products/{out['id']}", headers=pl.as_(pl.a)).json()
    assert (after["unit_price"], after["unit_cost"], after["margin_rule"]["kind"]) == ("130.00", "64.0000", "fixed")
    changes = {h["field"]: h for h in after["history"] if h["quote_id"] == quote}
    assert set(changes) == {"sale_mode", "fixed_price", "supplier"}
    assert (changes["sale_mode"]["old"], changes["sale_mode"]["new"]) == ({"value": "rule"}, {"value": "fixed"})
    assert changes["fixed_price"]["new"] == {"value": "130"}
    assert (changes["supplier"]["old"]["unit_cost"], changes["supplier"]["new"]["unit_cost"]) == ("62", "64")
    assert all(h["changed_by"] == pl.a.user_id and h["changed_at"] for h in after["history"])

    # sending the same values again changes nothing, and logs nothing
    again = pl.client.patch(f"/price-list/products/{out['id']}", json=patch, headers=pl.as_(pl.a))
    assert again.status_code == 200
    assert len(again.json()["history"]) == len(after["history"])

    # a row left out is removed, and logged
    gone = pl.client.patch(f"/price-list/products/{out['id']}", json={"suppliers": []}, headers=pl.as_(pl.a)).json()
    assert gone["suppliers"] == [] and gone["unit_cost"] is None and gone["unit_price"] == "130.00"
    assert gone["history"][0]["field"] == "supplier" and gone["history"][0]["new"] is None


def test_switching_the_preferred_supplier(pl: Api) -> None:
    out = post(
        pl,
        pl.a,
        {
            "display_name": "פחת",
            "family": "rcd",
            "suppliers": [supplier("ספק א׳", "214", preferred=True), supplier("ספק ב׳", "220")],
        },
    )
    rows = [{k: v for k, v in s.items() if k not in ("supplier_name", "in_force")} for s in out["suppliers"]]
    rows[0]["preferred"], rows[1]["preferred"] = False, True
    after = pl.client.patch(f"/price-list/products/{out['id']}", json={"suppliers": rows}, headers=pl.as_(pl.a)).json()
    assert after["unit_cost"] == "220.0000"
    assert [s["preferred"] for s in after["suppliers"]] == [True, False]


def test_a_sku_is_unique_per_tenant(pl: Api) -> None:
    body = {"display_name": "x", "family": "relay", "manufacturer_sku": "T-UNIQUE"}
    post(pl, pl.a, body)
    assert post(pl, pl.a, body, 409)["error"]["code"] == "sku_exists"
    post(pl, pl.b, body)  # another tenant may have the same sku


def test_a_manual_cost_is_checked_and_kept(pl: Api) -> None:
    """10 §8, §9.2: a cost typed in a quote with no supplier, checked against the catalog's list price (210)."""
    with Session(pl.engine) as s:
        item = s.scalar(select(m.CatalogItem.id).where(m.CatalogItem.sku == "S203M-C16"))
    quote = a_quote(pl, pl.a)
    body = {
        "display_name": 'מא"ז 3X16A',
        "family": "circuit_breaker",
        "brand": "ABB",
        "catalog_item_id": item,
        "source": "manual_entry",
        "quote_id": quote,
        "suppliers": [{"unit_cost": "1920", "price_date": TODAY.isoformat(), "source": "manual_entry"}],
    }
    out = post(pl, pl.a, body)
    assert out["sanity"]["warning_shown"] is True
    assert out["sanity"]["warnings"][0] == {"code": "far_from_list", "reference": "210.0000", "reference_date": None}
    assert (out["entered_in_quote"], out["entered_by"], out["list_price"]) == (quote, pl.a.user_id, "210.0000")
    assert out["suppliers"][0]["supplier_id"] is None and out["unit_cost"] == "1920.0000"  # saved anyway

    # a later supplier price list supersedes the older manual entry (07 §7.2)
    manual = {k: v for k, v in out["suppliers"][0].items() if k not in ("supplier_name", "in_force")}
    manual["price_date"] = (TODAY - timedelta(days=5)).isoformat()
    listed = supplier("ספק א׳", "2000")
    r = pl.client.patch(f"/price-list/products/{out['id']}", json={"suppliers": [manual, listed]}, headers=pl.as_(pl.a))
    assert r.json()["unit_cost"] == "2000.0000"


def test_brand_discount(pl: Api) -> None:
    """07 §7.2 priority 2: a product with no supplier price takes the list price less the brand's discount."""
    with Session(pl.engine) as s:
        item = s.scalar(select(m.CatalogItem.id).where(m.CatalogItem.sku == "S203M-C20"))
    out = post(
        pl, pl.b, {"display_name": "3X20A", "family": "circuit_breaker", "brand": "ABB", "catalog_item_id": item}
    )
    assert out["price_status"] == "missing"
    quote = a_quote(pl, pl.b)
    r = pl.client.put(
        "/price-list/brand-discounts/ABB", json={"discount_pct": "0.32", "quote_id": quote}, headers=pl.as_(pl.b)
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"brand": "ABB", "discount_pct": "0.3200", "priced_products": 1}
    after = pl.client.get(f"/price-list/products/{out['id']}", headers=pl.as_(pl.b)).json()
    assert (after["unit_cost"], after["price_status"]) == ("146.2000", "discount_based")  # 215 × 0.68
    assert after["unit_price"] == "182.75"
    assert pl.client.get("/price-list/brand-discounts", headers=pl.as_(pl.a)).json() == []  # tenant a has none
    bad = pl.client.put("/price-list/brand-discounts/ABB", json={"discount_pct": "1"}, headers=pl.as_(pl.b))
    assert bad.status_code == 422
    with tenant_session(pl.b.tenant_id, pl.engine) as s:
        logged = s.scalars(select(m.PriceHistory).where(m.PriceHistory.subject == "brand_discount:ABB")).all()
        assert [(h.new, h.quote_id) for h in logged] == [({"value": "0.32"}, quote)]
    assert pl.client.delete("/price-list/brand-discounts/ABB", headers=pl.as_(pl.b)).status_code == 204
    assert pl.client.delete("/price-list/brand-discounts/ABB", headers=pl.as_(pl.b)).status_code == 404


def test_margin_rules(pl: Api) -> None:
    out = post(pl, pl.a, {"display_name": "ממסר", "family": "timer", "suppliers": [supplier("ספק א׳", "100")]})
    assert out["unit_price"] == "125.00"
    h = pl.as_(pl.a)
    rule = pl.client.post(
        "/price-list/margin-rules",
        json={"level": "family", "target": "timer", "kind": "margin", "value": "0.25"},
        headers=h,
    )
    assert rule.status_code == 201, rule.text
    after = pl.client.get(f"/price-list/products/{out['id']}", headers=h).json()
    assert (after["unit_price"], after["margin_rule"]["level"]) == ("133.33", "family")

    sku = pl.client.post(
        "/price-list/margin-rules",
        json={"level": "sku", "target": out["id"], "kind": "markup", "value": "0.5"},
        headers=h,
    )
    assert pl.client.get(f"/price-list/products/{out['id']}", headers=h).json()["unit_price"] == "150.00"
    patched = pl.client.patch(f"/price-list/margin-rules/{sku.json()['id']}", json={"value": "0.4"}, headers=h).json()
    assert (patched["value"], patched["version"]) == ("0.4000", 2)

    def refused(body: dict[str, Any]) -> str:
        r = pl.client.post("/price-list/margin-rules", json=body, headers=h)
        assert r.status_code == 422, r.text
        return str(r.json()["error"]["details"][0]["type"])

    assert refused({"level": "default", "kind": "margin", "value": "1"}) == "margin_below_100"
    assert refused({"level": "default", "kind": "markup", "value": "0.1", "fixed_price": "5"}) == "value_or_fixed"
    assert refused({"level": "customer", "kind": "markup", "value": "0.1"}) == "missing"
    assert refused({"level": "family", "kind": "markup", "value": "0.1"}) == "missing"
    assert refused({"level": "default", "kind": "markup", "value": "0.1", "target": "x"}) == "not_allowed"
    assert (
        refused({"level": "sku", "kind": "markup", "value": "0.1", "target": "prd_01JD0DEM000000000000000000"})
        == "not_found"
    )
    no_kind = pl.client.post("/price-list/margin-rules", json={"level": "default", "value": "0.1"}, headers=h)
    assert no_kind.status_code == 422  # 07 §7.3: the kind must be chosen

    rules = pl.client.get("/price-list/margin-rules", headers=h).json()
    assert [r["level"] for r in rules][:2] == ["sku", "family"] and rules[-1]["level"] == "default"
    default = rules[-1]["id"]
    assert (
        pl.client.delete(f"/price-list/margin-rules/{default}", headers=h).json()["error"]["code"]
        == "default_rule_required"
    )
    assert pl.client.delete(f"/price-list/margin-rules/{sku.json()['id']}", headers=h).status_code == 204


def test_a_family_preferred_supplier(pl: Api) -> None:
    """07 §7.2.2 item 3: with no preferred supplier on the product, the family's beats the cheapest."""
    out = post(
        pl,
        pl.a,
        {
            "display_name": "מגען",
            "family": "contactor",
            "brand": "ABB",
            "suppliers": [supplier("ספק א׳", "90"), supplier("ספק ב׳", "80")],
        },
    )
    assert out["unit_cost"] == "80.0000"
    dearer = next(s["supplier_id"] for s in out["suppliers"] if s["unit_cost"] == "90.0000")
    h = pl.as_(pl.a)
    r = pl.client.put("/price-list/supplier-preferences/family/contactor", json={"supplier_id": dearer}, headers=h)
    assert r.status_code == 200 and r.json()["supplier_name"] == "ספק א׳"
    after = pl.client.get(f"/price-list/products/{out['id']}", headers=h).json()
    assert (after["unit_cost"], after["cost_source"]["via"]) == ("90.0000", "family_preferred")
    assert [p["key"] for p in pl.client.get("/price-list/supplier-preferences", headers=h).json()] == ["contactor"]
    other = pl.client.put(
        "/price-list/supplier-preferences/family/contactor",
        json={"supplier_id": "sup_01JD0DEM000000000000000000"},
        headers=pl.as_(pl.b),
    )
    assert other.status_code == 422
    assert pl.client.delete("/price-list/supplier-preferences/family/contactor", headers=h).status_code == 204


def test_a_foreign_price_is_converted_and_an_old_one_is_stale(pl: Api) -> None:
    old = (TODAY - timedelta(days=100)).isoformat()
    usd = post(
        pl,
        pl.a,
        {"display_name": "XT1", "family": "circuit_breaker", "suppliers": [supplier("ספק ב׳", "100", currency="USD")]},
    )
    assert usd["unit_cost"] == "370.0000"
    assert (usd["cost_source"]["original_currency"], usd["cost_source"]["fx_rate"]) == ("USD", "3.700000")
    stale = post(
        pl, pl.a, {"display_name": "ישן", "family": "relay", "suppliers": [supplier("ספק א׳", "5", price_date=old)]}
    )
    assert stale["price_status"] == "stale"
    gone = post(
        pl,
        pl.a,
        {
            "display_name": "פג",
            "family": "relay",
            "suppliers": [supplier("ספק א׳", "5", price_date=old, valid_until=(TODAY - timedelta(days=1)).isoformat())],
        },
    )
    assert (gone["price_status"], gone["suppliers"][0]["in_force"]) == ("missing", False)


def test_search_and_filters(pl: Api) -> None:
    h = pl.as_(pl.a)
    post(pl, pl.a, {"display_name": "חומר עזר", "family": "terminal", "consumable": True})
    post(pl, pl.a, {"display_name": "בלי עלות", "family": "terminal"})
    post(
        pl,
        pl.a,
        {
            "display_name": "זול",
            "family": "terminal",
            "sale_mode": "fixed",
            "fixed_price": "10",
            "suppliers": [supplier("ספק א׳", "9.5")],
        },
    )

    def names(**params: str) -> set[str]:
        return {p["display_name"] for p in pl.client.get("/price-list/products", params=params, headers=h).json()}

    assert "בלי עלות" in names(filter="nocost") and "חומר עזר" not in names(filter="nocost")
    assert names(filter="multi") >= {'מא"ז ABB S203M 3P ‏16A', "מגען"} and "זול" not in names(filter="multi")
    assert "זול" in names(filter="low")  # 5% against tenant a's floor
    assert names(q="B-20316") == {'מא"ז ABB S203M 3P ‏16A'}  # a supplier's sku
    assert names(q="t-s203m") == {'מא"ז ABB S203M 3P ‏16A'}
    assert names(family="terminal") == {"חומר עזר", "בלי עלות", "זול"}
    assert pl.client.get("/price-list/products", params={"filter": "nope"}, headers=h).status_code == 422
