"""Stage 1's code decisions (01): routing (§7), confirmation (§5.6), geometry and text source (§5.2), quality
(§5.3), the check on the classifier's answer (00 §7.2), panels (§5.4), input kind (§4.4), the revision rule (§4.5)
and template fingerprints (§5.7). Pages come from the golden PDFs; no model is called."""

import io
from pathlib import Path
from typing import get_args

import pytest
from PIL import Image, ImageDraw, ImageFilter
from pydantic import ValidationError

from konboro.contracts.intake import PageKind
from konboro.pipeline.intake import checks, classify, routing, templates
from konboro.pipeline.intake.drawing import PagePanels, input_kind, is_revision, merge_panels
from konboro.pipeline.intake.pages import PageRead, read_pages, render
from konboro_llm.stages.page_classification import ClassificationAnswer

GOLDEN = Path(__file__).resolve().parents[3] / "golden"


def golden(name: str) -> tuple[bytes, list[PageRead]]:
    path = next((GOLDEN / name).glob(f"{name}.*"))
    data = path.read_bytes()
    return data, read_pages("fil", "jpg" if path.suffix == ".jpg" else "pdf", data)


# --- routing (01 §7) ----------------------------------------------------------------------------------------------

ALL_KINDS: tuple[PageKind, ...] = get_args(PageKind)


@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.84, 0.85, 1.0])
def test_every_kind_has_a_route_and_diagrams_are_never_skipped(kind: PageKind, confidence: float) -> None:
    route = routing.route(kind, confidence)
    assert route in ("process", "context", "skip")
    if kind in ("single_line_diagram", "control_diagram", "other"):
        assert route == "process"


@pytest.mark.parametrize(
    ("kind", "confidence", "has_panels", "route"),
    [
        ("technical_data", 0.3, False, "context"),  # the rows S08 adds to 01 §7
        ("factory_template", 0.85, False, "skip"),
        ("factory_template", 0.84, False, "process"),  # unsure: decode it (01 §1)
        ("title_cover", 0.95, False, "skip"),
        ("title_cover", 0.5, False, "process"),
        ("title_cover", 0.99, True, "process"),  # a cover with a panel on it contradicts itself
        ("legend", 0.2, False, "context"),
        ("terminal_diagram", 0.9, False, "context"),
    ],
)
def test_route_table(kind: PageKind, confidence: float, has_panels: bool, route: str) -> None:
    assert routing.route(kind, confidence, has_panels) == route


def page(kind: PageKind, confidence: float = 0.95, by: str = "model") -> routing.RoutedPage:
    return routing.RoutedPage(kind, confidence, by)


@pytest.mark.parametrize(
    ("pages", "hint", "reasons"),
    [
        ([page("single_line_diagram"), page("legend")], None, []),
        ([page("single_line_diagram", 0.84)], None, ["low_confidence"]),
        ([page("single_line_diagram", 0.4, "user")], None, []),  # the user settled it
        ([page("legend"), page("general_notes")], None, ["no_diagram_pages"]),
        ([page("bom_table", 1.0)], None, []),  # a spreadsheet has no diagram by nature
        ([page("control_diagram")], 2, ["panel_count_mismatch"]),
    ],
)
def test_confirmation_reasons(pages: list[routing.RoutedPage], hint: int | None, reasons: list[str]) -> None:
    assert routing.confirmation_reasons(pages, panel_count=1, hinted_panels=hint) == reasons


# --- page reading and code checks (01 §5.1–5.3) -------------------------------------------------------------------


def test_cad_text_drawn_as_lines_is_read_by_ocr() -> None:
    """01 §5.2: 26-993 has a text layer of a few "ABB"s, and thousands of letters drawn as lines."""
    _, pages = golden("26-993")
    assert [p.rotation for p in pages] == [90] * 5  # the PDF's /Rotate (labels: page_rotation 90)
    assert {checks.geometry_source(p) for p in pages} == {"vector"}
    assert {checks.text_source(p) for p in pages} == {"ocr"}
    assert pages[1].chars == 9 and checks.text_coverage(pages[1]) < 0.01


@pytest.mark.parametrize("name", ["6199-2-50", "NEVIS-1", "NURSERY-1"])
def test_golden_pages_are_vector_with_ocr_text(name: str) -> None:
    _, pages = golden(name)
    assert {(checks.geometry_source(p), checks.text_source(p)) for p in pages} == {("vector", "ocr")}


def test_page_hashes_are_of_content_and_stable() -> None:
    data, pages = golden("NEVIS-1")
    again = read_pages("other-file", "pdf", data)
    assert [p.sha256 for p in pages] == [p.sha256 for p in again]
    assert len({p.sha256 for p in pages}) == 9


def test_sizes_are_after_rotation_and_images_use_their_dpi() -> None:
    _, pdf_pages = golden("NEVIS-1")
    assert pdf_pages[0].size_pt == (842.0, 595.0)  # landscape once /Rotate 270 is applied
    _, (photo,) = golden("BOM-HW-1")
    assert (photo.dpi, photo.size_pt) == (144.0, (421.5, 714.0))  # 843 × 1428 px at 144 DPI


def test_exif_orientation_turns_a_photo_upright() -> None:
    img = Image.new("RGB", (300, 100), "white")  # stored landscape, shown portrait
    exif = img.getexif()
    exif[0x0112] = 6  # "rotate 90 CW to view"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    (read,) = read_pages("fil", "jpg", out.getvalue())
    assert (read.rotation, read.size_pt) == (270, (100.0, 300.0))


def test_heic_is_read() -> None:
    """A 64 × 32 iPhone-format picture (made with macOS `sips`; this libheif build only decodes, 12 §8)."""
    (read,) = read_pages("fil", "heic", (Path(__file__).parent / "fixtures" / "sample.heic").read_bytes())
    assert (read.size_pt, read.fmt) == ((64.0, 32.0), "heic")


def handwriting(blur: float = 0, size: tuple[int, int] = (900, 1400)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for row in range(40, size[1] - 40, 34):
        for col in range(60, size[0] - 60, 46):
            draw.line([(col, row), (col + 30, row + 18)], fill="black", width=3)
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


def as_page(img: Image.Image) -> PageRead:
    out = io.BytesIO()
    img.save(out, "PNG")
    return read_pages("fil", "png", out.getvalue())[0]


@pytest.mark.parametrize(
    ("img", "quality"),
    [
        (handwriting(), "ok"),
        (handwriting(blur=4), "blurry"),
        (handwriting(size=(500, 700)), "low_resolution"),
    ],
    ids=["sharp", "blurred", "small"],
)
def test_photo_quality(img: Image.Image, quality: str) -> None:
    p = as_page(img)
    assert checks.quality(p, "raster", img).quality == quality


def test_a_drawing_running_off_the_picture_is_cropped() -> None:
    img = handwriting()
    ImageDraw.Draw(img).rectangle([0, 0, 899, 30], fill="black")  # ink all along the top edge
    assert checks.quality(as_page(img), "raster", img).quality == "cropped"


def test_the_golden_photo_is_readable() -> None:
    data, (photo,) = golden("BOM-HW-1")
    assert checks.quality(photo, "raster", render(photo, data, 1024)).quality == "ok"


def test_vector_pages_are_always_readable() -> None:
    _, pages = golden("NEVIS-1")
    assert checks.quality(pages[0], "vector", None).quality == "ok"


@pytest.mark.parametrize(
    ("text", "ratio"),
    [("לוח ראשי F1 C16A", 0.0), ("ab", 0.6), ("", 0.0), ("��", 1.0)],
)
def test_garbage_ratio(text: str, ratio: float) -> None:
    assert checks.garbage_ratio(text) == pytest.approx(ratio)


# --- the classifier's answer, checked (00 §7.2) ---------------------------------------------------------------------


def answer(**changes: object) -> ClassificationAnswer:
    fields: dict[str, object] = {
        "page_kind": "single_line_diagram",
        "page_kind_confidence": 0.9,
        "orientation": 0,
        "component_labels": "tags_and_models",
        "panels": [{"name": " לוח  ראשי ", "bbox": [100, 100, 600, 900], "confidence": 0.9}],
        "regions": [{"region_kind": "title_block", "bbox": [700, 850, 1000, 1000], "confidence": 0.8}],
        "title_block": {"drawing_number": "26/952-5", "date": "2026-10-05", "designer": "  ", "revision": None},
        "reasoning": "x",
    }
    fields.update(changes)
    return ClassificationAnswer.model_validate(fields)


def test_kinds_outside_the_closed_list_are_refused() -> None:
    with pytest.raises(ValidationError):
        answer(page_kind="poster")
    with pytest.raises(ValidationError):
        answer(page_kind_confidence=1.2)


def test_boxes_become_points_and_blanks_become_null() -> None:
    checked = classify.check(answer(), (842.0, 595.0))
    (panel,) = checked.panels
    assert (panel.name, panel.bbox) == ("לוח ראשי", (84.2, 59.5, 505.2, 535.5))
    assert checked.title_block is not None
    assert (checked.title_block.drawing_number, checked.title_block.designer) == ("26/952-5", None)


def test_an_empty_box_is_dropped() -> None:
    checked = classify.check(answer(panels=[{"bbox": [500, 500, 500, 900], "confidence": 0.9}]), (842.0, 595.0))
    assert (checked.panels, checked.dropped) == ([], 1)


def test_an_impossible_date_is_not_evidence() -> None:
    checked = classify.check(answer(title_block={"date": "2026-02-31", "drawing_number": "E-1"}), (100.0, 100.0))
    assert checked.title_block is not None and checked.title_block.date is None


def test_a_sideways_answer_turns_its_boxes() -> None:
    """The model saw a portrait image of a landscape page and says it must turn 90° clockwise to read."""
    checked = classify.check(
        answer(orientation=90, panels=[{"bbox": [0, 0, 500, 250], "confidence": 1}]), (600.0, 800.0)
    )
    (panel,) = checked.panels
    assert panel.bbox == (600.0, 0.0, 800.0, 300.0)  # on the 800 × 600 upright page


def test_stored_findings_round_trip() -> None:
    checked = classify.check(answer(), (842.0, 595.0))
    panels, regions = classify.from_stored(classify.stored(checked.panels, checked.regions))
    assert (panels, regions) == (checked.panels, checked.regions)


# --- panels, input kind, revisions (01 §5.4, §4.4, §4.5) -------------------------------------------------------------

BOX = (0.0, 0.0, 10.0, 10.0)


def test_panels_merge_by_name_and_count_only_process_pages() -> None:
    merged = merge_panels(
        [
            PagePanels("pg_1", "context", [("לוח ראשי", BOX, 0.9)]),  # a front view: not counted (01 §5.5)
            PagePanels("pg_2", "process", [("לוח ראשי", BOX, 0.9)]),
            PagePanels("pg_3", "process", [("לוח  ראשי", BOX, 0.7), ("לוח סככה", BOX, 0.95)]),
            PagePanels("pg_4", "process", []),
        ],
        None,
    )
    assert [(p.name, p.page_ids, p.confidence) for p in merged] == [
        ("לוח ראשי", ["pg_2", "pg_3"], 0.7),
        ("לוח סככה", ["pg_3"], 0.95),
        ("לוח 1", ["pg_4"], 1.0),  # two named panels: an unnamed page can't be given to either
    ]


def test_unnamed_panels_take_the_title_block_name() -> None:
    merged = merge_panels([PagePanels(f"pg_{n}", "process", [(None, BOX, 0.9)]) for n in range(5)], "KARWANI")
    assert [(p.name, len(p.page_ids)) for p in merged] == [("KARWANI", 5)]


def test_no_process_pages_means_no_panels() -> None:
    assert merge_panels([PagePanels("pg_1", "skip", [("x", BOX, 1.0)])], None) == []


@pytest.mark.parametrize(
    ("formats", "kinds", "labels", "kind"),
    [
        (["xlsx"], ["bom_table"], [], "bom_only"),
        (["jpg"], ["bom_table"], [], "bom_only"),
        (["pdf", "xlsx"], ["single_line_diagram", "bom_table"], ["tags_and_models"], "mixed"),
        (["pdf"], ["single_line_diagram"] * 3, ["tags_and_models", "tags_and_models", "none"], "factory_drawing"),
        (["pdf"], ["single_line_diagram"] * 2, ["tags_and_models", "none"], "designer_plan"),
        (["pdf"], ["single_line_diagram"], [], "designer_plan"),
    ],
)
def test_input_kind(formats: list[str], kinds: list[str], labels: list[str], kind: str) -> None:
    assert input_kind(formats, kinds, labels) == kind


@pytest.mark.parametrize(
    ("prev", "new", "shared", "revision"),
    [
        ("26/952-5", "26/952-5", 0, True),
        ("26/952-5", " 26 952 5 ", 0, True),  # the same number written otherwise
        ("26/952-5", "26/952", 0, False),
        (None, None, 5, True),  # 5 of 10 pages identical: half is enough
        (None, None, 4, False),
        ("A-1", "B-2", 10, True),  # either rule is enough (S08 decision)
    ],
)
def test_revision_rule(prev: str | None, new: str | None, shared: int, revision: bool) -> None:
    previous = {f"h{i}" for i in range(10)}
    pages = [f"h{i}" for i in range(shared)] + [f"n{i}" for i in range(10 - shared)]
    assert is_revision(prev, new, previous, pages) is revision


# --- templates (01 §5.7) ------------------------------------------------------------------------------------------


def fingerprints(name: str) -> list[str]:
    data, pages = golden(name)
    return [templates.fingerprint(render(p, data, 1024)) for p in pages]


def test_the_shared_template_page_matches_and_others_do_not() -> None:
    """NEVIS-1 pages 2–3 are its templates. NURSERY-1 page 3 is the same page; its page 2 is the same tables in
    another layout and must not match. (The factory's technical-data form, page 1 of both, is near-identical too,
    which is why only `factory_template` pages become templates.)"""
    nevis, nursery = fingerprints("NEVIS-1"), fingerprints("NURSERY-1")
    assert templates.similarity(nevis[2], nursery[2], None) >= templates.MATCH
    others = [
        templates.similarity(nevis[t], b, None) for t in (1, 2) for j, b in enumerate(nursery) if (t, j) != (2, 2)
    ]
    assert max(others) < templates.MATCH


def test_best_match_needs_the_threshold() -> None:
    fp = fingerprints("NEVIS-1")[2]
    saved = [templates.Template("tpl_1", "p", "factory_template", fp, None)]
    assert templates.best_match(fp, saved) == (saved[0], 1.0)
    assert templates.best_match(fingerprints("NEVIS-1")[4], saved) is None


@pytest.mark.parametrize(
    ("a", "b"), [("ס.ס לוחות חשמל ובקרה", " ס.ס  לוחות חשמל ובקרה "), ('כהן "הנדסה"', "כהן הנדסה")]
)
def test_producer_key(a: str, b: str) -> None:
    assert templates.producer_key(a) == templates.producer_key(b)
