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
from konboro.contracts.merge import AttributeValue, Instance
from konboro.pipeline.association import agent, assign, circuits, grammar, quantity, schemas
from konboro.pipeline.association.assign import Value
from konboro.pipeline.association.config import DEFAULT
from konboro.pipeline.association.merge import Built, components, instance_confidence, status
from konboro.pipeline.detection import library
from konboro.pipeline.stages import s4_association
from konboro_llm import LLMError
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
        ("Type A", "rcd", {"rcd_type": ["A"]}),
        ("סוג A", "rcd", {"rcd_type": ["A"]}),
        ("(x4)", "circuit_breaker", {"multiplicity": [4]}),
        ("×4", "circuit_breaker", {"multiplicity": [4]}),
        ("4 יציאות", "circuit_breaker", {"multiplicity": [4]}),
        ("16+N", "circuit_breaker", {"current_a": [16], "poles": [1], "neutral": [True]}),
        ("S203M", "circuit_breaker", {"model_token": ["S203M"]}),
        ("INC=12.8A", "circuit_breaker", {"load_current_a": [12.8]}),
        ("Ib=10A", "circuit_breaker", {"load_current_a": [10]}),
        ("500A/630A", "circuit_breaker", {"current_a": [630], "setting_a": [500]}),
        ("4×63A/0,03A", "rcd", {"poles": [4], "current_a": [63], "residual_ma": [30]}),
        ("5/800A", "current_transformer", {"ratio_secondary_a": [5], "ratio_primary_a": [800]}),
        ("800/5A", "current_transformer", {"ratio_primary_a": [800], "ratio_secondary_a": [5]}),
        ("LSI", "circuit_breaker", {"trip_unit": ["LSI"]}),
        ("MCCB", "circuit_breaker", {"symbol_class": ["mccb"]}),
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


def test_a_device_drawing_gives_the_family_and_disagreeing_values_are_a_conflict() -> None:
    built = [
        _built(1, "current_transformer", tag="Q0"),  # stage 3 took a breaker for a transformer once
        _built(2, tag="Q0", values={"current_a": 80, "poles": 4}),
        _built(3, tag="Q0", values={"current_a": 63, "poles": 4}, page=2),
    ]
    built[0].instance.confidence = 0.4
    comps, _, _ = components("drw_01X", built, SCH)
    assert len(comps) == 1 and comps[0].family == "circuit_breaker"
    assert comps[0].attributes["current_a"].value == 80
    assert comps[0].attributes["current_a"].confidence == round(0.95 * DEFAULT.conflict_penalty, 4)


def test_what_never_merges() -> None:
    built = [
        _built(1, values={"current_a": 16, "poles": 1}),
        _built(2, values={"current_a": 16, "poles": 1}, panel="pnl_02"),  # another panel
        _built(3, values={"current_a": 16, "poles": None}),  # a null against a known value
        _built(4, values={"current_a": 16, "poles": 1}, scope="other_location"),
        _built(5, values={"current_a": 16, "poles": 1}, mult=6),
    ]
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
