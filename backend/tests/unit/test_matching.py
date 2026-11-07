"""Stage 5 (05): catalog matching in code, on the sample catalog (S20 decision 1), with no database and no model.

Each test builds stage 4's components by hand and runs the flow of `pipeline/matching/match.py`. The agent is a
function that records what it was shown.
"""

import json
from typing import Any

import pytest

from konboro.contracts.common import StageIssue
from konboro.contracts.intake import ContextArtifact
from konboro.contracts.matching import ComponentMatch
from konboro.contracts.merge import AttributeValue, Cable, CircuitContext, Component, Instance
from konboro.db.catalog import (
    COMMON,
    COMMON_ACCESSORIES,
    SAMPLE,
    SAMPLE_ACCESSORIES,
    SAMPLE_KITS,
    parse,
    parse_accessories,
    parse_kits,
)
from konboro.pipeline.association import schemas
from konboro.pipeline.matching import notes as notes_mod
from konboro.pipeline.matching import query as q
from konboro.pipeline.matching.catalog import Catalog, Item, Kit, norm_sku, norm_token
from konboro.pipeline.matching.config import DEFAULT
from konboro.pipeline.matching.factory import Factory, Memory
from konboro.pipeline.matching.match import Inputs, corrected_poles, fitting, match_all, signature
from konboro.pipeline.matching.notes import NoteRule, Notes
from konboro_llm.stages.catalog_disambiguation import CatalogAnswer


def _sample() -> Catalog:
    rows = parse(SAMPLE.read_text(encoding="utf-8"))
    ids = {(r.brand, r.sku): f"cat_{n:03d}" for n, r in enumerate(rows)}
    items = {
        ids[(r.brand, r.sku)]: Item(
            id=ids[(r.brand, r.sku)],
            sku=r.sku,
            brand=r.brand,
            series=r.series,
            model_code=r.model_code,
            model_tokens=r.model_tokens,
            family=r.family,
            symbol_class=r.symbol_class,
            attributes=dict(r.attributes),
            status=r.status,
            replaced_by=ids[(r.brand, r.replaced_by_sku)] if r.replaced_by_sku else None,
        )
        for r in rows
    }
    kits: dict[str, list[Kit]] = {}
    for k in parse_kits(SAMPLE_KITS.read_text(encoding="utf-8")):
        kits.setdefault(ids[(k.brand, k.item_sku)], []).append(
            Kit(items[ids[(k.brand, k.part_sku)]], k.quantity, k.when_text, k.reason_he)
        )
    fits: dict[str, set[tuple[str, str]]] = {}
    for a in parse_accessories(SAMPLE_ACCESSORIES.read_text(encoding="utf-8")):
        fits.setdefault(ids[(a.brand, a.accessory_sku)], set()).add((a.fits_brand, a.fits_series))
    return Catalog(items, kits, fits)


CATALOG = _sample()
SKU = {i.sku: i for i in CATALOG.items.values()}


def factory(**kw: Any) -> Factory:
    base: dict[str, Any] = {
        "brand_preferences": {"*": "ABB"},
        "alternate_brands": {"*": ["Schneider"]},
        "attribute_defaults": {"circuit_breaker": {"curve": "C", "breaking_capacity_ka": 6}},
        "priced": frozenset(CATALOG.items),
    }
    return Factory(**(base | kw))


def comp(
    family: str,
    cls: str,
    attrs: dict[str, Any] | None = None,
    texts: tuple[str, ...] = (),
    *,
    cid: str = "cmp_0001",
    designators: tuple[str, ...] = ("F1",),
    brand: str | None = None,
    panel: str = "pnl_1",
    parents: tuple[str, ...] = (),
    circuit: CircuitContext | None = None,
    source: str = "drawing",
    confidence: float = 0.95,
) -> Component:
    names = schemas.default().names(family)
    values = {n: AttributeValue(value=None, source=None, confidence=None) for n in names}
    for k, v in (attrs or {}).items():
        values[k] = AttributeValue(value=v, source=source, confidence=0.95)  # type: ignore[arg-type]
    return Component(
        component_id=cid,
        drawing_id="drw_01J",
        panel_id=panel,
        family=family,
        symbol_class=cls,
        attributes=values,
        explicit_texts=list(texts),
        brand_hint=brand,
        quantity=1,
        designators=list(designators),
        parent_designators=list(parents),
        circuit_context=circuit,
        confidence=confidence,
        status="accepted",
    )


class Agent:
    def __init__(self, *answers: CatalogAnswer) -> None:
        self.answers = list(answers)
        self.shown: list[tuple[str, str, str, str | None]] = []

    def __call__(self, who: str, what: str, where: str, error: str | None) -> CatalogAnswer:
        self.shown.append((who, what, where, error))
        return self.answers.pop(0)


def run(
    *components: Component,
    fac: Factory | None = None,
    notes: Notes | None = None,
    ask: Any = None,
    corrected: frozenset[str] = frozenset(),
) -> list[ComponentMatch]:
    inp = Inputs(
        catalog=CATALOG,
        factory=fac or factory(),
        schemas=schemas.default(),
        notes=notes or Notes(),
        components={c.component_id: c for c in components},
        ask=ask,
        corrected=corrected,
    )
    return match_all(list(components), inp).matches


def one(*components: Component, **kw: Any) -> ComponentMatch:
    return run(*components, **kw)[0]


MCB_3X16 = {"current_a": 16, "poles": 3}


# --- 5.1 normalize and sign ---------------------------------------------------------------------------------------


def test_the_signature_has_the_shape_of_05_6_1() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16), fac=factory(brand_preferences={}))
    assert m.signature == "circuit_breaker|mcb|current_a=16|poles=3|curve=C|bc_ka>=6"


def test_the_signature_does_not_depend_on_the_order_read() -> None:
    a = comp("circuit_breaker", "mcb", {"poles": 3, "current_a": 16})
    b = comp("circuit_breaker", "mcb", {"current_a": 16, "poles": 3})
    attrs = {x.name: x for x in schemas.default().attributes("circuit_breaker")}
    needs_a = {n: q.Need(n, v.value, "exact", "drawing", True) for n, v in a.attributes.items() if v.value is not None}
    needs_b = {n: q.Need(n, v.value, "exact", "drawing", True) for n, v in b.attributes.items() if v.value is not None}
    assert signature(a, "mcb", needs_a, attrs) == signature(b, "mcb", needs_b, attrs)


def test_skus_and_tokens_normalize() -> None:
    assert norm_sku("s203m - c16") == norm_sku("S203M.C16") == "S203MC16"
    assert norm_token("ABB-XT1C", frozenset({"ABB"})) == "XT1C"
    assert norm_token("s 203m") == "S203M"


def test_the_class_narrows_the_family() -> None:
    """5.1 item 2: an MCB never comes back as a moulded-case breaker of the same current."""
    m = one(comp("circuit_breaker", "mccb", {"current_a": 80, "poles": 3}))
    assert m.chosen_sku == "XT1C160 TMD80 3P"
    # an MCB written as such stays one (an 80A one not in the catalog matches nothing); one only drawn is typed by
    # its current above the catalog's MCB range (BUG-070, `test_a_breaker_above_the_catalogs_mcb_range_…`)
    assert one(comp("circuit_breaker", "mcb", {"current_a": 80, "poles": 3}, ("MCB",))).status == "unmatched"


# --- 5.2 explicit sku -------------------------------------------------------------------------------------------------


def test_an_explicit_sku_matching_the_drawing() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, ("A9F74316",)))
    assert (m.status, m.method, m.chosen_sku, m.match_confidence) == ("matched", "explicit_sku", "A9F74316", 0.99)
    # 05 §5.2 item 5: the factory's own brand is offered first
    assert m.alternatives[0].manufacturer == "ABB" and m.alternatives[0].sku == "S203M-C16"


@pytest.mark.parametrize("written", ["A9F 74316", "a9f-74316", "A9F.74316"])
def test_an_explicit_sku_however_it_is_spelled(written: str) -> None:
    assert one(comp("circuit_breaker", "mcb", MCB_3X16, (written,))).chosen_sku == "A9F74316"


def test_an_explicit_sku_that_contradicts_the_drawing_is_a_conflict() -> None:
    """05 §5.2 item 3: the SKU says 16A, the drawing 20A; nothing is chosen."""
    m = one(comp("circuit_breaker", "mcb", {"current_a": 20, "poles": 3}, ("A9F74316",)))
    assert (m.status, m.chosen_sku, m.warnings) == ("conflict", None, ["attribute_conflict"])
    assert "20A" in m.reason and "16A" in m.reason
    assert m.missing_attributes == ["current_a"]


def test_a_discontinued_sku_takes_its_replacement() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, ("24343",)))
    assert m.chosen_sku == "A9F74316" and "discontinued_replaced" in m.warnings


# --- 5.2.1 explicit series --------------------------------------------------------------------------------------------


def test_a_series_narrows_and_fixes_what_it_fixes() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, ("S203M", "3×16A")))
    assert (m.method, m.chosen_sku, m.match_confidence) == ("explicit_series", "S203M-C16", 0.97)
    # every S203M is 10kA: the series' value, not the factory's 6kA default
    assert m.attributes_used["breaking_capacity_ka"].source == "series"
    assert m.attributes_used["curve"].source == "tenant_default"


def test_a_series_gives_the_poles_the_text_leaves_out() -> None:
    m = one(comp("circuit_breaker", "mcb", {"current_a": 16}, ("S203M",)))
    assert m.chosen_sku == "S203M-C16" and m.attributes_used["poles"].source == "series"


def test_a_model_written_with_its_brand_finds_the_catalogs_token() -> None:
    """BUG-110: 25/886's meter says "SATEC-135". The catalog keeps the brand in the token (PM135EH: SATEC135), so the
    model is looked up with its brand too, not only without it ("135"). The factory has no SATEC price, as the demo
    factory: without the text the preferred brand finds no meter; with it, the drawing names the brand and the model."""
    no_satec = frozenset(i for i, item in CATALOG.items.items() if item.brand != "SATEC")
    fac = factory(priced=no_satec)
    bare = one(comp("energy_meter", "energy_meter", {}, (), designators=("PM",)), fac=fac)
    assert (bare.status, bare.chosen_sku) == ("unmatched", None)
    for written in ("SATEC-135", "SATEC 135"):
        m = one(comp("energy_meter", "energy_meter", {}, (written,), designators=("PM",), brand="SATEC"), fac=fac)
        assert (m.status, m.method, m.chosen_sku) == ("matched", "explicit_series", "PM135EH"), written
        assert "catalog_gap" not in m.warnings


def test_fnv_the_series_contradicts_the_text() -> None:
    """05 §5.2.1 item 4, NEVIS-1: "3X6A" beside S204M, a 4-pole model. Nothing is chosen; both readings offered."""
    m = one(comp("circuit_breaker", "mcb", {"current_a": 6, "poles": 3}, ("S204M", "3×6A"), designators=("FNV",)))
    assert (m.status, m.chosen_sku) == ("conflict", None)
    assert "S204M" in m.reason and "3P" in m.reason and "4P" in m.reason
    assert {a.sku for a in m.alternatives} >= {"S203M-C6", "S204M-C6"}


def test_fnv_the_memory_settles_it() -> None:
    """05 §5.3's example: NEVIS-1's quote chose 3P; NURSERY-1's FNV gets it from the memory."""
    fnv = comp("circuit_breaker", "mcb", {"current_a": 6, "poles": 3}, ("S204M", "3×6A"), designators=("FNV",))
    sig = one(fnv).signature
    assert sig is not None
    m = one(fnv, fac=factory(memory=[Memory(None, sig, None, "S203M-C6")]))
    assert (m.status, m.method, m.chosen_sku) == ("matched", "memory", "S203M-C6")
    assert "זיכרון" in m.reason


def test_an_unknown_model_code_goes_to_the_catalog_gap() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, ("S803S",)))
    assert "catalog_gap" in m.warnings and m.status == "matched"


# --- 5.3 memory -------------------------------------------------------------------------------------------------------


def test_memory_the_customer_before_the_factory() -> None:
    c = comp("circuit_breaker", "mcb", MCB_3X16)
    sig = one(c).signature or ""
    fac = factory(
        customer_id="cus_1",
        memory=[Memory(None, sig, None, "A9F74316"), Memory("cus_1", sig, None, "A9F84316")],
    )
    assert one(c, fac=fac).chosen_sku == "A9F84316"
    assert one(c, fac=factory(customer_id="cus_2", memory=fac.memory)).chosen_sku == "A9F74316"


def test_memory_never_changes_an_electrical_value() -> None:
    c = comp("circuit_breaker", "mcb", MCB_3X16)
    sig = one(c).signature or ""
    m = one(c, fac=factory(memory=[Memory(None, sig, None, "S203M-C20")]))
    assert m.chosen_sku == "S203M-C16" and m.method != "memory"


def test_memory_never_over_a_brand_the_drawing_names() -> None:
    c = comp("circuit_breaker", "mcb", MCB_3X16, brand="ABB")
    sig = one(c).signature or ""
    m = one(c, fac=factory(memory=[Memory(None, sig, "ABB", "A9F74316")]))
    assert m.chosen_sku == "S203M-C16"


def test_the_memory_context_is_the_customers_brand_or_none() -> None:
    """S25b decision 6: a memory written for this match ("לזכור", 08 §7.4) belongs to the customer's brand when the
    customer's preference chose it, else to none: a brand the drawing names wins over memory anyway."""
    c = comp("circuit_breaker", "mcb", MCB_3X16)
    assert one(c, fac=factory(customer_brands={"circuit_breaker": "Schneider"})).brand_context == "Schneider"
    assert one(comp("circuit_breaker", "mcb", MCB_3X16, brand="ABB")).brand_context is None
    assert one(c, fac=factory()).brand_context is None  # the factory's own preference (ABB)
    # and a memory under that context is recalled for the next drawing in the same situation
    sig = one(c).signature or ""
    fac = factory(customer_brands={"circuit_breaker": "Schneider"}, memory=[Memory(None, sig, "Schneider", "A9F84316")])
    assert one(c, fac=fac).method == "memory"


# --- 5.4 brand --------------------------------------------------------------------------------------------------------


def test_brand_written_beside_the_component() -> None:
    assert one(comp("circuit_breaker", "mcb", MCB_3X16, brand="Schneider")).chosen_sku == "A9F74316"


def test_brand_from_the_notes_the_panel_before_the_drawing() -> None:
    notes = Notes(
        [
            NoteRule("circuit_breaker", "ABB", False, {}, "drawing", None),
            NoteRule("circuit_breaker", "Schneider", False, {}, "panel", "pnl_1"),
        ]
    )
    assert one(comp("circuit_breaker", "mcb", MCB_3X16), notes=notes).chosen_sku == "A9F74316"
    assert one(comp("circuit_breaker", "mcb", MCB_3X16, panel="pnl_2"), notes=notes).chosen_sku == "S203M-C16"


def test_or_equivalent_lets_the_factorys_brand_stand_in_marked() -> None:
    notes = notes_mod.read(
        [
            ContextArtifact(
                artifact_id="ctx_1",
                page_id=None,
                kind="general_notes",
                format="markdown",
                content='- כל המא"זים תוצרת שניידר או ש"ע',
            )
        ]
    )
    m = one(comp("circuit_breaker", "mcb", MCB_3X16), notes=notes)
    assert m.chosen_sku == "S203M-C16" and "substitution" in m.warnings
    assert m.substitution is not None and m.substitution.requested_brand == "Schneider"


def test_the_customers_brand_before_the_factorys() -> None:
    fac = factory(customer_brands={"circuit_breaker": "Schneider"})
    assert one(comp("circuit_breaker", "mcb", MCB_3X16), fac=fac).chosen_sku == "A9F74316"


def test_no_preference_any_brand_with_a_price() -> None:
    only_schneider = frozenset(i.id for i in CATALOG.items.values() if i.brand == "Schneider")
    m = one(comp("circuit_breaker", "mcb", MCB_3X16), fac=factory(brand_preferences={}, priced=only_schneider))
    assert m.chosen_sku == "A9F74316" and m.substitution is None


# --- 5.5 fill-in ------------------------------------------------------------------------------------------------------


def test_defaults_are_marked_and_cost_confidence() -> None:
    m = one(comp("circuit_breaker", "mcb", {"current_a": 16, "poles": 1}))
    assert m.chosen_sku == "S201M-C16"  # 1P, not the 1P+N SN201M: a neutral nobody asked for
    assert m.defaulted_attributes == ["curve", "breaking_capacity_ka"] and "defaulted_attribute" in m.warnings
    assert m.confidence == pytest.approx(0.95 * 0.9 * 0.9 * 0.9, abs=1e-4)


def test_the_notes_before_the_factorys_default() -> None:
    notes = Notes([NoteRule("circuit_breaker", None, False, {"breaking_capacity_ka": 10}, "10kA", None)])
    m = one(comp("circuit_breaker", "mcb", MCB_3X16), notes=notes, fac=factory(brand_preferences={"*": "Schneider"}))
    assert m.chosen_sku == "A9F84316"  # iC60H, 10kA; iC60N is 6kA
    assert m.attributes_used["breaking_capacity_ka"].source == "notes"


def test_a_system_default_costs_nothing() -> None:
    """05 §5.5: 30 mA is the system default; shown, not penalized."""
    m = one(comp("rcd", "rcd", {"current_a": 40, "poles": 4, "rcd_type": "A"}))
    assert m.chosen_sku == "F204A-40/0.03"
    assert m.attributes_used["residual_ma"].source == "system_default"
    assert m.method == "rules_unique" and m.confidence == pytest.approx(0.95 * 0.95, abs=1e-4)


@pytest.mark.parametrize("written", ['0.3mA-TYPE"A"', "0,3mA"])
def test_a_residual_written_in_amps_with_ma_is_inferred_not_defaulted(written: str) -> None:
    """BUG-052, MINHAROT-1's FB0: no RCD has 0.3 mA. It is 0.3 A, inferred (yellow), and the 30 mA default, the
    factory's or the system's, does not cover it."""
    fb0 = comp("rcd", "rcd", {"current_a": 40, "poles": 4, "rcd_type": "A"}, ("FB0", "4×40A", written))
    for fac in (factory(), factory(attribute_defaults={"rcd": {"residual_ma": 30}})):
        m = one(fb0, fac=fac)
        used = m.attributes_used["residual_ma"]
        assert m.chosen_sku == "F204A-40/0.3" and used.value == 300 and used.source == "inferred"
        assert used.note is not None and "0.3A" in used.note and "300mA" in used.note
        assert "residual_ma" not in m.defaulted_attributes
        assert "inferred_attribute" in m.warnings and m.confidence <= DEFAULT.yellow_max


def test_a_residual_read_from_the_drawing_is_left_alone() -> None:
    """The slip rule only stands in for a fill-in: a sensitivity the drawing gives is never replaced."""
    m = one(comp("rcd", "rcd", {"current_a": 40, "poles": 4, "rcd_type": "A", "residual_ma": 30}, ("0.3mA",)))
    assert m.chosen_sku == "F204A-40/0.03" and m.attributes_used["residual_ma"].source == "drawing"


# BUG-107, 25/886's FB devices: one symbol, "4×40A", '30mA-TYPE"A"', no curve and no SKU anywhere on the drawing
FB_4X40 = {"current_a": 40, "poles": 4, "rcd_type": "A"}


def test_an_rcbo_with_no_curve_and_no_rcbo_in_the_catalog_gets_the_rcds_ambiguous() -> None:
    """05 §5.6: it may be a residual-current device with no overcurrent protection. The RCDs with its values are
    offered, `ambiguous`, yellow at most; the component stays an `rcbo` and the reviewer confirms."""
    m = one(comp("rcbo", "rcbo", FB_4X40, ("FB20", "4×40A", '30mA-TYPE"A"'), designators=("FB20",)))
    assert m.status == "ambiguous" and m.chosen_sku == "F204A-40/0.03"
    assert m.confidence <= DEFAULT.yellow_max
    assert "family_relaxed" in m.warnings and "family_relaxed" in m.relaxations
    assert m.missing_attributes == ["curve"]
    assert "מפסק פחת" in m.reason and "עקומה" in m.reason
    assert m.attributes_used["current_a"].value == 40 and m.attributes_used["poles"].value == 4
    assert {a.sku for a in m.alternatives} <= {i.sku for i in CATALOG.items.values() if i.family == "rcd"}


def test_an_rcbo_with_a_curve_written_never_gets_an_rcd() -> None:
    m = one(comp("rcbo", "rcbo", FB_4X40 | {"curve": "C"}, ("4×C40A", '30mA-TYPE"A"')))
    assert m.status == "unmatched" and m.chosen_sku is None and "family_relaxed" not in m.warnings


def test_an_rcbo_with_a_breaking_capacity_written_never_gets_an_rcd() -> None:
    m = one(comp("rcbo", "rcbo", FB_4X40 | {"breaking_capacity_ka": 6}, ("4×40A", "6kA")))
    assert m.status == "unmatched" and m.chosen_sku is None


def test_an_rcbo_the_catalog_has_is_matched_as_an_rcbo_with_no_curve_written() -> None:
    m = one(comp("rcbo", "rcbo", {"current_a": 16, "poles": 1, "neutral": True, "rcd_type": "A"}))
    assert m.status == "matched" and m.chosen_sku == "DS201-C16-A30" and "family_relaxed" not in m.warnings


def test_the_rcds_keep_every_exact_value() -> None:
    """No RCD of 4P 32A: nothing relaxes the current, and nothing is offered."""
    m = one(comp("rcbo", "rcbo", {"current_a": 32, "poles": 4, "rcd_type": "A"}))
    assert m.status == "unmatched" and m.chosen_sku is None


def test_an_rcd_the_reviewer_chose_for_such_an_rcbo_comes_back_from_the_memory() -> None:
    fb = comp("rcbo", "rcbo", FB_4X40)
    sig = one(fb).signature
    assert sig is not None
    m = one(fb, fac=factory(memory=[Memory(None, sig, None, "F204A-40/0.03")]))
    assert (m.status, m.method, m.chosen_sku) == ("matched", "memory", "F204A-40/0.03")
    curved = comp("rcbo", "rcbo", FB_4X40 | {"curve": "C"})
    sig_c = one(curved).signature
    assert sig_c is not None
    m = one(curved, fac=factory(memory=[Memory(None, sig_c, None, "F204A-40/0.03")]))
    assert m.chosen_sku is None  # a curve is written: an RCD never stands for it, remembered or not


def test_the_residual_slip_rule_can_be_turned_off() -> None:
    fac = factory(inference_off=frozenset({"residual_written_in_amps_as_ma"}))
    m = one(comp("rcd", "rcd", {"current_a": 40, "poles": 4, "rcd_type": "A"}, ("0.3mA",)), fac=fac)
    assert m.attributes_used["residual_ma"].source == "system_default"


@pytest.mark.parametrize("family", sorted(schemas.SCHEMAS))
def test_current_and_poles_never_take_a_default(family: str) -> None:
    """05 §4.4, non-negotiable 4: even a tenant default for them is ignored."""
    fac = factory(attribute_defaults={family: {"current_a": 16, "poles": 3}}, auxiliary_families=frozenset())
    m = one(comp(family, family), fac=fac)
    for name in ("current_a", "poles"):
        used = m.attributes_used.get(name)
        assert used is None or used.source not in ("notes", "tenant_default", "system_default")


def test_a_missing_current_is_red_with_a_reason() -> None:
    m = one(comp("circuit_breaker", "mcb", {"poles": 3}))
    assert (m.status, m.chosen_sku, m.warnings) == ("unmatched", None, ["missing_required_attribute"])
    assert m.missing_attributes == ["current_a"] and "זרם" in m.reason


# --- 5.5.1 inference --------------------------------------------------------------------------------------------------


def _with_upstream(family: str, cls: str, attrs: dict[str, Any]) -> tuple[Component, Component]:
    f1 = comp("circuit_breaker", "mcb", MCB_3X16, ("S203M",), cid="cmp_0001", designators=("F1",))
    ctx = CircuitContext(upstream_designator="F1", upstream_component_id="cmp_0001")
    return f1, comp(family, cls, attrs, cid="cmp_0002", designators=("C1",), circuit=ctx)


def test_a_contactor_takes_its_current_from_the_breaker_above() -> None:
    f1, c1 = _with_upstream("contactor", "C", {"poles": 3})
    m = run(f1, c1, fac=factory(attribute_defaults={"contactor": {"coil_voltage_v": 230}}))[1]
    assert m.chosen_sku == "AF18-30-10-13"  # the smallest of 16A or more
    used = m.attributes_used["current_a"]
    assert used.source == "inferred" and used.note is not None and "F1" in used.note and "16A" in used.note
    assert "inferred_attribute" in m.warnings and m.confidence <= DEFAULT.yellow_max


def test_no_protective_device_known_no_inference() -> None:
    m = one(comp("contactor", "C", {"poles": 3}))
    assert m.status == "unmatched" and m.missing_attributes == ["current_a"]


def test_coils_take_the_technical_datas_control_voltage() -> None:
    notes = notes_mod.read(
        [
            ContextArtifact(
                artifact_id="ctx_1",
                page_id=None,
                kind="technical_data",
                format="json",
                content=json.dumps({"control_voltage": "230V-AC"}),
            )
        ]
    )
    m = one(comp("relay", "relay", {}), notes=notes)
    assert m.chosen_sku == "CR-P230AC2" and m.attributes_used["coil_voltage_v"].source == "inferred"


def test_two_candidates_told_apart_only_by_a_missing_value_ask_no_model() -> None:
    agent = Agent()
    m = one(comp("relay", "relay", {}), ask=agent)
    assert m.status == "ambiguous" and m.missing_attributes == ["coil_voltage_v"]
    assert agent.shown == [] and m.confidence <= DEFAULT.yellow_max


def test_an_untyped_breaker_is_typed_by_its_current() -> None:
    m = one(comp("circuit_breaker", "unknown_symbol", {"current_a": 125, "poles": 4}))
    assert m.chosen_sku == "XT1C160 TMD125 4P" and "breaker_type_inferred" in m.warnings
    assert m.confidence <= DEFAULT.yellow_max
    m = one(comp("circuit_breaker", "unknown_symbol", {"current_a": 40, "poles": 3}))
    assert m.chosen_sku == "S203M-C40"


def test_a_breaker_above_the_catalogs_mcb_range_is_not_an_mcb() -> None:
    """BUG-070: 25.26.100's Q0 "3×80A" came out an MCB and matched nothing ("מא"ז 3X80A"). The catalog's MCBs stop
    at 63A, so an 80A breaker is typed by its current, whether stage 4 left it untyped or called it an MCB."""
    for cls in ("mcb", "unknown_symbol"):
        m = one(comp("circuit_breaker", cls, {"current_a": 80, "poles": 3}))
        assert m.chosen_sku is not None and "breaker_type_inferred" in m.warnings
        assert m.chosen_sku.startswith("XT1")  # the moulded-case one
    m = one(comp("circuit_breaker", "mcb", {"current_a": 63, "poles": 3}))
    assert m.chosen_sku == "S203M-C63" and "breaker_type_inferred" not in m.warnings


def test_an_mccb_within_the_catalogs_mcb_range_is_typed_by_its_current() -> None:
    """BUG-077, BUG-078: 25.26.100's five 40A field breakers and two 10A ones came out MCCBs, from one sure reading
    spread to its peers and a disambiguation that never offered `mcb`. The user: no 40A MCCB exists there. A breaker
    read as an MCCB within the catalog's MCB range is typed again by its current (the converse of BUG-070)."""
    m = one(comp("circuit_breaker", "mccb", {"current_a": 40, "poles": 3}, designators=()))
    assert m.chosen_sku == "S203M-C40" and "breaker_type_inferred" in m.warnings
    assert m.confidence <= DEFAULT.yellow_max
    assert one(comp("circuit_breaker", "mccb", {"current_a": 10, "poles": 1}, designators=())).chosen_sku == "S201M-C10"

    # an MCCB it stays: written beside it (in Hebrew too, two words: 6199-2-50's 25A and 63A ones), by a prefix that
    # names one (Q), by its series, by the factory's own prefixes, or above the MCB range
    def forty(texts: tuple[str, ...] = (), designators: tuple[str, ...] = (), fac: Factory | None = None) -> str | None:
        c = comp("circuit_breaker", "mccb", {"current_a": 40, "poles": 3}, texts, designators=designators)
        return one(c, fac=fac).chosen_sku

    moulded = "XT1C160 TMD40 3P"
    assert forty(("MCCB",)) == forty(("בתיבה", "יצוקה")) == forty(designators=("Q2",)) == forty(("XT1",)) == moulded
    assert forty(designators=("F2",), fac=factory(designator_prefixes={"F": ("mcb", "mccb")})) == moulded
    m = one(comp("circuit_breaker", "mccb", {"current_a": 80, "poles": 3}, designators=()))
    assert m.chosen_sku == "XT1C160 TMD80 3P" and "breaker_type_inferred" not in m.warnings


def test_an_unsure_pole_mark_the_cable_contradicts_is_a_conflict() -> None:
    """BUG-079: 25.26.100's 25A feeder (5X6 cable) came out 1P from a pole mark read at 0.5, and matched S201M 1P
    25A. An unsure graphic reading the cable contradicts is the reviewer's to settle: nothing is chosen, both offered
    (05 §5.5.1, the user's answer). A sure one still stands, yellow (`test_poles_from_the_cable_only_…`)."""
    c = comp("circuit_breaker", "mcb", {"current_a": 25}, circuit=CircuitContext(cable=Cable(cores=5)))
    c.attributes["poles"] = AttributeValue(value=1, source="graphic", confidence=0.5)
    m = one(c)
    assert (m.status, m.chosen_sku) == ("conflict", None)
    assert "poles_cable_conflict" in m.warnings and m.missing_attributes == ["poles"]
    assert [a.sku for a in m.alternatives] == ["S201M-C25", "S203M-C25"]
    assert "1P" in m.reason and "3P" in m.reason
    # nothing filled in: the reading stays what was read
    assert m.attributes_used["poles"].value == 1 and m.attributes_used["poles"].source == "graphic"


def test_poles_corrected_by_the_cable_and_the_row_are_inferred() -> None:
    """S24b decision 12: stage 4 joined two breakers read 3P (graphic 0.6) on 3×1.5 to the thirteen beside them read
    1P, because their cable and the row's majority agree (`poles_corrected` on their instances). The component's poles
    are `inferred`, the note names both, and the line is yellow."""
    cable = CircuitContext(cable=Cable(cores=3, cross_section_mm2=1.5, raw="3×1.5"))
    c = comp("circuit_breaker", "mcb", {"current_a": 10}, circuit=cable)
    c.attributes["poles"] = AttributeValue(value=1, source="graphic", confidence=0.5)
    plain = one(c)
    assert plain.attributes_used["poles"].source == "graphic"
    m = one(c, corrected=frozenset({c.component_id}))
    assert (m.status, m.chosen_sku) == ("matched", "S201M-C10")
    used = m.attributes_used["poles"]
    assert (used.value, used.source) == (1, "inferred")
    assert used.note == 'הכבל 3×1.5 ורוב המא"זים הזהים בשורה: 1P'
    assert used.note in m.reason and m.confidence < 0.85
    # the instances say which components: their `poles_corrected` issue
    ins = Instance(
        instance_id="ins_001_0034",
        det_id="det_001_0034",
        page_id="pg_001",
        panel_id="pnl_01",
        bbox=(0, 0, 1, 1),
        family="circuit_breaker",
        symbol_class="mcb",
        attributes={},
        method="agent",
        status="uncertain",
        confidence=0.42,
        component_id=c.component_id,
        issues=[StageIssue(code="poles_corrected", severity="warning", message="…")],
    )
    other = ins.model_copy(update={"instance_id": "ins_001_0035", "component_id": "cmp_x", "issues": []})
    assert corrected_poles([ins, other]) == frozenset({c.component_id})


def test_an_overload_relays_range_holds_the_load() -> None:
    m = one(comp("overload_relay", "overload_relay", {}, circuit=CircuitContext(load_current_a=5.0)))
    assert m.chosen_sku == "TF42-5.7"


def test_poles_from_the_cable_only_without_text_or_graphic() -> None:
    cable = CircuitContext(cable=Cable(cores=3, cross_section_mm2=2.5))
    m = one(comp("circuit_breaker", "mcb", {"current_a": 16}, circuit=cable))
    assert m.chosen_sku == "S201M-C16" and m.attributes_used["poles"].source == "inferred"
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, circuit=cable, source="graphic"))
    assert m.chosen_sku == "S203M-C16" and "poles_cable_conflict" in m.warnings


def test_a_factory_turns_a_rule_off() -> None:
    f1, c1 = _with_upstream("contactor", "C", {"poles": 3})
    m = run(f1, c1, fac=factory(inference_off=frozenset({"contactor_current_from_upstream"})))[1]
    assert m.status == "unmatched"


def test_a_moulded_case_setting_must_lie_in_the_range() -> None:
    lsi = {"current_a": 160, "poles": 3, "trip_unit": "LSI"}
    assert one(comp("circuit_breaker", "mccb", lsi | {"setting_a": 100})).chosen_sku == "XT2N160 Ekip LSI In=160 3P"
    assert one(comp("circuit_breaker", "mccb", lsi | {"setting_a": 40})).status == "unmatched"


# --- 5.6 query, relaxation, ranking -----------------------------------------------------------------------------------


def test_exact_is_never_relaxed() -> None:
    m = one(comp("circuit_breaker", "mcb", {"current_a": 13, "poles": 3}))
    assert (m.status, m.chosen_sku) == ("unmatched", None) and "no_catalog_match" in m.warnings
    assert "13A" in m.reason


def test_a_brand_the_catalog_lacks_relaxes_to_the_allowed_alternate() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, brand="Hager"))
    assert m.chosen_sku == "A9F74316" and m.relaxations == ["substitution"]
    assert m.substitution is not None and (m.substitution.requested_brand, m.substitution.chosen_brand) == (
        "Hager",
        "Schneider",
    )
    assert m.confidence < 0.95 * 0.90 * 0.9 * 0.9


def test_the_preferred_series_relaxes_to_the_brands_others() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16), fac=factory(series={"circuit_breaker": "S200"}))
    assert m.chosen_sku == "S203M-C16" and m.relaxations == ["series_relaxed"]


def test_gte_upgrades_to_the_nearest() -> None:
    """05 §13 item 2: chosen automatically, the nearest first (6kA asked: 10kA over nothing)."""
    m = one(comp("circuit_breaker", "mcb", MCB_3X16 | {"breaking_capacity_ka": 6}))
    assert m.catalog_item is not None and m.catalog_item.attributes["breaking_capacity_ka"] == 10


def test_an_item_with_a_price_ranks_before_one_without() -> None:
    """Criterion 3, after the preferences (1) and the brand (2): two green lamps, no brand preferred."""
    lamp = comp("indicator_lamp", "pilot_light", {"color": "green", "coil_voltage_v": 230})
    for unpriced, expected in (("CL2-523G", "XB7EV03MP"), ("XB7EV03MP", "CL2-523G")):
        priced = frozenset(i for i, it in CATALOG.items.items() if it.sku != unpriced)
        assert one(lamp, fac=factory(brand_preferences={}, priced=priced)).chosen_sku == expected
    priced = frozenset(i for i, it in CATALOG.items.items() if it.sku != "S201M-C16")
    m = one(comp("circuit_breaker", "mcb", {"current_a": 16, "poles": 1}, ("S201M-C16",)), fac=factory(priced=priced))
    assert "no_cost_price" in m.warnings and m.has_cost_price is False


def test_ties_by_price_when_the_factory_says_so() -> None:
    """05 §13 item 1: two green lamps with made-up costs, never shown to anyone."""
    lamps = [i for i in CATALOG.items.values() if i.family == "indicator_lamp" and i.attributes["color"] == "green"]
    abb, sch = sorted(lamps, key=lambda i: i.brand)
    from decimal import Decimal

    fac = factory(brand_preferences={}, tie_break="price", costs={abb.id: Decimal("40"), sch.id: Decimal("30")})
    assert (
        one(comp("indicator_lamp", "pilot_light", {"color": "green", "coil_voltage_v": 230}), fac=fac).chosen_sku
        == sch.sku
    )


# --- 5.7–5.8 decision and the agent -----------------------------------------------------------------------------------


def _button() -> Component:
    return comp("push_button", "push_button", {}, ("EMS",), designators=("EMS",))


def test_the_agent_chooses_between_candidates_no_rule_decides() -> None:
    agent = Agent(CatalogAnswer(chosen_sku="MPET4-10R", confidence=0.95, reason="לחצן חירום"))
    m = one(_button(), ask=agent)
    assert (m.method, m.chosen_sku, m.match_confidence) == ("llm", "MPET4-10R", 0.85)  # capped (05 §6.3)
    assert m.llm_decision is not None and m.llm_decision["chosen_sku"] == "MPET4-10R"
    assert len(agent.shown) == 1


def test_an_answer_off_the_list_is_sent_back_once() -> None:
    agent = Agent(
        CatalogAnswer(chosen_sku="XB4BS8445", confidence=0.9, reason="x"),
        CatalogAnswer(chosen_sku="MPET4-10R", confidence=0.9, reason="x"),
    )
    assert one(_button(), ask=agent).chosen_sku == "MPET4-10R"
    assert agent.shown[1][3] is not None and "XB4BS8445" in (agent.shown[1][3] or "")


def test_the_agent_says_none_ambiguous_with_the_alternatives() -> None:
    agent = Agent(CatalogAnswer(chosen_sku=None, confidence=0.3, reason="לא כתוב צבע", missing_attributes=["color"]))
    m = one(_button(), ask=agent)
    assert (m.status, m.method, m.missing_attributes) == ("ambiguous", "llm", ["color"])
    assert m.alternatives and m.confidence <= DEFAULT.yellow_max


def test_the_agent_is_shown_no_price() -> None:
    """05 §12, non-negotiable 6: no list price, cost or customer detail in what the agent sees."""
    agent = Agent(CatalogAnswer(chosen_sku="MPET4-10R", confidence=0.9, reason="x"))
    one(_button(), ask=agent, fac=factory(customer_id="cus_secret"))
    shown = " ".join(x or "" for x in agent.shown[0])
    assert "95.00" not in shown and "38.00" not in shown and "cus_secret" not in shown
    assert "price" not in shown.casefold() and "₪" not in shown


def test_the_same_signature_is_matched_once() -> None:
    agent = Agent(CatalogAnswer(chosen_sku="MPET4-10R", confidence=0.9, reason="x"))
    buttons = [comp("push_button", "push_button", {}, ("EMS",), cid=f"cmp_{n:04d}") for n in range(3)]
    matches = run(*buttons, ask=agent)
    assert {m.chosen_sku for m in matches} == {"MPET4-10R"} and len(agent.shown) == 1
    assert [m.component_id for m in matches] == ["cmp_0000", "cmp_0001", "cmp_0002"]


def test_a_clear_advantage_decides_without_the_agent() -> None:
    agent = Agent()
    m = one(comp("indicator_lamp", "pilot_light", {"color": "red", "coil_voltage_v": 230}), ask=agent)
    assert m.method in ("rules_ranked", "rules_unique") and agent.shown == []


# --- 5.9 alternatives, kits, accessories ------------------------------------------------------------------------------


def test_alternatives_say_what_differs() -> None:
    m = one(comp("circuit_breaker", "mcb", MCB_3X16))
    diffs = {a.sku: a.diff for a in m.alternatives}
    assert len(m.alternatives) <= 3 and "S203M-C16" not in diffs
    assert any("Schneider במקום ABB" in d for d in diffs.values())


def test_a_kit_adds_its_part() -> None:
    """NEVIS-1's Q0: "4X80A ABB-XT1C … משולב פחת" is the breaker and its RCD module."""
    q0 = comp("circuit_breaker", "mccb", {"current_a": 80, "poles": 4}, ("ABB-XT1C", "4×80A", "משולב", "פחת"))
    m = one(q0)
    assert m.chosen_sku == "XT1C160 TMD80 4P"
    assert [(b.sku, b.quantity) for b in m.bundle_lines] == [("RC Sel 4P XT1", 1)]
    plain = one(comp("circuit_breaker", "mccb", {"current_a": 80, "poles": 4}, ("ABB-XT1C",)))
    assert plain.bundle_lines == []


def test_an_aux_contact_fits_its_breakers_series() -> None:
    """NEVIS-1: an NC aux contact (21/22) on F1."""
    f1 = comp("circuit_breaker", "mcb", MCB_3X16, ("S203M",), cid="cmp_0001", designators=("F1",))
    aux = comp("aux_contact", "aux_contact", {"contacts": "21/22"}, cid="cmp_0002", designators=(), parents=("F1",))
    m = run(aux, f1)[0]  # the order given; the device is matched first anyway
    assert m.chosen_sku == "S2C-H01" and m.brand_decision is not None and m.brand_decision.source == "parent"


def test_an_accessory_on_an_unmatched_device_stays_ambiguous() -> None:
    f1 = comp("circuit_breaker", "mcb", {"poles": 3}, cid="cmp_0001", designators=("F1",))
    aux = comp("aux_contact", "aux_contact", {"contacts": "21/22"}, cid="cmp_0002", designators=(), parents=("F1",))
    m = run(f1, aux)[1]
    assert (m.status, m.chosen_sku) == ("ambiguous", None)


def _with_common_accessories() -> Catalog:
    """The sample with `common.csv`'s shunt trip and its fits (BUG-109): YO-C XT5-XT6 fits the XT5 and XT6 models."""
    row = next(r for r in parse(COMMON.read_text(encoding="utf-8")) if r.sku.startswith("YO-C"))
    yo = Item("cat_yoc", row.sku, row.brand, row.series, row.model_code, row.model_tokens, row.family,
              row.symbol_class, dict(row.attributes), row.status, None)  # fmt: skip
    fits = {k: set(v) for k, v in CATALOG.fits.items()}
    for a in parse_accessories(COMMON_ACCESSORIES.read_text(encoding="utf-8")):
        assert a.accessory_sku == yo.sku
        fits.setdefault(yo.id, set()).add((a.fits_brand, a.fits_series))
    return Catalog({**CATALOG.items, yo.id: yo}, CATALOG.kits, fits)


def _trip_on(host: Component, catalog: Catalog) -> ComponentMatch:
    trip = comp("shunt_trip", "shunt_trip", {}, cid="cmp_0002", designators=(), parents=(host.designators[0],))
    inp = Inputs(catalog, factory(priced=frozenset(catalog.items)), schemas.default(), Notes(),
                 {c.component_id: c for c in (host, trip)})  # fmt: skip
    return match_all([trip, host], inp).matches[0]


def test_a_shunt_trip_fits_its_breakers_model() -> None:
    """BUG-109, 25/886: the XT5 breaker QE's shunt trip is YO-C XT5-XT6. "Tmax XT" runs from XT1 to XT6, so SOR-C XT1,
    which fits the series, is left out when one fits the XT5 by its model; S2C-A1 (an S200's) never fits."""
    cat = _with_common_accessories()
    xt5 = comp("circuit_breaker", "mccb", {"current_a": 630, "poles": 3}, ("ABB-XT5", "3×630A", "LSI", "36kA"),
               designators=("QE",))  # fmt: skip
    m = _trip_on(xt5, cat)
    assert (m.status, m.chosen_sku) == ("matched", "YO-C XT5-XT6 F/P 110-240VAC")
    assert m.brand_decision is not None and m.brand_decision.source == "parent"
    xt1 = comp("circuit_breaker", "mccb", {"current_a": 80, "poles": 3}, ("ABB-XT1C", "3×80A"), designators=("Q1",))
    assert _trip_on(xt1, cat).chosen_sku == "SOR-C 220-240VAC XT1"  # nothing fits an XT1 by its model: the series


def test_the_most_specific_fit_wins_on_every_parent() -> None:
    cat = _with_common_accessories()
    xt5 = ("ABB", "Tmax XT", ("XT5N630", "XT5N", "XT5"))
    xt1 = ("ABB", "Tmax XT", ("XT1C160", "XT1C", "XT1"))
    s200 = ("ABB", "S200M", ("S203M",))
    assert [i.sku for i in fitting(cat, "shunt_trip", (xt5,))] == ["YO-C XT5-XT6 F/P 110-240VAC"]
    assert [i.sku for i in fitting(cat, "shunt_trip", (xt1,))] == ["SOR-C 220-240VAC XT1"]
    assert [i.sku for i in fitting(cat, "shunt_trip", (xt1, xt5))] == ["SOR-C 220-240VAC XT1"]  # fits both: series
    assert [i.sku for i in fitting(cat, "shunt_trip", (s200,))] == ["S2C-A1"]
    assert fitting(cat, "shunt_trip", (s200, xt5)) == []  # one accessory on two series fits neither
    assert [i.sku for i in fitting(cat, "shunt_trip", (("Schneider", "Acti9 iC60N", ()),))] == ["A9A26946"]


# --- statuses, issues, auxiliary families -----------------------------------------------------------------------------


def test_auxiliary_families_get_no_sku() -> None:
    """S20 decision 3: terminals are listed apart; stage 7 counts them."""
    inp = Inputs(CATALOG, factory(), schemas.default(), Notes(), {})
    t = comp("terminal", "terminal", {}, cid="cmp_0009")
    result = match_all([t, comp("circuit_breaker", "mcb", MCB_3X16)], inp)
    assert result.auxiliary == ["cmp_0009"] and [m.component_id for m in result.matches] == ["cmp_0001"]
    assert result.stats.auxiliary == 1


def test_many_unmatched_is_reported() -> None:
    inp = Inputs(CATALOG, factory(), schemas.default(), Notes(), {})
    lost = [comp("circuit_breaker", "mcb", {"poles": 3}, cid=f"cmp_{n:04d}") for n in range(2)]
    result = match_all([*lost, comp("circuit_breaker", "mcb", MCB_3X16, cid="cmp_0100")], inp)
    assert [i.code for i in result.issues] == ["high_unmatched_ratio"]
    assert result.stats.by_status == {"matched": 1, "unmatched": 2}


def test_every_chosen_sku_is_in_the_catalog() -> None:
    """05 §1 item 2: never a made-up SKU."""
    cases = [
        comp("circuit_breaker", "mcb", MCB_3X16, ("S203M",)),
        comp("rcd", "rcd", {"current_a": 40, "poles": 4}),
        comp("contactor", "C", {"current_a": 25, "poles": 3, "coil_voltage_v": 230}),
        comp("indicator_lamp", "pilot_light", {"color": "green"}),
        comp("current_transformer", "current_transformer", {"ratio_primary_a": 125, "ratio_secondary_a": 5}),
    ]
    for c in cases:
        m = one(c)
        assert m.chosen_sku is None or m.chosen_sku in SKU, m
        if m.chosen_sku is None:
            assert m.reason


def test_notes_lines_read() -> None:
    rule = notes_mod.line_rule('כל המא"זים יהיו 10kA, תוצרת שניידר או ש"ע.')
    assert rule is not None and (rule.family, rule.brand, rule.equivalent) == ("circuit_breaker", "Schneider", True)
    assert rule.attributes == {"breaking_capacity_ka": 10}
    assert notes_mod.line_rule("הלוח יבנה לפי התקן") is None
    rcd = notes_mod.line_rule("- מפסקי פחת 30mA סוג A")
    assert rcd is not None and rcd.attributes == {"residual_ma": 30, "rcd_type": "A"}
    panel = notes_mod.read(
        [
            ContextArtifact(
                artifact_id="ctx_2",
                page_id=None,
                kind="notes_block",
                format="json",
                content=json.dumps({"panel_id": "pnl_1", "min_breaking_capacity_ka": 10}),
            )
        ]
    )
    assert [r.attributes for r in panel.applying("circuit_breaker", "pnl_1")] == [{"breaking_capacity_ka": 10}]
    assert panel.applying("circuit_breaker", "pnl_2") == []


def test_a_price_never_decides_a_value_nobody_wrote() -> None:
    """S203M comes in curves C and D. With no curve written and no default, the priced C does not win by its price:
    the estimator chooses (`ambiguous`, the curve missing)."""
    only_c = frozenset(i for i, it in CATALOG.items.items() if it.sku != "S203M-D16")
    m = one(comp("circuit_breaker", "mcb", MCB_3X16, ("S203M",)), fac=factory(attribute_defaults={}, priced=only_c))
    assert (m.status, m.missing_attributes) == ("ambiguous", ["curve"])
    assert {m.chosen_sku, *(a.sku for a in m.alternatives)} >= {"S203M-C16", "S203M-D16"}


def test_150_components_in_under_2_seconds_without_the_model() -> None:
    """05 §9: matching in code is fast; most of the 150 differ, so the signature cache helps little here."""
    import time

    comps = []
    for n in range(150):
        amps = (6, 10, 16, 20, 25, 32, 40)[n % 7]
        poles = (1, 2, 3)[n % 3]
        comps.append(comp("circuit_breaker", "mcb", {"current_a": amps, "poles": poles}, cid=f"cmp_{n:04d}"))
    start = time.perf_counter()
    matches = run(*comps)
    assert time.perf_counter() - start < 2.0
    assert len(matches) == 150


def test_a_motor_protection_breaker_is_its_range() -> None:
    """26-993's QLG1: "ABB-MS116 4-6.3A" gives a range, no current; the series gives the poles."""
    qlg = comp("circuit_breaker", "motor_protection", {"range_min_a": 4.0, "range_max_a": 6.3}, ("ABB-MS116",))
    m = one(qlg)
    assert (m.status, m.chosen_sku) == ("matched", "MS116-6.3")
    assert m.attributes_used["poles"].source == "series"
    unknown = one(comp("circuit_breaker", "motor_protection", {"range_min_a": 1.0, "range_max_a": 2.4}, ("PKZM",)))
    assert unknown.status == "unmatched" and unknown.missing_attributes == ["poles"]


def test_an_electronic_trip_unit_accepts_lsi() -> None:
    """6199-2-50: "מפסק אלקטרוני LSI 160A/160A"; stage 4 reads "אלקטרוני" as `electronic`."""
    lsi = {"current_a": 160, "poles": 3, "setting_a": 160}
    electronic = one(comp("circuit_breaker", "mccb", lsi | {"trip_unit": "electronic"}))
    assert electronic.chosen_sku == "XT2N160 Ekip LSI In=160 3P"
    assert one(comp("circuit_breaker", "mccb", lsi | {"trip_unit": "TMD"})).chosen_sku == "XT1C160 TMD160 3P"


def test_one_signature_one_sku_whatever_the_text_says() -> None:
    """05 §10: 100% consistency. Two buttons with the same signature and different words are decided once."""
    agent = Agent(CatalogAnswer(chosen_sku="MPET4-10R", confidence=0.9, reason="x"))
    a = comp("push_button", "push_button", {}, ("EMS",), cid="cmp_0001", designators=("EMS",))
    b = comp("push_button", "push_button", {}, ("חירום",), cid="cmp_0002", designators=("PB2",))
    assert {m.chosen_sku for m in run(a, b, ask=agent)} == {"MPET4-10R"} and len(agent.shown) == 1


def test_no_text_beside_it_no_agent() -> None:
    """A lamp with nothing written beside it but its tag: its colour is the estimator's to choose, not a model's."""
    agent = Agent()
    m = one(comp("indicator_lamp", "pilot_light", {"coil_voltage_v": 230}, ("L1",), designators=("L1",)), ask=agent)
    assert (m.status, m.missing_attributes) == ("ambiguous", ["color"]) and agent.shown == []


def test_a_stated_preference_is_part_of_the_signature() -> None:
    """NEVIS-1: SW1 has "1-0-2" beside it, SW3 nothing; they must not share a signature, or one gets the other's SKU."""
    sw1 = comp("selector_switch", "selector_switch", {"positions": "1-0-2"}, ("SW1",), cid="cmp_0001")
    sw3 = comp("selector_switch", "selector_switch", {}, (), cid="cmp_0002", designators=("SW3",))
    a, b = run(sw1, sw3)
    assert a.signature == "selector_switch|selector_switch|positions:1-0-2" and a.signature != b.signature


def test_every_line_is_named_as_the_factory_names_it() -> None:
    """The user, on 25.26.100's quote: professional names. A contactor's current is its AC-3 rating and its coil is
    named (the prototype's "מגען 3P ‏16A לפחות (AC-3)"); a motor-protection breaker is "מפסק מגן מנוע" with its range;
    a switch-disconnector is "מנתק" (the prototype's word). The detection library's names, the model's words, stay."""
    from konboro.pipeline.matching.text import describe

    contactor = describe("contactor", "contactor", "ABB", "AF09", {"poles": 3, "current_a": 9, "coil_voltage_v": 230})
    assert contactor == "מגען ABB AF09 3P 9A (AC-3) סליל 230V"
    mpcb = describe(
        "circuit_breaker", "motor_protection", "ABB", "MS116", {"poles": 3, "range_min_a": 2.5, "range_max_a": 4}
    )
    assert mpcb == "מפסק מגן מנוע ABB MS116 3P טווח 2.5–4A"
    assert describe("switch_disconnector", "switch_disconnector", None, None, {"poles": 4, "current_a": 125}) == (
        "מנתק 4P 125A"
    )
    assert describe("relay", "relay", None, None, {"coil_voltage_v": 24}) == "ממסר עזר סליל 24V"
    assert SKU["MS116-4"].description.startswith("מפסק מגן מנוע ABB")


def test_the_two_clocks_and_a_contactors_category_are_named() -> None:
    """S27b (the user): "שעון שבת" and "שעון אסטרונומי" are two products, and ESB25's 25A is an AC-1 rating. A clock
    nothing is known about keeps the library's name; a contactor with no category stays AC-3, as before."""
    from konboro.pipeline.matching.text import describe

    assert describe("time_switch", "time_switch", "ABB", "DWA1", {"astronomical": True, "coil_voltage_v": 230}) == (
        "שעון אסטרונומי ABB DWA1 סליל 230V"
    )
    assert describe("time_switch", "time_switch", "ABB", "D1", {"astronomical": False}) == "שעון שבת ABB D1"
    assert describe("time_switch", "time_switch", None, None, {}) == "שעון שבת / שעון פיקוד"
    esb = describe("contactor", None, "ABB", "ESB25", {"poles": 3, "current_a": 25, "utilization": "AC-1"})
    assert esb == "מגען ABB ESB25 3P 25A (AC-1)"


# --- S27b: the nearest products (05 §5.9.2) and the factory's own products (05 §5.6) ---------------------------------


def run_lines(*components: Component, catalog: Catalog = CATALOG, nearest: bool = True) -> list[ComponentMatch]:
    inp = Inputs(
        catalog=catalog,
        factory=factory(),
        schemas=schemas.default(),
        notes=Notes(),
        components={c.component_id: c for c in components},
        nearest=nearest,
    )
    return match_all(list(components), inp).matches


def test_nothing_matches_and_the_nearest_products_are_suggested() -> None:
    """A 3P 13A MCB is no product. Stage 5 suggests the three nearest, all 3P, each with what differs, and chooses
    none of them (05 §1 principles 2 and 3). The distance ranks before the brand: Schneider's 10A is nearer than
    ABB's 20A, and among the equally near the factory's ABB comes first."""
    m = run_lines(comp("circuit_breaker", "mcb", {"poles": 3, "current_a": 13, "curve": "C"}))[0]
    assert (m.status, m.chosen_sku, m.catalog_item) == ("unmatched", None, None)
    assert [n.sku for n in m.nearest] == ["S203M-C10", "S203M-C16", "A9F74310"]
    first = m.nearest[0]
    assert (first.diff, first.differs, first.manufacturer) == ("10A במקום 13A", ["current_a"], "ABB")
    assert first.catalog_item_id == SKU["S203M-C10"].id and first.product_id is None
    assert first.description == SKU["S203M-C10"].description


def test_another_pole_count_comes_last() -> None:
    """The user's decision 2: a product with the drawing's poles before any with other poles. 3P 63A D has no D curve
    in the sample, so the 3P C items come first, and a 1P one only after every 3P."""
    m = run_lines(comp("circuit_breaker", "mcb", {"poles": 3, "current_a": 63, "curve": "D"}))[0]
    assert m.status == "unmatched" and m.nearest
    poles = [SKU[n.sku].attributes.get("poles") for n in m.nearest]
    assert poles == sorted(poles, key=lambda p: p != 3) and poles[0] == 3
    assert "curve" in m.nearest[0].differs


def test_no_suggestion_without_the_current_or_with_the_flag_off() -> None:
    """05 §5.9.2: with the current missing there is nothing to compare with; the user picks the value (09 §6.4).
    With `catalog_lines` off, stage 5 is as before."""
    missing = run_lines(comp("circuit_breaker", "mcb", {"poles": 3, "curve": "C"}))[0]
    assert missing.status == "unmatched" and "missing_required_attribute" in missing.warnings and missing.nearest == []
    off = run_lines(comp("circuit_breaker", "mcb", {"poles": 3, "current_a": 13, "curve": "C"}), nearest=False)[0]
    assert off.status == "unmatched" and off.nearest == []


def test_a_factory_product_is_a_candidate() -> None:
    """05 §5.6 (S27b): a product made in "מוצר חדש", with its family's attributes, a brand and a model, is matched like
    a catalog item, and the match names it by `product_id`. A product typed in the price list (no attributes) is not."""
    from konboro.db import models as m
    from konboro.pipeline.matching.catalog import with_products

    made = m.Product(
        id="prd_01JNEW",
        family="circuit_breaker",
        symbol_class="mcb",
        brand="ABB",
        model_code="S203M",
        series="S200M",
        manufacturer_sku=None,
        attributes={"poles": 3, "current_a": 13, "curve": "C", "breaking_capacity_ka": 10, "neutral": False},
        catalog_item_id=None,
        display_name="x",
    )
    typed = m.Product(id="prd_01JTYPED", family="circuit_breaker", brand="ABB", model_code=None, attributes={})
    cat = with_products(CATALOG, [made, typed])
    assert "prd:prd_01JTYPED" not in cat.items
    found = run_lines(comp("circuit_breaker", "mcb", {"poles": 3, "current_a": 13, "curve": "C"}), catalog=cat)[0]
    assert (found.status, found.product_id, found.chosen_sku) == ("matched", "prd_01JNEW", "S203M")
    assert found.catalog_item is not None
    assert found.catalog_item.description == 'מפסק זרם אוטומטי (מא"ז) ABB S203M 3P 13A עקומה C 10kA'
    assert found.nearest == []


def test_a_contactor_with_no_category_written_is_ac3() -> None:
    """S27b (05 decision 6): "מגען 3X25" is 25A at AC-3. ESB25-30N-06 is rated 25A at AC-1 only, so it is no candidate
    unless the drawing writes AC-1; the signature doesn't change."""
    esb = Item(
        id="cat_esb25",
        sku="ESB25-30N-06",
        brand="ABB",
        series="ESB",
        model_code="ESB25",
        model_tokens=(),
        family="contactor",
        symbol_class=None,
        attributes={"current_a": 25, "poles": 3, "coil_voltage_v": 230, "utilization": "AC-1"},
        status="active",
        replaced_by=None,
    )
    cat = Catalog({**CATALOG.items, esb.id: esb}, CATALOG.kits, CATALOG.fits)
    plain = run_lines(comp("contactor", "contactor", {"current_a": 25, "poles": 3}), catalog=cat, nearest=False)[0]
    assert plain.chosen_sku != "ESB25-30N-06" and plain.signature == "contactor|contactor|current_a=25|poles=3"
    ac1 = run_lines(
        comp("contactor", "contactor", {"current_a": 25, "poles": 3, "utilization": "AC-1"}), catalog=cat, nearest=False
    )[0]
    assert ac1.chosen_sku == "ESB25-30N-06"
