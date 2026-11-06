"""The "לא פוענח" layer's rules (13 §4.4, S26): which stage-3 detections and orphan texts are spots, one box per
place, and the partial line's words. The database parts (lines, findings) are in
`tests/integration/test_api_unresolved.py`."""

from types import SimpleNamespace
from typing import Any

from konboro.contracts.detection import Detection, DetectionResult, OrphanText, PageDetections
from konboro.contracts.matching import ComponentMatch, UsedAttribute
from konboro.contracts.merge import AttributeValue, Instance, MergeResult, MissingInstance
from konboro.services import unresolved as u

TRACE = "trc_test"
PG = "pg_1"


def det(det_id: str, bbox: tuple[float, float, float, float], status: str = "unknown", **kw: Any) -> Detection:
    return Detection(
        det_id=det_id,
        page_id=PG,
        bbox=bbox,
        family="unknown",
        symbol_class="unknown_symbol",
        billable=False,
        method="llm_vision",
        detector_score=None,
        class_score=0.3,
        confidence=0.3,
        status=status,  # type: ignore[arg-type]
        owner_tile_id="tl_1",
        **kw,
    )


def detections(dets: list[Detection], orphans: list[OrphanText] | None = None) -> DetectionResult:
    page = PageDetections(page_id=PG, drawing_id="drw_1", detections=dets, orphan_texts=orphans or [], trace_id=TRACE)
    return DetectionResult(drawing_id="drw_1", pages=[page], trace_id=TRACE)


def instance(det_id: str | None, spans: list[str] | None = None) -> Instance:
    return Instance(
        instance_id=f"ins_{det_id or 'x'}",
        det_id=det_id,
        page_id=PG,
        panel_id=None,
        bbox=(0, 0, 1, 1),
        family="circuit_breaker",
        symbol_class="mcb",
        attributes={"current_a": AttributeValue(value=16, source="drawing", confidence=0.9, span_ids=spans or [])},
        method="geometric",
        status="accepted",
        confidence=0.9,
    )


def merge(instances: list[Instance], missing: list[MissingInstance] | None = None) -> MergeResult:
    return MergeResult(drawing_id="drw_1", instances=instances, missing=missing or [], trace_id=TRACE)


def manual(page_id: str, bbox: list[float]) -> Any:
    return SimpleNamespace(line_type="manual", boxes=[{"page_id": page_id, "bbox": bbox}])


def test_an_unknown_detection_is_a_spot_unless_stage_4_made_it_an_instance() -> None:
    result = detections(
        [
            det("det_1", (10, 10, 30, 30)),
            det("det_2", (50, 10, 70, 30), designator="X9"),
            det("det_3", (90, 10, 110, 30)),  # stage 4 read it: its family was known (S13)
            det("det_4", (130, 10, 150, 30), status="uncertain"),  # unsure is the line's colour, not the layer's
        ]
    )
    spots = u._unknown_symbols(result, merge([instance("det_3")]), [])
    assert [(s.kind, s.bbox) for s in spots] == [
        ("unknown_symbol", [10, 10, 30, 30]),
        ("unknown_symbol", [50, 10, 70, 30]),
    ]
    assert spots[0].note == "סימן שלא זיהינו. לא בספריית הסימנים"
    assert spots[1].note == "X9: סימן שלא זיהינו. לא בספריית הסימנים"
    assert u._unknown_symbols(None, None, []) == []


def test_a_component_marked_in_draw_mode_over_an_unknown_symbol_resolves_it() -> None:
    result = detections([det("det_1", (10, 10, 30, 30)), det("det_2", (50, 10, 70, 30))])
    marked = [manual(PG, [8, 8, 25, 32]), manual("pg_other", [50, 10, 70, 30])]  # the second is on another page
    spots = u._unknown_symbols(result, None, marked)  # type: ignore[arg-type]
    assert [s.bbox for s in spots] == [[50, 10, 70, 30]]


def test_an_orphan_text_is_a_spot_unless_an_instance_read_it_or_it_became_a_missing_line() -> None:
    orphans = [
        OrphanText(span_id="ts_1", text="C16", bbox=(10, 10, 20, 15), recovery_attempted=True),
        OrphanText(span_id="ts_2", text="30mA", bbox=(40, 10, 50, 15), recovery_attempted=True),
        OrphanText(span_id="ts_3", text="3X25A", bbox=(80, 10, 90, 15), recovery_attempted=False),
    ]
    missing = MissingInstance(
        instance_id="ins_m",
        page_id=PG,
        panel_id=None,
        bbox=(78, 8, 95, 18),
        family="rcd",
        origin="orphan_text",
        confidence=0.5,
    )
    spots = u._orphan_texts(detections([], orphans), merge([instance("det_1", ["ts_2"])], [missing]))
    assert [(s.kind, s.note) for s in spots] == [("orphan_text", '"C16": ערך חשמלי שלא שויך לאף רכיב')]
    # with no stage 4 (the review fixture), every orphan text stays
    assert len(u._orphan_texts(detections([], orphans), None)) == 3


def test_one_box_per_place_keeps_the_more_specific_kind() -> None:
    same = [10.0, 10.0, 50.0, 50.0]
    spots = [
        u.Spot("partial", PG, [11, 11, 50, 50], "RNV", line_id="ln_1"),
        u.Spot("orphan_text", PG, same, '"9 / 5"'),
        u.Spot("partial", "pg_2", same, "on another page"),
        u.Spot("partial", PG, [10, 10, 200, 200], "a bigger box around it"),  # covers it, not covered by it
    ]
    kept = u.one_per_place(spots)
    assert [(s.kind, s.page_id, s.note) for s in kept] == [
        ("orphan_text", PG, '"9 / 5"'),
        ("partial", "pg_2", "on another page"),
        ("partial", PG, "a bigger box around it"),
    ]


def test_covered() -> None:
    assert u.covered([0, 0, 10, 10], [0, 0, 10, 5])  # half
    assert not u.covered([0, 0, 10, 10], [0, 0, 10, 4.9])
    assert not u.covered([0, 0, 10, 10], [20, 20, 30, 30])
    assert not u.covered([0, 0, 0, 10], [0, 0, 10, 10])  # no area


def test_the_words_of_a_partial_line() -> None:
    assert u._and(["אין דגם", "אין מחיר"]) == "אין דגם ואין מחיר"
    assert u._and(["הזרם לא כתוב", "מספר הקטבים לא כתוב", "אין מחיר"]) == (
        "הזרם לא כתוב, מספר הקטבים לא כתוב ואין מחיר"
    )
    assert u._and(["אין מחיר", "אין מחיר"]) == "אין מחיר"

    def line(*values: Any) -> Any:
        return SimpleNamespace(status_reasons=[{"source": "match", "value": v, "status": "red"} for v in values])

    assert u._not_identified(line("unmatched")) == ["אין דגם"]
    assert u._not_identified(line("ambiguous")) == ["כמה מוצרים מתאימים"]
    assert u._not_identified(line("conflict")) == ["ערכים סותרים"]
    assert u._not_identified(line("explicit_model", "inferred_attribute")) == []
    assert u._not_identified(line({"code": "defaulted_attribute", "value": "6kA"})) == []
    price_only = SimpleNamespace(status_reasons=[{"source": "price", "value": "missing", "status": "red"}])
    assert u._not_identified(price_only) == []


def test_current_and_poles_count_as_read_only_from_the_drawing_or_the_user() -> None:
    def used(source: str, value: Any = 16) -> UsedAttribute:
        return UsedAttribute(value=value, source=source)  # type: ignore[arg-type]

    match = ComponentMatch.model_construct(
        attributes_used={
            "current_a": used("inferred"),
            "poles": used("graphic", 3),
            "curve": used("system_default", "C"),
        }
    )
    assert u._unread(match, "current_a")
    assert not u._unread(match, "poles")
    assert u._unread(match, "breaking_capacity_ka")  # not used at all
    assert u._unread(ComponentMatch.model_construct(attributes_used={"poles": used("drawing", None)}), "poles")
