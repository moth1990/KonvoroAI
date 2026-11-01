"""Stage 2 (02): rendering, the PDF's text and lines, OCR checks, normalization, the wire graph and tiling.

Synthetic PDFs are built with pypdfium2's C API (tests may import it; product code goes through konboro.services.pdf).
"""

import ctypes
import gzip
import io
import json
import math
import random
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import pytest
from PIL import Image, ImageDraw

from konboro.contracts.intake import Page, PagePanel
from konboro.pipeline.extraction import deepzoom, normalize, ocr, render, tiles, vector, wires
from konboro.pipeline.extraction.config import DEFAULT, ExtractionConfig
from konboro.pipeline.extraction.geometry import turn_box, turned_size, unturn_fraction
from konboro.pipeline.extraction.normalize import Text
from konboro.pipeline.intake.pages import read_pages, render_at
from konboro.pipeline.stages import s2_extraction
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider

GOLDEN = Path(__file__).resolve().parents[3] / "golden"


# ---------- synthetic PDFs ----------


def make_pdf(
    texts: list[tuple[str, float, float, float]] = (),  # type: ignore[assignment]
    lines: list[tuple[float, float, float, float]] = (),  # type: ignore[assignment]
    rotate: int = 0,
    size: tuple[float, float] = (595.0, 842.0),
    pages: int = 1,
) -> bytes:
    """Text (string, x, y from the bottom, angle ccw) in Helvetica 10 pt, and lines, on every page."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        _draw(doc, doc.new_page(*size), texts, lines, rotate)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _draw(doc: Any, page: Any, texts: Any, lines: Any, rotate: int) -> None:
    font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    for s, x, y, angle in texts:
        obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, 10)
        buf = ctypes.create_string_buffer((s + "\x00").encode("utf-16-le"))
        pdfium_c.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(pdfium_c.FPDF_WCHAR)))
        if angle:
            a = math.radians(angle)
            pdfium_c.FPDFPageObj_Transform(obj, math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
        pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        pdfium_c.FPDFPage_InsertObject(page.raw, obj)
    for x0, y0, x1, y1 in lines:
        path = pdfium_c.FPDFPageObj_CreateNewPath(x0, y0)
        pdfium_c.FPDFPath_LineTo(path, x1, y1)
        pdfium_c.FPDFPath_SetDrawMode(path, 0, 1)
        pdfium_c.FPDFPageObj_SetStrokeWidth(path, 1.0)
        pdfium_c.FPDFPage_InsertObject(page.raw, path)
    if rotate:
        pdfium_c.FPDFPage_SetRotation(page.raw, rotate // 90)
    pdfium_c.FPDFPage_GenerateContent(page.raw)


def has_ink(image: Image.Image, box: tuple[float, float, float, float], scale: float) -> bool:
    crop = image.crop(tuple(round(v * scale) for v in box)).convert("L")  # type: ignore[arg-type]
    return crop.point(lambda v: 255 if v < 160 else 0).getbbox() is not None


# ---------- geometry ----------


@pytest.mark.parametrize("turn", [0, 90, 180, 270])
def test_a_turn_and_its_inverse_give_the_box_back(turn: int) -> None:
    size = (800.0, 500.0)
    box = (10.0, 20.0, 110.0, 70.0)
    turned = turn_box(box, size, turn)
    assert turn_box(turned, turned_size(size, turn), (360 - turn) % 360) == pytest.approx(box)


def test_a_quarter_turn_moves_the_top_left_corner_to_the_top_right() -> None:
    assert turn_box((0.0, 0.0, 10.0, 20.0), (800.0, 500.0), 90) == (480.0, 0.0, 500.0, 10.0)


@pytest.mark.parametrize("turn", [0, 90, 180, 270])
def test_a_crop_renders_the_same_place_on_a_turned_page(turn: int) -> None:
    data = make_pdf(lines=[(100, 700, 200, 700)])
    read = read_pages("fil", "pdf", data)[0]
    read.extra_rotation = turn
    upright = turned_size(read.size_pt, turn)
    whole = render_at(read, data, 72)
    ink = whole.convert("L").point(lambda v: 255 if v < 160 else 0).getbbox()
    assert ink is not None
    box = (ink[0] - 5.0, ink[1] - 5.0, ink[2] + 5.0, ink[3] + 5.0)
    crop = render_at(read, data, 72, unturn_fraction(box, upright, turn))
    assert crop.convert("L").point(lambda v: 255 if v < 160 else 0).getbbox() is not None


# ---------- 2.1 DPI ----------


def page(**changes: Any) -> Page:
    base: dict[str, Any] = {
        "page_id": "pg_1",
        "file_id": "fil_1",
        "page_no": 1,
        "sha256": "abc",
        "size_pt": (842.0, 595.0),
        "geometry_source": "vector",
        "text_source": "ocr",
        "quality": "ok",
        "page_kind": "single_line_diagram",
        "page_kind_confidence": 0.9,
        "route": "process",
        "classified_by": "model",
    }
    return Page.model_validate(base | changes)


def test_dpi_rules() -> None:
    assert render.choose_dpi(page(geometry_source="raster"), None, DEFAULT) == 300
    assert render.choose_dpi(page(geometry_source="raster", quality="low_resolution"), None, DEFAULT) == 400
    # text 14.4 pt tall is 30 px at 150 DPI; small text never goes above 300 or big text below 150
    assert render.choose_dpi(page(), 14.4, DEFAULT) == 150
    assert render.choose_dpi(page(), 4.0, DEFAULT) == 300
    assert render.choose_dpi(page(), 40.0, DEFAULT) == 150
    assert render.choose_dpi(page(), 8.0, DEFAULT) == 270
    assert render.choose_dpi(page(geometry_source="raster"), None, DEFAULT, photo_dpi=96) == 96


def test_a_huge_page_is_rendered_smaller() -> None:
    cfg = ExtractionConfig(max_render_px=10_000_000)
    dpi = render.choose_dpi(page(size_pt=(3969.0, 1701.0), geometry_source="raster"), None, cfg)
    assert (3969 * dpi / 72) * (1701 * dpi / 72) <= 10_000_000


def test_the_text_height_of_drawn_letters_comes_from_their_strokes() -> None:
    data = (GOLDEN / "NEVIS-1" / "NEVIS-1.pdf").read_bytes()
    height = vector.read(data, 4, 0, with_text=False).text_height_pt
    assert height is not None and 5 < height < 10  # 2–3 mm letters on an A4 diagram


# ---------- 2.2 the PDF's own text and lines ----------


@pytest.mark.parametrize("rotate", [0, 90, 270])
def test_pdf_words_land_on_their_ink_and_read_in_their_direction(rotate: int) -> None:
    data = make_pdf(texts=[("C16", 100, 700, 0), ("30mA", 300, 400, 90)], rotate=rotate)
    read = read_pages("fil", "pdf", data)[0]
    vp = vector.read(data, 0, 0, with_text=True)
    words = {w.text: w for w in vp.words}
    assert set(words) == {"C16", "30mA"}
    assert words["C16"].rotation == (0 - rotate) % 360
    assert words["30mA"].rotation == (90 - rotate) % 360
    image = render_at(read, data, 144)
    for w in vp.words:
        assert has_ink(image, w.bbox, 2.0), w


def test_words_split_at_spaces_and_keep_their_size() -> None:
    vp = vector.read(make_pdf(texts=[("3P 10kA", 100, 700, 0)]), 0, 0, with_text=True)
    assert [w.text for w in vp.words] == ["3P", "10kA"]
    assert all(6 < w.font_size_pt < 12 for w in vp.words)


def test_a_page_without_a_reliable_text_layer_gives_no_words() -> None:
    assert vector.read(make_pdf(texts=[("C16", 100, 700, 0)]), 0, 0, with_text=False).words == []


def test_lines_come_out_with_width_and_on_the_upright_page() -> None:
    data = make_pdf(lines=[(100, 742, 300, 742)])  # 100 pt from the top of a portrait A4
    flat = vector.read(data, 0, 0, with_text=False).paths
    assert [p.points for p in flat] == [[(100.0, 100.0), (300.0, 100.0)]]
    assert flat[0].width == 1.0
    turned = vector.read(data, 0, 90, with_text=False).paths  # turned clockwise: now vertical, on the right
    assert turned[0].points == [(742.0, 100.0), (742.0, 300.0)]
    rows = json.loads(gzip.decompress(vector.paths_json(flat)))
    assert rows == [{"k": "line", "pts": [[100.0, 100.0], [300.0, 100.0]], "w": 1.0, "c": None}]


def test_golden_layers_are_kept() -> None:
    data = (GOLDEN / "NEVIS-1" / "NEVIS-1.pdf").read_bytes()
    assert ("TEXT", True) in vector.read(data, 4, 0, with_text=False).layers


@pytest.mark.parametrize(
    ("value", "hex_"),
    [((0, 0, 0), None), ((1, 1, 1), None), ((1.0, 0.0, 0.0), "#ff0000"), ((0, 1, 0, 0), "#ff00ff"), ([0.5], "#808080")],
)
def test_colours(value: Any, hex_: str | None) -> None:
    assert vector.hex_color(value) == hex_


def test_hebrew_comes_back_in_reading_order() -> None:
    assert vector.visual_to_logical('16A ז"אמ') == 'מא"ז 16A'
    assert vector.visual_to_logical("C16") == "C16"


# ---------- 2.4 normalization ----------


def norm(raw: str, source: str = "ocr", confidence: float = 0.9) -> Text:
    return normalize.normalize(Text(raw, (0.0, 0.0, 10.0, 5.0), 0, confidence, source))


@pytest.mark.parametrize(
    ("raw", "text", "tags"),
    [
        ("16 A", "16A", {"current_a": 16}),
        ("16a", "16A", {"current_a": 16}),
        ("16א", "16A", {"current_a": 16}),
        ("3X16A", "3×16A", {"poles": 3, "current_a": 16}),
        ("3×16", "3×16", {"poles": 3}),
        ("3P", "3P", {"poles": 3}),
        ("C16", "C16", {"curve": "C", "current_a": 16}),
        ("10KA", "10kA", {"breaking_capacity_ka": 10}),
        ("30MA", "30mA", {"residual_ma": 30}),
        ("4x25mm2", "4×25mm²", {"cable_cores": 4}),
        ("INC=8A", "INC=8A", {"setting_a": 8}),
    ],
)
def test_units_spacing_and_tags(raw: str, text: str, tags: dict[str, Any]) -> None:
    t = norm(raw, source="pdf_text", confidence=1.0)
    assert (t.text, t.tags, t.raw_text) == (text, tags, raw)
    assert t.corrections == [] and t.confidence == 1.0


@pytest.mark.parametrize(
    ("raw", "text", "rule"),
    [("C1O", "C10", "O_to_0"), ("3OmA", "30mA", "O_to_0"), ("l6A", "16A", "l_to_1"), ("1SkA", "15kA", "S_to_5")],
)
def test_ocr_fixes_follow_the_dictionary_and_cost_ten_percent(raw: str, text: str, rule: str) -> None:
    t = norm(raw)
    assert t.text == text and t.raw_text == raw
    assert t.corrections == [{"from": raw, "to": text, "rule": rule}]
    assert t.confidence == pytest.approx(0.81)


@pytest.mark.parametrize("raw", ["18A", "B10", "S204M", "SO1", "Q1", "OK"])
def test_no_fix_without_a_dictionary_token_and_never_a_number(raw: str) -> None:
    t = norm(raw)
    assert t.text == raw and t.corrections == []


def test_the_pdf_text_layer_is_never_fixed() -> None:
    assert norm("C1O", source="pdf_text", confidence=1.0).text == "C1O"


def placed(raw: str, x0: float, x1: float, y: float = 0.0, span_id: str = "ts_1") -> Text:
    t = normalize.normalize(Text(raw, (x0, y, x1, y + 5.0), 0, 0.9, "ocr"))
    t.span_id = span_id
    return t


def test_neighbours_merge_into_one_span() -> None:
    spans = [
        placed("3P", 0, 10, span_id="ts_1"),
        placed("10kA", 12, 30, span_id="ts_2"),
        placed("Q1", 60, 70, span_id="ts_3"),  # too far, and a designator
        placed("16", 0, 8, y=20, span_id="ts_4"),
        placed("A", 9, 12, y=20, span_id="ts_5"),
    ]
    merged = {m.text: m for m in normalize.merge(spans, (100.0, 100.0))}
    assert set(merged) == {"3P 10kA", "Q1", "16A"}
    assert merged["3P 10kA"].merged_from == ["ts_1", "ts_2"]
    assert merged["3P 10kA"].bbox == (0, 0, 30, 5.0)
    assert merged["3P 10kA"].tags == {"poles": 3, "breaking_capacity_ka": 10}
    assert merged["16A"].raw_text == "16A" and merged["16A"].merged_from == ["ts_4", "ts_5"]
    assert merged["Q1"].merged_from == []


def test_a_designator_is_not_merged_into_a_rating() -> None:
    merged = normalize.merge([placed("Q1", 0, 8, span_id="ts_1"), placed("C16", 10, 20, span_id="ts_2")], (100, 100))
    assert sorted(m.text for m in merged) == ["C16", "Q1"]


# ---------- 2.6 tiling ----------


def test_any_box_up_to_the_overlap_lies_whole_in_one_tile() -> None:
    rnd = random.Random(7)  # noqa: S311 (a fixed seed for a repeatable property test)
    for _ in range(40):
        tile, overlap = 1024, 256
        area = (rnd.randint(0, 500), rnd.randint(0, 500), 0, 0)
        area = (area[0], area[1], area[0] + rnd.randint(100, 9000), area[1] + rnd.randint(100, 6000))
        image = (area[2] + rnd.randint(0, 300), area[3] + rnd.randint(0, 300))
        grid = tiles.grid(area, image, tile, overlap)
        for _ in range(200):
            w, h = rnd.randint(1, overlap), rnd.randint(1, overlap)
            x = rnd.uniform(area[0], max(area[0], area[2] - w))
            y = rnd.uniform(area[1], max(area[1], area[3] - h))
            assert any(
                t.bbox_px[0] <= x and t.bbox_px[1] <= y and x + w <= t.bbox_px[2] and y + h <= t.bbox_px[3]
                for t in grid
            ), (area, x, y, w, h)


def test_the_grid_steps_by_tile_minus_overlap_and_pads_past_the_page() -> None:
    grid = tiles.grid((0, 0, 2000, 1000), (2000, 1000), 1024, 256)
    assert [(t.row, t.col, t.bbox_px[0], t.bbox_px[1]) for t in grid] == [(0, 0, 0, 0), (0, 1, 768, 0), (0, 2, 1536, 0)]
    assert grid[2].padding_px == (0, 560, 24, 0)
    assert grid[0].padding_px == (0, 0, 24, 0)


def test_one_tile_for_a_small_area() -> None:
    assert len(tiles.grid((10, 10, 500, 400), (600, 600), 1024, 256)) == 1


def test_tiles_cover_the_whole_page_whatever_stage_1_boxed() -> None:
    """BUG-019: a component outside the panel box stage 1 found is still on a tile."""
    data = make_pdf(texts=[("Q1", 100, 800, 0), ("PM", 500, 40, 0)], lines=[(50, 420, 550, 420)])
    read = read_pages("fil_1", "pdf", data)[0]
    top_only = PagePanel(panel_id="pnl_1", name="x", bbox=(50.0, 20.0, 300.0, 120.0), confidence=0.9)
    ctx, _, _ = context()
    p = page(size_pt=read.size_pt, panels=[top_only], sha256=read.sha256)
    out = s2_extraction.extract_page(ctx, p, 1, read, data, ocr.FakeOcrEngine(lambda im: []))
    assert out.render is not None
    covered = (min(t.bbox_px[0] for t in out.tiles), min(t.bbox_px[1] for t in out.tiles))
    assert covered == (0, 0)
    assert max(t.bbox_px[2] for t in out.tiles) >= out.render.width_px
    assert max(t.bbox_px[3] for t in out.tiles) >= out.render.height_px
    assert any(t.panel_ids == ["pnl_1"] for t in out.tiles) and any(t.panel_ids == [] for t in out.tiles)


def test_a_cut_tile_is_white_past_the_page_and_blank_tiles_are_found() -> None:
    image = Image.new("RGB", (1500, 1100), "white")
    ImageDraw.Draw(image).rectangle((1400, 1000, 1499, 1099), fill="black")
    t = tiles.grid((0, 0, 1500, 1100), image.size, 1024, 256)[-1]
    piece = tiles.cut(image, t)
    assert piece.size == (1024, 1024)
    assert piece.getpixel((1023, 1023)) == (255, 255, 255)  # padding
    assert tiles.white_share(piece) < DEFAULT.blank_threshold  # 1% ink is not blank on a line drawing
    assert tiles.white_share(tiles.cut(image, tiles.grid((0, 0, 1500, 1100), image.size, 1024, 256)[0])) == 1.0


# ---------- 2.3 OCR ----------


def ink_tile(boxes: list[tuple[int, int, int, int]], size: int = 1024) -> Image.Image:
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    for b in boxes:
        draw.rectangle(b, fill="black")
    return img


def test_a_word_without_ink_is_dropped_and_boxes_shrink_to_their_ink() -> None:
    img = ink_tile([(100, 100, 140, 120)])
    t = tiles.TileGeom(0, 0, (0, 0, 1024, 1024), (0, 0, 0, 0))
    words = [ocr.OcrWord("C16", (90, 90, 160, 130), 0, 0.9), ocr.OcrWord("Q1", (500, 500, 540, 520), 0, 0.9)]
    readings = ocr._check(words, img, t, (2048, 2048), 2.0)
    assert [(r.text, r.bbox) for r in readings] == [("C16", (50.0, 50.0, 70.5, 60.5))]


def test_coloured_ink_is_kept() -> None:
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle((10, 10, 30, 20), fill=(220, 0, 0))
    found = ocr.ink_box(img, (0, 0, 50, 50))
    assert found is not None and found[1] is not None and found[1].startswith("#d")


def test_a_word_on_an_inner_tile_edge_is_cut_but_not_on_the_page_edge() -> None:
    img = ink_tile([(0, 100, 30, 120), (1000, 300, 1023, 320)])
    inner = tiles.TileGeom(0, 1, (768, 0, 1792, 1024), (0, 0, 0, 0))  # the page continues to the left
    words = [ocr.OcrWord("C1", (0, 100, 30, 120), 0, 0.9), ocr.OcrWord("Q", (1000, 300, 1023, 320), 0, 0.9)]
    cut = {r.text: r.cut for r in ocr._check(words, img, inner, (1792, 1024), 1.0)}
    assert cut == {"C1": True, "Q": False}  # the tile's right edge is the page's


def reading(text: str, box: tuple[float, float, float, float], conf: float = 0.9, cut: bool = False) -> ocr.Reading:
    return ocr.Reading(text, box, 0, conf, cut, None)


def test_copies_from_overlapping_tiles_become_one_span() -> None:
    combined = ocr.combine(
        [
            reading("C1", (10, 10, 18, 15), cut=True),
            reading("C16", (10, 10, 22, 15)),
            reading("C16", (10.2, 10, 22, 15.1), conf=0.6),
            reading("Q2", (50, 10, 60, 15)),
        ]
    )
    assert sorted((r.text, r.confidence) for r in combined) == [("C16", 0.9), ("Q2", 0.9)]


def test_copies_that_disagree_are_left_for_a_re_read() -> None:
    combined = ocr.combine([reading("C16", (10, 10, 22, 15)), reading("C18", (10, 10, 22, 15), conf=0.6)])
    assert [(r.text, r.confidence) for r in combined] == [("C16", ocr.DISAGREE_CONFIDENCE)]


def test_read_page_drops_what_is_below_the_minimum() -> None:
    img = ink_tile([(100, 100, 140, 120), (300, 300, 340, 320)])
    t = tiles.TileGeom(0, 0, (0, 0, 1024, 1024), (0, 0, 0, 0))
    engine = ocr.FakeOcrEngine(
        lambda im: [ocr.OcrWord("C16", (100, 100, 140, 120), 0, 0.9), ocr.OcrWord("x", (300, 300, 340, 320), 0, 0.3)]
    )
    kept = ocr.read_page(engine, img, [(t, img)], 1.0, "sha:0", DEFAULT)
    assert [r.text for r in kept] == ["C16"]
    assert engine.seen[0].key == "sha:0:tile:(0, 0, 1024, 1024)"


def test_a_re_read_replaces_only_when_it_is_more_confident() -> None:
    crop = ink_tile([(0, 0, 1023, 1023)], size=200)
    answers = {"first": 0.95}

    def answer(im: ocr.OcrImage) -> list[ocr.OcrWord]:
        return [ocr.OcrWord("C10", (0, 0, im.size[0], im.size[1]), 0, answers["first"])]

    unsure = reading("C1O", (10, 10, 22, 15), conf=0.6)
    sure = reading("C16", (40, 10, 52, 15), conf=0.9)
    word = reading("שלום", (60, 10, 80, 15), conf=0.6)  # not electrical: not read again
    engine = ocr.FakeOcrEngine(answer)
    changed = ocr.reread(engine, [unsure, sure, word], lambda box, dpi: crop, (100, 100), "k", DEFAULT)
    assert changed == 1 and unsure.text == "C10" and unsure.confidence == 0.95
    assert len(engine.seen) == 1 and ":reread:600:" in engine.seen[0].key
    answers["first"] = 0.5
    again = reading("C1O", (10, 10, 22, 15), conf=0.6)
    assert ocr.reread(engine, [again], lambda box, dpi: crop, (100, 100), "k", DEFAULT) == 0 and again.text == "C1O"


def test_claude_vision_ocr_checks_the_answer() -> None:
    def answer(request: Any) -> dict[str, Any]:
        assert request.stage == "ocr_transcription"
        assert "1024 × 1024" in request.user_text
        return {
            "words": [
                {"text": "C16", "box": [30, 20, 10, 5], "rotation": 90, "legible": "clear"},
                {"text": "  ", "box": [1, 1, 2, 2], "legible": "clear"},
                {"text": "Q1", "box": [1, 2, 3], "legible": "clear"},
                {"text": "3OmA", "box": [40, 40, 60, 50], "legible": "unsure"},
            ]
        }

    engine = ocr.ClaudeVisionOcr(LLMClient({"anthropic": FakeProvider(answer)}))
    words = engine.read(ocr.OcrImage(b"png", (1024, 1024), "k"))
    assert [(w.text, w.box, w.rotation, w.confidence) for w in words] == [
        ("C16", (10, 5, 30, 20), 90, ocr.ClaudeVisionOcr.CLEAR),
        ("3OmA", (40, 40, 60, 50), 0, ocr.ClaudeVisionOcr.UNSURE),
    ]


# ---------- 2.5 wire graph ----------


def path(*pts: tuple[float, float], kind: str = "line") -> vector.Path:
    return vector.Path(kind, list(pts), 0.5, None)


PAGE = (1000.0, 1000.0)


def test_a_t_junction_splits_the_line_it_lands_on() -> None:
    segs = wires.wiring_segments([path((50, 100), (250, 100)), path((150, 100.3), (150, 300))], PAGE, [])
    g = wires.build(segs)
    assert len(g.nodes) == 4 and len(g.edges) == 3


def test_lines_that_only_cross_are_not_connected() -> None:
    g = wires.build(wires.wiring_segments([path((50, 100), (250, 100)), path((150, 50), (150, 200))], PAGE, []))
    assert len(g.nodes) == 4 and len(g.edges) == 2


def test_a_chain_of_segments_is_one_edge() -> None:
    g = wires.build(wires.wiring_segments([path((50, 50), (100, 50), (100.2, 100), (150, 100))], PAGE, []))
    assert len(g.edges) == 1 and len(g.edges[0][2]) == 2


def test_letters_frames_and_specks_are_not_wires() -> None:
    paths = [
        path((100, 100), (300, 100)),  # a wire
        path((300, 300), (305, 310)),  # a stroke inside a text box
        path((500, 500), (504, 504)),  # a speck no text box covers
        path((20, 50), (950, 50)),  # a frame line across the page
        path((10, 300), (10, 600)),  # inside the border band
        path((800, 900), (900, 900)),  # inside the title block
        path((600, 600), (700, 600), (700, 700), kind="rect"),
    ]
    g = wires.build(wires.wiring_segments(paths, PAGE, [(298, 298, 310, 312)], [(780, 880, 960, 960)]))
    assert len(g.edges) == 1
    body = json.loads(gzip.decompress(g.to_json()))
    assert body["nodes"] == [[100.0, 100.0], [300.0, 100.0]] and body["block_links"] == []


# ---------- the viewer's pyramid ----------


def test_the_pyramid_halves_down_to_one_pixel() -> None:
    image = Image.new("RGB", (1200, 700), "white")
    out = list(deepzoom.tiles(image, 510, 1))
    levels = {level for level, *_ in out}
    assert levels == set(range(deepzoom.max_level(1200, 700) + 1)) and max(levels) == 11
    top = [(c, r) for level, c, r, _ in out if level == 11]
    assert sorted(top) == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
    first = Image.open(io.BytesIO(next(b for level, c, r, b in out if (level, c, r) == (11, 1, 0))))
    assert first.size == (512, 511)  # one pixel of overlap on each inner side
    assert b'TileSize="510"' in deepzoom.descriptor(1200, 700, 510, 1)


def test_the_pyramid_is_packed_with_an_index_of_byte_ranges() -> None:
    image = Image.new("RGB", (1200, 700), "white")
    blob, raw_index = deepzoom.pack(image, 510, 1)
    index = json.loads(raw_index)
    assert len(index) == len(list(deepzoom.tiles(image, 510, 1)))
    offset, length = index["11/1_0"]
    assert Image.open(io.BytesIO(blob[offset : offset + length])).size == (512, 511)


# ---------- the page, end to end ----------


class Store:
    def __init__(self) -> None:
        self.put_keys: dict[str, int] = {}

    def put(self, tenant_id: str, key: str, body: bytes, content_type: str = "") -> None:
        assert key.startswith(f"tenants/{tenant_id}/")
        self.put_keys[key] = len(body)


class Row:
    render_key: str | None = None
    tiles_prefix: str | None = None
    tile_count: int | None = None


TENANT = "tnt_01JD0DEM000000000000000000"
DRAWING = "drw_01JD0DEM000000000000000000"


def context() -> tuple[Any, Store, Row]:
    from types import SimpleNamespace

    store, row = Store(), Row()
    session = SimpleNamespace(get_one=lambda *a: row)
    ctx = SimpleNamespace(
        storage=store, tenant_id=TENANT, drawing=SimpleNamespace(id=DRAWING), trace_id="trc_x", session=session
    )
    return ctx, store, row


def test_a_page_with_a_text_layer_needs_no_ocr() -> None:
    data = make_pdf(texts=[("Q1", 100, 700, 0), ("C16", 100, 650, 0)], lines=[(50, 600, 400, 600)])
    read = read_pages("fil_1", "pdf", data)[0]
    ctx, store, row = context()
    engine = ocr.FakeOcrEngine(lambda im: pytest.fail("no OCR on a text layer"))
    p = page(size_pt=read.size_pt, text_source="pdf_text", sha256=read.sha256)
    out = s2_extraction.extract_page(ctx, p, 1, read, data, engine)
    assert sorted((s.text, s.source, s.confidence) for s in out.text_spans) == [
        ("C16", "pdf_text", 1.0),
        ("Q1", "pdf_text", 1.0),
    ]
    # 10 pt text is 30 px at 216 DPI (02 §2.1)
    assert out.render is not None and out.render.dpi == 216 and out.render.px_per_pt == pytest.approx(3.0)
    assert out.wire_graph is not None and out.wire_graph.status == "built" and out.wire_graph.edge_count == 1
    assert out.stats.ocr_span_count == 0 and out.issues == []
    assert (
        row.render_key == out.render.image_uri and row.tile_count == out.stats.tile_count - out.stats.blank_tile_count
    )
    assert out.render.dzi_uri in store.put_keys and all(t.image_uri in store.put_keys for t in out.tiles)
    pyramid = out.render.dzi_uri.rsplit("/", 1)[0]
    assert {f"{pyramid}/tiles.bin", f"{pyramid}/index.json"} <= set(store.put_keys)
    assert not any("page_files" in k for k in store.put_keys)  # packed, not one object per tile


def test_a_golden_page_goes_through_ocr_with_ids_tiles_and_keys() -> None:
    data = (GOLDEN / "NEVIS-1" / "NEVIS-1.pdf").read_bytes()
    read = read_pages("fil_1", "pdf", data)[4]
    w, h = read.size_pt
    panel = PagePanel(panel_id="pnl_1", name="x", bbox=(0.05 * w, 0.05 * h, 0.8 * w, 0.85 * h), confidence=0.9)
    p = page(size_pt=read.size_pt, rotation_applied=read.rotation, panels=[panel], sha256=read.sha256)
    ctx, store, _ = context()

    def answer(im: ocr.OcrImage) -> list[ocr.OcrWord]:
        gray = Image.open(io.BytesIO(im.data)).convert("L").point(lambda v: 255 if v < 160 else 0)
        box = gray.getbbox()
        return [ocr.OcrWord("C1O", box, 0, 0.9)] if box else []

    engine = ocr.FakeOcrEngine(answer)
    out = s2_extraction.extract_page(ctx, p, 3, read, data, engine)
    assert out.render is not None and 150 <= out.render.dpi <= 300
    assert out.tiles and all(t.tile_id.startswith("tl_003_r") for t in out.tiles)
    assert len(engine.seen) == sum(1 for t in out.tiles if not t.is_blank)
    assert out.text_spans and all(s.span_id.startswith("ts_003_") for s in out.text_spans)
    assert all(set(s.text.split()) == {"C10"} and s.corrections for s in out.text_spans)
    assert all(t.panel_ids == ["pnl_1"] for t in out.tiles if not t.is_blank)
    assert out.wire_graph is not None and out.wire_graph.status == "built"
    assert out.vector is not None and out.vector.paths_uri in store.put_keys


def test_a_page_with_too_many_paths_skips_the_wire_graph() -> None:
    data = make_pdf(texts=[("Q1", 100, 700, 0)], lines=[(50, 600, 400, 600), (50, 500, 400, 500)])
    read = read_pages("fil_1", "pdf", data)[0]
    ctx, _, _ = context()
    out = s2_extraction.extract_page(
        ctx,
        page(size_pt=read.size_pt, text_source="pdf_text"),
        1,
        read,
        data,
        ocr.FakeOcrEngine(lambda im: []),
        ExtractionConfig(vector_too_complex=1),
    )
    assert out.wire_graph is not None and out.wire_graph.status == "skipped"
    assert [i.code for i in out.issues] == ["vector_too_complex"]


def test_a_page_with_no_text_says_so() -> None:
    data = make_pdf(lines=[(50, 600, 400, 600)])
    read = read_pages("fil_1", "pdf", data)[0]
    ctx, _, _ = context()
    out = s2_extraction.extract_page(ctx, page(size_pt=read.size_pt), 1, read, data, ocr.FakeOcrEngine(lambda im: []))
    assert [(i.code, i.severity) for i in out.issues] == [("no_text_found", "warning")]
    assert "עמוד 1" in out.issues[0].message


# ---------- the run step's line (prototype line 762) ----------


def progress_with(*pages: tuple[str, str | None, int | None]) -> Any:
    from types import SimpleNamespace

    from konboro.services.drawings import Progress

    rows = [(SimpleNamespace(route=route, text_source=text, tile_count=n), "f.pdf") for text, route, n in pages]
    return Progress(drawing=None, name="", files=[], runs=[], pages=rows, panels=[], quote_id=None)  # type: ignore[arg-type]


def test_the_run_step_says_how_the_text_was_read_and_counts_tiles() -> None:
    from konboro.services.drawings import stage_summary

    ocr_only = progress_with(("ocr", "process", 30), ("ocr", "process", 28), (None, "context", None))
    assert stage_summary(ocr_only, 2) == "שכבת טקסט חסרה, OCR על 2 עמודים · 58 אריחים"
    mixed = progress_with(("pdf_text", "process", 1), ("mixed", "process", 0))
    assert stage_summary(mixed, 2) == "שכבת טקסט חלקית, OCR על עמוד אחד · אריח אחד"
    assert stage_summary(progress_with(("pdf_text", "process", 4)), 2) == "טקסט מהקובץ · 4 אריחים"
