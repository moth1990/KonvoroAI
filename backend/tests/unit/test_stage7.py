"""Stage 7's engine (07 §5): lines, cost and price on stage 7's path, derived items and labor, the final colour,
totals, a rerun's carry and the version diff. Pure: no database, every amount exact."""

import time
from datetime import date, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from konboro.contracts.matching import BundleLine, CatalogItemSnapshot, ComponentMatch, MatchingResult, UsedAttribute
from konboro.contracts.merge import AttributeValue, Component, ContextElement, MergeResult, MissingInstance
from konboro.contracts.validation import Issue, PanelSummary, ValidationResult
from konboro.domain.pricing.cost import CostContext, SupplierPrice
from konboro.domain.pricing.margin import Rule
from konboro.pipeline.pricing.book import Book, Item, Product, price
from konboro.pipeline.pricing.derived import DerivedRule, Labor, Requirement, ip_fits, starter_pack
from konboro.pipeline.pricing.diff import LineSnap, diff
from konboro.pipeline.pricing.engine import Carry, PricedQuote, QuoteInput, amounts, price_quote
from konboro.pipeline.pricing.lines import Draft
from konboro.pipeline.pricing.status import finalize

DAY = date(2026, 11, 3)
DRW, PNL, TRC = "drw_1", "pnl_1", "trc_1"
DEFAULT = Rule(id="mr_default", level="default", kind="markup", value=D("0.25"))


def sp(id: str, cost: str, **kw: Any) -> SupplierPrice:
    kw.setdefault("price_date", DAY - timedelta(days=10))
    return SupplierPrice(
        id=id, supplier_id=kw.pop("supplier", "sup_a"), unit_cost=D(cost), currency=kw.pop("currency", "ILS"), **kw
    )


def item(id: str, sku: str, family: str = "circuit_breaker", width: str | None = "3", **attrs: Any) -> Item:
    return Item(
        id=id,
        sku=sku,
        brand="ABB",
        family=family,
        description=f"{family} {sku}",
        attributes=attrs,
        module_width=D(width) if width else None,
    )


def product(id: str, item_id: str | None, sku: str | None, *suppliers: SupplierPrice, **kw: Any) -> Product:
    return Product(
        product_id=id,
        name=kw.pop("name", f"מוצר {id}"),
        family=kw.pop("family", "circuit_breaker"),
        brand="ABB",
        manufacturer_sku=sku,
        catalog_item_id=item_id,
        suppliers=suppliers,
        **kw,
    )


ITEMS = [
    item("ci_s203_16", "S203M-C16", current_a=16, poles=3),
    item("ci_s203_25", "S203M-C25", current_a=25, poles=3),
    item("ci_s203_20", "S203M-C20", current_a=20, poles=3),
    item("ci_main", "XT1C160", width="6", current_a=160, poles=4),
    item(
        "ci_enc_24",
        "MISTRAL-24M",
        "enclosure",
        None,
        modules=24,
        rows=2,
        height_mm=400,
        width_mm=310,
        depth_mm=140,
        ip="IP65",
    ),
    item(
        "ci_enc_54",
        "MISTRAL-54M",
        "enclosure",
        None,
        modules=54,
        rows=3,
        height_mm=550,
        width_mm=460,
        depth_mm=160,
        ip="IP65",
    ),
    item(
        "ci_cab",
        "NSYSM-1200800300",
        "enclosure",
        None,
        modules=192,
        rows=6,
        height_mm=1200,
        width_mm=800,
        depth_mm=300,
        ip="IP55",
    ),
    item("ci_rail", "DIN35-460", "din_rail", None, length_mm=460),
    item("ci_bb", "BB-250A", "busbar", None, current_a=250),
    item("ci_t4", "ZS4", "terminal", None, cross_section_mm2=4),
    item("ci_lbl", "LBL-ENG", "label", None),
]
PRODUCTS = [
    product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "138")),
    product("prd_25", "ci_s203_25", "S203M-C25", sp("psp_25", "150")),
    product("prd_main", "ci_main", "XT1C160", sp("psp_main", "1000")),
    product("prd_enc54", "ci_enc_54", "MISTRAL-54M", sp("psp_enc", "400"), family="enclosure"),
]


def book(**kw: Any) -> Book:
    kw.setdefault("products", PRODUCTS)
    kw.setdefault("rules", [DEFAULT])
    kw.setdefault("items", ITEMS)
    return Book(cost=CostContext(on_date=DAY), **kw)


def comp(id: str, family: str = "circuit_breaker", qty: int = 1, **kw: Any) -> Component:
    attrs = {k: AttributeValue(value=v, source="drawing", confidence=0.95) for k, v in kw.pop("attrs", {}).items()}
    return Component(
        component_id=id,
        drawing_id=DRW,
        panel_id=kw.pop("panel", PNL),
        family=family,
        symbol_class=kw.pop("cls", "mcb"),
        quantity=qty,
        confidence=0.95,
        status="accepted",
        attributes=attrs,
        **kw,
    )


def match(cid: str, sku: str | None, status: str = "matched", conf: float = 0.95, **kw: Any) -> ComponentMatch:
    snap = CatalogItemSnapshot(sku=sku, manufacturer="ABB", description=f'מא"ז {sku}') if sku else None
    return ComponentMatch(
        component_id=cid,
        status=status,
        chosen_sku=sku,
        catalog_item=snap,  # type: ignore[arg-type]
        method=kw.pop("method", "rules_unique"),
        match_confidence=conf,
        confidence=conf,
        **kw,
    )


def quote(comps: list[Component], matches: list[ComponentMatch], **kw: Any) -> PricedQuote:
    merge = MergeResult(
        drawing_id=DRW,
        components=comps,
        missing=kw.pop("missing", []),
        context_elements=kw.pop("context", []),
        trace_id=TRC,
    )
    matching = MatchingResult(drawing_id=DRW, matches=matches, auxiliary=kw.pop("auxiliary", []), trace_id=TRC)
    validation = ValidationResult(
        drawing_id=DRW, issues=kw.pop("issues", []), panel_summaries=kw.pop("summaries", []), trace_id=TRC
    )
    kw.setdefault("book", book())
    kw.setdefault("rules", [])
    return price_quote(
        QuoteInput(
            tenant_id="tnt_1",
            quote_date=DAY,
            panels=kw.pop("panels", [(PNL, "לוח ראשי")]),
            merge=merge,
            matching=matching,
            validation=validation,
            scope="qv_1",
            **kw,
        )
    )


def rule(kind: str, **params: Any) -> DerivedRule:
    return DerivedRule(
        id=f"dr_{kind}",
        key=kind,
        kind=kind,
        explanation_he=kind,
        params=params,
        item={"family": {"terminals": "terminal", "labels": "label"}.get(kind, kind)},
    )


def by_key(q: PricedQuote) -> dict[str, Draft]:
    return {ln.key: ln for ln in q.lines}


# --- 7.1 lines and 7.2–7.3 price -----------------------------------------------------------------------------------


def test_a_matched_line_is_priced_by_the_default_markup_and_traced() -> None:
    q = quote([comp("cmp_1", qty=4)], [match("cmp_1", "S203M-C16")])
    ln = by_key(q)["c:cmp_1"]
    assert (ln.priced.unit_cost, ln.priced.unit_price_raw, ln.priced.unit_price) == (
        D("138"),
        D("172.5000"),
        D("172.50"),
    )
    assert amounts(ln).line_total == D("690.00") and amounts(ln).line_cost == D("552")
    assert ln.priced.cost_source and ln.priced.cost_source["supplier_price_id"] == "psp_16"
    assert ln.priced.margin_rule and ln.priced.margin_rule["rule_id"] == "mr_default"
    assert (ln.status, ln.product_id, ln.catalog_item_id) == ("green", "prd_16", "ci_s203_16")


def test_only_the_identical_product_is_priced() -> None:
    """07 §7.2: NURSERY-1's 3X20A stays without a price beside 3X16A and 3X25A."""
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C20")])
    ln = by_key(q)["c:cmp_1"]
    assert ln.priced.unit_price is None and ln.status == "red"
    assert {"source": "price", "value": "missing", "status": "red", "issues": ["missing_cost"]} in ln.status_reasons
    assert [f.code for f in q.findings] == ["missing_cost"] and q.findings[0].line_keys == ("c:cmp_1",)
    assert ln.issue_ids == [q.findings[0].finding_id("qv_1")]


def test_unmatched_and_ambiguous_lines() -> None:
    q = quote(
        [comp("cmp_1"), comp("cmp_2", attrs={"current_a": 10, "poles": 1})],
        [match("cmp_1", "S203M-C16", "ambiguous"), match("cmp_2", None, "unmatched", method=None)],
    )
    lines = by_key(q)
    assert lines["c:cmp_1"].status == "yellow" and lines["c:cmp_1"].priced.unit_price == D("172.50")
    two = lines["c:cmp_2"]
    assert (two.status, two.priced.unit_price, two.description) == ("red", None, 'מא"ז 1X10A')
    assert "missing_cost" not in two.priced.issues  # no SKU is a match problem, not a price-list one


def test_rounding_to_the_shekel_and_a_fixed_product_price() -> None:
    fixed = product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "138"), sale_mode="fixed", fixed_price=D("185"))
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=book(rounding="shekel", products=[fixed]))
    ln = by_key(q)["c:cmp_1"]
    assert ln.priced.unit_price == D("185.00") and ln.priced.margin_rule["kind"] == "fixed"  # type: ignore[index]
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=book(rounding="ten"))
    assert by_key(q)["c:cmp_1"].priced.unit_price == D("170.00")  # 172.50 → 170


def test_stale_and_discount_based_prices_are_yellow() -> None:
    old = product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "138", price_date=DAY - timedelta(days=200)))
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=book(products=[old]))
    ln = by_key(q)["c:cmp_1"]
    assert (ln.priced.price_status, ln.status) == ("stale", "yellow")
    assert [f.code for f in q.findings] == ["stale_price"]
    listed = product("prd_16", "ci_s203_16", "S203M-C16", list_price=D("200"))
    b = Book(
        cost=CostContext(on_date=DAY, brand_discounts={"ABB": D("0.30")}),
        products=[listed],
        rules=[DEFAULT],
        items=ITEMS,
    )
    ln = by_key(quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=b))["c:cmp_1"]
    assert (ln.priced.unit_cost, ln.priced.price_status, ln.status) == (D("140.0000"), "discount_based", "yellow")


def test_a_customer_rule_beats_a_fixed_price_and_no_rule_is_an_error() -> None:
    fixed = product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "100"), sale_mode="fixed", fixed_price=D("185"))
    customer = Rule(id="mr_cus", level="customer", kind="margin", value=D("0.5"), customer_id="cus_1")
    b = book(products=[fixed], rules=[DEFAULT, customer], customer_id="cus_1")
    assert by_key(quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=b))["c:cmp_1"].priced.unit_price == D(
        "200.00"
    )
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=book(rules=[]))
    assert by_key(q)["c:cmp_1"].priced.unit_price is None and [f.code for f in q.findings] == ["no_margin_rule"]
    assert q.findings[0].severity == "error"


def test_margin_floors_only_tag() -> None:
    b = book(min_line_margin=D("0.25"), min_quote_margin=D("0.25"))
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=b)
    ln = by_key(q)["c:cmp_1"]
    assert ln.priced.unit_price == D("172.50") and ln.status == "green"  # the price and colour don't move
    codes = {f.code: f for f in q.findings}
    assert codes["below_margin_floor"].message == "הרווח בשורה 20% (רצפה: 25%)"
    assert codes["quote_below_margin_floor"].message == "הרווח בהצעה 20% (רצפה: 25%)"


def test_fx_rate_missing_leaves_the_line_without_a_price() -> None:
    usd = product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "40", currency="USD"))
    q = quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], book=book(products=[usd]))
    assert by_key(q)["c:cmp_1"].priced.unit_price is None
    assert [(f.code, f.severity) for f in q.findings] == [("fx_rate_missing", "error")]


def test_kits_accessories_missing_rows_and_supply_scope() -> None:
    kit = BundleLine(
        sku="S203M-C25", manufacturer="ABB", description="מודול פחת", quantity=1, reason="ערכה", has_cost_price=True
    )
    main = product("prd_main", "ci_main", "XT1C160", sp("psp_main", "1000"), includes={"S203M-C25": True})
    comps = [
        comp("cmp_q0", designators=["Q0"]),
        comp("cmp_f1", designators=["F1"]),
        comp("cmp_aux", "aux_contact", parent_designators=["F1"], cls="aux_contact"),
        comp("cmp_out", supply_scope="other_location"),
        comp("cmp_prep", supply_scope="prepare_only", designators=["EMS"]),
    ]
    matches = [
        match("cmp_q0", "XT1C160", bundle_lines=[kit]),
        match("cmp_f1", "S203M-C16"),
        match("cmp_aux", "S203M-C25"),
        match("cmp_out", "S203M-C16"),
        match("cmp_prep", "S203M-C16"),
    ]
    missing = [
        MissingInstance(
            instance_id="ins_9",
            page_id="pg_1",
            panel_id=None,
            bbox=(0, 0, 1, 1),
            family="relay",
            origin="טקסט בלי סימן",
            confidence=0.4,
        )
    ]
    q = quote(
        comps,
        matches,
        missing=missing,
        book=book(products=[main, *PRODUCTS[:2]]),
        summaries=[PanelSummary(panel_id=PNL, hierarchy_available=False, main_device_component_id="cmp_q0")],
    )
    lines = by_key(q)
    part = lines["c:cmp_q0:kit:0"]
    assert part.parent == "c:cmp_q0" and part.included and part.status == "green"  # priced in Q0's
    assert lines["c:cmp_q0"].line_group == "feed" and lines["c:cmp_f1"].line_group == "outputs"
    assert lines["c:cmp_aux"].parent == "c:cmp_f1" and lines["c:cmp_aux"].priced.unit_price == D("187.50")
    assert lines["c:cmp_out"].line_group == "outside"
    assert "c:cmp_prep" not in lines and q.panels[0].notes == ['הכנה בלבד: מא"ז S203M-C16 (EMS)']
    gone = lines["m:ins_9"]  # a missing row with no panel goes to the first one
    assert (gone.line_type, gone.status, gone.panel_id) == ("missing", "red", PNL)


def test_auxiliary_components_get_no_line_of_their_own() -> None:
    q = quote(
        [comp("cmp_1"), comp("cmp_t", "terminal", qty=12, cls="terminal")],
        [match("cmp_1", "S203M-C16")],
        auxiliary=["cmp_t"],
    )
    assert set(by_key(q)) == {"c:cmp_1"}


# --- 7.5 colour -----------------------------------------------------------------------------------------------------


def test_the_worst_source_wins_and_every_reason_is_kept() -> None:
    warn = Issue(
        issue_id="iss_w",
        source="rule",
        rule_id="R",
        rule_version=1,
        category="D",
        severity="warning",
        panel_id=PNL,
        component_ids=["cmp_1"],
        message="m",
    )
    info = warn.model_copy(update={"issue_id": "iss_i", "severity": "info"})
    used = {"residual_ma": UsedAttribute(value=30, source="tenant_default")}
    q = quote(
        [comp("cmp_1")],
        [match("cmp_1", "S203M-C16", conf=0.7, defaulted_attributes=["residual_ma"], attributes_used=used)],
        issues=[warn, info],
    )
    ln = by_key(q)["c:cmp_1"]
    assert ln.status == "yellow"
    sources = [(r["source"], r["status"]) for r in ln.status_reasons]
    assert sources == [
        ("confidence", "yellow"),
        ("match", "green"),
        ("match", "green"),
        ("validator", "yellow"),
        ("validator", "green"),
        ("price", "green"),
    ]
    assert {"code": "defaulted_attribute", "value": "פחת 30mA"} in [r["value"] for r in ln.status_reasons]
    assert ln.issue_ids == ["iss_w", "iss_i"]
    error = warn.model_copy(update={"issue_id": "iss_e", "severity": "error"})
    assert by_key(quote([comp("cmp_1")], [match("cmp_1", "S203M-C16")], issues=[error]))["c:cmp_1"].status == "red"
    low = by_key(quote([comp("cmp_1")], [match("cmp_1", "S203M-C16", conf=0.4)]))["c:cmp_1"]
    assert low.status == "red"


def test_derived_and_manual_lines_are_coloured_by_price() -> None:
    b = book()
    manual = Draft(
        key="u:1",
        panel_id=PNL,
        line_type="manual",
        description="x",
        qty=D(1),
        priced=price(None, b),
        reasons=[{"source": "confidence", "value": 0.1, "status": "red"}],
    )
    finalize(manual)
    assert manual.status == "red" and manual.status_reasons[0] == {
        "source": "user",
        "value": "manual",
        "status": "green",
    }
    enc = Draft(
        key="d:x",
        panel_id=PNL,
        line_type="derived",
        description="ארון",
        qty=D(1),
        priced=price(PRODUCTS[3], b),
        reasons=[{"source": "confidence", "value": 0.1, "status": "red"}],
    )
    finalize(enc)
    assert enc.status == "green"  # a derived line's confidence doesn't count (07 §7.5)


# --- 7.4 derived items and labor ------------------------------------------------------------------------------------


def outputs(n: int) -> tuple[list[Component], list[ComponentMatch]]:
    comps = [comp(f"cmp_{i}", designators=[f"F{i}"]) for i in range(n)]
    return comps, [match(c.component_id, "S203M-C16") for c in comps]


def test_enclosure_by_modules_with_spare() -> None:
    comps, matches = outputs(10)  # 10 × 3 modules = 30, + 20% = 36 → the 54-module board
    q = quote(comps, matches, rules=[rule("enclosure", spare_pct="0.20")])
    enc = by_key(q)[f"d:{PNL}:enclosure"]
    assert (enc.sku, enc.status, enc.priced.unit_price) == ("MISTRAL-54M", "green", D("500.00"))
    assert enc.derived and enc.derived["explanation"].startswith("30 מודולים ברכיבים + 20% רזרבה = 36")
    assert len(enc.derived["from_component_ids"]) == 10


def test_enclosure_from_the_notes_spare_and_by_dimensions() -> None:
    comps, matches = outputs(6)  # 18 modules, + 30% from the notes = 24 (rounded up 23.4) → the 24-module board
    q = quote(comps, matches, rules=[rule("enclosure")], requirements={PNL: Requirement("הערות הלוח", spare_pct=30)})
    enc = by_key(q)[f"d:{PNL}:enclosure"]
    assert enc.sku == "MISTRAL-24M" and "(הערות הלוח)" in (enc.derived or {})["explanation"]
    assert enc.status == "red"  # the board has no price in the factory's list
    dims = Requirement("עמוד הנתונים (עמ׳ 1)", 1200, 800, 300, "IP55")
    q = quote(comps, matches, rules=[rule("enclosure")], requirements={None: dims})  # one panel: the data page counts
    enc = by_key(q)[f"d:{PNL}:enclosure"]
    assert enc.sku == "NSYSM-1200800300"
    assert {"source": "match", "value": "context_page", "status": "green"} in enc.status_reasons
    assert "לפי המודולים נדרשים 18, ובארון 192" in (enc.derived or {})["explanation"]


def test_no_enclosure_fits_is_a_red_row() -> None:
    comps, matches = outputs(10)
    q = quote(comps, matches, rules=[rule("enclosure")], requirements={PNL: Requirement("הערות הלוח", 3000, 800, 300)})
    enc = by_key(q)[f"d:{PNL}:enclosure"]
    assert (enc.description, enc.status) == ("ארון: לא נמצא מתאים ל-3000×800×300", "red")
    assert [f.code for f in q.findings if f.code == "enclosure_not_found"] == ["enclosure_not_found"]
    q = quote(*outputs(30), rules=[rule("enclosure")], book=book(items=[i for i in ITEMS if i.id != "ci_cab"]))
    assert by_key(q)[f"d:{PNL}:enclosure"].description == "ארון: לא נמצא מתאים ל-108 מודולים"


def test_ip_compares_both_digits() -> None:
    assert ip_fits("IP65", "IP55") and ip_fits("IP55", None) and ip_fits("IP55", "sealed")
    assert not ip_fits("IP54", "IP55") and not ip_fits(None, "IP55")


def test_rails_and_busbars_follow_the_enclosure_and_its_includes() -> None:
    comps, matches = outputs(10)
    main = comp("cmp_q0", designators=["Q0"])
    summaries = [PanelSummary(panel_id=PNL, hierarchy_available=False, main_device_component_id="cmp_q0")]
    rules_ = [rule("enclosure"), rule("din_rail"), rule("busbar")]
    q = quote([main, *comps], [match("cmp_q0", "XT1C160"), *matches], rules=rules_, summaries=summaries)
    lines = by_key(q)
    assert lines[f"d:{PNL}:din_rail"].qty == D(3) and lines[f"d:{PNL}:din_rail"].sku == "DIN35-460"
    assert lines[f"d:{PNL}:busbar"].sku == "BB-250A" and lines[f"d:{PNL}:busbar"].qty == D(3)
    context = [ContextElement(det_id="det_1", family="busbar", panel_id=PNL, bbox=(0, 0, 1, 1))]
    q = quote(
        [main, *comps], [match("cmp_q0", "XT1C160"), *matches], rules=rules_, summaries=summaries, context=context
    )
    assert by_key(q)[f"d:{PNL}:busbar"].qty == D(1)  # the busbar stage 3 saw
    q = quote(
        [main, *comps],
        [match("cmp_q0", "XT1C160"), *matches],
        rules=rules_,
        summaries=summaries,
        includes_default={"busbar": True, "din_rail": True},
    )
    lines = by_key(q)
    assert f"d:{PNL}:busbar" not in lines and f"d:{PNL}:din_rail" not in lines
    assert {"source": "match", "value": "enclosure_includes", "status": "green"} in lines[
        f"d:{PNL}:enclosure"
    ].status_reasons


def test_a_rule_that_fails_is_reported_and_the_rest_run() -> None:
    comps, matches = outputs(10)
    no_rails = book(items=[i for i in ITEMS if i.family != "din_rail"])
    q = quote(comps, matches, rules=[rule("enclosure"), rule("din_rail"), rule("labels")], book=no_rails)
    assert [(f.code, f.values["rule_key"]) for f in q.findings if f.code == "derived_rule_failed"] == [
        ("derived_rule_failed", "din_rail")
    ]
    assert f"d:{PNL}:labels" in by_key(q)


def test_terminals_from_the_auxiliary_components_and_labels() -> None:
    comps, matches = outputs(4)
    t4 = comp("cmp_t", "terminal", qty=12, cls="terminal", attrs={"cross_section_mm2": 4})
    t2 = comp("cmp_t2", "terminal", qty=6, cls="terminal")
    q = quote(
        [*comps, t4, t2],
        matches,
        auxiliary=["cmp_t", "cmp_t2"],
        rules=[rule("terminals"), rule("labels", per_output="1", per_panel="1")],
    )
    lines = by_key(q)
    assert lines[f"d:{PNL}:terminals:4"].qty == D(12) and lines[f"d:{PNL}:terminals:4"].sku == "ZS4"
    assert lines[f"d:{PNL}:terminals:4"].derived["from_component_ids"] == ["cmp_t"]  # type: ignore[index]
    assert lines[f"d:{PNL}:terminals:x"].qty == D(6)
    assert lines[f"d:{PNL}:labels"].qty == D(5)  # 4 outputs + the panel's


def test_consumables_labor_and_a_service_row() -> None:
    comps, matches = outputs(2)  # 2 × 138 cost = 276
    labor_rule = Rule(id="mr_labor", level="family", kind="markup", value=D("0.5"), target="labor")
    b = book(rules=[DEFAULT, labor_rule])
    q = quote(
        comps,
        matches,
        book=b,
        rules=[rule("consumables", pct="0.05"), rule("service", contains="חום")],
        labor=Labor(D("150"), {"circuit_breaker": D("0.15")}),
        requirements={PNL: Requirement("הערות הלוח", services=('חישוב חום ע"י יצרן הלוח',))},
    )
    lines = by_key(q)
    cons = lines[f"d:{PNL}:consumables"]
    assert (cons.priced.unit_cost, cons.priced.unit_price) == (D("13.8000"), D("17.25"))  # 5% of 276, the default rule
    labor = lines[f"l:{PNL}"]
    assert (labor.qty, labor.unit, labor.priced.unit_price) == (D("0.300"), "hour", D("225.00"))  # the labor rule
    assert amounts(labor).line_total == D("67.50000")
    heat = lines[f"d:{PNL}:service:0"]
    assert (heat.status, heat.priced.unit_price) == ("yellow", None)
    assert labor.derived and labor.derived["explanation"].startswith("0.3 שעות")


def test_a_consumable_product_gets_no_line() -> None:
    cons = product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_16", "138"), consumable=True)
    q = quote(
        [comp("cmp_1"), comp("cmp_2")],
        [match("cmp_1", "S203M-C16"), match("cmp_2", "S203M-C25")],
        book=book(products=[cons, PRODUCTS[1]]),
    )
    assert set(by_key(q)) == {"c:cmp_2"}


def test_the_starter_pack_has_a_function_for_every_rule() -> None:
    from konboro.pipeline.pricing.derived import KINDS

    version, rules = starter_pack()
    assert version >= 1 and {r["kind"] for r in rules} == set(KINDS)
    assert all(r["approval"] == "pending_expert" for r in rules)  # S22 decision 3
    assert next(r for r in rules if r["key"] == "consumables")["params"]["pct"] == "0"


# --- totals, carry, reproduction, performance -----------------------------------------------------------------------


def test_totals_discount_vat_and_unpriced_lines() -> None:
    q = quote(
        [comp("cmp_1", qty=4), comp("cmp_2")],
        [match("cmp_1", "S203M-C16"), match("cmp_2", "S203M-C20")],
        discount_pct=D("0.03"),
        vat_rate=D("0.18"),
    )
    s = q.totals
    assert (s.sums.price_total, s.discount, s.net_total) == (D("690.00"), D("20.70"), D("669.30"))
    assert (s.vat, s.gross_total) == (D("120.47"), D("789.77"))
    assert s.sums.unpriced_count == 1 and s.sums.line_counts == {"green": 1, "yellow": 0, "red": 1}
    assert s.margin_abs == D("117.30") and s.margin_pct == D("0.1753")


def test_a_rerun_keeps_what_the_user_did() -> None:
    comps, matches = outputs(10)
    rules_ = [rule("enclosure"), rule("labels")]
    manual = Draft(
        key="u:ln_9", panel_id=PNL, line_type="manual", description="כבל", qty=D(2), priced=price(PRODUCTS[0], book())
    )
    carry = Carry(
        deleted=frozenset({f"d:{PNL}:labels", "c:cmp_3"}),
        overrides={"c:cmp_0": {"unit_price": "150.00", "scope": "quote"}},
        manual=[manual],
    )
    q = quote(comps, matches, rules=rules_, carry=carry, book=book(min_line_margin=D("0.5")))
    lines = by_key(q)
    assert f"d:{PNL}:labels" not in lines and "c:cmp_3" not in lines and f"d:{PNL}:enclosure" in lines
    over = lines["c:cmp_0"]
    assert over.priced.unit_price == D("150.00") and over.override and over.priced.margin_rule["kind"] == "override"  # type: ignore[index]
    assert "below_margin_floor" not in over.priced.issues
    assert lines["u:ln_9"].status == "green" and lines["u:ln_9"].line_type == "manual"


def test_the_same_input_gives_the_same_quote_to_the_agora() -> None:
    comps, matches = outputs(20)
    rules_ = [rule(k) for k in ("enclosure", "din_rail", "busbar", "labels")]
    a, b = (quote(comps, matches, rules=rules_, vat_rate=D("0.18")) for _ in range(2))
    assert [(ln.key, ln.priced, ln.status, ln.status_reasons) for ln in a.lines] == [
        (ln.key, ln.priced, ln.status, ln.status_reasons) for ln in b.lines
    ]
    assert a.totals == b.totals and [f.finding_id("qv") for f in a.findings] == [f.finding_id("qv") for f in b.findings]


def test_150_lines_price_in_under_a_second() -> None:
    """07 §9: 150 lines ≤ 1 s."""
    comps, matches = outputs(150)
    rules_ = [rule(k) for k in ("enclosure", "din_rail", "busbar", "terminals", "labels", "consumables")]
    start = time.perf_counter()
    q = quote(comps, matches, rules=rules_, labor=Labor(D("150"), {"circuit_breaker": D("0.15")}))
    assert time.perf_counter() - start < 1.0 and len(q.lines) >= 150


# --- diff (07 §7.7) -------------------------------------------------------------------------------------------------


def snap(key: str, qty: str, price: str | None, **kw: Any) -> LineSnap:
    total = D(price) * D(qty) if price else None
    return LineSnap(
        key=key,
        panel_id=PNL,
        description=key,
        sku=kw.get("sku", "S"),
        qty=D(qty),
        unit_price=D(price) if price else None,
        line_total=total,
        unit_cost=kw.get("cost"),
        cost_ref=kw.get("cost_ref"),
        rule_ref=kw.get("rule_ref"),
    )


def test_the_diff_between_two_versions() -> None:
    before = [snap("a", "2", "100", cost_ref="psp_1"), snap("b", "1", "50"), snap("c", "1", "10")]
    after = [snap("a", "2", "110", cost_ref="psp_2"), snap("b", "3", "50"), snap("d", "1", "5")]
    out = diff(before, after, 1, D("260"), D("375"))
    by = {x["key"]: x for x in out["lines"]}
    assert by["a"]["change"] == "changed" and by["a"]["why"] == ["cost"] and by["a"]["delta"] == "20"
    assert by["b"]["why"] == ["qty"] and by["b"]["delta"] == "100"
    assert (
        by["c"]["change"] == "removed"
        and by["d"]["change"] == "added"
        and "c" not in {k for k in by if by[k]["change"] == "added"}
    )
    assert (out["from_version"], out["delta"]) == (1, "115")
    assert diff(before, before, 1, D(1), D(1))["lines"] == []


@pytest.mark.parametrize("rule_ref", ["mr_1", "fixed"])
def test_a_rule_change_is_named(rule_ref: str) -> None:
    out = diff([snap("a", "1", "100", rule_ref="mr_0")], [snap("a", "1", "120", rule_ref=rule_ref)], 1, D(0), D(0))
    assert out["lines"][0]["why"] == ["margin_rule"]
