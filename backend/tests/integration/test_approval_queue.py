"""The pilot approval queue (00 §14.2, S24): factory products become candidates, only an explicit approval promotes
one through `konboro_promote`, the global record carries `pilot_engineer` and nothing private (10 §11), a rejection
touches nothing global, and no tenant sees or decides another's candidates."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.queue import seed_queue
from konboro.services import knowledge as kn
from konboro.services import price_list as pl

from .api import Api, ApiTenant, add_tenant, set_tenant_flag

pytestmark = pytest.mark.integration

FLAG = "approval_queue"


@pytest.fixture(scope="module")
def seeded(api: Api, migrated_db: dict[str, Engine]) -> Api:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the flags and the sample catalog
    return api


def factory(api: Api, *, flag: bool = True) -> ApiTenant:
    tenant = add_tenant(api.engine)
    set_tenant_flag(api.engine, tenant.tenant_id, FLAG, flag)
    return tenant


def add_product(api: Api, tenant: ApiTenant, sku: str | None, brand: str | None, **extra: Any) -> str:
    with tenant_session(tenant.tenant_id, api.engine) as s:
        view = pl.create_product(
            s,
            pl.Actor(tenant.tenant_id, tenant.user_id),
            pl.ProductIn(
                display_name=extra.get("name", f"מוצר {sku}"),
                family=extra.get("family", "circuit_breaker"),
                source="manual_entry",
                manufacturer_sku=sku,
                brand=brand,
                suppliers=[
                    pl.SupplierPriceIn(unit_cost=Decimal("142.80"), price_date=date.today(), supplier_name="ספק פרטי")
                ],
            ),
        )
    return view.id


def queue(api: Api, tenant: ApiTenant, status: int = 200) -> dict[str, Any]:
    r = api.client.get("/knowledge-candidates", headers=api.as_(tenant))
    assert r.status_code == status, r.text
    return dict(r.json())


def decide(
    api: Api, tenant: ApiTenant, cid: str, action: str, status: int = 200, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = api.client.post(f"/knowledge-candidates/{cid}/{action}", json=body or {}, headers=api.as_(tenant))
    assert r.status_code == status, r.text
    return dict(r.json())


def global_item(api: Api, brand: str, sku: str) -> m.CatalogItem | None:
    with Session(api.engine) as s:
        row = s.scalar(select(m.CatalogItem).where(m.CatalogItem.brand == brand, m.CatalogItem.sku == sku))
        if row is not None:
            s.expunge(row)
    return row


def test_a_product_the_catalog_lacks_is_proposed_once(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    pid = add_product(api, tenant, "MCN316", "Hager", name='מא"ז Hager 3P ‏16A')
    add_product(api, tenant, "S201M-C6", "ABB")  # in the master catalog already
    add_product(api, tenant, None, None, name="בורר 1-0-2", family="selector_switch")  # no SKU: nothing to promote
    add_product(api, tenant, "X-1", "—")  # the prototype's "no brand"
    with tenant_session(tenant.tenant_id, api.engine) as s:  # an edit of the same product proposes nothing new
        pl.update_product(s, pl.Actor(tenant.tenant_id, tenant.user_id), pid, {"brand": "Hager"})

    body = queue(api, tenant)
    assert body["pending"] == 1
    [item] = body["items"]
    assert item["kind"] == "catalog_item"
    assert item["what"] == "Hager MCN316"
    assert item["evidence"] == 'מא"ז Hager 3P ‏16A'
    assert item["origin"] == "הזנה ידנית"
    assert (item["status"], item["promoted"]) == ("pending", False)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        payload = s.scalar(select(m.KnowledgeCandidate.payload))
    assert payload == {"sku": "MCN316", "brand": "Hager", "family": "circuit_breaker"}  # no price, no supplier


def test_approval_promotes_with_pilot_engineer_and_nothing_private(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    pid = add_product(api, tenant, "LC1D09M7", "Schneider", name="מגען TeSys לפרויקט של לקוח פרטי", family="contactor")
    [item] = queue(api, tenant)["items"]
    assert global_item(api, "Schneider", "LC1D09M7") is None

    done = decide(api, tenant, item["id"], "approve")
    assert (done["status"], done["promoted"]) == ("approved", True)
    row = global_item(api, "Schneider", "LC1D09M7")
    assert row is not None
    assert (row.source, row.source_tenant_id, row.approved_by) == ("pilot_engineer", tenant.tenant_id, tenant.user_id)
    assert row.approved_at is not None
    assert (row.family, row.list_price, row.list_currency, row.attributes) == ("contactor", None, None, {})
    with tenant_session(tenant.tenant_id, api.engine) as s:
        assert s.get_one(m.Product, pid).catalog_item_id == row.id  # the factory's product now has its item
    decide(api, tenant, item["id"], "approve", status=409)
    decide(api, tenant, item["id"], "reject", status=409)


def test_a_rejection_keeps_it_with_the_factory(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    add_product(api, tenant, "CDA440D", "Hager", family="rcd")
    [item] = queue(api, tenant)["items"]
    done = decide(api, tenant, item["id"], "reject", body={"reason": "  מוצר מיוחד שלנו "})
    assert (done["status"], done["reason"], done["promoted"]) == ("rejected", "מוצר מיוחד שלנו", False)
    assert global_item(api, "Hager", "CDA440D") is None
    add_product(api, tenant, "cda440d", "HAGER")  # the same SKU again is not queued a second time
    assert queue(api, tenant)["pending"] == 0


def test_the_prototype_kinds_reach_their_global_tables(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        seed_queue(s, tenant.tenant_id)
        seed_queue(s, tenant.tenant_id)  # a rerun adds nothing
    items = {i["what"]: i for i in queue(api, tenant)["items"]}
    assert len(items) == 6
    for what in ('"SAVE" ← שמור (מעגל רזרבי)', "ממסר צעד (טלרופטור)", '"מ.פ." ← מפסק פחת', "מנתק SOCOMEC 4P ‏125A"):
        assert decide(api, tenant, items[what]["id"], "approve")["promoted"] is True
    with Session(api.engine) as s:
        spelling = s.scalar(select(m.SpellingPattern).where(m.SpellingPattern.pattern == "SAVE"))
        symbol = s.get(m.SymbolClass, "step_relay")
        abbreviation = s.scalar(select(m.Abbreviation).where(m.Abbreviation.text == "מ.פ."))
    assert spelling is not None and (spelling.source, spelling.source_tenant_id) == ("pilot_engineer", tenant.tenant_id)
    assert symbol is not None and (symbol.source, symbol.family) == ("pilot_engineer", "relay")
    assert abbreviation is not None  # curated already: the approval finds it and leaves it as it is
    assert abbreviation.source == "curated"
    assert global_item(api, "SOCOMEC", "SIRCO-4P-125") is not None
    # the order: pending oldest first, then the decided ones
    statuses = [i["status"] for i in queue(api, tenant)["items"]]
    assert statuses == ["pending", "pending", "approved", "approved", "approved", "approved"]


def test_an_attribute_fills_a_gap_and_never_overwrites(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    item = global_item(api, "ABB", "S201M-C10")
    assert item is not None and "cross_section_mm2" not in item.attributes
    with tenant_session(tenant.tenant_id, api.engine) as s:
        fill = kn.propose(
            s,
            tenant.tenant_id,
            "catalog_attribute",
            {"catalog_item_id": item.id, "name": "cross_section_mm2", "value": 25},
            {"text": "NURSERY · F1"},
        )
        clash = kn.propose(
            s,
            tenant.tenant_id,
            "catalog_attribute",
            {"catalog_item_id": item.id, "name": "current_a", "value": 16},
            {"text": "NURSERY · F2"},
        )
    assert fill is not None and clash is not None
    decide(api, tenant, fill, "approve")
    after = global_item(api, "ABB", "S201M-C10")
    assert after is not None and after.attributes["cross_section_mm2"] == 25
    assert after.attribute_provenance["cross_section_mm2"]["source"] == "pilot_engineer"
    assert after.source == "import"  # the row keeps its own source

    body = decide(api, tenant, clash, "approve", status=409)
    assert body["error"]["code"] == "global_conflict"
    assert global_item(api, "ABB", "S201M-C10").attributes["current_a"] == 10  # type: ignore[union-attr]
    pending = {i["id"]: i["status"] for i in queue(api, tenant)["items"]}
    assert pending[clash] == "pending"  # nothing changed


def test_a_payload_that_carries_money_still_promotes_none(seeded: Api) -> None:
    """The function copies only the record's fields, even from a row written past the service's whitelist."""
    api, tenant = seeded, factory(seeded)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        s.add(
            m.KnowledgeCandidate(
                id=(cid := new_id("kc")),
                tenant_id=tenant.tenant_id,
                kind="catalog_item",
                payload={
                    "sku": "SMUGGLED-1",
                    "brand": "Hager",
                    "family": "rcd",
                    "list_price": "999.00",
                    "unit_cost": "500.00",
                    "supplier": "ספק פרטי",
                    "customer": "לקוח",
                    "attributes": {"residual_ma": 30},
                },
                dedupe_key="HAGER|SMUGGLED-1",
            )
        )
    decide(api, tenant, cid, "approve")
    row = global_item(api, "Hager", "SMUGGLED-1")
    assert row is not None
    assert (row.list_price, row.list_currency, row.attributes) == (None, None, {"residual_ma": 30})


def test_no_tenant_sees_or_decides_another_tenants_candidates(seeded: Api) -> None:
    api = seeded
    a, b = factory(api), factory(api)
    add_product(api, a, "A9N61500", "Schneider")
    [item] = queue(api, a)["items"]
    assert queue(api, b)["items"] == []
    decide(api, b, item["id"], "approve", status=404)
    decide(api, b, item["id"], "reject", status=404)
    with tenant_session(b.tenant_id, api.engine) as s, pytest.raises(DBAPIError, match="not found"):
        s.execute(text("SELECT konboro_promote(:c, :r)"), {"c": item["id"], "r": new_id("cat")})
    assert global_item(api, "Schneider", "A9N61500") is None


def test_the_function_promotes_only_an_approved_candidate(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded)
    add_product(api, tenant, "A9N61508", "Schneider")
    [item] = queue(api, tenant)["items"]
    with tenant_session(tenant.tenant_id, api.engine) as s, pytest.raises(DBAPIError, match="not approved"):
        s.execute(text("SELECT konboro_promote(:c, :r)"), {"c": item["id"], "r": new_id("cat")})
    with tenant_session(tenant.tenant_id, api.engine) as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("INSERT INTO spelling_patterns (id, pattern, meaning_he) VALUES ('spl_x', 'X', 'x')"))


def test_with_the_flag_off_there_is_no_queue(seeded: Api) -> None:
    api, tenant = seeded, factory(seeded, flag=False)
    add_product(api, tenant, "A9N61510", "Schneider")
    queue(api, tenant, status=404)
    with tenant_session(tenant.tenant_id, api.engine) as s:
        assert s.scalar(select(m.KnowledgeCandidate.id)) is None
