"""Stage 3 (03): the library and its dictionary, the checks on the model's answers, de-duplication and the owner
tile, designators, orphan text, the disambiguation call, confidence and status, and a page end to end on a drawn
image with stand-in answers. No real model is called."""

import io
import random
import types
from typing import Any

import pytest
from PIL import Image, ImageDraw

from konboro.contracts.common import Bbox
from konboro.contracts.extraction import PageExtraction, Render, TextSpan, Tile
from konboro.contracts.intake import Page, PagePanel
from konboro.db.ids import new_id
from konboro.devtools import fake_llm
from konboro.pipeline.detection import candidates, designators, disambiguate, library, orphans, reference, search
from konboro.pipeline.detection.candidates import Candidate
from konboro.pipeline.detection.config import DEFAULT, DetectionConfig
from konboro.pipeline.detection.sheets import abbreviations_text, families_text, reference_sheet
from konboro.pipeline.stages import s3_symbols
from konboro_llm import ImageInput, LLMClient, LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.symbol_detection import DetectionAnswer, SymbolAnswer
from konboro_llm.stages.symbol_disambiguation import DisambiguationAnswer

LIB = library.default()


def span(text: str, bbox: Bbox, tags: dict[str, Any] | None = None, n: int = 1) -> TextSpan:
    return TextSpan(
        span_id=f"ts_001_{n:04d}",
        text=text,
        raw_text=text,
        bbox=bbox,
        source="ocr",
        confidence=0.9,
        color=None,
        tags=tags or {},
    )


def cand(bbox: Bbox, family: str = "circuit_breaker", cls: str = "mcb", **kw: Any) -> Candidate:
    defaults: dict[str, Any] = {"role": "device", "detector_score": 0.9, "class_score": 0.9}
    return Candidate(bbox=bbox, family=family, symbol_class=cls, **(defaults | kw))


def answer(box: list[float], family: str = "circuit_breaker", cls: str = "mcb", **kw: Any) -> SymbolAnswer:
    return SymbolAnswer(box=box, family=family, symbol_class=cls, **({"sure": True} | kw))


# ---------- the library (03 §4.3–4.6) ----------


def test_every_class_has_a_drawn_example_and_every_example_a_class() -> None:
    drawn = {c for c, _ in reference.FILES}
    assert drawn == {c.symbol_class for c in library.CLASSES}
    for _, name in reference.FILES:
        assert reference.path(f"reference/{name}").exists()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("מ.פ.", "rcd"),
        ("מ.פ", None),
        ("TC", "shunt_trip"),
        ("C1", "contactor"),
        ("K1", "contactor"),
        ("c 12", None),
        ("C12", "contactor"),
        ("NVR", "voltage_relay"),
        ("R5", "relay"),
        ("SATEC 135E", None),
        ("kwh", "energy_meter"),
        ("", None),
    ],
)
def test_the_abbreviation_dictionary(text: str, expected: str | None) -> None:
    found = LIB.classify_text(text)
    assert (found.symbol_class if found else None) == expected


def test_tenant_and_designer_abbreviations_win_over_global_ones() -> None:
    classes = list(library.CLASSES)
    lib = library.build(classes, [("TC", "shunt_trip")], [("TC", "timer")], [("TC", "contactor")])
    assert lib.classify_text("TC").symbol_class == "contactor"  # type: ignore[union-attr]
    lib = library.build(classes, [("TC", "shunt_trip")], [("TC", "timer")])
    assert lib.classify_text("TC").symbol_class == "timer"  # type: ignore[union-attr]
    assert library.build(classes, [("X", "no_such_class")]).classify_text("X") is None
    assert lib.version != LIB.version  # what the model is shown changed, so its cassette keys do


def test_the_sheet_and_the_lists_name_every_family_but_junctions() -> None:
    sheet = reference_sheet(LIB)
    assert sheet.width == 8 * 128 and sheet.height > 128
    text = families_text(LIB)
    assert "- circuit_breaker:" in text and "junction" not in text
    assert "RCD / מ.פ. / מפסק פחת = rcd" in abbreviations_text(LIB)


# ---------- the model's answers, checked (search.py) ----------


def tile_image(*boxes: tuple[int, int, int, int], size: int = 200) -> Image.Image:
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    for b in boxes:
        draw.rectangle(b, outline="black", width=2)
    return image


def search_image(
    image: Image.Image,
    origin: tuple[int, int] = (100, 100),
    padding: tuple[int, int, int, int] = (0, 0, 0, 0),
    page: tuple[int, int] = (1000, 1000),
) -> search.SearchImage:
    return search.SearchImage(image, origin, padding, page, "k", "tl_001_r0c0")


def test_a_box_is_shrunk_to_its_ink_and_placed_on_the_page() -> None:
    img = search_image(tile_image((40, 40, 60, 80)))
    (c,) = search.check([answer([30, 30, 70, 90])], img, 2.0, LIB, DEFAULT)
    assert c.bbox == ((40 + 100) / 2, (40 + 100) / 2, (61 + 100) / 2, (81 + 100) / 2)  # ink box is exclusive at x1
    assert c.method == "llm_vision" and c.detector_score == DEFAULT.sure_score and c.needs_decision is None


def test_answers_off_the_page_without_ink_or_off_the_lists_are_dropped() -> None:
    img = search_image(tile_image((40, 40, 60, 80), (150, 10, 190, 40)), padding=(0, 60, 0, 0))  # right 60 px padded
    answers = [
        answer([150, 10, 190, 40]),  # centre in the padding (03 §3.2 padding_reject)
        answer([100, 100, 120, 120]),  # blank paper
        answer([40, 40, 60, 80], family="spaceship", cls="warp_drive"),  # not in the library
        answer([40, 40, 60, 80], cls="rcd"),  # a class names its family
        answer([40, 40, 60, 80], cls="mcbx"),  # a family without a valid class: its default, then a decision
        answer([40, 40], cls="mcb"),
    ]
    found = search.check(answers, img, 1.0, LIB, DEFAULT)
    assert [(c.family, c.symbol_class, c.needs_decision) for c in found] == [
        ("rcd", "rcd", None),
        ("circuit_breaker", "mcb", "class_unknown"),
    ]
    assert found[1].detector_score == DEFAULT.unsure_score


def test_an_unsure_answer_waits_for_a_decision() -> None:
    (c,) = search.check(
        [answer([40, 40, 60, 80], sure=False)], search_image(tile_image((40, 40, 60, 80))), 1.0, LIB, DEFAULT
    )
    assert c.needs_decision == "unsure" and c.confidence == DEFAULT.unsure_score


def test_a_box_with_text_is_classed_by_the_dictionary_and_its_text_is_its_tag() -> None:
    img = search_image(tile_image((40, 40, 90, 70)))
    known, unknown = search.check(
        [
            answer([40, 40, 90, 70], family="relay", cls="relay", box_text="C1", sure=False),
            answer([40, 40, 90, 70], family="energy_meter", cls="energy_meter", box_text="SATEC 135E"),
        ],
        img,
        1.0,
        LIB,
        DEFAULT,
    )
    assert (known.family, known.symbol_class, known.class_score, known.needs_decision) == (
        "contactor",
        "contactor",
        1.0,
        None,
    )
    assert known.tag == "C1" and known.detector_score == DEFAULT.sure_score
    assert unknown.symbol_class == "energy_meter" and unknown.needs_decision == "box_text_unknown"
    assert unknown.tag is None  # "SATEC 135E" is a model, not a tag


def test_a_symbol_against_an_inner_tile_edge_is_cut() -> None:
    image = tile_image((150, 40, 199, 80))
    inner = search.check([answer([150, 40, 199, 80])], search_image(image), 1.0, LIB, DEFAULT)
    page_edge = search.check([answer([150, 40, 199, 80])], search_image(image, page=(300, 300)), 1.0, LIB, DEFAULT)
    assert inner[0].cut and not page_edge[0].cut  # the page ends there: nothing continues past it


# ---------- 3.5: one copy per symbol, the owner tile ----------


def test_copies_from_overlapping_tiles_become_one_and_the_whole_one_wins() -> None:
    a = cand((100, 100, 120, 140), tile_id="tl_a", cut=True, detector_score=0.95)
    b = cand((100.5, 100, 120, 140.5), tile_id="tl_b")
    c = cand((101, 101, 119, 139), tile_id="tl_c", detector_score=0.7)
    other = cand((200, 100, 220, 140), tile_id="tl_a")
    kept, removed = candidates.deduplicate([a, b, c, other], DEFAULT)
    assert removed == 2 and len(kept) == 2 and b in kept and a not in kept and c not in kept
    assert sorted(b.seen_in) == ["tl_a", "tl_b", "tl_c"]


def test_a_symbol_boxed_in_two_parts_along_its_wire_is_one() -> None:
    cross = cand((564.2, 241.9, 569.1, 247.5), family="fuse", cls="fuse", tag="F4", detector_score=0.7)
    body = cand((560.6, 248.5, 570.9, 281.3), tag="F4")
    pole = cand((575.0, 248.5, 585.0, 281.3), tag="F4")  # beside it, not along the wire: another symbol
    kept, removed = candidates.deduplicate([cross, body, pole], DEFAULT)
    assert removed == 1 and kept[0] is body
    assert body.bbox == (560.6, 241.9, 570.9, 281.3) and body.family == "circuit_breaker"


def test_one_place_holds_one_symbol_whatever_the_two_tiles_called_it() -> None:
    a = cand((100, 100, 140, 140), detector_score=0.9)
    b = cand((101, 101, 140, 141), family="switch_disconnector", cls="switch_disconnector", detector_score=0.7)
    kept, _ = candidates.deduplicate([b, a], DEFAULT)
    assert kept == [a] and [c for c, _ in a.candidates] == ["switch_disconnector"]


def test_any_symbol_seen_in_several_tiles_comes_out_once() -> None:
    rnd = random.Random(12)  # noqa: S311  (test data)
    for _ in range(200):
        x, y, w, h = rnd.uniform(0, 500), rnd.uniform(0, 500), rnd.uniform(5, 60), rnd.uniform(5, 60)
        copies = [
            cand(
                (
                    x + rnd.uniform(-1, 1),
                    y + rnd.uniform(-1, 1),
                    x + w + rnd.uniform(-1, 1),
                    y + h + rnd.uniform(-1, 1),
                ),
                tile_id=f"tl_{i}",
                detector_score=rnd.choice((0.7, 0.9)),
            )
            for i in range(rnd.randint(2, 4))
        ]
        kept, removed = candidates.deduplicate(copies, DEFAULT)
        assert len(kept) == 1 and removed == len(copies) - 1
        assert sorted(kept[0].seen_in) == sorted(c.tile_id for c in copies)


def test_the_owner_tile_holds_the_box_whole_farthest_from_its_edges() -> None:
    tiles = [("tl_left", (0.0, 0.0, 100.0, 100.0)), ("tl_right", (75.0, 0.0, 175.0, 100.0))]
    assert candidates.owner_tile((80, 40, 90, 50), tiles) == "tl_left"  # 10 pt from tl_left's edge, 5 from tl_right's
    assert candidates.owner_tile((86, 40, 96, 50), tiles) == "tl_right"  # 4 pt from tl_left's edge, 11 from tl_right's
    assert candidates.owner_tile((95, 40, 105, 50), tiles) == "tl_right"  # tl_left doesn't hold it whole
    assert candidates.owner_tile((50, 40, 170, 50), tiles) == "tl_right"  # larger than the overlap: the most of it
    assert candidates.owner_tile((500, 500, 510, 510), tiles) is None


# ---------- 3.7: designators ----------


def test_the_nearest_tag_shaped_span_is_the_designator() -> None:
    c = cand((100, 100, 110, 130))
    spans = [
        span("F1", (114, 100, 122, 107), n=1),
        span("F2", (100, 160, 108, 167), n=2),
        span("3X16A", (114, 110, 130, 117), {"current_a": 16}, n=3),
    ]
    designators.link(c, spans, DEFAULT)
    assert (c.designator, c.designator_span_id) == ("F1", "ts_001_0001")


def test_the_tag_the_model_read_wins_also_a_little_farther() -> None:
    c = cand((100, 100, 110, 110), family="contactor", cls="contactor", role="power_contact", tag="c2")
    spans = [span("C9", (112, 100, 118, 106), n=1), span("C2", (135, 100, 141, 106), n=2)]  # 25 pt off, radius 20
    designators.link(c, spans, DEFAULT)
    assert c.designator == "C2"


@pytest.mark.parametrize(
    ("family", "text", "tag", "expected"),
    [
        ("circuit_breaker", "C16", None, None),  # a breaker's curve and current, not its tag
        ("contactor", "C1", None, "C1"),
        ("circuit_breaker", "ABB", None, None),  # letters only: a brand
        ("circuit_breaker", "FNV", "FNV", "FNV"),  # unless the model read it as the tag
        ("indicator_lamp", "L1", None, "L1"),  # NEVIS-1's lamps are L1–L3
        ("circuit_breaker", "L1", None, None),  # a phase
        ("circuit_breaker", "PE", "PE", None),  # never
        ("busbar", "W0", None, "W0"),
    ],
)
def test_reserved_words_and_ratings(family: str, text: str, tag: str | None, expected: str | None) -> None:
    c = cand((100, 100, 110, 110), family=family, cls=family if family != "circuit_breaker" else "mcb", tag=tag)
    designators.link(c, [span(text, (113, 100, 121, 107))], DEFAULT)
    assert c.designator == expected


def test_a_box_labelled_with_letters_takes_them_and_an_aux_contact_takes_only_what_the_model_read() -> None:
    coil = cand((100, 100, 140, 120), family="voltage_relay", cls="voltage_relay")
    designators.link(coil, [span("NVR", (110, 104, 130, 116))], DEFAULT)
    assert coil.designator == "NVR"
    aux = cand((100, 100, 110, 130), family="aux_contact", cls="aux_contact", role="aux_contact")
    designators.link(aux, [span("F2", (113, 100, 121, 107))], DEFAULT)
    assert aux.designator is None


def test_devices_without_a_tag_are_flagged_on_a_tagged_drawing_only() -> None:
    billable = {c.symbol_class: c.billable for c in library.CLASSES}
    tagged = [cand((0, 0, 1, 1), designator="F1"), cand((0, 0, 1, 1), designator="F2")]
    lonely = cand((0, 0, 1, 1))
    bus = cand((0, 0, 1, 1), family="busbar", cls="busbar")
    designators.flag_untagged([*tagged, lonely, bus], billable, DEFAULT)
    assert lonely.flags == ["no_tag"] and bus.flags == [] and tagged[0].flags == []
    plan = [cand((0, 0, 1, 1)), cand((0, 0, 1, 1)), cand((0, 0, 1, 1), designator="F1")]
    designators.flag_untagged(plan, billable, DEFAULT)  # a designer's plan without tags (6199-2-50)
    assert all(c.flags == [] for c in plan)


# ---------- 3.6: text with no symbol near it ----------


def test_electrical_text_far_from_every_symbol_is_searched_once_then_handed_on() -> None:
    found = [cand((100, 100, 110, 130))]
    spans = [
        span("C16", (115, 105, 130, 112), {"curve": "C", "current_a": 16}, n=1),  # beside the breaker
        span("30mA", (400, 400, 420, 408), {"residual_ma": 30}, n=2),  # alone
        span("32A", (430, 400, 445, 408), {"current_a": 32}, n=3),  # alone, near the one above: one search
        span("5x2.5", (700, 700, 730, 708), {"cable_cores": 5}, n=4),  # a cable: no device expected
        span("16A", (900, 900, 915, 908), {"current_a": 16}, n=5),  # alone, its search finds nothing
    ]
    render = Image.new("RGB", (2000, 2000), "white")
    seen: list[tuple[tuple[int, int], str]] = []

    def run(jobs: list[tuple[search.SearchImage, str]]) -> list[list[Candidate]]:
        seen.extend((img.origin_px, hint) for img, hint in jobs)
        return [[cand((405, 385, 415, 398), family="rcd", cls="rcd")] if i == 0 else [] for i in range(len(jobs))]

    new, left, searches = orphans.recover(found, spans, render, 2.0, (1000, 1000), "k", run, DEFAULT)
    assert searches == 2 and "30mA, 32A" in seen[0][1]
    assert seen[0][0] == ((400 - 90) * 2, (400 - 90) * 2)
    assert [(c.family, c.method) for c in new] == [("rcd", "orphan_recovery")]
    assert [(o.text, o.recovery_attempted) for o in left] == [("16A", True)]
    assert new[0].confidence == pytest.approx(0.9 * 0.9)  # 03 §6.3


def test_orphan_searches_stop_at_the_page_limit() -> None:
    spans = [span(f"{i}A", (i * 100.0, 0, i * 100.0 + 10, 8), {"current_a": i}, n=i) for i in range(1, 6)]
    cfg = DetectionConfig(max_orphan_searches=2)
    _, left, searches = orphans.recover(
        [], spans, Image.new("RGB", (100, 100)), 0.1, (1000, 100), "k", lambda jobs: [[] for _ in jobs], cfg
    )
    assert searches == 2 and [o.recovery_attempted for o in left] == [True, True, False, False, False]


# ---------- 3.4: the disambiguation call ----------


def test_candidates_are_the_family_then_the_confusable_ones() -> None:
    c = cand((0, 0, 10, 10), cls="mccb")
    assert disambiguate.candidate_classes(c, LIB, DEFAULT) == [
        "mccb",
        "mcb",
        "motor_protection",
        "rcbo",
        "switch_disconnector",
    ]


@pytest.mark.parametrize(
    ("decision", "cls", "kept", "expected"),
    [
        ("choose", "rcbo", True, ("rcbo", "rcbo", "detector_llm")),
        ("choose", "timer", True, ("circuit_breaker", "mcb", "llm_vision")),  # off the list: ignored
        ("none_of_these", None, True, ("circuit_breaker", library.UNKNOWN, "detector_llm")),
        ("not_a_symbol", None, False, None),
    ],
)
def test_the_answer_is_checked_before_it_applies(decision: str, cls: str | None, kept: bool, expected: Any) -> None:
    c = cand((0, 0, 10, 10), detector_score=0.7, needs_decision="unsure")
    answer_ = DisambiguationAnswer(decision=decision, symbol_class=cls, confidence=0.8, reason="r")  # type: ignore[arg-type]
    assert disambiguate.apply(c, answer_, ["mcb", "rcbo"], LIB) is kept
    if kept:
        assert (c.family, c.symbol_class, c.method) == expected and c.needs_decision is None
        assert c.llm_decision is not None
    if expected and expected[2] == "detector_llm":
        assert c.confidence == pytest.approx(0.7 * 0.8)  # 03 §6.3: detector × the answer


def test_the_budget_and_non_billable_symbols() -> None:
    found = [cand((i * 20.0, 0, i * 20.0 + 10, 10)) for i in range(8)]
    for c in found[:4]:
        c.needs_decision, c.detector_score = "unsure", 0.7
    bus = cand((0, 50, 400, 55), family="busbar", cls="busbar", needs_decision="unsure", detector_score=0.7)
    asked: list[Candidate] = []

    def decide(c: Candidate, classes: list[str], crop: Image.Image) -> DisambiguationAnswer:
        asked.append(c)
        return DisambiguationAnswer(decision="choose", symbol_class=classes[0], confidence=0.9, reason="r")

    kept, calls, over = disambiguate.resolve(
        [*found, bus], decide, Image.new("RGB", (900, 300), "white"), 2.0, LIB, DEFAULT
    )
    assert calls == 2 and over  # 25% of 9 symbols, and four billable ones wanted a decision
    assert bus not in asked and len(kept) == 9


# ---------- 6.3, and a page end to end ----------


@pytest.mark.parametrize(
    ("confidence", "cls", "expected"),
    [
        (0.9, "mcb", "accepted"),
        (0.85, "mcb", "accepted"),
        (0.84, "mcb", "uncertain"),
        (0.5, "mcb", "uncertain"),
        (0.49, "mcb", "unknown"),
        (0.99, library.UNKNOWN, "unknown"),
    ],
)
def test_status_bands(confidence: float, cls: str, expected: str) -> None:
    assert s3_symbols.status(confidence, cls, DEFAULT) == expected


class Storage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.puts: list[str] = []

    def get(self, tenant_id: str, key: str) -> bytes:
        return self.files[key]

    def put(self, tenant_id: str, key: str, body: bytes, content_type: str) -> None:
        self.puts.append(key)


def test_a_page_end_to_end_with_the_stand_in_model() -> None:
    """One breaker on a page of two tiles (one blank); the stand-in model of E2E answers, tagged Q1."""
    drawing_id = new_id("drw")
    image = Image.new("RGB", (1400, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((600, 100, 640, 180), outline="black", width=3)  # in both tiles' overlap
    render_png = io.BytesIO()
    image.save(render_png, "PNG")
    tiles = [
        Tile(
            tile_id="tl_001_r0c0",
            row=0,
            col=0,
            bbox_pt=(0, 0, 512, 512),
            bbox_px=(0, 0, 1024, 1024),
            image_uri="t0",
            padding_px=(0, 0, 624, 0),
        ),
        Tile(
            tile_id="tl_001_r0c1",
            row=0,
            col=1,
            bbox_pt=(384, 0, 896, 512),
            bbox_px=(768, 0, 1792, 1024),
            image_uri="t1",
            padding_px=(0, 392, 624, 0),
            is_blank=True,
        ),
    ]
    extraction = PageExtraction(
        page_id="pg_01",
        drawing_id=drawing_id,
        render=Render(dpi=144, px_per_pt=2.0, width_px=1400, height_px=400, image_uri="render.png", dzi_uri=None),
        text_spans=[span("Q1", (321, 50, 330, 58), n=1)],
        tiles=tiles,
        trace_id="trc_01",
    )
    page = Page(
        page_id="pg_01",
        file_id="fil_01",
        page_no=5,
        sha256="abc",
        size_pt=(700, 200),
        geometry_source="vector",
        text_source="ocr",
        quality="ok",
        page_kind="single_line_diagram",
        page_kind_confidence=0.9,
        route="process",
        panels=[PagePanel(panel_id="pnl_01", name="ראשי", bbox=(0, 0, 700, 200), confidence=0.9)],
        classified_by="model",
    )
    storage = Storage({"render.png": render_png.getvalue()})
    stored = types.SimpleNamespace()
    ctx = types.SimpleNamespace(
        storage=storage,
        session=types.SimpleNamespace(get_one=lambda model, id_: stored),
        tenant_id=new_id("tnt"),
        drawing=types.SimpleNamespace(id=drawing_id),
        trace_id="trc_01",
    )
    llm = LLMClient({"anthropic": FakeProvider(fake_llm.answer)})
    sheet = ImageInput(b"", key="sheet")
    ask = search.model_asker(llm, search.Prompt(LIB, sheet), None)
    decide = disambiguate.model_decider(llm, LIB, lambda r: Image.new("RGB", (8, 8)), "", "k", None)

    result, found = s3_symbols.detect_page(ctx, page, 1, extraction, LIB, search.searcher(ask, LIB, DEFAULT), decide)  # type: ignore[arg-type]

    (d,) = result.detections
    assert d.det_id == "det_001_0001" and d.family == "circuit_breaker" and d.method == "llm_vision"
    assert d.bbox == (300.0, 50.0, 320.5, 74.0)  # the stand-in's 48 px box, shrunk to its ink
    assert d.designator == "Q1" and d.status == "accepted" and d.panel_id == "pnl_01"
    assert d.owner_tile_id == "tl_001_r0c0" and d.crop_uri and d.crop_uri.endswith("/crops/det_001_0001.png")
    assert storage.puts == [d.crop_uri]
    assert result.library_version == LIB.version and result.detector_model == "symbol_detection"
    assert result.stats.detection_count == 1 and result.stats.llm_calls == 0
    assert stored.symbol_count == 1 and stored.symbol_llm_count == 0
    assert found[0].bbox == d.bbox


def test_the_stand_in_model_answers_both_routes() -> None:
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((10, 10, 30, 30), outline="black")
    buf = io.BytesIO()
    image.save(buf, "PNG")
    req: LLMRequest[Any] = LLMRequest(
        stage="symbol_detection",
        system="",
        user_text="",
        output_schema=DetectionAnswer,
        images=[ImageInput(b""), ImageInput(buf.getvalue())],
    )
    (symbol,) = fake_llm.answer(req)["symbols"]
    assert symbol["box"][:2] == [10, 10] and symbol["tag"] == "Q1"
    req.user_text = orphans.HINT.format(texts="16A")
    assert fake_llm.answer(req) == {"symbols": []}
    pick: LLMRequest[Any] = LLMRequest(
        stage="symbol_disambiguation", system="", user_text="- rcd: x\n- rcbo: y", output_schema=DisambiguationAnswer
    )
    assert fake_llm.answer(pick)["symbol_class"] == "rcd"


def test_the_prompt_does_not_depend_on_the_order_the_database_returns_rows_in() -> None:
    rows = list(library.CLASSES)[::-1]
    refs = library.curated_references()[::-1]
    shuffled = library.build(rows, list(library.ABBREVIATIONS), references=refs)
    assert shuffled.version == LIB.version and families_text(shuffled) == families_text(LIB)
    assert reference_sheet(shuffled).tobytes() == reference_sheet(LIB).tobytes()
