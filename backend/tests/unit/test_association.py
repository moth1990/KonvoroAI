"""Stage 4 (04): the spelling grammar, the attribute schemas, geometric association, shared labels and the neutral
pole, multiplicity, circuit numbers and supply scope, the circuit walk, the tile agent's check and its retries, the
merge, confidence and status, and the run step's line. No real model is called."""

import itertools
import json
from typing import Any

import pytest
from PIL import Image

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection
from konboro.contracts.extraction import TextSpan, Tile
from konboro.contracts.merge import AttributeValue, Cable, CircuitContext, Instance
from konboro.pipeline.association import agent, assign, circuits, grammar, quantity, schemas
from konboro.pipeline.association.assign import Value
from konboro.pipeline.association.config import DEFAULT
from konboro.pipeline.association.merge import Built, components, instance_confidence, one_name_per_tag, status
from konboro.pipeline.detection import library
from konboro.pipeline.stages import s4_association
from konboro_llm import LLMAccountError, LLMError
from konboro_llm.stages.text_association import TileAnswer

SCH = schemas.default()
FAMILIES = {f for f, cs in library.default().families.items() if any(c.billable for c in cs)}
CLASS_FAMILY = {c.symbol_class: c.family for c in library.CLASSES}


def det(
    n: int,
    bbox: Bbox,
    family: str = "circuit_breaker",
    cls: str = "mcb",
    tag: str | None = None,
    role: str = "device",
    billable: bool = True,
    tile: str = "tl_001_r0c0",
    page: str = "pg_001",
    confidence: float = 0.9,
) -> Detection:
    return Detection(
        det_id=f"det_001_{n:04d}",
        page_id=page,
        bbox=bbox,
        family=family,
        symbol_class=cls,
        billable=billable,
        method="llm_vision",
        detector_score=confidence,
        class_score=confidence,
        confidence=confidence,
        status="accepted",
        owner_tile_id=tile,
        designator=tag,
        role=role,  # type: ignore[arg-type]
    )


def span(n: int, text: str, bbox: Bbox, confidence: float = 1.0, rotation: int = 0) -> TextSpan:
    return TextSpan(
        span_id=f"ts_001_{n:04d}",
        text=text,
        raw_text=text,
        bbox=bbox,
        rotation=rotation,  # type: ignore[arg-type]
        source="ocr",
        confidence=confidence,
    )


def keys(text: str, family: str = "circuit_breaker") -> dict[str, list[Any]]:
    return grammar.values(text, family)


# ---------- the spelling grammar (04 §5.1) ----------


def test_the_grammar_is_a_data_file_that_loads() -> None:
    g = grammar.load()
    assert g.version
    ids = [p.id for p in g.patterns]
    assert len(ids) == len(set(ids))
    assert set(g.scope_phrases) == {"other_location", "prepare_only", "by_others"}


def test_an_unknown_builder_or_a_repeated_id_is_refused() -> None:
    base = {"version": "t", "scope_phrases": {}}
    with pytest.raises(ValueError, match="builder"):
        grammar.from_json(base | {"patterns": [{"id": "x", "re": "a", "build": "nope"}]})
    with pytest.raises(ValueError, match="unique"):
        grammar.from_json(base | {"patterns": [{"id": "x", "re": "a"}, {"id": "x", "re": "b"}]})


@pytest.mark.parametrize(
    ("text", "family", "expected"),
    [
        ("C16", "circuit_breaker", {"curve": ["C"], "current_a": [16]}),
        ("B32", "circuit_breaker", {"curve": ["B"], "current_a": [32]}),
        ("3×16A", "circuit_breaker", {"poles": [3], "current_a": [16]}),
        ("1P+N", "circuit_breaker", {"poles": [1], "neutral": [True]}),
        ("4P", "circuit_breaker", {"poles": [4]}),
        ("16A", "circuit_breaker", {"current_a": [16]}),
        ("10kA", "circuit_breaker", {"breaking_capacity_ka": [10]}),
        ("6000", "circuit_breaker", {"breaking_capacity_ka": [6]}),
        ("30mA", "rcd", {"residual_ma": [30]}),
        ("0.03A", "rcd", {"residual_ma": [30]}),
        ("0,03", "rcd", {"residual_ma": [30]}),
        ("40/0.03", "rcd", {"current_a": [40], "residual_ma": [30]}),
        ("40A/30mA", "rcd", {"current_a": [40], "residual_ma": [30]}),
        # BUG-044: S.S לוחות writes the sensitivity and the type as one word (26/956-1, FB0)
        ('30mA-TYPE"A"', "rcd", {"residual_ma": [30], "rcd_type": ["A"]}),
        ("30mA-TYPE״A״", "rcd", {"residual_ma": [30], "rcd_type": ["A"]}),
        ("30mA-Type-AC", "rcd", {"residual_ma": [30], "rcd_type": ["AC"]}),
        ('30mA TYPE "A"', "rcd", {"residual_ma": [30], "rcd_type": ["A"]}),
        ('Type "B"', "rcd", {"rcd_type": ["B"]}),
        ("30mA-type A", "rcd", {"residual_ma": [30], "rcd_type": ["A"]}),
        ("Type A", "rcd", {"rcd_type": ["A"]}),
        ("סוג A", "rcd", {"rcd_type": ["A"]}),
        ("(x4)", "circuit_breaker", {"multiplicity": [4]}),
        ("×4", "circuit_breaker", {"multiplicity": [4]}),
        ("4 יציאות", "circuit_breaker", {"multiplicity": [4]}),
        ("16+N", "circuit_breaker", {"current_a": [16], "poles": [1], "neutral": [True]}),
        ("S203M", "circuit_breaker", {"model_token": ["S203M"]}),
        # BUG-110: a brand and its model as one word, as 25/886 writes its meter and its ATS controller
        ("SATEC-135", "energy_meter", {"brand": ["SATEC"], "model_token": ["SATEC-135"]}),
        ("AMDAR-AM530D", "ats", {"brand": ["AMDAR"], "model_token": ["AMDAR-AM530D"]}),
        ("AMDAR", "ats", {"brand": ["AMDAR"]}),
        ("INC=12.8A", "circuit_breaker", {"load_current_a": [12.8]}),
        ("3(2.4-4)A", "circuit_breaker", {"poles": [3], "range_min_a": [2.4], "range_max_a": [4]}),  # BUG-080
        ("1×10AC", "circuit_breaker", {"poles": [1], "current_a": [10], "curve": ["C"]}),  # BUG-080
        ("Ib=10A", "circuit_breaker", {"load_current_a": [10]}),
        ("500A/630A", "circuit_breaker", {"current_a": [630], "setting_a": [500]}),
        ("4×63A/0,03A", "rcd", {"poles": [4], "current_a": [63], "residual_ma": [30]}),
        ("5/800A", "current_transformer", {"ratio_secondary_a": [5], "ratio_primary_a": [800]}),
        ("800/5A", "current_transformer", {"ratio_primary_a": [800], "ratio_secondary_a": [5]}),
        ("LSI", "circuit_breaker", {"trip_unit": ["LSI"]}),
        ("LS/I", "circuit_breaker", {"trip_unit": ["LS/I"]}),  # S27b: as the catalog writes it
        ("שעון אסטרונומי", "time_switch", {"astronomical": [True]}),  # S27b
        ("AC-1", "contactor", {"utilization": ["AC-1"]}),  # BUG-108: 25/886's C3
        ("AC3", "contactor", {"utilization": ["AC-3"]}),
        ("ac-3", "contactor", {"utilization": ["AC-3"]}),
        ("AC 3", "contactor", {"utilization": ["AC-3"]}),
        ("3×25A (AC-1)", "contactor", {"poles": [3], "current_a": [25], "utilization": ["AC-1"]}),
        ("MCCB", "circuit_breaker", {"symbol_class": ["mccb"]}),
        ("מפסק בתיבה יצוקה 25A", "circuit_breaker", {"symbol_class": ["mccb"], "current_a": [25]}),  # BUG-077
        ("4P 100kA B+C", "surge_protector", {"poles": [4], "imax_ka": [100], "spd_class": ["B+C"]}),
        ("CEE 5×16A", "socket_outlet", {"poles": [3], "neutral": [True], "current_a": [16]}),
        ("36-40", "circuit_breaker", {"circuit_range": [(36, 40)]}),
        ("שמור", "circuit_breaker", {"spare": [True]}),
        ("SAVE", "circuit_breaker", {"spare": [True]}),
        ("עם נעילה", "circuit_breaker", {"lockable": [True]}),
        ("IP54", "circuit_breaker", {"ip_rating": ["IP54"]}),
    ],
)
def test_the_spellings_of_04_5_1(text: str, family: str, expected: dict[str, list[Any]]) -> None:
    found = keys(text, family)
    for key, values in expected.items():
        assert found.get(key) == values, (text, found)


def test_the_citation_check_accepts_a_one_word_rcd_rating() -> None:
    """BUG-044: the tile agent cited 30mA and type A from FB0's span; the check (04 §5.5) refused both."""
    span = '30mA-TYPE"A"'
    assert grammar.contains(span, "rcd", "residual_ma", 30)
    assert grammar.contains(span, "rcd", "rcd_type", "A")
    assert not grammar.contains(span, "rcd", "residual_ma", 300)  # a misread number is still refused


def test_one_text_several_meanings_the_family_picks() -> None:
    """04 §5.1 rule 2: "6000" beside a breaker is its breaking capacity; beside a meter it is not."""
    assert keys("6000", "circuit_breaker") == {"breaking_capacity_ka": [6]}
    assert keys("6000", "energy_meter") == {}
    assert keys("10kA", "surge_protector") == {"imax_ka": [10]}
    assert keys("5/800A", "circuit_breaker").get("ratio_primary_a") is None
    assert keys("3×100A", "fuse") == {"multiplicity": [3], "current_a": [100]}  # three fuses, not three poles


def test_a_load_current_is_never_the_rated_current() -> None:
    """04 §5.1: INC= beside every NEVIS-1 breaker is the circuit's load (26-993: about 0.8 × rated)."""
    for text in ("INC=12.8A", "INC=8A", "Ib=10A"):
        assert "current_a" not in keys(text)
        assert not grammar.contains(text, "circuit_breaker", "current_a", 12.8)


def test_an_unknown_prefix_is_kept_as_text() -> None:
    assert keys("XYZ=4A") == {"unknown_prefixed": ["XYZ=4A"]}
    assert keys("IR=500A") == {"setting_a": [500]}


def test_a_cable_and_a_circuit_number_are_not_device_values() -> None:
    cable = keys("5×2,5²-N2XY")
    assert cable["cable_cores"] == [5] and cable["cable_cross_section_mm2"] == [2.5] and "poles" not in cable
    assert keys("4×240²-NA2XY+150CU")["cable_cores"] == [4]
    assert keys("36-40") == {"circuit_range": [(36, 40)]}
    assert keys("40-36") == {}  # not a range


def test_the_citation_check_of_04_5_5() -> None:
    """The agent says current_a=16 citing "C20": the grammar's reading of "C20" has no 16."""
    assert not grammar.contains("C20", "circuit_breaker", "current_a", 16)
    assert grammar.contains("C20", "circuit_breaker", "current_a", 20)
    assert grammar.contains("C20", "circuit_breaker", "curve", "C")
    assert grammar.contains("16+N", "circuit_breaker", "neutral", True)
    assert not grammar.contains("16A", "circuit_breaker", "current_a", True)


# ---------- the attribute schemas (05 §4.4) ----------


def test_current_and_poles_never_take_a_default() -> None:
    for family, attrs in schemas.SCHEMAS.items():
        for a in attrs:
            if a.name in ("current_a", "poles"):
                assert not a.default_allowed, family
    assert SCH.must_read("circuit_breaker") == ("current_a", "poles")
    assert "curve" in SCH.required("circuit_breaker")
    assert SCH.must_read("energy_meter") == ()


def test_every_billable_family_has_a_schema() -> None:
    assert set(schemas.SCHEMAS) >= FAMILIES


def test_a_schema_row_from_the_database_keeps_the_never_default_rule() -> None:
    row = {"name": "current_a", "required": True, "match_mode": "exact", "default_allowed": True}
    assert schemas._from_row(row).default_allowed is False


# ---------- geometric association (04 §5.2) ----------


def test_each_span_goes_to_the_symbol_that_scores_it_highest() -> None:
    left = det(1, (100, 100, 110, 140), tag="F1")
    right = det(2, (160, 100, 170, 140), tag="F2")
    texts = assign.texts([span(1, "3×16A", (112, 110, 128, 116)), span(2, "C10", (172, 110, 186, 116))])
    a = assign.associate([left, right], texts, SCH)
    assert [lk.span_id for lk in a.links[left.det_id]] == ["ts_001_0001"]
    assert [lk.span_id for lk in a.links[right.det_id]] == ["ts_001_0002"]
    by_id = {t.id: t for t in texts}
    r = assign.read(left, a.links[left.det_id], by_id, SCH, CLASS_FAMILY)
    assert {k: v.value for k, v in r.values.items()} == {"poles": 3, "current_a": 16}


def test_a_contactors_category_written_under_its_rating_is_read() -> None:
    """BUG-108: 25/886 page 24 writes "AC-1" under C3's "3×25A", a span of its own. It is the contactor's, from the
    drawing, so stage 5 looks for a 25A AC-1 product
    (`test_matching.py::test_a_contactor_with_no_category_written_is_ac3`).
    "AC" alone is an RCD's type and a category beside a breaker is read as nothing."""
    contactor = det(1, (698.96, 287.17, 713.63, 295.75), family="contactor", cls="contactor", tag="C3")
    rating = span(1, "3×25A", (715.29, 286.62, 732.18, 291.05))
    texts = assign.texts([rating, span(2, "AC-1", (716.95, 291.6, 730.8, 296.03))])
    a = assign.associate([contactor], texts, SCH)
    r = assign.read(contactor, a.links[contactor.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY)
    assert {k: v.value for k, v in r.values.items()} == {"poles": 3, "current_a": 25, "utilization": "AC-1"}
    assert r.values["utilization"].source == "drawing" and r.values["utilization"].span_ids == ["ts_001_0002"]
    assert "utilization" not in keys("AC-1", "circuit_breaker") and "utilization" not in keys("TYPE AC", "rcd")
    assert keys("AC-15", "contactor") == {} and keys("30mA TYPE AC", "contactor").get("utilization") is None


def test_a_brand_and_model_written_as_one_word_inside_a_meter_are_its() -> None:
    """BUG-110: 25/886's meter PM is a box with "רב מודד" and "SATEC-135" in it; the model is its text, and SATEC its
    brand, as "SATEC 135" already was. A tag with a dash (QG-1) is no brand's model."""
    meter = det(1, (567, 351, 621, 373), family="energy_meter", cls="energy_meter", tag="PM")
    texts = assign.texts([span(1, "SATEC-135", (575, 366, 613, 371)), span(2, "QG-1", (580, 356, 600, 361))])
    a = assign.associate([meter], texts, SCH)
    r = assign.read(meter, a.links[meter.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY)
    assert r.explicit_texts == ["SATEC-135"]
    assert [v.value for v in r.context["brand"]] == ["SATEC"]
    assert [v.value for v in r.context["model_token"]] == ["SATEC-135"]
    assert keys("QG-1", "energy_meter") == {}


def test_text_that_means_nothing_to_a_family_is_not_its() -> None:
    """ "30mA" beside a contactor: no fit, so it is no contactor's."""
    contactor = det(1, (100, 100, 110, 120), family="contactor", cls="contactor")
    a = assign.associate([contactor], assign.texts([span(1, "30mA", (112, 105, 125, 110))]), SCH)
    assert not a.links[contactor.det_id]


def test_the_search_is_on_the_whole_page_within_the_radius() -> None:
    d = det(1, (100, 100, 110, 130), tile="tl_001_r0c0")  # radius 3 × 30 pt
    near = span(1, "C16", (150, 110, 160, 116))  # 40 pt away, maybe past the tile's edge
    far = span(2, "C20", (220, 110, 230, 116))  # 110 pt away
    a = assign.associate([d], assign.texts([near, far]), SCH)
    assert [lk.span_id for lk in a.links[d.det_id]] == ["ts_001_0001"]


def test_a_tag_on_the_page_reads_as_nothing() -> None:
    """C1 is the contactor's tag, not curve C at 1 A (NEVIS-1)."""
    texts = assign.texts([span(1, "C1", (0, 0, 5, 5)), span(2, "C16", (0, 10, 5, 15))], {"C1"})
    assert texts[0].readings == [] and texts[1].readings


def test_a_count_is_read_where_no_symbol_took_it_as_its_tag() -> None:
    """BUG-067: 25.26.100's "X11" is a terminal's tag at the line's end and the count under the breaker's rating."""
    spans = [span(1, "X11", (0, 0, 5, 5)), span(2, "X11", (0, 100, 5, 105)), span(3, "C1", (0, 200, 5, 205))]
    texts = assign.texts(spans, {"X11", "C1"}, {"ts_001_0001"})
    assert texts[0].readings == [] and [(r.key, r.value) for r in texts[1].readings] == [("multiplicity", 11)]
    assert texts[2].readings == []  # any other tag reads as nothing wherever it is written


def test_a_close_competitor_lowers_the_association_and_unresolves() -> None:
    a1 = det(1, (100, 100, 110, 140))
    a2 = det(2, (130, 100, 140, 140))
    texts = assign.texts([span(1, "3×16A", (114, 115, 126, 121))])  # in the middle
    a = assign.associate([a1, a2], texts, SCH)
    owner = a1 if a.links[a1.det_id] else a2
    link = a.links[owner.det_id][0]
    assert link.margin < DEFAULT.resolved_gap and link.confidence < DEFAULT.resolved_confidence
    r = assign.read(owner, a.links[owner.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY)
    assert not assign.resolved(owner, r, a.links[owner.det_id], SCH, False)


def test_a_symbol_is_resolved_when_current_and_poles_are_clear() -> None:
    d = det(1, (100, 100, 110, 140))
    texts = assign.texts([span(1, "3×16A", (112, 110, 128, 116)), span(2, "S203M", (112, 120, 128, 126))])
    a = assign.associate([d], texts, SCH)
    r = assign.read(d, a.links[d.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY)
    assert assign.resolved(d, r, a.links[d.det_id], SCH, False)
    assert not assign.resolved(d, r, a.links[d.det_id], SCH, True)  # a shared label nearby
    only_current = assign.texts([span(1, "16A", (112, 110, 128, 116))])
    a = assign.associate([d], only_current, SCH)
    r = assign.read(d, a.links[d.det_id], {t.id: t for t in only_current}, SCH, CLASS_FAMILY)
    assert not assign.resolved(d, r, a.links[d.det_id], SCH, False)  # no poles


def test_two_values_for_one_attribute_are_a_conflict_and_lsi_refines_electronic() -> None:
    d = det(1, (100, 100, 130, 130), cls="mccb")
    texts = assign.texts(
        [
            span(1, "500A", (132, 100, 150, 106)),
            span(2, "630A", (132, 110, 150, 116)),
            span(3, "אלקטרוני", (132, 120, 160, 126)),
            span(4, "LSI", (132, 128, 145, 134)),
        ]
    )
    a = assign.associate([d], texts, SCH)
    r = assign.read(d, a.links[d.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY)
    assert r.conflicts == ["current_a"]
    assert r.values["trip_unit"].value == "LSI"


def test_a_class_hint_in_the_text_stays_within_the_family() -> None:
    d = det(1, (100, 100, 130, 130))
    texts = assign.texts([span(1, "63A", (132, 100, 150, 106)), span(2, "MCCB", (132, 110, 155, 116))])
    a = assign.associate([d], texts, SCH)
    assert assign.read(d, a.links[d.det_id], {t.id: t for t in texts}, SCH, CLASS_FAMILY).symbol_class == "mccb"


def test_one_label_over_a_row_is_a_shared_label() -> None:
    """S13 decision: "C16" over four breakers with no text of their own."""
    row = [det(i, (100 + 30 * i, 200, 110 + 30 * i, 240)) for i in range(1, 5)]
    texts = assign.texts([span(1, "C16", (180, 170, 195, 178))])
    a = assign.associate(row, texts, SCH)
    assert len(a.shared_labels) == 1
    assert a.shared_labels[0].applies_to == sorted(d.det_id for d in row)
    by_id = {t.id: t for t in texts}
    for d in row:
        r = assign.read(d, a.links[d.det_id], by_id, SCH, CLASS_FAMILY)
        assert r.values["current_a"].value == 16
    labelled = [d for d in row if any(not lk.shared for lk in a.links[d.det_id])]
    others = [d for d in row if d not in labelled]
    assert all(
        assign.read(d, a.links[d.det_id], by_id, SCH, CLASS_FAMILY).values["current_a"].source == "shared_label"
        for d in others
    )


def test_a_row_where_each_has_its_own_text_has_no_shared_label() -> None:
    row = [det(i, (100 + 30 * i, 200, 110 + 30 * i, 240)) for i in range(1, 4)]
    texts = assign.texts([span(i, "16A", (112 + 30 * i, 210, 124 + 30 * i, 216)) for i in range(1, 4)])
    assert not assign.associate(row, texts, SCH).shared_labels


def test_the_neutral_pole_on_its_own_line_joins_its_breaker() -> None:
    """NEVIS-1 F3: the breaker, and a contact on the N line beside it (untagged, or with the breaker's tag)."""
    breaker = det(1, (389, 242, 400, 281), tag="F3")
    contact = det(2, (365, 250, 374, 265), family="switch_disconnector", cls="switch_disconnector")
    tagged = det(3, (684, 251, 693, 265), family="relay", cls="relay", tag="F5", role="relay_contact")
    host = det(4, (708, 242, 719, 281), tag="F5")
    aux = det(5, (340, 250, 350, 270), family="aux_contact", cls="aux_contact")
    spans = [span(1, '"N"', (360, 225, 368, 232)), span(2, '"N"', (680, 225, 688, 232))]
    out = assign.absorb_neutral([breaker, contact, tagged, host, aux], spans)
    assert out == {contact.det_id: breaker.det_id, tagged.det_id: host.det_id}
    assert assign.absorb_neutral([breaker, contact], []) == {}  # no N line, no neutral
    # NURSERY-1 F1: the N contact read as a breaker too, with the breaker's tag; the breaker is never its guest
    small = det(6, (365, 250, 374, 265), tag="F3", confidence=0.7)
    assert assign.absorb_neutral([breaker, small], spans[:1]) == {small.det_id: breaker.det_id}


# ---------- multiplicity, circuit numbers, supply scope (04 §5.1.1–5.1.2) ----------


def test_words_on_one_baseline_are_a_line() -> None:
    texts = assign.texts(
        [
            span(1, "בפילר", (602, 498, 626, 508)),
            span(2, "חשמל", (580, 499, 598, 509)),
            span(3, "קיים", (549, 499, 566, 509)),
        ]
    )
    found = quantity.lines(texts)
    assert len(found) == 1 and sorted(found[0].span_ids) == ["ts_001_0001", "ts_001_0002", "ts_001_0003"]


@pytest.mark.parametrize(
    ("words", "scope"),
    [
        ("תוספת מפסק חדש בפילר חשמל קיים", "other_location"),
        ("הכנה בלבד", "prepare_only"),
        ("הכנה לגנרטור", "prepare_only"),
        ("Preparation for a Remote Emergency Push Button", "prepare_only"),
        ('ע"י אחרים', "by_others"),
        ("לא בתכולה", "by_others"),
        ("לוח ראשי", None),
    ],
)
def test_scope_phrases_in_hebrew_and_english(words: str, scope: str | None) -> None:
    line = quantity.Line(assign.texts([span(1, words, (0, 0, 10, 5))]), (0, 0, 10, 5))
    assert quantity.scope_of(line) == scope


def test_a_scope_phrase_belongs_to_the_nearest_symbol_of_any_kind() -> None:
    """6199-2-50: "הכנה בלבד" beside the generator (a load) leaves the changeover switch in the panel."""
    generator = det(1, (900, 580, 930, 610), family="motor_load", cls="motor_load", billable=False)
    switch = det(2, (800, 560, 830, 600), family="changeover_switch", cls="changeover_switch")
    line = quantity.Line(assign.texts([span(1, "הכנה בלבד", (935, 590, 980, 600))]), (935, 590, 980, 600))
    assert quantity.supply_scopes([generator, switch], [line]) == {}
    breaker = det(3, (692, 521, 718, 549))
    other = quantity.Line(assign.texts([span(2, "בפילר חשמל קיים", (600, 498, 680, 508))]), (600, 498, 680, 508))
    assert quantity.supply_scopes([breaker], [other])[breaker.det_id].scope == "other_location"


def test_a_mark_on_the_cable_is_outlets_not_devices() -> None:
    """04 §5.1.1 rule 2: "(x4)" on the line with the cable: one breaker feeding 4 outlets."""
    texts = assign.texts([span(1, "(x4)", (100, 300, 112, 306)), span(2, "5×2.5²-N2XY", (114, 300, 150, 306))])
    found = quantity.lines(texts)
    assert quantity.on_cable_line("ts_001_0001", found)
    alone = assign.texts([span(1, "(x4)", (100, 300, 112, 306))])
    assert not quantity.on_cable_line("ts_001_0001", quantity.lines(alone))


def test_a_count_code_read_stands_when_the_agent_cites_none() -> None:
    """BUG-067: on 25.26.100's live run the tile agent answered count 1, with no span, for the breakers marked "x2"
    and "X11": that is no reading, not a reading of 1. A count the agent cites wins."""
    d = det(1, (100, 100, 144, 137))
    r = assign.Read(context={"multiplicity": [Value(2, "drawing", ["ts_001_0002"], 1.0, 1.0, 1.0)]})
    assert s4_association._multiplicity(d, r, (1, []), []).count == 2
    assert s4_association._multiplicity(d, r, (3, ["ts_001_0002"]), []).count == 3
    assert s4_association._multiplicity(d, assign.Read(), (1, []), []).count == 1


def test_a_range_of_circuit_numbers_goes_to_the_device_in_its_column() -> None:
    a = det(1, (100, 100, 120, 130))
    b = det(2, (200, 100, 220, 130))
    texts = assign.texts([span(1, "36-40", (102, 400, 118, 408)), span(2, "67-70", (202, 400, 218, 408))])
    assert quantity.circuit_ranges([a, b], texts) == {
        a.det_id: ((36, 40), "ts_001_0001"),
        b.det_id: ((67, 70), "ts_001_0002"),
    }


def test_the_range_cross_check() -> None:
    """04 §5.1.1 rule 4: equal → fine; a range with no multiplicity, or a different one → a mismatch."""
    assert not quantity.Multiplicity(count=5, circuit_range=(36, 40)).mismatch
    assert quantity.Multiplicity(count=1, circuit_range=(67, 70)).mismatch
    assert quantity.Multiplicity(count=3, circuit_range=(36, 40)).mismatch
    assert not quantity.Multiplicity(count=1, outputs=4, circuit_range=(80, 83)).mismatch
    assert not quantity.Multiplicity(count=4).mismatch


# ---------- the circuit walk (02 §2.5, 04 §5.1.1 rule 3, 05 §5.5.1) ----------


def _wires(*polylines: list[tuple[float, float]]) -> circuits.Wires:
    nodes: list[tuple[float, float]] = []
    edges = []
    for line in polylines:
        ids = []
        for p in line:
            if p not in nodes:
                nodes.append(p)
            ids.append(nodes.index(p))
        for a, b in itertools.pairwise(ids):
            edges.append((a, b, []))
    return circuits.Wires.build(nodes, edges)


def test_a_device_below_on_the_line_and_the_device_above_it() -> None:
    breaker = det(1, (95, 100, 105, 140))
    contactor = det(2, (95, 200, 105, 230), family="contactor", cls="contactor")
    w = _wires([(100, 60), (100, 100), (100, 140), (100, 200), (100, 230), (100, 300)])
    below, walk = circuits.downstream(w, breaker, [breaker, contactor])
    assert [d.det_id for d in below] == [contactor.det_id]
    assert walk.points
    up = circuits.upstream(w, contactor, [breaker, contactor])
    assert up is not None and up.det_id == breaker.det_id


def test_a_junction_ends_the_circuit() -> None:
    """A bus: the line from the main breaker branches to two breakers, which are not its chain."""
    main = det(1, (95, 100, 105, 140))
    left = det(2, (45, 250, 55, 290))
    right = det(3, (145, 250, 155, 290))
    w = _wires(
        [(100, 140), (100, 200)], [(50, 200), (100, 200), (150, 200)], [(50, 200), (50, 250)], [(150, 200), (150, 250)]
    )
    below, _ = circuits.downstream(w, main, [main, left, right])
    assert below == []


def test_a_bare_cable_is_read_and_a_rating_is_not_a_cable() -> None:
    """BUG-072: 25.26.100 writes "3X1.5" and "N2XY" as two spans along the line; "3×80A" is a breaker."""
    assert keys("3×1.5") == {"cable_cores": [3], "cable_cross_section_mm2": [1.5], "cable_raw": ["3×1.5"]}
    assert keys("5×6")["cable_cores"] == [5] and keys("5×2.5—ø20")["cable_cores"] == [5]
    assert "cable_cores" not in keys("3×80A") and "cable_cores" not in keys("3×16")


def test_the_cable_along_its_outgoing_line_is_the_breakers() -> None:
    """BUG-072: the cable is written halfway down the line to the outlet, far from the breaker. The walk down its
    line finds it (05 §5.5.1's poles from the cable cores). A cable past the next breaker is that breaker's."""
    breaker = det(1, (95, 100, 105, 140), cls="mcb")
    outlet = det(2, (90, 500, 110, 520), family="terminal", cls="terminal")
    feeder = det(3, (295, 100, 305, 140), cls="mcb")
    sub = det(4, (295, 250, 305, 290), cls="mcb")
    w = _wires([(100, 140), (100, 320), (100, 500)], [(300, 140), (300, 250)], [(300, 290), (300, 500)])
    spans = [
        span(1, "3×1.5", (88, 300, 97, 360), rotation=90),
        span(2, "N2XY", (88, 240, 97, 280), rotation=90),
        span(3, "5×6", (288, 380, 297, 420), rotation=90),
    ]
    work = s4_association.PageWork(detections=[breaker, outlet, feeder, sub], wires=w, texts=assign.texts(spans))
    for d in [*work.detections[::2], sub]:
        work.built.append(_built(int(d.det_id[-4:]), values={"current_a": 10}))
        work.built[-1].instance.det_id = d.det_id
        work.built[-1].circuit_context = CircuitContext()
    s4_association.chains([work])
    by_det = {b.instance.det_id: b for b in work.built}
    assert by_det[breaker.det_id].circuit_context.cable.cores == 3
    assert by_det[breaker.det_id].circuit_context.cable.raw == "3×1.5"
    assert by_det[feeder.det_id].circuit_context.cable is None  # the 5×6 is below the next breaker: its
    assert by_det[sub.det_id].circuit_context.cable.cores == 5


def test_a_circle_drawn_as_two_arcs_is_not_a_junction() -> None:
    """BUG-072: 25.26.100's breaker ends are circles of two arcs between the same two nodes."""
    w = circuits.Wires.build(
        [(100, 140), (100, 150), (100, 400), (60, 400), (140, 400)],
        [(0, 1, [(104, 145)]), (0, 1, [(96, 145)]), (1, 2, []), (2, 3, []), (2, 4, [])],
    )
    assert w.degree(1) == 2 and w.degree(2) == 3
    ticked = circuits.Wires.build([(0, 0), (0, 10), (0, 100), (2, 12)], [(0, 1, []), (1, 2, []), (1, 3, [])])
    assert ticked.degree(1) == 2  # a 3 pt dead end on the line is a tick, not a branch


def test_a_copy_overlapping_the_breaker_is_not_the_next_breaker() -> None:
    """25.26.100's eval run: a breaker found twice, the second box inside the first's lower part. The cable below is
    the breaker's: the walk goes through its own copy."""
    breaker = det(1, (95, 100, 105, 140))
    copy = det(2, (99, 110, 105, 145))
    w = _wires([(100, 140), (100, 145), (100, 320), (100, 500)])
    cable = assign.texts([span(1, "3×1.5", (88, 300, 97, 360), rotation=90)])
    found = circuits.cable_below(w, breaker, [breaker, copy], cable)
    assert found is not None and found.span.text == "3×1.5"


def test_the_walk_steps_over_a_wire_drawn_to_an_arcs_middle() -> None:
    """BUG-072: on 25.26.100 the outgoing wire starts half a point from the end circle's arc, at no node of it."""
    breaker = det(1, (95, 100, 105, 140))
    outlet = det(2, (90, 400, 110, 420), family="terminal", cls="terminal")
    w = circuits.Wires.build(
        [(100, 140), (96, 145), (100.5, 150.0), (100.5, 400)],
        [(0, 1, [(100, 150)]), (0, 1, []), (2, 3, [])],  # the circle: two arcs 0–1; the wire from (100.5, 150)
    )
    below, walk = circuits.downstream(w, breaker, [breaker, outlet])
    assert [d.det_id for d in below] == [outlet.det_id] and max(q[1] for _, q in walk.segments) == 400


def test_the_wire_graph_reads_back_from_stage_2s_file() -> None:
    import gzip

    body = {"nodes": [[0, 0], [0, 10]], "edges": [{"a": 0, "b": 1, "pts": []}], "block_links": []}
    w = circuits.Wires.from_json(gzip.compress(json.dumps(body).encode()))
    assert w.nodes_in((-1, -1, 1, 1)) == [0]


# ---------- the tile agent's check (04 §5.5) ----------


def _job(own: list[Detection], texts: list[TextSpan], context: list[Detection] | None = None) -> agent.TileJob:
    tile = Tile(
        tile_id="tl_001_r0c0", row=0, col=0, bbox_pt=(0, 0, 400, 400), bbox_px=(0, 0, 1000, 1000), image_uri="x"
    )
    t = assign.texts(texts)
    reads = {d.det_id: assign.Read() for d in own}
    return agent.TileJob(tile, own, context or [], t, reads, (0, 0), 2.5)


def _answer(*instances: dict[str, Any], **rest: Any) -> TileAnswer:
    return TileAnswer.model_validate({"instances": list(instances), **rest})


def _attr(
    name: str, value: Any, evidence: str | None = "text", spans: list[str] | None = None, **kw: Any
) -> dict[str, Any]:
    return {"name": name, "value": value, "evidence": evidence, "span_ids": spans or [], **kw}


BREAKER = det(1, (100, 100, 110, 140))
C20 = span(1, "C20", (112, 110, 125, 116))


def test_an_answer_that_misses_or_repeats_a_symbol_is_refused() -> None:
    job = _job([BREAKER, det(2, (200, 100, 210, 140))], [C20])
    with pytest.raises(agent.Refused, match="no answer for d2"):
        agent.check(_answer({"det": "d1"}), job, SCH, FAMILIES)
    with pytest.raises(agent.Refused, match="twice"):
        agent.check(_answer({"det": "d1"}, {"det": "d1"}, {"det": "d2"}), job, SCH, FAMILIES)
    with pytest.raises(agent.Refused, match="not symbols you answer for"):
        agent.check(_answer({"det": "d1"}, {"det": "d2"}, {"det": "c1"}), job, SCH, FAMILIES)


def test_a_value_not_written_in_its_span_is_refused() -> None:
    """04 §5.5's own example: current_a=16 citing "C20"."""
    job = _job([BREAKER], [C20])
    c = agent.check(_answer({"det": "d1", "attributes": [_attr("current_a", 16, spans=["s1"])]}), job, SCH, FAMILIES)
    assert c.values[BREAKER.det_id] == {} and c.citation_mismatches == 1 and c.values_cited == 1
    c = agent.check(
        _answer({"det": "d1", "attributes": [_attr("current_a", 20, spans=["s1"]), _attr("curve", "c", spans=["s1"])]}),
        job,
        SCH,
        FAMILIES,
    )
    assert {k: (v.value, v.source) for k, v in c.values[BREAKER.det_id].items()} == {
        "current_a": (20, "drawing"),
        "curve": ("C", "drawing"),
    }
    assert c.citation_mismatches == 0


def test_a_span_we_did_not_show_or_too_far_is_refused() -> None:
    far = span(2, "C16", (390, 390, 399, 399))
    job = _job([BREAKER], [C20, far])
    c = agent.check(_answer({"det": "d1", "attributes": [_attr("current_a", 16, spans=["s9"])]}), job, SCH, FAMILIES)
    assert c.values[BREAKER.det_id] == {}
    c = agent.check(_answer({"det": "d1", "attributes": [_attr("current_a", 16, spans=["s2"])]}), job, SCH, FAMILIES)
    assert c.values[BREAKER.det_id] == {} and "too far" in c.rejected[0]


def test_graphic_evidence_is_for_poles_only_with_a_note() -> None:
    job = _job([BREAKER], [C20])
    ok = _attr("poles", 3, "graphic", graphic_note="three strokes", confidence=0.95)
    no_note = _attr("poles", 3, "graphic")
    current = _attr("current_a", 20, "graphic", graphic_note="looks like 20")
    c = agent.check(_answer({"det": "d1", "attributes": [ok]}), job, SCH, FAMILIES)
    v = c.values[BREAKER.det_id]["poles"]
    assert (v.value, v.source, v.confidence) == (3, "graphic", DEFAULT.graphic_max)  # 6.4: at most 0.85
    for bad in (no_note, current):
        assert agent.check(_answer({"det": "d1", "attributes": [bad]}), job, SCH, FAMILIES).values[BREAKER.det_id] == {}


def test_a_multiplicity_needs_its_mark() -> None:
    mark = span(2, "(x6)", (112, 120, 124, 126))
    job = _job([BREAKER], [C20, mark])
    ok = agent.check(_answer({"det": "d1", "multiplicity": {"count": 6, "span_ids": ["s2"]}}), job, SCH, FAMILIES)
    assert ok.multiplicity[BREAKER.det_id] == (6, ["ts_001_0002"])
    bad = agent.check(_answer({"det": "d1", "multiplicity": {"count": 4, "span_ids": ["s2"]}}), job, SCH, FAMILIES)
    assert bad.multiplicity[BREAKER.det_id] == (1, []) and bad.citation_mismatches == 1


def test_a_span_given_to_two_symbols_stays_with_the_nearest() -> None:
    other = det(2, (140, 100, 150, 140))
    job = _job([BREAKER, other], [C20])
    both = _answer(
        {"det": "d1", "attributes": [_attr("current_a", 20, spans=["s1"])]},
        {"det": "d2", "attributes": [_attr("current_a", 20, spans=["s1"])]},
    )
    c = agent.check(both, job, SCH, FAMILIES)
    assert "current_a" in c.values[BREAKER.det_id] and c.values[other.det_id] == {}


def test_a_shared_label_may_reach_further_and_marks_its_source() -> None:
    row = [det(i, (40 * i, 300, 40 * i + 10, 340)) for i in range(1, 5)]
    label = span(1, "C10", (95, 150, 110, 156))  # far above the row
    job = _job(row, [label])
    shared = {"span_ids": ["s1"], "applies_to": ["d1", "d2", "d3", "d4"], "reason": "row"}
    answers = [
        {"det": f"d{i}", "attributes": [_attr("current_a", 10, spans=["s1"])], "uses_shared_label": True}
        for i in range(1, 5)
    ]
    c = agent.check(_answer(*answers, shared_labels=[shared]), job, SCH, FAMILIES)
    assert len(c.shared_labels) == 1
    assert all(c.values[d.det_id]["current_a"].source == "shared_label" for d in row)


def test_missed_symbols_brand_and_texts() -> None:
    job = _job([BREAKER], [C20, span(2, "ABB", (112, 120, 124, 126))])
    c = agent.check(
        _answer(
            {"det": "d1", "brand_hint": "ABB", "explicit_texts": ["s1", "s2", "s9"]},
            possible_missed=[
                {"bbox_tile_px": [610, 300, 560, 220], "family_guess": "circuit_breaker", "span_ids": ["s1"]},
                {"bbox_tile_px": [1, 1, 2, 2], "family_guess": "spaceship"},
            ],
        ),
        job,
        SCH,
        FAMILIES,
    )
    assert c.brand_hint == {BREAKER.det_id: "ABB"}
    assert c.explicit_texts[BREAKER.det_id] == ["C20", "ABB"]
    assert c.missed == [
        {"bbox": (224.0, 88.0, 244.0, 120.0), "family": "circuit_breaker", "span_ids": ["ts_001_0001"], "reason": ""}
    ]
    unwritten = agent.check(_answer({"det": "d1", "brand_hint": "Hager"}), job, SCH, FAMILIES)
    assert unwritten.brand_hint == {}


def test_the_agent_sees_numbered_frames_and_a_proposal() -> None:
    job = _job([BREAKER], [C20], context=[det(9, (300, 300, 310, 340), family="busbar", cls="busbar", billable=False)])
    parts = agent.prompt_parts(job, SCH)
    assert parts["own"].startswith("- d1: circuit_breaker / mcb, box [250, 250, 275, 350], read: current_a, poles")
    assert parts["context"].startswith("- c1: busbar / busbar")
    assert parts["spans"] == '- s1: "C20" [280, 275, 312, 290]'
    assert parts["proposal"] == "- d1: no text"
    drawn = agent.draw(Image.new("RGB", (1000, 1000), "white"), job)
    assert drawn.getpixel((248, 300)) == agent.OWN and drawn.getpixel((748, 800)) == agent.CONTEXT
    assert agent.image_key("sha:0:300", job) == agent.image_key("sha:0:300", job)


def test_refused_twice_then_the_fallback_model_then_code_alone() -> None:
    """5.5: ask again with the reason; after two refusals the fallback model; then fallback_geometric."""
    job = _job([BREAKER], [C20])
    calls: list[tuple[str, bool]] = []
    answers = [_answer(), _answer(), _answer({"det": "d1"})]

    def ask(j: Any, image: Any, parts: Any, correction: str, fallback: bool) -> TileAnswer:
        calls.append((correction, fallback))
        return answers[len(calls) - 1]

    result = agent.run_tile(job, Image.new("RGB", (1000, 1000), "white"), ask, SCH, FAMILIES)
    assert result.checked is not None and result.calls == 3
    assert calls == [("", False), ("no answer for d1", False), ("no answer for d1", True)]

    def broken(*_: Any) -> TileAnswer:
        raise LLMError("down")

    assert agent.run_tile(job, Image.new("RGB", (1000, 1000), "white"), broken, SCH, FAMILIES).checked is None

    def refused(*_: Any) -> TileAnswer:
        raise LLMAccountError("credit balance is too low")

    with pytest.raises(LLMAccountError):  # BUG-061: the stage fails; no tile falls back to code alone
        agent.run_tile(job, Image.new("RGB", (1000, 1000), "white"), refused, SCH, FAMILIES)


def test_the_agents_values_win_and_text_poles_beat_drawn_ones() -> None:
    d = BREAKER
    code = assign.Read(
        values={"poles": Value(3, "drawing", ["ts_1"], 1, 1, 1), "current_a": Value(16, "drawing", ["ts_1"], 1, 1, 1)}
    )
    from_agent = {"poles": Value(1, "graphic", [], 0.85, 1, 1)}
    values, conflicts = s4_association._final_values(d, code, from_agent, set(), True)
    assert values["poles"].value == 3 and conflicts == ["poles"]
    assert values["current_a"].value == 16  # the agent gave none: code's stays
    weak = assign.Read(values={"current_a": Value(16, "drawing", ["ts_1"], 1, 0.6, 1)})
    values, _ = s4_association._final_values(d, weak, {}, {"current_a"}, True)
    assert "current_a" not in values  # the agent says it's not there, and code wasn't sure
    values, _ = s4_association._final_values(d, weak, None, set(), False)
    assert values["current_a"].value == 16  # no agent: code alone


# ---------- the merge (04 §5.8) ----------


def _built(
    n: int,
    family: str = "circuit_breaker",
    tag: str | None = None,
    role: str = "device",
    values: dict[str, Any] | None = None,
    page: int = 1,
    panel: str = "pnl_01",
    mult: int = 1,
    brand: str | None = None,
    cls: str | None = None,
    scope: str = "in_panel",
) -> Built:
    attrs = {
        name: AttributeValue(
            value=(values or {}).get(name),
            source="drawing" if (values or {}).get(name) is not None else None,
            confidence=0.95 if (values or {}).get(name) is not None else None,
            span_ids=[],
        )
        for name in SCH.names(family)
    }
    i = Instance(
        instance_id=f"ins_{page:03d}_{n:04d}",
        det_id=f"det_{page:03d}_{n:04d}",
        page_id=f"pg_{page:03d}",
        panel_id=panel,
        bbox=(0, 0, 10, 10),
        family=family,
        symbol_class=cls or {"circuit_breaker": "mcb"}.get(family, family),
        attributes=attrs,
        multiplicity=mult,
        brand_hint=brand,
        method="geometric",
        status="accepted",
        confidence=0.9,
    )
    return Built(i, tag, role, scope, order=(page, float(n), 0.0))


def test_nevis_1_by_tag() -> None:
    """04 §5.8: FP1 on pages 7 and 8 → one device; C1's power contacts and coil → one contactor; F1, F2 and F12
    the same → one component of 3."""
    f16 = {"current_a": 16, "poles": 3}
    built = [
        _built(1, tag="FP1", values={"current_a": 6, "poles": 1}, page=1),
        _built(2, tag="FP1", values={"current_a": 6, "poles": 1}, page=2),
        _built(3, "contactor", tag="C1", role="power_contact", page=1),
        _built(4, "contactor", tag="C1", role="coil", page=2),
        _built(5, tag="F1", values=f16),
        _built(6, tag="F2", values=f16),
        _built(7, tag="F12", values=f16, page=2),
    ]
    comps, owner, _ = components("drw_01X", built, SCH)
    by_tags = {tuple(c.designators): c for c in comps}
    assert by_tags[("FP1",)].quantity == 1 and len(by_tags[("FP1",)].instance_ids) == 2
    assert by_tags[("C1",)].quantity == 1 and by_tags[("C1",)].family == "contactor"
    assert by_tags[("F1", "F2", "F12")].quantity == 3
    assert by_tags[("F1", "F2", "F12")].attributes["current_a"].value == 16
    assert len(owner) == 7 and all(c.component_id.startswith("cmp_01X_") for c in comps)


def test_a_preparation_drawn_under_the_same_tag_on_the_same_page_is_its_own_device() -> None:
    """BUG-036: 26/993's page 5 tags the remote emergency button (prepare only) and the door's button EMS. The door's
    button stays in the panel and the remote one keeps its scope; on another page, a scope follows the device."""
    built = [
        _built(8, "push_button", tag="EMS", page=5, cls="emergency_button", scope="prepare_only"),
        _built(9, "push_button", tag="EMS", page=5, cls="emergency_button"),
    ]
    comps, owner, _ = components("drw_01X", built, SCH)
    by_scope = {c.supply_scope: c for c in comps}
    assert set(by_scope) == {"in_panel", "prepare_only"}
    assert by_scope["in_panel"].designators == ["EMS"] and by_scope["in_panel"].quantity == 1
    assert by_scope["in_panel"].instance_ids == ["ins_005_0009"]
    assert by_scope["prepare_only"].instance_ids == ["ins_005_0008"] and len(owner) == 2
    elsewhere = [
        _built(1, "changeover_switch", tag="Q0", page=3, scope="prepare_only"),
        _built(2, "changeover_switch", tag="Q0", page=4),
        _built(3, "contactor", tag="C1", role="coil", page=4, scope="prepare_only"),
        _built(4, "contactor", tag="C1", page=4),
    ]
    comps, _, _ = components("drw_01X", elsewhere, SCH)
    assert sorted((c.designators[0], len(c.instance_ids)) for c in comps) == [("C1", 2), ("Q0", 2)]


def test_a_list_of_tags_is_one_device_per_tag() -> None:
    """BUG-031: 26-993 draws its three current transformers once, tagged "MS1/MS2/MS3" (03 §3.7 item 5)."""
    built = [
        _built(1, "current_transformer", tag="MS1/MS2/MS3"),
        _built(2, "current_transformer", tag="MS2", page=2),  # MS2 drawn again on its own
        _built(3, "aux_contact", tag="Q1/Q2", role="aux_contact"),
    ]
    comps, owner, _ = components("drw_01X", built, SCH)
    ct = next(c for c in comps if c.family == "current_transformer")
    assert ct.designators == ["MS1", "MS2", "MS3"] and ct.quantity == 3
    assert len(ct.instance_ids) == len(set(ct.instance_ids)) == 2
    aux = next(c for c in comps if c.family == "aux_contact")
    assert aux.parent_designators == ["Q1", "Q2"] and aux.designators == []
    assert len(owner) == 3


def test_a_device_drawing_gives_the_family_and_disagreeing_values_are_a_conflict() -> None:
    built = [
        _built(1, "current_transformer", tag="Q0"),  # stage 3 took a breaker for a transformer once
        _built(2, tag="Q0", values={"current_a": 80, "poles": 4}),
        _built(3, tag="Q0", values={"current_a": 63, "poles": 4}, page=2),
    ]
    built[0].instance.confidence = 0.4
    comps, _, _ = components("drw_01X", built, SCH)
    assert len(comps) == 1 and comps[0].family == "circuit_breaker"  # an unsure part of its drawing, beside it
    assert comps[0].attributes["current_a"].value == 80
    assert comps[0].attributes["current_a"].confidence == round(0.95 * DEFAULT.conflict_penalty, 4)
    # BUG-066: the same transformer drawn away from the breaker is a device of its own, to review
    built[0].instance.bbox = (400, 0, 410, 10)
    built[0].instance.issues = []
    comps, _, _ = components("drw_01X", built, SCH)
    ct = next(c for c in comps if c.family == "current_transformer")
    assert ct.designators == [] and ct.quantity == 1 and ct.status == "uncertain"
    assert [i.code for i in built[0].instance.issues] == ["tag_conflict"]


def test_a_tag_beside_symbols_of_two_families_names_the_nearest() -> None:
    """BUG-081: 25.26.100's "T1" under the clock's box was linked to the selector beside it and to C130,131's coil
    too, and the selector became T1's device. One written tag names the nearest symbol; one touching it (Q0's ring
    read as a current transformer, S24b decision 4) keeps it, and so do the nearest's own family (a coil and its
    contacts) and an accessory on it."""
    t1 = ("ts_001_0156", (3209.0, 669.0, 3220.0, 682.0))

    def at(b: Built, box: tuple[float, float, float, float], span: tuple[str, Bbox] | None = t1) -> Built:
        b.instance.bbox, b.designator_span = box, span
        return b

    clock = at(_built(1, "timer", tag="T1", role="coil"), (3168, 688, 3220, 710))
    contact = at(
        _built(2, "timer", tag="T1", role="relay_contact"), (3274, 534, 3293, 579), ("ts_001_0062", (0, 0, 1, 1))
    )
    selector = at(_built(3, "selector_switch", tag="T1"), (3253, 628, 3293, 675))
    coil = at(_built(4, "contactor", tag="T1", role="coil"), (3262, 689, 3320, 711))
    ring = at(_built(5, "current_transformer", tag="T1"), (3221, 690, 3232, 700))
    trip = at(_built(6, "shunt_trip", tag="T1"), (3330, 690, 3340, 700))
    built = [clock, contact, selector, coil, ring, trip]
    one_name_per_tag(built)
    assert [b.designator for b in built] == ["T1", "T1", None, None, "T1", "T1"]
    # a tag nearest a device drawing is the merge's to weigh (Q0's ring read as a CT joins Q0, S24b decision 4)
    q0 = ("ts_001_0001", (100.0, 100.0, 110.0, 107.0))
    breaker = at(_built(7, tag="Q0"), (112, 100, 130, 130), q0)
    far_ring = at(_built(8, "current_transformer", tag="Q0"), (112, 140, 130, 150), q0)
    one_name_per_tag([breaker, far_ring])
    assert (breaker.designator, far_ring.designator) == ("Q0", "Q0")
    comps, _, _ = components("drw_01X", [clock, contact, selector, coil], SCH)
    assert {(c.family, tuple(c.designators), c.quantity) for c in comps} == {
        ("timer", ("T1",), 1),
        ("selector_switch", (), 1),
        ("contactor", (), 1),
    }


def test_a_breaker_takes_the_poles_read_on_its_alike_peers() -> None:
    """BUG-088, the user on 25.26.100's five 40A field breakers: "they're all the same". The tile agent read a pole
    mark on two of them; the three beside them, drawn alike and rated alike, join their component (as a breaker
    whose cable gives the read poles does, BUG-072). Each keeps its poles unread and says why it joined. An RCD's 4P
    beside them doesn't count, peers that disagree give nothing, and a breaker in another row stays apart."""

    def at(b: Built, x: float, y: float = 320.0, h: float = 36.0) -> Built:
        b.instance.bbox = (x, y, x + 47.0, y + h)
        return b

    read = {"current_a": 40, "poles": 3}
    row = [
        at(_built(1, values=read), 800),
        at(_built(2, values={"current_a": 40}), 1286),
        at(_built(3, values={"current_a": 40}), 1762, y=315, h=46),  # its box drawn taller, centred on the row
        at(_built(4, values=read), 2284),
        at(_built(5, values={"current_a": 40}), 2555),
        at(_built(6, "rcd", values={"current_a": 40, "poles": 4, "residual_ma": 30}), 2650),
        at(_built(7, values={"current_a": 40}), 2555, y=1128),  # another row
    ]
    comps, _, _ = components("drw_01X", row, SCH)
    forty = sorted(
        ((c.quantity, c.attributes["poles"].value) for c in comps if c.family == "circuit_breaker"), reverse=True
    )
    assert forty == [(5, 3), (1, None)]
    joined = [b for b in row[1:5] if b.instance.attributes["poles"].value is None]
    assert len(joined) == 3 and all(i.code == "poles_from_peers" for b in joined for i in b.instance.issues)
    # peers that disagree give nothing
    split = [
        at(_built(11, values=read), 800),
        at(_built(12, values={"current_a": 40}), 900),
        at(_built(13, values={"current_a": 40, "poles": 1}), 1000),
    ]
    comps, _, _ = components("drw_01X", split, SCH)
    assert sorted((c.quantity, c.attributes["poles"].value or 0) for c in comps) == [(1, 0), (1, 1), (1, 3)]


def test_the_majority_pole_mark_of_alike_peers_wins() -> None:
    """BUG-088 (live run `drw_01M6N7AYFVQG8MDSXYKZXB8KPM`): the tile agent read 3P on two of the five 40A field
    breakers (0.6) and 4P on one (0.5), and none on two. The user: the two unread take the majority's 3P; the one that
    disagreed keeps its 4P and its own line, flagged (outvoting it made 6199-2-50's real 1P breaker a 3P one). A tie
    gives nothing, a pole count written in text is never overruled, and the 4P RCDs beside them never vote."""

    def at(b: Built, x: float, poles: int | None = None, conf: float = 0.6, source: str = "graphic") -> Built:
        b.instance.bbox = (x, 319.0, x + 47.0, 355.0)
        if poles is not None:
            b.instance.attributes["poles"] = AttributeValue(value=poles, source=source, confidence=conf, span_ids=[])  # type: ignore[arg-type]
        return b

    forty = {"current_a": 40}
    row = [
        at(_built(1, values=forty), 800, 3),
        at(_built(2, values=forty), 1286, 3),
        at(_built(3, values=forty), 1762, 4, conf=0.5),
        at(_built(4, values=forty), 2283),
        at(_built(5, values=forty), 2555),
        at(_built(6, "rcd", values={"current_a": 40, "poles": 4, "residual_ma": 30}), 2650),
        at(_built(7, "rcd", values={"current_a": 40, "poles": 4, "residual_ma": 30}), 2750),
    ]
    comps, _, _ = components("drw_01X", row, SCH)
    breakers = [c for c in comps if c.family == "circuit_breaker"]
    assert sorted((c.quantity, c.attributes["poles"].value) for c in breakers) == [(1, 4), (4, 3)]
    assert row[2].instance.attributes["poles"].value == 4  # kept as read, its own line, flagged
    assert [i.code for i in row[2].instance.issues] == ["poles_peer_conflict"]
    assert all(i.code == "poles_from_peers" for b in row[3:5] for i in b.instance.issues)

    def outcome(marks: list[tuple[int | None, str]]) -> list[tuple[int, int]]:
        built = [at(_built(20 + n, values=forty), 800 + 100 * n, p, source=src) for n, (p, src) in enumerate(marks)]
        comps, _, _ = components("drw_01X", built, SCH)
        return sorted((c.quantity, c.attributes["poles"].value or 0) for c in comps)

    assert outcome([(3, "graphic"), (3, "graphic"), (4, "drawing")]) == [(1, 4), (2, 3)]  # written in text
    assert outcome([(3, "graphic"), (4, "graphic"), (None, "graphic")]) == [(1, 0), (1, 3), (1, 4)]  # a tie


def test_a_mark_both_its_cable_and_the_majority_contradict_is_corrected() -> None:
    """S24b decision 12 (live run `drw_01M6NFV83V6MQMWTVVMSFW6ZMD`, the user: "Yes, correct it"): main panel's two
    10A breakers "X2" read 3P (graphic 0.6) on a 3×1.5 cable, in a row of thirteen read 1P. Their cable and their alike
    peers' majority agree on 1P, so they join the row's component: 15 × 1P. The instance keeps what was read and says
    why it joined (`poles_corrected`); stage 5 makes the value `inferred`. A disagreeing mark with no cable keeps its
    own flagged line (decision 11, 6199-2-50's shed), and a sure mark or a count written in text is never changed."""

    def at(
        b: Built, x: float, poles: int | None, cores: int | None = 3, conf: float = 0.5, src: str = "graphic"
    ) -> Built:
        b.instance.bbox = (x, 464.3, x + 44.4, 502.3)
        b.instance.attributes["poles"] = AttributeValue(
            value=poles,
            source=src if poles is not None else None,  # type: ignore[arg-type]
            confidence=conf if poles is not None else None,
            span_ids=[],
        )
        if cores is not None:
            b.circuit_context = CircuitContext(cable=Cable(cores=cores, cross_section_mm2=1.5, raw="3×1.5"))
        return b

    ten = {"current_a": 10}

    def row(mark: tuple[int, float, str], cores: int | None = 3) -> list[Built]:
        peers = [at(_built(n, values=ten), 650 + 100 * n, 1) for n in range(1, 4)]
        x2 = at(_built(9, values=ten, mult=2), 1877.7, mark[0], cores, conf=mark[1], src=mark[2])
        x2.instance.bbox = (1877.7, 454.9, 1922.2, 509.1)  # drawn taller, centred on the row
        return [*peers, x2]

    built = row((3, 0.6, "graphic"))
    comps, _, _ = components("drw_01X", built, SCH)
    assert [(c.quantity, c.attributes["poles"].value) for c in comps] == [(5, 1)]
    assert comps[0].attributes["poles"].source == "graphic"  # the row's marks; stage 5 says `inferred`
    x2 = built[-1].instance
    assert x2.attributes["poles"].value == 3  # kept as read (00 §5.3)
    assert [i.code for i in x2.issues] == ["poles_corrected"]
    assert "3×1.5" in x2.issues[0].message and "1P" in x2.issues[0].message

    def outcome(mark: tuple[int, float, str], cores: int | None = 3) -> list[tuple[int, int]]:
        comps, _, _ = components("drw_01X", row(mark, cores), SCH)
        return sorted((c.quantity, c.attributes["poles"].value) for c in comps)

    assert outcome((3, 0.6, "graphic"), cores=None) == [(2, 3), (3, 1)]  # no cable: its own flagged line
    assert outcome((3, 0.6, "graphic"), cores=5) == [(2, 3), (3, 1)]  # its cable backs the mark
    assert outcome((3, 0.9, "graphic")) == [(2, 3), (3, 1)]  # a sure mark
    assert outcome((3, 0.6, "drawing")) == [(2, 3), (3, 1)]  # written in text


def test_one_tag_merges_one_family_never_a_terminal_over_breakers() -> None:
    """BUG-066 (25.26.100): "X2" read as the tag of terminals, 16A breakers and an RCD made one terminal × 76. A tag
    merges the drawings of one device; a symbol of another family under it stays itself, untagged, for review."""
    built = [
        _built(1, "terminal", tag="X2"),
        _built(2, "terminal", tag="X2"),
        _built(3, tag="X2", values={"current_a": 16, "poles": 1}),
        _built(4, tag="X2", values={"current_a": 16, "poles": 1}),
        _built(5, tag="X2", values={"current_a": 16, "poles": 1}),
        _built(6, "rcd", tag="X2", values={"current_a": 40, "poles": 4}),
        _built(7, "contactor", tag="X2", role="coil"),  # a coil or contacts are a device's drawings: no conflict
        _built(8, "shunt_trip", tag="X2"),  # an accessory under a device's tag sits on that device
    ]
    built[5].instance.confidence = 0.42
    for n, b in enumerate(built):  # each drawn in its own place, 60 pt apart
        b.instance.bbox = (60.0 * n, 0, 60.0 * n + 10, 10)
    comps, owner, _ = components("drw_01X", built, SCH)
    by_family = {c.family: c for c in comps}
    assert by_family["terminal"].designators == ["X2"] and by_family["terminal"].quantity == 1
    assert len(by_family["terminal"].instance_ids) == 3  # the two terminals and the coil
    assert by_family["circuit_breaker"].quantity == 3 and by_family["circuit_breaker"].designators == []
    assert by_family["rcd"].quantity == 1 and by_family["rcd"].attributes["current_a"].value == 40
    assert by_family["shunt_trip"].parent_designators == ["X2"] and by_family["shunt_trip"].designators == []
    assert all(c.status == "uncertain" for c in (by_family["circuit_breaker"], by_family["rcd"]))
    assert len(owner) == 8


def test_what_never_merges() -> None:
    built = [
        _built(1, values={"current_a": 16, "poles": 1}),
        _built(2, values={"current_a": 16, "poles": 1}, panel="pnl_02"),  # another panel
        _built(3, values={"current_a": 16, "poles": None}),  # a null against a known value, not drawn beside it
        _built(4, values={"current_a": 16, "poles": 1}, scope="other_location"),
        _built(5, values={"current_a": 16, "poles": 1}, mult=6),
    ]
    built[2].instance.bbox = (0, 100, 10, 110)  # another row: BUG-088's alike peers join a null to a known value
    comps, _, _ = components("drw_01X", built, SCH)
    assert len(comps) == 4
    first = next(
        c for c in comps if c.panel_id == "pnl_01" and c.supply_scope == "in_panel" and c.attributes["poles"].value == 1
    )
    assert first.quantity == 7  # 1 + 6: untagged, by multiplicity


def test_an_aux_contact_is_an_accessory_and_an_untagged_contact_joins_its_device() -> None:
    built = [
        _built(1, "aux_contact", tag="F1", role="aux_contact"),
        _built(2, "aux_contact", tag="F2", role="aux_contact"),
        _built(3, "relay", tag="R1", role="coil"),
        _built(4, "relay", role="relay_contact"),  # R1's contact with no tag
    ]
    comps, owner, _ = components("drw_01X", built, SCH)
    aux = next(c for c in comps if c.family == "aux_contact")
    assert aux.quantity == 2 and aux.parent_designators == ["F1", "F2"] and aux.designators == []
    relay = next(c for c in comps if c.family == "relay")
    assert relay.quantity == 1 and len(relay.instance_ids) == 2
    assert len(owner) == 4


def test_breakers_with_unknown_poles_and_different_cables_do_not_merge() -> None:
    """BUG-072: a 16A breaker on 3×2.5 and one on 5×2.5 are 1P and 3P by their cables (05 §5.5.1); with the poles
    not written they stay two components, so each takes its own cable's poles."""
    built = [_built(n, values={"current_a": 16}) for n in (1, 2, 3)]
    for b, cores in zip(built, (3, 3, 5), strict=True):
        b.circuit_context = CircuitContext(cable=Cable(cores=cores))
    known = _built(4, values={"current_a": 16, "poles": 1})
    known.circuit_context = CircuitContext(cable=Cable(cores=5))
    comps, _, _ = components("drw_01X", [*built, known], SCH)
    by_cores = sorted((c.quantity, c.circuit_context.cable.cores) for c in comps if c.attributes["poles"].value is None)
    assert by_cores == [(1, 5), (2, 3)]


def test_breakers_whose_cable_gives_the_poles_the_others_read_are_one_component() -> None:
    """BUG-072 (25.26.100's live run): the agent read the pole mark on 10 of the 13 10A lighting breakers. The other
    three, on the same 3×1.5 cables, are the same product by 05 §5.5.1 (3 cores: 1P): one line, not two. Their own
    poles stay unread (stage 5 fills in, 00 §5.3); a 5-core one or a 2P one stays apart."""
    read = [_built(n, values={"current_a": 10, "poles": 1}) for n in (1, 2)]
    unread = [_built(n, values={"current_a": 10}) for n in (3, 4)]
    other = _built(5, values={"current_a": 10})
    two = _built(6, values={"current_a": 10, "poles": 2})
    for b in [*read, *unread, two]:
        b.circuit_context = CircuitContext(cable=Cable(cores=3))
    other.circuit_context = CircuitContext(cable=Cable(cores=5))
    comps, _, _ = components("drw_01X", [*read, *unread, other, two], SCH)
    by_poles = sorted((c.attributes["poles"].value or 0, c.quantity) for c in comps)
    assert by_poles == [(0, 1), (1, 4), (2, 1)]
    assert all(b.instance.attributes["poles"].value is None for b in unread)


def test_terminals_tagged_like_a_selector_are_selectors() -> None:
    """BUG-051: MINHAROT-1's SW2–SW5 were read as their two contact points, terminals, while SW1 was read as a
    selector. Untagged terminals and a strip's X1 stay terminals; a tie between two families names none."""
    built = [
        _built(1, "selector_switch", tag="SW1", page=3),
        _built(2, "terminal", tag="SW2", page=3),
        _built(3, "terminal", tag="SW2", page=3),
        _built(4, "terminal", tag="SW3", page=2),
        _built(5, "terminal", tag="SW3", page=2),
        _built(6, "terminal", page=2),
        _built(7, "terminal", page=2),
        _built(8, "terminal", tag="X1"),
        _built(9, "indicator_lamp", tag="L1"),  # NURSERY-1: lamps L1–L3, and terminals L4, N4 for circuit 4
        _built(10, "terminal", tag="L4"),
        _built(11, "terminal", tag="N4"),
    ]
    comps, owner, issues = components("drw_01X", built, SCH)
    selectors = next(c for c in comps if c.family == "selector_switch")
    assert selectors.designators == ["SW1", "SW2", "SW3"] and selectors.quantity == 3
    assert selectors.symbol_class == "selector_switch" and selectors.confidence <= DEFAULT.family_by_tag_max
    assert selectors.status == "uncertain"
    terminals = next(c for c in comps if c.family == "terminal")
    assert terminals.designators == ["L4", "N4", "X1"] and terminals.quantity == 5
    assert [(i.code, i.severity) for i in issues] == [("family_by_tag", "warning")]
    assert "SW2, SW3" in issues[0].message and "SW1" in issues[0].message
    assert len(owner) == 11

    tie = [_built(1, "relay", tag="K1"), _built(2, "contactor", tag="K2"), _built(3, "terminal", tag="K3")]
    assert {c.family for c in components("drw_01X", tie, SCH)[0]} == {"relay", "contactor", "terminal"}


def _drawn_poles(b: Built, poles: int | None) -> Built:
    b.instance.attributes["poles"] = AttributeValue(
        value=poles, source="graphic" if poles else None, confidence=0.6 if poles else None, span_ids=[]
    )
    return b


def test_a_contactor_drawn_as_single_pole_contacts_has_a_pole_per_contact() -> None:
    """BUG-053: MINHAROT-1's C1 switches F2–F4, one single-pole contact on each circuit; only the third is tagged.
    C2 is drawn once, three-pole. Poles written as text are never recounted."""
    built = [
        _drawn_poles(_built(1, "contactor", role="power_contact"), None),
        _drawn_poles(_built(2, "contactor", role="power_contact"), 1),
        _drawn_poles(_built(3, "contactor", tag="C1", role="power_contact"), 1),
        _built(4, "contactor", tag="C1", role="coil", page=3),
        _drawn_poles(_built(9, "contactor", tag="C2", role="power_contact"), 3),
        _built(10, "contactor", tag="C2", role="coil", page=3),
    ]
    comps, _, _ = components("drw_01X", built, SCH)
    assert len(comps) == 1 and comps[0].designators == ["C1", "C2"] and comps[0].quantity == 2
    poles = comps[0].attributes["poles"]
    assert poles.value == 3 and poles.source == "graphic" and poles.confidence == 0.6

    written = [
        _built(1, "contactor", role="power_contact"),
        _built(2, "contactor", tag="C1", role="power_contact", values={"poles": 1}),
    ]
    assert components("drw_01X", written, SCH)[0][0].attributes["poles"].value == 1

    one = [_drawn_poles(_built(1, "contactor", tag="C1", role="power_contact"), 1)]
    assert components("drw_01X", one, SCH)[0][0].attributes["poles"].value == 1


def test_an_aux_contact_drawn_again_where_it_is_used_is_counted_once() -> None:
    """BUG-054: MINHAROT-1 draws five 21/22 contacts beside F2–F6 on page 5 (two read with a neighbour's tag, three
    with none) and three of them again on page 8, read with F2–F4. Page 8's join page 5's. When the devices' page
    has fewer contacts than are bound for it, each is counted where it is drawn."""
    breakers = [_built(n, tag=f"F{n}", values={"current_a": 10, "poles": 1}, page=5) for n in range(2, 7)]
    home = [
        _built(11, "aux_contact", tag="F2", role="aux_contact", page=5),
        _built(12, "aux_contact", tag="F3", role="aux_contact", page=5),
        *[_built(n, "aux_contact", role="aux_contact", page=5) for n in (13, 14, 15)],
    ]
    used = [_built(n, "aux_contact", tag=f"F{n - 19}", role="aux_contact", page=8) for n in (21, 22, 23)]
    comps, owner, _ = components("drw_01X", breakers + home + used, SCH)
    aux = [c for c in comps if c.family == "aux_contact"]
    assert sum(c.quantity for c in aux) == 5
    assert sorted({t for c in aux for t in c.parent_designators}) == ["F2", "F3", "F4"]
    assert sum(len(c.instance_ids) for c in aux) == 8 and len(owner) == 13

    comps, _, _ = components("drw_01X", breakers + home[:2] + used, SCH)
    assert sum(c.quantity for c in comps if c.family == "aux_contact") == 5  # 2 on page 5, 3 on page 8


def test_a_shunt_trip_drawn_on_its_breaker_and_as_its_coil_is_one() -> None:
    """BUG-111: 26-993 draws QG1's shunt trip on page 3 ("T.C" "G1", one tag since stage 3's item 7) and its coil
    TC-G1 beside TC-G2 on page 5: two shunt trips, not three."""
    built = [
        _built(12, "shunt_trip", tag="TC-G1", page=3),
        _built(3, "shunt_trip", tag="TC-G1", page=5),
        _built(4, "shunt_trip", tag="TC-G2", page=5),
    ]
    comps, owner, _ = components("drw_01X", built, SCH)
    assert [(c.quantity, c.designators) for c in comps] == [(2, ["TC-G1", "TC-G2"])]
    assert len(owner) == 3


def test_a_sure_drawing_of_a_tag_lifts_an_unsure_one_of_its_family() -> None:
    """BUG-112, 04 §6.4: 26-993 draws TC-G1 and TC-G2 unsurely on their breakers on page 3 (0.56) and surely as their
    coils on page 5 (0.9). The component is as sure as its sure drawings; each instance keeps its own confidence."""
    built = [
        _built(12, "shunt_trip", tag="TC-G1", page=3),
        _built(13, "shunt_trip", tag="TC-G2", page=3),
        _built(3, "shunt_trip", tag="TC-G1", page=5),
        _built(4, "shunt_trip", tag="TC-G2", page=5),
    ]
    built[0].instance.confidence = built[1].instance.confidence = 0.56
    comps, _, _ = components("drw_01X", built, SCH)
    assert [(c.quantity, c.confidence, c.status) for c in comps] == [(2, 0.9, "accepted")]
    assert [b.instance.confidence for b in built] == [0.56, 0.56, 0.9, 0.9]


def test_an_unsure_drawing_is_not_lifted_when_it_says_more_or_differs() -> None:
    """BUG-112: an unsure drawing that alone carries a value, a value that conflicts, or a tag with no sure drawing
    of the family keeps the device at its lowest."""
    alone = [
        _built(1, tag="Q1", values={"current_a": 16}, page=3),
        _built(2, tag="Q1", values={"current_a": 16, "poles": 3}, page=5),
    ]
    alone[1].instance.confidence = 0.6
    comps, _, _ = components("drw_01X", alone, SCH)
    assert comps[0].confidence == 0.6  # the unsure drawing alone reads the poles
    differ = [
        _built(1, tag="Q1", values={"current_a": 16}, page=3),
        _built(2, tag="Q1", values={"current_a": 20}, page=5),
    ]
    differ[1].instance.confidence = 0.6
    comps, _, _ = components("drw_01X", differ, SCH)
    assert comps[0].confidence == round(0.6 * 0.8, 4)  # a conflict lifts nothing
    unsure = [_built(1, "shunt_trip", tag="TC1", page=3), _built(2, "shunt_trip", tag="TC1", page=5)]
    unsure[0].instance.confidence, unsure[1].instance.confidence = 0.8, 0.56
    comps, _, _ = components("drw_01X", unsure, SCH)
    assert comps[0].confidence == 0.56  # no sure drawing


def test_a_drawing_of_another_family_is_never_lifted() -> None:
    """BUG-112: a contactor's coil drawn unsure under the contactor's tag still counts; so does an untagged symbol of
    the same family, which is its own device."""
    built = [_built(1, "contactor", tag="C1", page=2), _built(2, "coil", tag="C1", role="coil", page=4)]
    built[1].instance.confidence = 0.6
    comps, _, _ = components("drw_01X", built, SCH)
    assert [c.confidence for c in comps if c.designators == ["C1"]] == [0.6]
    loose = [_built(1, "shunt_trip", tag="TC1", page=3), _built(2, "shunt_trip", page=5)]
    loose[1].instance.confidence = 0.56
    comps, _, _ = components("drw_01X", loose, SCH)
    assert min(c.confidence for c in comps) == 0.56


def test_a_shunt_trip_surer_than_its_breaker_still_sits_on_it() -> None:
    """BUG-109: 25/886 draws the XT5 breaker QE (0.73) on the single-line page and its shunt-trip coil under the same
    tag QE (0.9) in the control circuit. The breaker keeps its tag, and the shunt trip sits on it."""
    built = [
        _built(1, tag="QE", values={"current_a": 630, "poles": 3}, cls="mccb", page=2),
        _built(2, "shunt_trip", tag="QE", page=4),
        _built(3, "shunt_trip", tag="QE", role="coil", page=5),  # however it is drawn, never the breaker's own coil
    ]
    built[0].instance.confidence = 0.729
    comps, owner, _ = components("drw_01X", built, SCH)
    by_family = {c.family: c for c in comps}
    breaker, trips = by_family["circuit_breaker"], [c for c in comps if c.family == "shunt_trip"]
    assert breaker.designators == ["QE"] and breaker.quantity == 1
    assert not any(i.code == "tag_conflict" for b in built for i in b.instance.issues)
    assert trips and all(c.parent_designators == ["QE"] and c.designators == [] for c in trips)
    assert len(owner) == 3


def test_two_brands_for_one_component() -> None:
    built = [
        _built(1, values={"current_a": 16, "poles": 1}, brand="ABB"),
        _built(2, values={"current_a": 16, "poles": 1}, brand="Hager"),
    ]
    comps, _, issues = components("drw_01X", built, SCH)
    assert comps[0].brand_hint is None and [i.code for i in issues] == ["brand_conflict"]


def test_confidence_and_status() -> None:
    """6.4: the detection's confidence × the lowest required attribute found; ≥ 0.85 accepted."""
    values = {"current_a": Value(16, "drawing", [], 1.0, 1.0, 0.95), "poles": Value(3, "graphic", [], 0.85, 1, 1)}
    assert instance_confidence(0.9, values, SCH.required("circuit_breaker")) == round(0.9 * 0.85, 4)
    assert instance_confidence(0.9, {}, SCH.required("circuit_breaker")) == 0.9
    assert status(0.85) == "accepted" and status(0.8499) == "uncertain"


def test_missed_symbols_are_always_red() -> None:
    from konboro.pipeline.association.merge import missing_instance

    m = missing_instance(
        "ins_m001_0001",
        "pg_001",
        None,
        (0, 0, 1, 1),
        "circuit_breaker",
        {"current_a": Value(20, "drawing", ["ts_1"], 1, 1, 1)},
        "orphan_text",
    )
    assert m.confidence == DEFAULT.missing_max and m.status == "missing" and m.attributes["current_a"].value == 20
    assert s4_association._family_guess(assign.texts([span(1, "C20", (0, 0, 1, 1))])[0]) == "circuit_breaker"
    assert s4_association._family_guess(assign.texts([span(1, "30mA", (0, 0, 1, 1))])[0]) == "rcd"
    assert s4_association._family_guess(assign.texts([span(1, "5×2.5²-N2XY", (0, 0, 1, 1))])[0]) is None


# ---------- the run step's line (prototype line 764) ----------


def test_the_run_step_counts_devices_and_products() -> None:
    from konboro.services.drawings import Progress, stage_summary

    def p(components: tuple[int, int, bool] | None) -> Progress:
        return Progress(
            drawing=None, name="", files=[], runs=[], pages=[], panels=[], quote_id=None, components=components
        )  # type: ignore[arg-type]

    assert stage_summary(p((44, 13, True)), 4) == "איחוד לפי תגים: 44 מכשירים ב-13 מוצרים"
    assert stage_summary(p((1, 1, False)), 4) == "מכשיר אחד במוצר אחד"
    assert stage_summary(p(None), 4) is None


@pytest.mark.parametrize(
    ("text", "family", "expected"),
    [
        ("5×16A", "socket_outlet", {"poles": [3], "neutral": [True], "current_a": [16]}),  # 5 pins: 3P+N
        ("3×16A", "socket_outlet", {"poles": [1], "neutral": [True], "current_a": [16]}),
        ("CEE", "socket_outlet", {"socket_standard": ["CEE"]}),
        ("21/22", "aux_contact", {"contacts": ["21/22"]}),
        ("1-0-2", "selector_switch", {"positions": ["1-0-2"]}),
        ("ירוקה", "indicator_lamp", {"color": ["green"]}),
    ],
)
def test_what_the_first_recording_cited_that_the_grammar_could_not_read(
    text: str, family: str, expected: dict[str, list[Any]]
) -> None:
    """S13: values the tile agent cited, refused only because no pattern read them (grammar g2)."""
    assert keys(text, family) == expected


def test_one_value_written_over_several_spans_is_proven_by_them_together() -> None:
    """NEVIS-1: an aux contact's "21" and "22", a selector's "1", "0", "2", each its own span."""
    aux = det(1, (100, 100, 110, 140), family="aux_contact", cls="aux_contact")
    job = _job([aux], [span(1, "21", (112, 100, 118, 106)), span(2, "22", (112, 130, 118, 136))])
    c = agent.check(
        _answer({"det": "d1", "attributes": [_attr("contacts", "21/22", spans=["s1", "s2"])]}), job, SCH, FAMILIES
    )
    assert c.values[aux.det_id]["contacts"].value == "21/22" and c.citation_mismatches == 0
    sel = det(1, (100, 100, 110, 140), family="selector_switch", cls="selector_switch")
    digits = [span(i, t, (112 + 8 * i, 100, 118 + 8 * i, 106)) for i, t in enumerate(("1", "0", "2"), start=1)]
    c = agent.check(
        _answer({"det": "d1", "attributes": [_attr("positions", "1-0-2", spans=["s1", "s2", "s3"])]}),
        _job([sel], digits),
        SCH,
        FAMILIES,
    )
    assert c.values[sel.det_id]["positions"].value == "1-0-2"
    wrong = agent.check(
        _answer({"det": "d1", "attributes": [_attr("positions", "2-0-1", spans=["s1", "s2"])]}),
        _job([sel], digits),
        SCH,
        FAMILIES,
    )
    assert wrong.citation_mismatches == 1


# ---------- a lamp's colour from its fill (BUG-057) ----------


def _lamp(fill: tuple[int, int, int] | None, outline: tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    """A lamp as MINHAROT-1 draws it at 2 px per point: a circle with a cross, two quadrants filled, at (10, 10)."""
    from PIL import ImageDraw

    im = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(im)
    box = (20, 20, 60, 60)
    if fill is not None:
        draw.pieslice(box, 225, 315, fill=fill)
        draw.pieslice(box, 45, 135, fill=fill)
    draw.ellipse(box, outline=outline, width=2)
    draw.line((26, 26, 54, 54), fill=outline, width=2)
    draw.line((26, 54, 54, 26), fill=outline, width=2)
    return im


def test_a_lamps_colour_is_its_fill() -> None:
    from konboro.pipeline.association import colour

    lamp = (10.0, 10.0, 30.0, 30.0)
    assert colour.fill(_lamp((0, 200, 0)), lamp, 2.0) == "green"
    assert colour.fill(_lamp((230, 0, 0)), lamp, 2.0) == "red"
    assert colour.fill(_lamp((230, 0, 0), outline=(230, 0, 0)), lamp, 2.0) == "red"  # HT1: a red ring too
    assert colour.fill(_lamp(None), lamp, 2.0) is None  # drawn black, no fill
    assert colour.fill(_lamp(None, outline=(0, 160, 0)), lamp, 2.0) is None  # a green CAD layer, lines only
    assert colour.fill(_lamp((0, 200, 0)), (40.0, 40.0, 50.0, 50.0), 2.0) is None  # beside the lamp, not on it
    two = _lamp((0, 200, 0))
    two.paste(_lamp((230, 0, 0)).crop((20, 40, 60, 60)), (20, 40))
    assert colour.fill(two, lamp, 2.0) is None  # half green, half red: no one colour
