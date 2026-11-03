"""The BOM-only path (01 §5.8, S14): reading spreadsheets, the column mapping and what its model may see, a
picture's transcription checked in code, the row rules, the BOM words, and stage 4's rows → components. No real
model is called."""

import io
import json
import re
from datetime import date
from typing import Any

import pytest
from openpyxl import Workbook

from konboro.devtools import fake_llm
from konboro.pipeline.association import bom, schemas
from konboro.pipeline.bom import mapping, sheets, table, terms
from konboro.pipeline.bom.table import BomColumn, BomRow, BomTable
from konboro.pipeline.detection import library
from konboro.pipeline.intake.drawing import name_key
from konboro_llm import ImageInput, LLMClient
from konboro_llm.providers import FakeProvider
from konboro_llm.stages import table_transcription
from konboro_llm.stages.table_transcription import MappingAnswer, TableAnswer

SCH = schemas.default()
GOLDEN = json.loads(open("../golden/BOM-HW-1/labels.json", encoding="utf-8").read())  # noqa: SIM115


def xlsx(*sheets_rows: list[list[Any]], titles: tuple[str, ...] = ()) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]
    for i, rows in enumerate(sheets_rows):
        ws = wb.create_sheet(titles[i] if i < len(titles) else f"Sheet{i + 1}")
        for r in rows:
            ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --- spreadsheets ---------------------------------------------------------------------------------------------


def test_a_workbook_reads_one_sheet_per_page_as_text() -> None:
    data = xlsx(
        [["תיאור", "כמות", "מחיר"], ['מא"ז 1X16', 12, 18.5], ["מגען 3X25", 2.0, None], [None, None, None]],
        [],
        [["פריט", "כמות"], ["סליל הפסקה", 1]],
        titles=("לוח ראשי", "ריק", "לוח משנה"),
    )
    found = sheets.read("xlsx", data)
    assert [s.name for s in found] == ["לוח ראשי", "ריק", "לוח משנה"]
    assert found[0].rows == [["תיאור", "כמות", "מחיר"], ['מא"ז 1X16', "12", "18.5"], ["מגען 3X25", "2"]]
    assert found[1].rows == []


def test_cell_text() -> None:
    assert sheets.text(None) is None
    assert sheets.text("  ") is None
    assert sheets.text(3.0) == "3"
    assert sheets.text(0.1) == "0.1"
    assert sheets.text(True) == "TRUE"
    assert sheets.text(date(2026, 11, 2)) == "2026-11-02"
    assert sheets.text('מא"ז\n 1X16') == 'מא"ז 1X16'


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1255"])
@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_csv_in_hebrew_excel_encodings_and_delimiters(encoding: str, delimiter: str) -> None:
    body = delimiter.join(["פריט", "כמות"]) + "\r\n" + delimiter.join(['"מא""ז 1X16"', "12"]) + "\r\n"
    [sheet] = sheets.read("csv", body.encode(encoding))
    assert sheet.name is None
    assert sheet.rows == [["פריט", "כמות"], ['מא"ז 1X16', "12"]]


def test_a_broken_workbook_is_unreadable() -> None:
    with pytest.raises(sheets.UnreadableSheetError):
        sheets.read("xlsx", b"PK\x03\x04 not really a workbook")
    with pytest.raises(sheets.UnreadableSheetError):
        sheets.read("csv", b"\xff\xfe\x00\x81\x00")


# --- column mapping -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "role"),
    [
        ("תיאור", "item"),
        ("תאור פריט", "item"),
        ("Description", "item"),
        ("כמות", "quantity"),
        ("Qty", "quantity"),
        ("כמ'", "quantity"),
        ("מחיר יחידה", "price"),
        ('סה"כ', "price"),
        ("Unit price", "price"),
        ("שם לוח", "panel"),
        ('מק"ט', "model"),
        ("Part number", "model"),
        ("יצרן", "brand"),
        ("יח'", "unit"),
        ("מס'", "row_number"),
        ("#", "row_number"),
        ("הערות", None),
        (None, None),
    ],
)
def test_header_roles(header: str | None, role: str | None) -> None:
    assert mapping.role_of(header) == role


def test_letters() -> None:
    assert [mapping.letter(i) for i in (0, 1, 25, 26, 27, 701)] == ["A", "B", "Z", "AA", "AB", "ZZ"]


def test_masked_leaves_no_number() -> None:
    assert mapping.masked('מא"ז 3X16') == 'מא"ז <int>X<int>'
    assert mapping.masked("₪ 1,250.00") == "₪ <decimal>.<int>"
    assert not re.search(r"\d", mapping.masked("12.50 / 7 / 1,5"))


def test_the_header_row_is_found_below_a_title() -> None:
    rows: list[sheets.Cells] = [["הצעת מחיר לוח 3"], [], ["מס'", "תיאור", "כמות", "מחיר"], ["1", "מגען", "2", "120"]]
    assert mapping.header_row(rows) == 2
    unknown: list[sheets.Cells] = [["רכיב", "יחידות"], ["מגען", "2"]]
    assert mapping.header_row(unknown) == 0  # "רכיב" is known; the other is the model's
    plain: list[sheets.Cells] = [["אלפא", "בטא"], ["מגען", "2"]]
    assert mapping.header_row(plain) == 0  # text over a number
    none: list[sheets.Cells] = [['מא"ז', "2"], ["מגען", "1"]]
    assert mapping.header_row(none) is None


def test_code_maps_known_headers_without_the_model() -> None:
    rows: list[sheets.Cells] = [["תיאור", "כמות", "מחיר"], ["מגען 3X25", "2", "120"]]

    def ask(_: str) -> MappingAnswer:
        raise AssertionError("no model for headers code knows")

    m = mapping.map_sheet(rows, ask)
    assert [(c.role, c.by) for c in m.columns] == [("item", "code"), ("quantity", "code"), ("price", "code")]
    assert m.sure and m.header_row == 0


def test_the_model_sees_no_number_and_maps_only_what_code_does_not_know() -> None:
    """Non-negotiable 6: a price column can't be told from a quantity column before the mapping, so the model gets
    the shapes of numbers only (S14 decision 2). Its roles never override code's."""
    rows: list[sheets.Cells] = [
        ["Artikel", "Menge", "Preis", "תיאור"],
        ["iC60N C16", "12", "18.50", 'מא"ז 1X16'],
        ["LC1D25", "2", "₪120", "מגען 3X25"],
    ]
    seen: list[str] = []

    def ask(columns: str) -> MappingAnswer:
        seen.append(columns)
        return MappingAnswer.model_validate(
            {
                "columns": [
                    {"column": "A", "role": "model"},
                    {"column": "B", "role": "quantity"},
                    {"column": "C", "role": "price"},
                    {"column": "D", "role": "other"},  # code knows D: ignored
                ]
            }
        )

    m = mapping.map_sheet(rows, ask)
    assert [(c.role, c.by) for c in m.columns] == [
        ("model", "model"),
        ("quantity", "model"),
        ("price", "model"),
        ("item", "code"),
    ]
    assert not m.sure  # the model touched it: the user confirms (S14 decision 1)
    [text] = seen
    assert not re.search(r"\d", text)
    assert "<int>" in text and "<decimal>" in text and "₪<int>" in text


def test_the_mapping_request_carries_no_digit_of_the_sheet() -> None:
    """The request the client sends: the fixed prompt around the masked columns, nothing else from the file."""
    requests: list[Any] = []

    def answer(request: Any) -> dict[str, Any]:
        requests.append(request)
        return {"columns": [{"column": "A", "role": "item"}, {"column": "B", "role": "quantity"}]}

    client = LLMClient({"anthropic": FakeProvider(answer)})
    rows: list[sheets.Cells] = [["X", "Y"], ["מגען 3X25", "1234567"], ["ABC-9876", "4321"]]
    m = mapping.map_sheet(rows, lambda c: table_transcription.map_columns(client, c).data)
    assert [c.role for c in m.columns] == ["item", "quantity"]
    [request] = requests
    columns = request.user_text.split("\n\n", 1)[1]
    assert not re.search(r"\d", columns)
    for secret in ("1234567", "4321", "9876", "25"):
        assert secret not in request.user_text
    assert not request.images


def test_no_header_and_no_model_leaves_columns_other() -> None:
    m = mapping.map_sheet([["מגען", "2"]], None)
    assert [c.role for c in m.columns] == ["other", "other"]
    assert m.header_row is None and not m.sure


# --- a picture's transcription --------------------------------------------------------------------------------


def answer_of(rows: list[tuple[str | None, str | None]], **extra: Any) -> TableAnswer:
    return TableAnswer.model_validate(
        {
            "panel_name": extra.get("panel_name"),
            "project_name": extra.get("project_name"),
            "columns": extra.get(
                "columns", [{"header": "כמות", "role": "quantity"}, {"header": "פרטים", "role": "item"}]
            ),
            "rows": [
                {
                    "cells": [{"text": q, "confidence": 0.9}, {"text": t, "confidence": 0.8}],
                    "box": extra.get("box", [0, 100 + 50 * n, 1000, 140 + 50 * n]),
                }
                for n, (q, t) in enumerate(rows)
            ],
        }
    )


def test_the_answer_has_no_field_for_the_customer() -> None:
    """01 §5.8 / 00 §7.1: "לכבוד" and the customer's contact details are not kept; there is nowhere for them to go."""
    fields = set(TableAnswer.model_fields)
    assert fields == {"panel_name", "project_name", "columns", "rows"}
    assert set(table_transcription.Row.model_fields) == {"cells", "box"}


def test_a_picture_is_checked_in_code() -> None:
    a = TableAnswer.model_validate(
        {
            "panel_name": " לוח קומה 2 ",
            "project_name": "",
            "columns": [
                {"header": "כמות", "role": "quantity"},
                {"header": "פרטים", "role": "item"},
                {"header": "מחיר", "role": "price"},
            ],
            "rows": [
                {
                    "cells": [
                        {"text": "2", "confidence": 1.4},
                        {"text": " מגען  3X25 ", "confidence": -1},
                        {"text": "₪99", "confidence": 1},
                    ],
                    "box": [900, 210, 100, 200],
                },
                {"cells": [{"text": "1", "confidence": 0.9}], "box": [0, 980, 1000, 1005]},  # short, past the edge
                {"cells": [{"text": None, "confidence": 1}, {"text": None, "confidence": 1}], "box": [0, 0, 1, 1]},
            ],
        }
    )
    t = table.from_answer(a, (500.0, 800.0))
    assert t.source == "image" and t.mapping_sure
    assert (t.panel_name, t.project_name) == ("לוח קומה 2", None)
    assert [r.cells for r in t.rows] == [["2", "מגען 3X25", None], ["1", None, None]]  # money dropped, empty row out
    assert t.rows[0].confidence == [1.0, 0.0, 1.0]
    assert t.rows[0].bbox == pytest.approx((50.0, 160.0, 450.0, 168.0))
    assert t.rows[1].bbox == pytest.approx((0.0, 784.0, 500.0, 800.0))
    assert t.cropped  # the last row touches the bottom edge (bom_possibly_cropped)


def test_a_last_row_clear_of_the_edge_is_not_cropped() -> None:
    assert not table.from_answer(answer_of([("1", "מגען")]), (100.0, 100.0)).cropped


# --- row rules ------------------------------------------------------------------------------------------------


def test_a_row_without_quantity_continues_the_one_above_in_a_picture() -> None:
    """BOM-HW-1 row 8: "רב מודד SATEC…" goes on in "התראות לצורך הפעלת ממסר" on the next line."""
    t = table.from_answer(
        answer_of([("1", "רב מודד SATEC PRO335 כולל"), (None, "התראות לצורך הפעלת ממסר"), ("1", "לחצן חירום")]),
        (1000.0, 1000.0),
    )
    found = table.items(t)
    assert [(i.rows, i.text, i.quantity) for i in found] == [
        ([1, 2], "רב מודד SATEC PRO335 כולל התראות לצורך הפעלת ממסר", 1),
        ([3], "לחצן חירום", 1),
    ]
    assert found[0].bbox == pytest.approx((0.0, 100.0, 1000.0, 190.0))


def spreadsheet(rows: list[list[str | None]], roles: list[str]) -> BomTable:
    return BomTable(
        source="spreadsheet",
        columns=[
            BomColumn(index=i, letter=mapping.letter(i), header=None, role=r, by="code")  # type: ignore[arg-type]
            for i, r in enumerate(roles)
        ],
        rows=[BomRow(row=n, cells=r) for n, r in enumerate(rows, start=2)],
        mapping_sure=True,
    )


def test_spreadsheet_rules() -> None:
    t = spreadsheet(
        [
            ["לוח ראשי", None, None, None],  # a heading: no quantity is made up
            ['מא"ז 1X16', "12", "לוח ראשי", "iC60N"],
            ["מגען 3X25", "2 יח'", None, None],  # the panel cell merged: the one above
            ["כבל", "2.5", "לוח משנה", None],  # not a whole number
            ['סה"כ', "16", None, None],
            ["מגען 3X25", "0", None, None],  # zero: nothing to quote, but a number
            [None, None, None, None],
        ],
        ["item", "quantity", "panel", "model"],
    )
    found = table.items(t)
    assert [(i.rows, i.text, i.quantity, i.panel, i.model) for i in found] == [
        ([3], 'מא"ז 1X16', 12, "לוח ראשי", "iC60N"),
        ([4], "מגען 3X25", 2, "לוח ראשי", None),
        ([5], "כבל", None, "לוח משנה", None),
        ([7], "מגען 3X25", None, "לוח משנה", None),
    ]
    assert found[2].issues == ["bom_quantity_unreadable"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5", (5, True)),
        (" 12 ", (12, True)),
        ("x3", (3, True)),
        ("4 יח'", (4, True)),
        ("1.5", (None, True)),
        ("0", (None, True)),
        ("", (None, False)),
        (None, (None, False)),
        ("ללא", (None, False)),
    ],
)
def test_quantity(text: str | None, expected: tuple[int | None, bool]) -> None:
    assert table.quantity(text) == expected


def test_user_roles_settle_the_mapping() -> None:
    t = spreadsheet([["מגען", "2"]], ["other", "other"]).model_copy(update={"mapping_sure": False})
    assert not table.mapping_complete(t)
    u = table.with_roles(t, {0: "item", 1: "quantity"})
    assert [(c.role, c.by) for c in u.columns] == [("item", "user"), ("quantity", "user")]
    assert u.mapping_sure and table.mapping_complete(u)


def test_panels_of_a_bom_only_drawing() -> None:
    a = spreadsheet(
        [["מגען", "1", "לוח א"], ["מגען", "1", "לוח ב"], ["מגען", "1", None]], ["item", "quantity", "panel"]
    )
    b = spreadsheet([["מגען", "1", None]], ["item", "quantity", "panel"])
    c = BomTable(source="image", panel_name="לוח קומה 3", columns=[], rows=[], mapping_sure=True)
    assert table.panels([("pg_a", a), ("pg_b", b)], None) == [
        ("לוח א", ["pg_a"]),
        ("לוח ב", ["pg_a"]),
        ("לוח 1", ["pg_b"]),
    ]
    assert table.panels([("pg_b", b)], "לוח ראשי") == [("לוח ראשי", ["pg_b"])]
    assert table.panels([("pg_c", c)], "לוח ראשי") == [("לוח קומה 3", ["pg_c"])]


# --- BOM words ------------------------------------------------------------------------------------------------


def test_every_term_names_a_family_and_class_of_the_library() -> None:
    classes = {c.symbol_class: c.family for c in library.CLASSES}
    for written, family, cls in terms.TERMS:
        assert family in {c.family for c in library.CLASSES}, written
        assert cls is None or classes[cls] == family, written


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("מפסק 3X250", ("circuit_breaker", terms.UNTYPED)),  # 05 §5.5.1 decides the class by its current
        ("מפסק3X125", ("circuit_breaker", terms.UNTYPED)),
        ('מא"ז 1X16', ("circuit_breaker", "mcb")),
        ("מא״ז 16+N", ("circuit_breaker", "mcb")),
        ('מא"ז פחת 2X16', ("rcbo", "rcbo")),
        ("פחת 4X40", ("rcd", "rcd")),
        ("מפסק פחת 4X40", ("rcd", "rcd")),
        ("ממסר פחת 4X40A", ("rcd", "rcd")),  # BUG-056
        ("ממסר פיקוד", ("relay", "relay")),
        ("מגן מתח יתר 40KA", ("surge_protector", "surge_protector")),
        ("סליל הפסקה", ("shunt_trip", "shunt_trip")),
        ("משנה זרם 250/5", ("current_transformer", "current_transformer")),
        ("רב מודד SATEC כולל התראות לצורך הפעלת ממסר", ("energy_meter", "energy_meter")),
        ("לחצן חירום", ("push_button", "emergency_button")),
        ("מגען 2X25", ("contactor", "contactor")),
        ("שעון שבת", ("time_switch", "time_switch")),
        ("MCB C16", ("circuit_breaker", "mcb")),
        ("ממפסק", None),  # inside another word
        ("ארון", None),
    ],
)
def test_bom_words(text: str, expected: tuple[str, str] | None) -> None:
    assert terms.family_of(text) == expected


# --- stage 4: rows → components -------------------------------------------------------------------------------


def golden_table() -> BomTable:
    """BOM-HW-1 as its labels transcribe it: one row per line of the form, row 8's second line, and row 2."""
    rows: list[tuple[str | None, str | None]] = []
    for r in sorted(GOLDEN["rows"], key=lambda r: r["row"]):
        if r["row"] == 8:
            rows += [("1", "רב מודד SATEC PRO335 כולל"), (None, "התראות לצורך הפעלת ממסר")]
        elif r["row"] == 15:
            rows += [("1", "מפסק 3X40"), ("4", r["raw"])]  # the form's own line 2, and its 4 on line 15
        else:
            rows.append((str(r["qty"]), r["raw"]))
    return table.from_answer(answer_of(rows, panel_name='לוח חשמל קומה י"א'), (600.0, 1000.0))


def test_bom_hw_1_rows_become_components() -> None:
    t = golden_table()
    found = bom.rows([("pg_1", t)], {name_key('לוח חשמל קומה י"א'): "pnl_1"}, None, SCH)
    comps = bom.components("drw_1", found)
    assert len(found) == 20
    by_text = {c.explicit_texts[0]: c for c in comps}
    breaker = by_text["מפסק 3X250"]
    assert (breaker.family, breaker.symbol_class, breaker.quantity) == ("circuit_breaker", terms.UNTYPED, 1)
    assert breaker.attributes["current_a"].value == 250 and breaker.attributes["poles"].value == 3
    mcb = by_text['מא"ז 16+N']
    assert (mcb.attributes["current_a"].value, mcb.attributes["poles"].value, mcb.attributes["neutral"].value) == (
        16,
        1,
        True,
    )
    rcd = by_text["פחת 4X40"]
    assert (rcd.family, rcd.quantity) == ("rcd", 6)
    assert rcd.attributes["residual_ma"].value is None  # 30 mA is stage 5's system default (05 §5.5), not read here
    ct = by_text["משנה זרם 250/5"]
    assert (ct.attributes["ratio_primary_a"].value, ct.attributes["ratio_secondary_a"].value, ct.quantity) == (
        250,
        5,
        3,
    )
    spd = by_text["מגן מתח יתר 40KA"]
    assert spd.attributes["imax_ka"].value == 40
    meter = by_text["רב מודד SATEC PRO335 כולל התראות לצורך הפעלת ממסר"]
    assert (meter.family, meter.brand_hint) == ("energy_meter", "SATEC") and "PRO335" in meter.explicit_texts
    assert by_text['מא"ז 1X16'].quantity == 54
    assert sum(c.quantity for c in comps) == 91
    for c in comps:
        assert c.panel_id == "pnl_1"
        for a in c.attributes.values():
            assert a.value is None or (a.source == "bom" and a.span_ids == [])
    for r in found:
        assert r.instance.method == "bom" and r.instance.det_id is None and r.instance.rows and r.instance.bbox


def test_the_same_product_on_two_rows_merges_and_a_different_one_does_not() -> None:
    t = spreadsheet(
        [['מא"ז 1X16', "10"], ['מא"ז 1X16', "4"], ['מא"ז 1X20', "1"], ["דבר לא מוכר", "3"], ["מגען", "x"]],
        ["item", "quantity"],
    )
    assert bom.rows([("pg_1", t)], {}, None, SCH) == []  # no panel: nothing to point at
    found = bom.rows([("pg_1", t)], {"לוח 1": "pnl_1"}, None, SCH)
    comps = bom.components("drw_1", found)
    assert [(c.explicit_texts[0], c.quantity, c.status) for c in comps] == [
        ('מא"ז 1X16', 14, "accepted"),
        ('מא"ז 1X20', 1, "accepted"),
        ("דבר לא מוכר", 3, "uncertain"),  # red: the user says what it is
        ("מגען", 0, "uncertain"),  # no quantity is made up
    ]
    unknown = comps[2]
    assert unknown.family == bom.UNKNOWN_FAMILY and unknown.confidence <= 0.4
    codes = [i.code for r in found for i in r.issues]
    assert "bom_unknown_item" in codes and "bom_quantity_unreadable" in codes


def test_an_unconfirmed_mapping_keeps_its_rows_yellow() -> None:
    t = spreadsheet([['מא"ז 1X16', "10"]], ["item", "quantity"]).model_copy(update={"mapping_sure": False})
    [row] = bom.rows([("pg_1", t)], {"לוח 1": "pnl_1"}, None, SCH)
    assert row.instance.status == "uncertain"
    assert [i.code for i in row.issues] == ["bom_mapping_unsure", "missing_required"]


def test_the_stand_in_model_answers_both_calls() -> None:
    client = LLMClient(fake_llm.fake_providers())
    picture = table_transcription.transcribe(client, ImageInput(b"x"))
    t = table.from_answer(picture.data, (595.0, 842.0))
    assert t.panel_name == fake_llm.BOM_PANEL and not t.cropped
    assert [i.text for i in table.items(t)][-1] == "רב מודד SATEC כולל יציאת ממסר"
    m = table_transcription.map_columns(client, "- A: header 'X'; samples: (empty)\n- B: header 'Y'; samples: <int>")
    assert [c.role for c in m.data.columns] == ["item", "quantity"]


def _named(source: str, panel: str | None) -> BomTable:
    return BomTable(source=source, panel_name=panel, columns=[], rows=[], mapping_sure=True)  # type: ignore[arg-type]


def test_only_a_picture_heading_needs_its_panel_name_checked() -> None:
    # BUG-030: the model gives no confidence for a heading; a picture's is always the user's to check.
    from konboro.pipeline.stages.s1_intake import heading_panel_from_picture

    photo = {"pg_a": _named("image", 'לוח חשמל קומה י"א')}
    assert heading_panel_from_picture(photo) == 'לוח חשמל קומה י"א'
    assert heading_panel_from_picture({"pg_a": _named("image", None)}) is None
    assert heading_panel_from_picture({"pg_s": _named("spreadsheet", "לוח 2")}) is None
    assert heading_panel_from_picture({"pg_s": _named("spreadsheet", "לוח 2"), **photo}) == 'לוח חשמל קומה י"א'
