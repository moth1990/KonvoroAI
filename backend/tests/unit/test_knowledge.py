"""The approval queue's whitelist (10 §11, 00 §9): a candidate carries only its global record's fields."""

from typing import Any

import pytest

from konboro.services import knowledge as kn

RAW: dict[str, dict[str, Any]] = {
    "catalog_item": {
        "sku": " A9F74316 ",
        "brand": "Schneider",
        "family": "circuit_breaker",
        "attributes": {"poles": 3},
    },
    "abbreviation": {"text": "מ.פ.", "family": "rcd", "display_he": "מפסק פחת"},
    "spelling": {"pattern": "SAVE", "meaning_he": "שמור"},
    "symbol": {"id": "step_relay", "family": "relay", "display_name_he": "ממסר צעד", "billable": True},
    "catalog_attribute": {"catalog_item_id": "cat_1", "name": "current_a", "value": 16},
}
PRIVATE = {
    "price": "100",
    "unit_cost": "80",
    "list_price": "120",
    "fixed_price": "130",
    "supplier": "ספק",
    "supplier_id": "sup_1",
    "customer": "לקוח",
    "customer_id": "cus_1",
    "project": "פרויקט",
    "designer": "מתכנן",
    "tenant_id": "tnt_1",
    "display_name": "השם של המפעל",
}


@pytest.mark.parametrize("kind", kn.KINDS)
def test_every_kind_drops_private_fields(kind: str) -> None:
    payload = kn.clean_payload(kind, {**RAW[kind], **PRIVATE})
    assert set(payload) <= set(kn.FIELDS[kind])
    assert not set(payload) & set(PRIVATE)


def test_an_items_attributes_lose_money_and_names_too() -> None:
    payload = kn.clean_payload(
        "catalog_item", {**RAW["catalog_item"], "attributes": {"poles": 3, "unit_cost": "80", "customer": "לקוח"}}
    )
    assert payload == {"sku": "A9F74316", "brand": "Schneider", "family": "circuit_breaker", "attributes": {"poles": 3}}
    only_private = kn.clean_payload("catalog_item", {**RAW["catalog_item"], "attributes": {"price": "1"}})
    assert "attributes" not in only_private


@pytest.mark.parametrize(("kind", "missing"), [("catalog_item", "brand"), ("spelling", "meaning_he"), ("symbol", "id")])
def test_a_required_field_is_required(kind: str, missing: str) -> None:
    with pytest.raises(kn.KnowledgeError, match="invalid_payload"):
        kn.clean_payload(kind, {**RAW[kind], missing: "  " if kind != "symbol" else None})


def test_bad_kinds_and_attributes_are_refused() -> None:
    with pytest.raises(kn.KnowledgeError, match="unknown_kind"):
        kn.clean_payload("price", {})
    with pytest.raises(kn.KnowledgeError, match="invalid_payload"):
        kn.clean_payload("catalog_item", {**RAW["catalog_item"], "attributes": "3P"})


def test_the_same_thing_has_one_key() -> None:
    a = kn.dedupe_key("catalog_item", kn.clean_payload("catalog_item", RAW["catalog_item"]))
    b = kn.dedupe_key("catalog_item", {"sku": "a9f74316", "brand": "SCHNEIDER", "family": "x"})
    assert a == b == "SCHNEIDER|A9F74316"
    assert kn.dedupe_key("catalog_attribute", RAW["catalog_attribute"]) == "cat_1|current_a"
    assert kn.dedupe_key("abbreviation", RAW["abbreviation"]) == "מ.פ."
    assert kn.dedupe_key("spelling", RAW["spelling"]) == "SAVE"
    assert kn.dedupe_key("symbol", RAW["symbol"]) == "step_relay"


def test_the_cards_title() -> None:
    assert kn.what_he("catalog_item", kn.clean_payload("catalog_item", RAW["catalog_item"]), {}) == "Schneider A9F74316"
    assert kn.what_he("catalog_item", RAW["catalog_item"], {"what": "ארון"}) == "ארון"
    assert kn.what_he("abbreviation", RAW["abbreviation"], {}) == '"מ.פ." ← מפסק פחת'
    assert kn.what_he("abbreviation", {"text": "X"}, {}) == '"X"'
    assert kn.what_he("spelling", RAW["spelling"], {}) == '"SAVE" ← שמור'
    assert kn.what_he("symbol", RAW["symbol"], {}) == "ממסר צעד"
    assert kn.what_he("catalog_attribute", RAW["catalog_attribute"], {}) == "current_a = 16"
