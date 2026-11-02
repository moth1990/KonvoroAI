"""konboro.domain.pricing (07 §7.2–7.3, 10 §8). Every amount is a Decimal and every expected value is exact."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from konboro.domain.pricing import money
from konboro.domain.pricing.cost import CostContext, ProductCosts, SupplierPrice, candidates, unit_cost
from konboro.domain.pricing.fx import MAX_AGE_DAYS, FxRate, FxRateMissing, convert, rate_for
from konboro.domain.pricing.margin import (
    InvalidRule,
    Rule,
    Subject,
    check,
    line_floor,
    pick,
    price,
    quote_floor,
    sale_price,
)
from konboro.domain.pricing.sanity import check_cost

DAY = date(2026, 11, 2)


def sp(id: str, cost: str, supplier: str | None = None, **kw: object) -> SupplierPrice:
    kw.setdefault("price_date", date(2026, 10, 1))
    kw.setdefault("currency", "ILS")
    return SupplierPrice(id=id, supplier_id=supplier, unit_cost=D(cost), **kw)  # type: ignore[arg-type]


def product(*suppliers: SupplierPrice, **kw: object) -> ProductCosts:
    kw.setdefault("family", "mcb")
    kw.setdefault("brand", "ABB")
    return ProductCosts(product_id="prd_1", suppliers=suppliers, **kw)  # type: ignore[arg-type]


def ctx(**kw: object) -> CostContext:
    kw.setdefault("on_date", DAY)
    return CostContext(**kw)  # type: ignore[arg-type]


# --- fx -------------------------------------------------------------------------------------------------------------

RATES = [
    FxRate("USD", date(2026, 10, 30), D("3.70")),
    FxRate("USD", date(2026, 10, 20), D("3.60")),
    FxRate("EUR", date(2026, 10, 1), D("4.00")),
]


def test_fx_uses_the_latest_rate_on_or_before_the_date() -> None:
    assert rate_for(RATES, "USD", DAY).rate == D("3.70")
    assert rate_for(RATES, "USD", date(2026, 10, 25)).rate == D("3.60")


def test_fx_rate_older_than_seven_days_is_missing() -> None:
    assert rate_for(RATES, "USD", date(2026, 10, 30) + timedelta(days=MAX_AGE_DAYS)).rate == D("3.70")
    with pytest.raises(FxRateMissing):
        rate_for(RATES, "USD", date(2026, 10, 30) + timedelta(days=MAX_AGE_DAYS + 1))
    with pytest.raises(FxRateMissing):
        rate_for(RATES, "EUR", DAY)
    with pytest.raises(FxRateMissing):  # a later rate is never used for an earlier date
        rate_for(RATES, "USD", date(2026, 10, 19))


def test_convert_keeps_the_rate_and_its_date() -> None:
    same = convert(D("10"), "ILS", "ILS", RATES, DAY)
    assert same.amount == D("10") and same.fx_rate is None
    usd = convert(D("12.345"), "USD", "ILS", RATES, DAY)
    assert usd.amount == D("45.6765")  # 12.345 × 3.70, 4 places
    assert (usd.original_currency, usd.original_amount, usd.fx_rate, usd.fx_date) == (
        "USD",
        D("12.345"),
        D("3.70"),
        date(2026, 10, 30),
    )


# --- cost order (07 §7.2.2) -----------------------------------------------------------------------------------------

A = sp("psp_a", "138", "sup_a", preferred=True, supplier_name="ספק א׳")
B = sp("psp_b", "131", "sup_b", supplier_name="ספק ב׳")
C = sp("psp_c", "135", "sup_c")


def test_1_the_line_supplier_wins_for_this_quote() -> None:
    cost = unit_cost(product(A, B), ctx(), line_supplier_id="sup_b")
    assert cost.unit_cost == D("131") and cost.source and cost.source["via"] == "line"
    assert cost.source["supplier"] == "ספק ב׳" and cost.price_status == "ok"


def test_2_then_the_product_preferred_supplier() -> None:
    cost = unit_cost(product(A, B), ctx())
    assert cost.unit_cost == D("138") and cost.source and cost.source["via"] == "product_preferred"


def test_a_line_supplier_the_product_does_not_have_is_ignored() -> None:
    cost = unit_cost(product(A, B), ctx(), line_supplier_id="sup_x")
    assert cost.unit_cost == D("138")


def test_3_then_the_family_preferred_supplier_before_the_brand_one() -> None:
    prefs = {("family", "mcb"): "sup_c", ("brand", "ABB"): "sup_b"}
    cost = unit_cost(product(B, C), ctx(supplier_preferences=prefs))
    assert cost.unit_cost == D("135") and cost.source and cost.source["via"] == "family_preferred"
    cost = unit_cost(product(B, C), ctx(supplier_preferences={("brand", "ABB"): "sup_c"}))
    assert cost.unit_cost == D("135") and cost.source and cost.source["via"] == "brand_preferred"


def test_a_preference_for_a_supplier_the_product_lacks_falls_through() -> None:
    prefs = {("family", "mcb"): "sup_x"}
    cost = unit_cost(product(B, C, brand=None), ctx(supplier_preferences=prefs))
    assert cost.unit_cost == D("131") and cost.source and cost.source["via"] == "cheapest"


def test_4_otherwise_the_cheapest_in_force() -> None:
    cost = unit_cost(product(C, B), ctx())
    assert cost.unit_cost == D("131") and cost.source and cost.source["supplier_price_id"] == "psp_b"


def test_cheapest_ties_go_to_the_newest_then_the_id() -> None:
    old = sp("psp_1", "100", "s1", price_date=date(2026, 9, 1))
    new = sp("psp_2", "100", "s2", price_date=date(2026, 10, 1))
    same_day = sp("psp_0", "100", "s3", price_date=date(2026, 10, 1))
    cost = unit_cost(product(old, new, same_day), ctx())
    assert cost.source and cost.source["supplier_price_id"] == "psp_0"


def test_cheapest_compares_in_the_quote_currency() -> None:
    usd = sp("psp_usd", "36", "s1", currency="USD")  # 36 × 3.70 = 133.20
    cost = unit_cost(product(usd, C), ctx(fx_rates=RATES))
    assert cost.unit_cost == D("133.2000")
    assert cost.source and cost.source["original_currency"] == "USD" and cost.source["fx_rate"] == "3.70"


def test_cheapest_skips_a_price_with_no_rate() -> None:
    eur = sp("psp_eur", "1", "s1", currency="EUR")
    assert unit_cost(product(eur, C), ctx(fx_rates=RATES)).unit_cost == D("135")
    missing = unit_cost(product(eur), ctx(fx_rates=RATES))
    assert (missing.unit_cost, missing.price_status, missing.issue) == (None, "missing", "fx_rate_missing")


def test_a_chosen_supplier_with_no_rate_has_no_price() -> None:
    eur = sp("psp_eur", "1", "s1", currency="EUR", preferred=True)
    cost = unit_cost(product(eur, C), ctx(fx_rates=RATES))
    assert (cost.unit_cost, cost.issue) == (None, "fx_rate_missing")


def test_an_expired_price_is_skipped_at_every_step() -> None:
    """S18 decision 2: past valid_until is not in force, even for the line's or the preferred supplier."""
    expired = date(2026, 11, 1)
    a = sp("psp_a", "100", "sup_a", preferred=True, valid_until=expired)
    b = sp("psp_b", "131", "sup_b", valid_until=DAY)  # valid on its last day
    cost = unit_cost(product(a, b), ctx(), line_supplier_id="sup_a")
    assert cost.unit_cost == D("131") and cost.source and cost.source["via"] == "cheapest"


def test_stale_after_stale_days() -> None:
    at_limit = sp("p", "10", "s", price_date=DAY - timedelta(days=90))
    older = sp("p", "10", "s", price_date=DAY - timedelta(days=91))
    assert unit_cost(product(at_limit), ctx()).price_status == "ok"
    assert unit_cost(product(older), ctx()).price_status == "stale"
    assert unit_cost(product(older), ctx(stale_days=120)).price_status == "ok"


def test_a_manual_entry_with_no_supplier_prices_the_line() -> None:
    manual = sp("psp_m", "142.80", None, source="manual_entry")
    cost = unit_cost(product(manual), ctx())
    assert cost.unit_cost == D("142.80") and cost.source
    assert (cost.source["type"], cost.source["supplier_id"], cost.source["supplier"]) == ("manual_entry", None, None)


def test_a_later_supplier_price_list_supersedes_an_older_manual_entry() -> None:
    manual = sp("psp_m", "100", None, source="manual_entry", price_date=date(2026, 9, 1))
    listed = sp("psp_l", "120", "sup_l", price_date=date(2026, 10, 1))
    assert [p.id for p in candidates(product(manual, listed), DAY)] == ["psp_l"]
    assert unit_cost(product(manual, listed), ctx()).unit_cost == D("120")
    # a manual entry newer than the price list stays, and is the cheaper one here
    newer = sp("psp_m", "100", None, source="manual_entry", price_date=date(2026, 10, 15))
    assert unit_cost(product(newer, listed), ctx()).unit_cost == D("100")


def test_brand_discount_is_priority_2() -> None:
    p = product(list_price=D("210.00"), list_currency="ILS")
    cost = unit_cost(p, ctx(brand_discounts={"ABB": D("0.32")}))
    assert cost.unit_cost == D("142.8000") and cost.price_status == "discount_based"
    assert cost.source == {"type": "brand_discount", "list_price": "210.00", "discount_pct": "0.32"}


def test_a_supplier_price_beats_the_brand_discount() -> None:
    p = product(C, list_price=D("210.00"))
    assert unit_cost(p, ctx(brand_discounts={"ABB": D("0.32")})).unit_cost == D("135")


def test_brand_discount_converts_a_foreign_list_price() -> None:
    p = product(list_price=D("50"), list_currency="USD")
    cost = unit_cost(p, ctx(brand_discounts={"ABB": D("0.2")}, fx_rates=RATES))
    assert cost.unit_cost == D("148.0000")  # 50 × 0.8 × 3.70
    assert cost.source and cost.source["original_cost"] == "40.0000"
    no_rate = product(list_price=D("50"), list_currency="EUR")
    assert unit_cost(no_rate, ctx(brand_discounts={"ABB": D("0.2")}, fx_rates=RATES)).issue == "fx_rate_missing"


def test_brand_discount_list_price_without_currency_is_the_quote_currency() -> None:
    p = product(list_price=D("100"))
    assert unit_cost(p, ctx(brand_discounts={"ABB": D("0.1")})).unit_cost == D("90.0000")


def test_no_brand_discount_without_a_list_price_a_brand_or_a_discount() -> None:
    discounts = {"ABB": D("0.32")}
    assert unit_cost(product(), ctx(brand_discounts=discounts)).issue == "missing_cost"
    assert unit_cost(product(list_price=D("1"), brand=None), ctx(brand_discounts=discounts)).issue == "missing_cost"
    assert unit_cost(product(list_price=D("1")), ctx()).issue == "missing_cost"


def test_missing_when_nothing_prices_it() -> None:
    cost = unit_cost(product(), ctx())
    assert (cost.unit_cost, cost.price_status, cost.source, cost.issue) == (
        None,
        "missing",
        {"type": "missing"},
        "missing_cost",
    )


def test_identical_product_only() -> None:
    """07 §7.2: NURSERY-1's 3X20A has no price, although 3X16A and 3X25A do. Prices belong to one product, so a
    product without rows of its own never borrows a neighbour's."""
    s203_16 = ProductCosts("prd_16", "mcb", "ABB", [sp("psp_16", "138", "sup_a")])
    s203_25 = ProductCosts("prd_25", "mcb", "ABB", [sp("psp_25", "145", "sup_a")])
    s203_20 = ProductCosts("prd_20", "mcb", "ABB", [])
    assert unit_cost(s203_16, ctx()).unit_cost == D("138")
    assert unit_cost(s203_25, ctx()).unit_cost == D("145")
    assert unit_cost(s203_20, ctx()).price_status == "missing"


# --- margin rules (07 §7.3) -----------------------------------------------------------------------------------------

SUBJECT = Subject(product_id="prd_1", family="mcb", brand="ABB", customer_id="cus_1")
RULES = [
    Rule("mr_default", "default", "markup", D("0.25")),
    Rule("mr_brand", "brand", "markup", D("0.30"), target="ABB"),
    Rule("mr_family", "family", "markup", D("0.28"), target="mcb"),
    Rule("mr_sku", "sku", "margin", D("0.20"), target="prd_1"),
    Rule("mr_customer", "customer", "markup", D("0.10"), customer_id="cus_1"),
    Rule("mr_customer_sku", "customer_sku", "markup", D("0.05"), target="prd_1", customer_id="cus_1"),
]


@pytest.mark.parametrize(
    ("dropped", "winner"),
    [
        (0, "mr_customer_sku"),
        (1, "mr_customer"),
        (2, "mr_sku"),
        (3, "mr_family"),
        (4, "mr_brand"),
        (5, "mr_default"),
    ],
)
def test_the_most_specific_rule_wins(dropped: int, winner: str) -> None:
    """customer_sku > customer > sku > family > brand > default: drop the more specific ones one at a time."""
    order = ["mr_customer_sku", "mr_customer", "mr_sku", "mr_family", "mr_brand", "mr_default"]
    rules = [r for r in RULES if r.id not in order[:dropped]]
    rule = pick(rules, SUBJECT, DAY)
    assert rule and rule.id == winner


def test_rules_for_another_target_do_not_apply() -> None:
    other = Subject(product_id="prd_2", family="rcd", brand="Schneider", customer_id="cus_2")
    rule = pick(RULES, other, DAY)
    assert rule and rule.id == "mr_default"


def test_customer_rules_need_a_customer() -> None:
    no_customer = Subject(product_id="prd_1", family="mcb", brand="ABB")
    rule = pick(RULES, no_customer, DAY)
    assert rule and rule.id == "mr_sku"


def test_a_brand_rule_needs_a_brand() -> None:
    no_brand = Subject(product_id="prd_9", family="relay", brand=None)
    rules = [Rule("mr_b", "brand", value=D("0.3"), target=None), Rule("mr_d", "default", value=D("0.25"))]
    rule = pick(rules, no_brand, DAY)
    assert rule and rule.id == "mr_d"


def test_a_fixed_product_is_the_sku_level() -> None:
    """S18 decision 6: the product's fixed price beats family, brand and default, and loses to customer rules."""
    fixed = Subject("prd_1", "mcb", "ABB", sale_mode="fixed", fixed_price=D("185"), customer_id="cus_1")
    rules = [r for r in RULES if r.level not in ("customer_sku", "customer")]
    assert sale_price(D("138"), rules, fixed, DAY).unit_price_raw == D("185")
    sale = sale_price(D("138"), RULES, fixed, DAY)
    assert sale.rule and sale.rule["rule_id"] == "mr_customer_sku"
    assert sale.unit_price_raw == D("144.9000")


def test_stored_sku_rules_do_not_apply_to_a_fixed_product() -> None:
    fixed = Subject("prd_1", "mcb", "ABB", sale_mode="fixed", fixed_price=D("185"))
    sale = sale_price(D("138"), RULES, fixed, DAY)
    assert sale.rule == {"rule_id": "prd_1", "level": "sku", "kind": "fixed", "value": None, "fixed_price": "185"}


def test_a_fixed_product_without_a_price_falls_back_to_rules() -> None:
    broken = Subject("prd_1", "mcb", "ABB", sale_mode="fixed", fixed_price=None)
    rule = pick(RULES, broken, DAY)
    assert rule and rule.id == "mr_family"


def test_validity_dates() -> None:
    rules = [
        Rule("mr_d", "default", value=D("0.25")),
        Rule("mr_past", "family", value=D("0.5"), target="mcb", valid_to=date(2026, 11, 1)),
        Rule("mr_future", "family", value=D("0.6"), target="mcb", valid_from=date(2026, 11, 3)),
    ]
    rule = pick(rules, SUBJECT, DAY)
    assert rule and rule.id == "mr_d"
    edges = [Rule("mr_edge", "family", value=D("0.5"), target="mcb", valid_from=DAY, valid_to=DAY)]
    rule = pick(edges, SUBJECT, DAY)
    assert rule and rule.id == "mr_edge"


def test_same_level_the_latest_then_the_version_then_the_id() -> None:
    rules = [
        Rule("mr_2", "family", value=D("0.1"), target="mcb", valid_from=date(2026, 1, 1)),
        Rule("mr_1", "family", value=D("0.2"), target="mcb", valid_from=date(2026, 6, 1)),
    ]
    assert pick(rules, SUBJECT, DAY).id == "mr_1"  # type: ignore[union-attr]
    versions = [Rule("mr_a", "default", value=D("0.1")), Rule("mr_b", "default", value=D("0.2"), version=2)]
    assert pick(versions, SUBJECT, DAY).id == "mr_b"  # type: ignore[union-attr]
    ids = [Rule("mr_b", "default", value=D("0.1")), Rule("mr_a", "default", value=D("0.2"))]
    assert pick(ids, SUBJECT, DAY).id == "mr_a"  # type: ignore[union-attr]


def test_formulas() -> None:
    """07 §3: cost 100, markup 25% -> 125; margin 25% -> 133.33…"""
    assert price(D("100"), Rule("r", "default", "markup", D("0.25"))) == D("125.0000")
    assert price(D("100"), Rule("r", "default", "margin", D("0.25"))) == D("133.3333")
    assert price(D("100"), Rule("r", "default", fixed_price=D("99.90"))) == D("99.90")
    assert price(None, Rule("r", "default", fixed_price=D("99.90"))) == D("99.90")
    assert price(None, Rule("r", "default", "markup", D("0.25"))) is None
    assert price(D("0.1"), Rule("r", "default", "margin", D("0.6667"))) == D("0.3000")  # 0.30003 to 4 places


def test_rule_checks() -> None:
    with pytest.raises(InvalidRule, match="100%"):
        check(Rule("r", "default", "margin", D("1")))
    with pytest.raises(InvalidRule, match="not both"):
        check(Rule("r", "default", "markup", D("0.2"), fixed_price=D("1")))
    with pytest.raises(InvalidRule, match="not both"):
        price(D("1"), Rule("r", "default", "markup"))
    check(Rule("r", "default", "markup", D("1.5")))  # a markup may be above 100%
    check(Rule("r", "default", "margin", D("0.99")))


def test_sale_price_trace_and_no_rule() -> None:
    sale = sale_price(D("100"), [Rule("mr_d", "default", "margin", D("0.25"))], SUBJECT, DAY)
    assert sale.unit_price_raw == D("133.3333") and sale.issue is None
    assert sale.rule == {"rule_id": "mr_d", "level": "default", "kind": "margin", "value": "0.25", "fixed_price": None}
    none = sale_price(D("100"), [], SUBJECT, DAY)
    assert (none.unit_price_raw, none.rule, none.issue) == (None, None, "no_margin_rule")
    no_cost = sale_price(None, [Rule("mr_d", "default", value=D("0.25"))], SUBJECT, DAY)
    assert no_cost.unit_price_raw is None and no_cost.issue is None


def test_margin_floors_only_report() -> None:
    floor = D("0.15")
    finding = line_floor(D("100"), D("92"), floor)
    assert finding and (finding.code, finding.margin_pct, finding.floor) == ("below_margin_floor", D("0.0800"), floor)
    assert line_floor(D("100"), D("85"), floor) is None  # exactly at the floor
    assert line_floor(D("100"), None, floor) is None
    assert line_floor(D("100"), D("92"), None) is None
    quote = quote_floor(D("0.1"), floor)
    assert quote and quote.code == "quote_below_margin_floor"
    assert quote_floor(D("0.2"), floor) is None
    assert quote_floor(None, floor) is None
    assert quote_floor(D("0.1"), None) is None


def test_money_rounds_half_up_to_four_places() -> None:
    assert money(D("1.00005")) == D("1.0001")
    assert money(D("1.00004")) == D("1.0000")


# --- sanity (10 §8) -------------------------------------------------------------------------------------------------


def test_sanity_against_the_list_price() -> None:
    ok = check_cost(D("142.80"), list_price=D("210.00"))
    assert ok.warnings == [] and ok.ratio_to_list == D("0.68")
    assert ok.as_json() == {"list_price": "210.00", "ratio_to_list": "0.68", "warning_shown": False, "warnings": []}
    above = check_cost(D("1920"), list_price=D("210.00"))
    assert [w.code for w in above.warnings] == ["far_from_list"]
    below = check_cost(D("19.20"), list_price=D("210.00"))
    assert [w.code for w in below.warnings] == ["far_from_list"]
    assert check_cost(D("63"), list_price=D("210")).warnings == []  # exactly 30%
    assert check_cost(D("1"), list_price=D("0")).ratio_to_list is None


def test_sanity_against_similar_products() -> None:
    similar = [D("130"), D("138"), D("145")]
    assert check_cost(D("140"), similar_costs=similar).warnings == []
    far = check_cost(D("414"), similar_costs=similar)
    assert [(w.code, w.reference) for w in far.warnings] == [("far_from_similar", D("138"))]
    assert [w.code for w in check_cost(D("46"), similar_costs=similar).warnings] == ["far_from_similar"]
    assert check_cost(D("47"), similar_costs=similar).warnings == []
    assert check_cost(D("5"), similar_costs=[D("0")]).warnings == []


def test_sanity_against_the_previous_price() -> None:
    when = date(2026, 6, 1)
    jump = check_cost(D("160"), previous=(D("100"), when))
    assert jump.as_json()["warnings"] == [
        {"code": "jump_from_previous", "reference": "100", "reference_date": "2026-06-01"}
    ]
    assert jump.as_json()["warning_shown"] is True
    assert check_cost(D("150"), previous=(D("100"), when)).warnings == []
    assert [w.code for w in check_cost(D("49"), previous=(D("100"), when)).warnings] == ["jump_from_previous"]
    assert check_cost(D("5"), previous=(D("0"), when)).warnings == []


def test_sanity_json_without_a_list_price() -> None:
    assert check_cost(D("1")).as_json() == {
        "list_price": None,
        "ratio_to_list": None,
        "warning_shown": False,
        "warnings": [],
    }
    far = check_cost(D("1000"), list_price=D("10"))
    assert far.as_json()["warnings"] == [{"code": "far_from_list", "reference": "10", "reference_date": None}]
