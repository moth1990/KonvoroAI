"""Upload checks (01 §4.2–4.3, §8): format by content, page counts without rendering, the check order."""

import io
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from konboro.services.intake import MB, Limits, check_file, check_upload, detect_format, message

NURSERY = Path(__file__).resolve().parents[3] / "golden" / "NURSERY-1" / "NURSERY-1.pdf"
A4 = (595.0, 842.0)


def pdf(pages: int = 1, size: tuple[float, float] = A4) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(*size)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def zipped(files: dict[str, bytes], extra: dict[str, bytes] | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in {**files, **(extra or {})}.items():
            z.writestr(name, data)
    return out.getvalue()


def xlsx(sheets: int) -> bytes:
    parts = {"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>"}
    parts |= {f"xl/worksheets/sheet{i}.xml": b"<worksheet/>" for i in range(1, sheets + 1)}
    return zipped(parts)


SAMPLES = {
    "pdf": pdf(),
    "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
    "jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 32,
    "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32,
    "heic": b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32,
    "xlsx": xlsx(2),
    "csv": 'פריט,כמות\nמא"ז 3P 16A,4\n'.encode(),
    "zip": zipped({"a.pdf": pdf()}),
    "dwg": b"AC1027" + b"\x00" * 64,
    "dxf": b"  0\nSECTION\n  2\nHEADER\n",
}


@pytest.mark.parametrize("fmt", SAMPLES)
def test_format_comes_from_the_content(fmt: str) -> None:
    assert detect_format(SAMPLES[fmt]) == fmt


def test_the_extension_does_not_matter() -> None:
    assert check_file("drawing.pdf", SAMPLES["dwg"], Limits()).error == "cad_not_supported"
    assert check_file("scan.dwg", SAMPLES["pdf"], Limits()).error is None


@pytest.mark.parametrize("data", [b"just some words here", b"\x00\x01\x02binary", b""])
def test_unknown_content_is_unsupported(data: bytes) -> None:
    assert detect_format(data) is None
    assert check_file("x.bin", data, Limits()).error == "unsupported_format"


@pytest.mark.parametrize("fmt", ["dwg", "dxf"])
def test_cad_files_get_the_v2_message(fmt: str) -> None:
    f = check_file(f"MAIN_BOARD.{fmt}", SAMPLES[fmt], Limits())
    assert f.error == "cad_not_supported"
    assert f.message == "קבצי DWG ו-DXF עדיין לא נתמכים. ייצאו PDF מתוכנת השרטוט (Plot ל-PDF) והעלו אותו."


def test_pages_are_counted_without_rendering() -> None:
    f = check_file("NURSERY-1.pdf", NURSERY.read_bytes(), Limits())
    assert (f.error, f.detected_format, f.page_count) == (None, "pdf", 9)
    assert check_file("p.png", SAMPLES["png"], Limits()).page_count == 1
    assert check_file("bom.xlsx", SAMPLES["xlsx"], Limits()).page_count == 2
    assert check_file("bom.csv", SAMPLES["csv"], Limits()).page_count == 1


def test_the_first_failing_check_wins() -> None:
    # Too large and a DWG: size is checked first (01 §4.3).
    big_dwg = SAMPLES["dwg"] + b"\x00" * (21 * MB)
    assert check_file("big.dwg", big_dwg, Limits()).error == "too_large"
    # Too many pages and a page too large: the count comes first.
    assert check_file("x.pdf", pdf(3, (5000, 3500)), Limits(max_pages_per_file=2)).error == "too_many_pages"


def test_size_limit_is_exactly_20_mb() -> None:
    at_limit = SAMPLES["csv"] + b"," * (20 * MB - len(SAMPLES["csv"]))
    assert check_file("ok.csv", at_limit, Limits()).error is None
    f = check_file("scan_site.pdf", at_limit + b",", Limits())
    assert f.error == "too_large"
    assert (
        f.message == "הקובץ scan_site.pdf גדול מ-20MB. אפשר לייצא אותו מחדש בלי תמונות ברזולוציה גבוהה, או לפצל אותו."
    )


def test_the_plan_sets_the_page_limit() -> None:
    f = check_file("project_full.pdf", pdf(31), Limits())
    assert f.error == "too_many_pages"
    assert f.message == message("too_many_pages", name="project_full.pdf", n=31, max=30)
    assert check_file("project_full.pdf", pdf(31), Limits(max_pages_per_file=60)).error is None


def test_a_page_over_2_square_metres_is_refused() -> None:
    # A0 (2384 × 3370 pt) is 1 m². 5000 × 3500 pt is about 2.18 m².
    assert check_file("a0.pdf", pdf(1, (2384, 3370)), Limits()).error is None
    f = check_file("huge.pdf", pdf(2, (5000, 3500)), Limits())
    assert (f.error, f.message) == ("page_too_large", message("page_too_large", page=1, name="huge.pdf"))


def test_a_broken_pdf_is_corrupt() -> None:
    assert check_file("x.pdf", b"%PDF-1.7\nnot really", Limits()).error == "file_corrupt"


def test_one_bad_file_rejects_the_whole_upload() -> None:
    result = check_upload([("NURSERY-1.pdf", NURSERY.read_bytes()), ("MAIN_BOARD.dwg", SAMPLES["dwg"])], Limits())
    assert not result.ok
    assert [(f.name, f.error) for f in result.files] == [
        ("NURSERY-1.pdf", None),
        ("MAIN_BOARD.dwg", "cad_not_supported"),
    ]


def test_every_file_is_reported_at_once() -> None:
    result = check_upload([("a.dwg", SAMPLES["dwg"]), ("b.bin", b"\x00\x01")], Limits())
    assert [f.error for f in result.files] == ["cad_not_supported", "unsupported_format"]


def test_too_many_files() -> None:
    result = check_upload([(f"{i}.csv", SAMPLES["csv"]) for i in range(21)], Limits())
    assert (result.ok, result.error) == (False, "too_many_files")


def test_too_many_pages_in_the_whole_drawing() -> None:
    result = check_upload([(f"{i}.pdf", pdf(30)) for i in range(7)], Limits())
    assert (result.ok, result.error, result.total_pages) == (False, "drawing_too_many_pages", 210)


def test_a_zip_is_unpacked_and_each_file_checked() -> None:
    archive = zipped({"panels/main.pdf": pdf(2), "bom.csv": SAMPLES["csv"]}, {"__MACOSX/._main.pdf": b"junk"})
    result = check_upload([("drawing.zip", archive)], Limits())
    assert result.ok
    assert [(f.name, f.detected_format, f.page_count) for f in result.files] == [
        ("drawing.zip/panels/main.pdf", "pdf", 2),
        ("drawing.zip/bom.csv", "csv", 1),
    ]


def test_a_zip_with_a_bad_file_or_a_zip_inside_is_rejected() -> None:
    result = check_upload([("d.zip", zipped({"a.pdf": pdf(), "b.dwg": SAMPLES["dwg"]}))], Limits())
    assert [f.error for f in result.files] == [None, "cad_not_supported"]
    nested = check_upload([("d.zip", zipped({"inner.zip": SAMPLES["zip"]}))], Limits())
    assert [f.error for f in nested.files] == ["zip_nested"]


def test_a_zip_that_unpacks_too_large_is_refused_before_reading() -> None:
    result = check_upload([("d.zip", zipped({"a.csv": SAMPLES["csv"]}))], Limits(max_zip_uncompressed_mb=0))
    assert [f.error for f in result.files] == ["zip_too_large"]


def test_the_hash_is_of_the_content() -> None:
    a, b = check_file("a.pdf", SAMPLES["pdf"], Limits()), check_file("b.pdf", SAMPLES["pdf"], Limits())
    assert a.sha256 == b.sha256 and len(a.sha256) == 64
