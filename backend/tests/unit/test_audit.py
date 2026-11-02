"""The quote audit (11, S15): reading the quote and its arithmetic, signing its lines, matching them to the drawing's
components, the nine difference types, their money, and the golden quotes against their labels (the oracle: the
labels stand in for the pipeline's components). No real model is called."""

import io
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from eval.normalizers import load
from konboro.contracts.common import StageIssue
from konboro.contracts.merge import AttributeValue, Component, Instance, MergeResult
from konboro.db import models as m
from konboro.devtools import fake_llm
from konboro.pipeline.audit import quote as q
from konboro.pipeline.audit.differences import audit, describe, find_price
from konboro.pipeline.audit.match import DrawnComponent, assign, compare
from konboro.pipeline.audit.signature import sign, split_included
from konboro.pipeline.audit.step import drawn_components
from konboro.pipeline.bom import sheets
from konboro.services.audits import evidence_boxes
from konboro_llm import ImageInput, LLMClient
from konboro_llm.providers import FakeProvider
from konboro_llm.stages import table_transcription
from konboro_llm.stages.table_transcription import QuoteAnswer

GOLDEN = Path(__file__).resolve().parents[3] / "golden"
AUX = frozenset({"terminal"})


def line(
    index: int, text: str, qty: int | str | None, unit: str | None = None, total: str | None = None
) -> q.QuoteLine:
    qty_d = Decimal(qty) if qty is not None else None
    unit_d = Decimal(unit) if unit is not None else None
    total_d = Decimal(total) if total is not None else (qty_d * unit_d if qty_d and unit_d else None)
    return q.QuoteLine(index=index, text=text, qty=qty_d, unit_price=unit_d, total=total_d)


def read(*lines: q.QuoteLine, totals: list[q.QuoteTotal] | None = None) -> q.QuoteRead:
    return q.QuoteRead(source="spreadsheet", lines=list(lines), totals=totals or [])


def comp(
    cid: str,
    family: str,
    qty: int = 1,
    designators: tuple[str, ...] = (),
    cls: str = "unknown_symbol",
    pages: tuple[int, ...] = (),
    confidence: float = 1.0,
    conflicts: tuple[str, ...] = (),
    **values: Any,
) -> DrawnComponent:
    instances = [(f"ins_{cid}_{p}_{i}", p) for i, p in enumerate(pages or (1,) * qty)]
    return DrawnComponent(
        f"cmp_{cid}", family, cls, values, qty, list(designators), confidence, instances, list(conflicts)
    )


def types(o: Any) -> list[str]:
    return sorted(d.type for d in o.differences)


# --- amounts, totals and headers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,250", "1250"),
        ("1,250.00", "1250.00"),
        ("14,022.00 ₪", "14022.00"),
        ("12,5", "12.5"),
        ('42 ש"ח', "42"),
        ("1.234.567", "1234567"),
        ("-42.00", "-42.00"),
        ("", None),
        ("אין", None),
        (None, None),
    ],
)
def test_amounts_are_parsed_in_code(text: str | None, value: str | None) -> None:
    got = q.amount(text)
    assert got == (Decimal(value) if value is not None else None)
    assert got is None or isinstance(got, Decimal)


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ('סה"כ', "subtotal"),
        ('סה"כ לפני מע"מ', "subtotal"),
        ('מע"מ 18%', "vat"),
        ('סה"כ כולל מע"מ', "with_vat"),
        ("לתשלום", "with_vat"),
        ("הנחה 5%", "discount"),
        ("Total", "subtotal"),
    ],
)
def test_total_rows_by_their_label(label: str, kind: str) -> None:
    assert q.total_kind(label) == kind


def test_money_headers_tell_unit_price_from_total() -> None:
    assert q.price_role("מחיר יחידה") == "unit_price"
    assert q.price_role('סה"כ') == "line_total"
    assert q.price_role("הנחה") == "discount"
    assert q.price_role("תיאור") is None


def test_heading_number_and_date() -> None:
    assert q.heading(["הצעת מחיר מס' 10271", "תאריך: 04/10/2026"]) == ("10271", "2026-10-04")
    assert q.heading(["Quote no. 4455", "2026-10-13"]) == ("4455", "2026-10-13")
    assert q.heading(["שלום"]) == (None, None)


# --- reading a spreadsheet, a text table and a picture ---------------------------------------------------------


def xlsx(rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


QUOTE_SHEET = [
    ["הצעת מחיר מס' 10288"],
    ["תאריך 13/10/2026"],
    [],
    ["תיאור", "כמות", "מחיר יחידה", 'סה"כ'],
    ['מא"ז 3X16A', 3, 185, 555],
    ["ממסרים", None, None, None],  # a section heading
    ["מגען 3X25A", 2, 180, 360],
    ['סה"כ', None, None, 915],
    ['מע"מ', None, None, 164.7],
]


def test_a_spreadsheet_quote_keeps_its_money_in_decimal() -> None:
    [sheet] = sheets.read("xlsx", xlsx(QUOTE_SHEET))
    r = q.from_sheet(sheet, None)
    assert (r.number, r.date) == ("10288", "2026-10-13")
    assert [(ln.index, ln.text, ln.qty, ln.unit_price, ln.total) for ln in r.lines] == [
        (1, 'מא"ז 3X16A', Decimal(3), Decimal(185), Decimal(555)),
        (2, "מגען 3X25A", Decimal(2), Decimal(180), Decimal(360)),
    ]
    assert [(t.kind, t.amount) for t in r.totals] == [("subtotal", Decimal(915)), ("vat", Decimal("164.7"))]
    assert r.total_before_vat == Decimal(915)
    assert q.check(r) == []


def test_money_columns_the_wrong_way_round_are_swapped_by_the_arithmetic() -> None:
    rows: list[list[Any]] = [["תיאור", "כמות", "מחיר", "מחיר"], ["מגען", 2, 360, 180], ["ממסר", 3, 30, 10]]
    [sheet] = sheets.read("xlsx", xlsx(rows))
    r = q.from_sheet(sheet, None)
    assert [(ln.unit_price, ln.total) for ln in r.lines] == [(Decimal(180), Decimal(360)), (Decimal(10), Decimal(30))]


def test_an_unknown_header_goes_to_the_model_with_every_number_masked() -> None:
    requests: list[Any] = []

    def answer(request: Any) -> dict[str, Any]:
        requests.append(request)
        letters = re.findall(r"^- ([A-Z]+):", request.user_text, re.M)
        return {
            "columns": [{"column": x, "role": r} for x, r in zip(letters, ["item", "quantity", "price"], strict=False)]
        }

    client = LLMClient({"anthropic": FakeProvider(answer)})
    rows: list[list[Any]] = [["פירוט", "יח'", "₪"], ['מא"ז 3X16A', 3, 185], ["מגען 3X25A", 2, 180]]
    [sheet] = sheets.read("xlsx", xlsx(rows))
    r = q.from_sheet(sheet, lambda c: table_transcription.map_columns(client, c).data)
    [request] = requests
    assert not re.search(r"\d", request.user_text.split("\n\n", 1)[1])
    for secret in ("185", "180", "16"):
        assert secret not in request.user_text
    assert [ln.unit_price for ln in r.lines] == [Decimal(185), Decimal(180)]
    assert "quote_mapping_unsure" in r.issues


def test_a_pdf_text_table_needs_known_headers() -> None:
    rows: list[list[str | None]] = [["תיאור", "כמות", "מחיר"], ['מא"ז 1X16A', "4", "42"]]
    r = q.from_text_table(rows, ["הצעה מספר 5555"])
    assert r is not None and r.source == "text" and r.number == "5555"
    assert [(ln.qty, ln.unit_price) for ln in r.lines] == [(Decimal(4), Decimal(42))]
    assert q.from_text_table([["a", "b"], ["c", "d"]], []) is None


def quote_answer(rows: list[tuple[str | None, ...]], **extra: Any) -> QuoteAnswer:
    return QuoteAnswer.model_validate(
        {
            "quote_number": extra.get("quote_number", "10271"),
            "quote_date": extra.get("quote_date", "04.10.2026"),
            "columns": [
                {"header": "תיאור", "role": "item"},
                {"header": "כמות", "role": "quantity"},
                {"header": "מחיר", "role": "unit_price"},
                {"header": 'סה"כ', "role": "line_total"},
            ],
            "rows": [
                {
                    "cells": [{"text": t, "confidence": extra.get("confidence", 0.9)} for t in r],
                    "box": [0, 100 * n, 1100, 100 * n + 50],
                }
                for n, r in enumerate(rows)
            ],
            "totals": extra.get("totals", []),
        }
    )


def test_a_picture_is_checked_in_code() -> None:
    answer = quote_answer(
        [
            ("הגנת מנוע 4-6.3A", "4", "260", "1,040"),
            ("מנתק נתיך גליל", "1", "275", "275"),
            ("+נתיכים", None, None, None),  # the description's second line
            ('סה"כ', None, None, "1,315"),
            (None, None, None, None),
        ],
        totals=[{"label": 'סה"כ כולל מע"מ', "amount": "1,551.70", "confidence": 1.4}],
        confidence=1.7,
    )
    r = q.from_answer(answer, (595.0, 842.0), page_no=1)
    assert r.number == "10271" and r.date == "2026-10-04"
    assert [ln.text for ln in r.lines] == ["הגנת מנוע 4-6.3A", "מנתק נתיך גליל +נתיכים"]
    assert r.lines[1].rows == [2, 3]
    assert all(ln.confidence == 1.0 for ln in r.lines)  # clamped
    assert r.lines[0].bbox == (0.0, 0.0, 595.0, pytest.approx(42.1))  # past the grid: clamped
    assert [(t.kind, t.amount) for t in r.totals] == [("subtotal", Decimal(1315)), ("with_vat", Decimal("1551.70"))]
    assert r.totals[1].confidence == 1.0


def test_pages_join_into_one_quote() -> None:
    a = q.from_answer(quote_answer([('מא"ז 1X10A', "4", "42", "168")]), (595, 842), 1)
    b = q.from_answer(
        quote_answer(
            [("מגען", "1", "180", "180")],
            quote_number=None,
            totals=[{"label": 'סה"כ', "amount": "348", "confidence": 1}],
        ),
        (595, 842),
        2,
    )
    joined = q.join([a, b])
    assert [(ln.index, ln.page_no) for ln in joined.lines] == [(1, 1), (2, 2)]
    assert joined.number == "10271" and joined.total_before_vat == Decimal(348)
    assert q.join([]).issues == ["quote_no_lines"]


def test_the_transcription_answer_has_no_field_for_the_customer() -> None:
    fields = set(QuoteAnswer.model_fields) | set(QuoteAnswer.model_json_schema()["$defs"])
    assert not any(re.search(r"customer|phone|email|address|לקוח", f, re.I) for f in fields)
    assert "Leave out the customer's name" in table_transcription.QUOTE


def test_only_the_quote_transcription_asks_the_model_for_money() -> None:
    """S15 decision 1: the quote's own page is the one request whose answer carries prices; the BOM transcription
    and the column mapping still never ask for one."""
    assert "money exactly as written" in table_transcription.QUOTE
    assert "do not copy money" in table_transcription.TRANSCRIBE
    provider = FakeProvider(fake_llm.answer)
    client = LLMClient({"anthropic": provider})
    got = table_transcription.transcribe_quote(client, ImageInput(b"png", key="k"))
    assert got.data.quote_number == fake_llm.QUOTE_NUMBER
    [request] = provider.requests
    assert request.stage == "table_transcription" and request.output_schema is QuoteAnswer


# --- the arithmetic check -------------------------------------------------------------------------------------


def test_arithmetic_finds_a_wrong_line_and_a_wrong_sum() -> None:
    r = read(
        line(1, "a", 3, "33.33", "100.00"),  # rounding of the unit price: fine
        line(2, "b", 2, "42", "94"),
        line(3, "c", 1, None, "50"),  # no unit price: nothing to check
        totals=[q.QuoteTotal(kind="subtotal", label='סה"כ', amount=Decimal("250"))],
    )
    breaks = q.check(r)
    assert [(b.line_index, b.expected, b.written) for b in breaks] == [
        (2, Decimal(84), Decimal(94)),
        (None, Decimal("244.00"), Decimal(250)),
    ]
    assert breaks[0].delta == Decimal(10)


def test_total_before_vat_takes_a_discount_off() -> None:
    r = read(
        line(1, "a", 1, "100"),
        totals=[
            q.QuoteTotal(kind="subtotal", label='סה"כ', amount=Decimal(100)),
            q.QuoteTotal(kind="discount", label="הנחה", amount=Decimal(-10)),
        ],
    )
    assert r.total_before_vat == Decimal(90)
    assert read(line(1, "a", 1, None)).total_before_vat is None
    assert read(line(1, "a", 2, "5")).total_before_vat == Decimal(10)


# --- signatures -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "family", "values", "extra"),
    [
        ('מא"ז 3X16A', "circuit_breaker", {"poles": 3, "current_a": 16}, {}),
        ('מא"ז N+16', "circuit_breaker", {"poles": 1, "neutral": True, "current_a": 16}, {}),
        ("מפסק משולב פחת עד 4X100A", "circuit_breaker", {"poles": 4}, {"current_max_a": 100.0}),
        ("הגנת מנוע 4-6.3A", "circuit_breaker", {"range_min_a": 4, "range_max_a": 6.3}, {"cls": "motor_protection"}),
        ("מנורת קוטר 22", "indicator_lamp", {}, {}),
        ("בורר 0-1-2", "selector_switch", {"positions": "0-1-2"}, {}),
        ("משנה זרם 125/5A", "current_transformer", {"ratio_primary_a": 125, "ratio_secondary_a": 5}, {}),
        ("ארון 1000/800/300 כולל פסי צבירה", "enclosure", {}, {"dims_mm": (300, 800, 1000)}),
        ("מגען 3X25A", "contactor", {"poles": 3, "current_a": 25}, {}),
        ("שורה בלי מוצר", None, {}, {}),
    ],
)
def test_signatures(text: str, family: str | None, values: dict[str, Any], extra: dict[str, Any]) -> None:
    s = sign(text)
    assert s.family == family
    assert s.values == values
    for k, v in extra.items():
        assert getattr(s, k) == v


def test_included_items() -> None:
    assert split_included("מנתק נתיך גליל+נתיכים") == ("מנתק נתיך גליל", ["נתיכים"])
    assert split_included("ארון 1000/800/300 כולל פסי צבירה אפס ארקה") == ("ארון 1000/800/300", ["פסי צבירה אפס ארקה"])
    assert split_included('מא"ז N+16') == ('מא"ז N+16', [])
    s = sign("מנתק נתיך גליל+נתיכים")
    assert (s.family, s.cls) == ("fuse", "fuse_base")
    assert [(i.family, i.text) for i in s.included] == [("fuse", "נתיכים")]
    assert [i.family for i in sign("בקר טמפרטורה כולל גשש PT100").included] == []


def test_every_golden_quote_line_is_signed() -> None:
    for g in ("26-993", "NEVIS-1", "NURSERY-1"):
        quote = json.loads((GOLDEN / g / "actual_quote.json").read_text(encoding="utf-8"))
        for ln in quote["lines"]:
            assert sign(ln.get("text") or ln["description"]).signed, (g, ln)


# --- matching ---------------------------------------------------------------------------------------------------


def test_the_neutral_must_match_when_poles_are_written() -> None:
    f3 = comp("f3", "circuit_breaker", poles=1, neutral=True, current_a=16)
    f10 = comp("f10", "circuit_breaker", poles=1, current_a=16)
    assert compare(sign('מא"ז 1X16A'), f10).conflicts == []  # type: ignore[union-attr]
    assert compare(sign('מא"ז 1X16A'), f3).conflicts == ["neutral"]  # type: ignore[union-attr]
    assert compare(sign('מא"ז N+16'), f3).conflicts == []  # type: ignore[union-attr]


def test_a_value_the_line_does_not_write_never_stops_a_match() -> None:
    p = compare(sign("מגע עזר"), comp("a", "aux_contact", contacts="21/22"))
    assert p is not None and not p.near and p.tier == 0


def test_a_range_matches_up_to_its_current() -> None:
    q0 = comp("q0", "circuit_breaker", poles=4, current_a=80)
    p = compare(sign("מפסק משולב פחת עד 4X100A"), q0)
    assert p is not None and not p.near and p.tier == 1
    assert compare(sign("מפסק עד 4X63A"), q0).conflicts == ["current_a"]  # type: ignore[union-attr]


def test_a_motor_protection_is_not_a_breaker_and_its_range_bounds_the_current() -> None:
    assert compare(sign("הגנת מנוע 4-6.3A"), comp("qg", "circuit_breaker", cls="mccb", poles=4, current_a=125)) is None
    p = compare(sign("הגנת מנוע 4-6.3A"), comp("qg", "circuit_breaker", poles=4, current_a=125))
    assert p is not None and p.conflicts == ["current_a"]
    p = compare(sign("הגנת מנוע 4-6.3A"), comp("ql", "overload_relay", range_min_a=4, range_max_a=6.3))
    assert p is not None and not p.near and p.agreed == 2


def test_families_a_line_word_stands_for() -> None:
    assert compare(sign("מנתק 4X125A"), comp("sg", "changeover_switch", poles=4, current_a=125)) is not None
    assert compare(sign("מפסק 4X125A"), comp("sg", "changeover_switch", poles=4, current_a=125)) is None
    assert compare(sign("רב מודד SATEC"), comp("pm", "measuring_instrument")) is not None
    assert compare(sign("שורה בלי מוצר"), comp("x", "relay")) is None


def test_positions_and_dimensions() -> None:
    assert compare(sign("בורר 0-1-2"), comp("sw", "selector_switch", positions="1-0-2")).conflicts == []  # type: ignore[union-attr]
    cab = sign("ארון 1000/800/300")
    assert compare(cab, comp("e", "enclosure", dims_mm=[800, 1000, 300])).conflicts == []  # type: ignore[union-attr]
    assert compare(cab, comp("e", "enclosure", dims_mm=[1200, 800, 300])).conflicts == ["dims_mm"]  # type: ignore[union-attr]


def test_the_assignment_prefers_the_line_that_agrees_on_more() -> None:
    qg = comp("qg", "circuit_breaker", qty=2, designators=("QG1", "QG2"), poles=4, current_a=125)
    lines = [(1, sign("הגנת מנוע 4-6.3A"), Decimal(4)), (16, sign("מפסק 4X125A"), Decimal(1))]
    a = assign(lines, [qg])
    assert a.absorbed(16) == [("cmp_qg", 1)] and a.absorbed(1) == []


def test_a_line_with_no_quantity_takes_what_it_matches() -> None:
    a = assign([(1, sign("מגען"), None)], [comp("c", "contactor", qty=5)])
    assert a.absorbed(1) == [("cmp_c", 5)] and a.line_left[1] is None


# --- the differences, one type at a time --------------------------------------------------------------------------


def test_missing_in_quote_priced_from_the_same_family_and_poles() -> None:
    o = audit(
        read(line(1, 'מא"ז 2X10A', 1, "140"), line(2, 'מא"ז 2X32A', 1, "150")),
        [
            comp("f9", "circuit_breaker", poles=2, current_a=10, designators=("F9",)),
            comp("f12", "circuit_breaker", poles=2, current_a=32, designators=("F12",)),
            comp("f11", "circuit_breaker", poles=2, current_a=16, designators=("F11",)),
            comp("c", "contactor", qty=3, poles=3, designators=("C1", "C2", "C5")),
        ],
    )
    missing = {d.designators[0]: d for d in o.differences if d.type == "missing_in_quote"}
    assert missing["F11"].amount == Decimal(140)  # 10 A is nearer to 16 A than 32 A
    assert missing["F11"].suggested_line.price_source.model_dump() == {"kind": "same_family_poles", "line_index": 1}  # type: ignore[union-attr]
    assert missing["C1"].amount is None and missing["C1"].drawing_qty == 3 and missing["C1"].severity == "high"
    assert o.summary.missing_items == 4 and o.summary.missing_items_without_price == 3
    assert o.summary.value_at_risk == Decimal("140.00")
    assert missing["C1"].message == "בשרטוט 3 × מגען 3P (C1, C2, C5), ואין להם שורה בהצעה"


def test_qty_short_is_priced_at_its_own_line() -> None:
    o = audit(
        read(line(16, "מפסק 4X125A", 1, "1250")),
        [comp("qg", "circuit_breaker", qty=2, designators=("QG1", "QG2"), poles=4, current_a=125)],
    )
    [d] = o.differences
    assert (d.type, d.drawing_qty, d.quote_qty, d.amount, d.quote_line_index) == (
        "qty_short",
        Decimal(2),
        Decimal(1),
        Decimal(1250),
        16,
    )
    assert d.suggested_line is not None and d.suggested_line.price_source.kind == "this_line"  # type: ignore[union-attr]
    assert o.lines[0].status == "quantity_differs"


def test_qty_over_and_a_double_count() -> None:
    fp1 = comp("fp1", "circuit_breaker", poles=1, current_a=6, designators=("FP1",), pages=(7, 8))
    o = audit(read(line(13, 'מא"ז 1X6A', 2, "42")), [fp1])
    [d] = o.differences
    assert (d.type, d.amount, d.severity) == ("possible_double_count", Decimal(-42), "medium")
    assert "בעמודים 7, 8" in d.message
    assert o.summary.over_charged == Decimal("42.00") and o.summary.value_at_risk == 0
    o = audit(read(line(13, 'מא"ז 1X6A', 3, "42")), [fp1])
    assert types(o) == ["qty_over"] and o.differences[0].amount == Decimal(-84)


def test_attribute_mismatch_one_value_apart() -> None:
    o = audit(
        read(line(1, 'מא"ז 3X16A', 1, "185")),
        [comp("f", "circuit_breaker", poles=3, current_a=20, designators=("F18",))],
    )
    [d] = o.differences
    assert d.type == "attribute_mismatch" and d.amount == Decimal(0) and d.confidence == 0.8
    assert o.lines[0].status == "attribute_differs"
    two_apart = audit(read(line(1, 'מא"ז 1X6A', 1, "42")), [comp("f", "circuit_breaker", poles=2, current_a=16)])
    assert types(two_apart) == ["extra_in_quote", "missing_in_quote"]


def test_an_attribute_mismatch_risks_the_price_difference() -> None:
    o = audit(
        read(line(1, 'מא"ז 3X16A', 1, "185"), line(2, 'מא"ז 3X20A', 1, "200")),
        [comp("a", "circuit_breaker", poles=3, current_a=20), comp("b", "circuit_breaker", poles=3, current_a=20)],
    )
    [d] = [d for d in o.differences if d.type == "attribute_mismatch"]
    assert d.amount == Decimal(15) and d.quote_line_index == 1


def test_extra_in_quote_is_shown_apart() -> None:
    o = audit(read(line(1, "שעון שבת", 1, "250")), [])
    [d] = o.differences
    assert (d.type, d.severity) == ("extra_in_quote", "low") and d.confidence < 0.6
    assert o.summary.to_check == 1 and o.lines[0].status == "not_in_drawing"


def test_an_enclosure_line_with_no_enclosure_drawn_is_the_panel_s_cabinet() -> None:
    o = audit(read(line(1, "ארון 1000/800/300 כולל פסי צבירה", 1, "4200")), [comp("wo", "busbar", designators=("WO",))])
    assert o.differences == [] and o.lines[0].status == "matched"
    assert o.included == {"cmp_wo": 1} and o.lines[0].component_ids == ["cmp_wo"]


def test_arithmetic_differences() -> None:
    o = audit(
        read(
            line(1, "מגען", 2, "180", "380"), totals=[q.QuoteTotal(kind="subtotal", label='סה"כ', amount=Decimal(300))]
        ),
        [comp("c", "contactor", qty=2)],
    )
    assert types(o) == ["arithmetic", "arithmetic"]
    by_line = {d.quote_line_index: d for d in o.differences}
    assert by_line[1].amount == Decimal(20) and "2 × 180.00 = 360.00" in by_line[1].message
    assert by_line[None].amount == Decimal(-80)
    assert o.lines[0].status == "arithmetic"


def test_a_drawing_conflict_the_quote_settles_is_an_info_note() -> None:
    fnv = comp("fnv", "circuit_breaker", poles=3, current_a=6, designators=("FNV",), conflicts=("poles",))
    o = audit(read(line(2, 'מא"ז 3X6A', 1, "185")), [fnv])
    [d] = o.differences
    assert (d.type, d.severity) == ("drawing_conflict", "info")
    assert o.summary.differences == 0 and o.summary.info_notes == 1


def test_auxiliary_material_is_not_a_difference() -> None:
    o = audit(read(), [comp("t", "terminal", qty=6)], AUX)
    [d] = o.differences
    assert d.type == "not_a_difference" and d.amount is None
    assert o.summary.differences == 0 and o.summary.not_differences == 1


def test_an_unsigned_line_makes_a_missing_item_unsure() -> None:
    o = audit(read(line(1, "פריט מיוחד", 1, "99")), [comp("c", "contactor")])
    missing = next(d for d in o.differences if d.type == "missing_in_quote")
    assert missing.confidence == 0.55


def test_find_price_ignores_lines_without_one() -> None:
    lines = [line(1, 'מא"ז 2X10A', 1, None, None), line(2, "מגען", 1, "180")]
    sigs = {ln.index: sign(ln.text) for ln in lines}
    assert find_price(comp("f", "circuit_breaker", poles=2, current_a=16), lines, sigs) is None
    price = find_price(comp("c", "contactor"), lines, sigs)
    assert price is not None and price.unit == Decimal(180) and price.source.kind == "same_signature"


def test_describe() -> None:
    assert describe("circuit_breaker", "mcb", {"poles": 2, "current_a": 16}) == 'מא"ז 2X16A'
    assert (
        describe("circuit_breaker", "unknown_symbol", {"poles": 1, "neutral": True, "current_a": 10}) == "מפסק 1P+N 10A"
    )
    assert describe("contactor", "contactor", {"poles": 3}) == "מגען 3P"
    assert describe("current_transformer", "x", {"ratio_primary_a": 125}) == "משנה זרם 125/5A"
    assert describe("circuit_breaker", "motor_protection", {"range_min_a": 4, "range_max_a": 6.3}) == "מגן מנוע 4–6.3A"


def test_money_is_decimal_and_a_string_in_the_contract() -> None:
    o = audit(
        read(line(16, "מפסק 4X125A", 1, "1250.50")), [comp("qg", "circuit_breaker", qty=2, poles=4, current_a=125)]
    )
    [d] = o.differences
    assert isinstance(d.amount, Decimal)
    assert d.model_dump(mode="json")["amount"] == "1250.50"
    assert o.summary.model_dump(mode="json")["value_at_risk"] == "1250.50"


# --- stage 4's components, as the audit sees them ------------------------------------------------------------


def test_drawn_components_from_stage_4() -> None:
    def inst(iid: str, page: str, issues: list[StageIssue] | None = None) -> Instance:
        return Instance(
            instance_id=iid, det_id=None, page_id=page, panel_id="pnl_1", bbox=None, family="circuit_breaker",
            symbol_class="mcb", method="geometric", status="accepted", confidence=0.9, issues=issues or [],
        )  # fmt: skip

    conflict = StageIssue(
        code="attribute_conflict", severity="warning", message="ערכים סותרים בשרטוט עבור poles. נבחר: poles=3."
    )
    merge = MergeResult(
        drawing_id="drw_01X",
        instances=[inst("ins_1", "pg_7"), inst("ins_2", "pg_8", [conflict])],
        components=[
            Component(
                component_id="cmp_1",
                drawing_id="drw_01X",
                panel_id="pnl_1",
                family="circuit_breaker",
                symbol_class="mcb",
                quantity=1,
                designators=["FP1"],
                instance_ids=["ins_1", "ins_2"],
                confidence=0.9,
                status="accepted",
                attributes={
                    "poles": AttributeValue(value=1, source="drawing", confidence=0.9),
                    "curve": AttributeValue(value=None, source=None, confidence=None),
                },
            ),
            Component(
                component_id="cmp_2",
                drawing_id="drw_01X",
                panel_id="pnl_1",
                family="relay",
                symbol_class="relay",
                quantity=1,
                confidence=0.9,
                status="accepted",
                supply_scope="by_others",
            ),
        ],
        trace_id="trc_x",
    )
    [c] = drawn_components({"pg_7": 7, "pg_8": 8}, merge)
    assert c.values == {"poles": 1} and c.pages == [7, 8] and c.drawings == 2 and c.conflicts == ["poles"]


# --- the golden quotes against their labels (the oracle) -----------------------------------------------------------


def oracle_components(g: str) -> list[DrawnComponent]:
    """The labels' products as stage 4's components: each drawn once per process page the labels say it is on."""
    d = load(GOLDEN / g)
    raw = json.loads((GOLDEN / g / "labels.json").read_text(encoding="utf-8"))
    routes = {p.no: p.route for p in d.pages}
    pages_of = {des: c.get("pages", []) for c in raw.get("components", []) for des in c.get("designators", [])}
    out: list[DrawnComponent] = []
    for p in d.panels:
        for n, c in enumerate(p.components):
            values = dict(c.attributes)
            if "range_a" in values:
                lo, hi = str(values.pop("range_a")).split("-")
                values["range_min_a"], values["range_max_a"] = float(lo), float(hi)
            drawn = sorted({pg for des in c.designators for pg in pages_of.get(des, []) if routes.get(pg) == "process"})
            instances = [(f"ins_{n}_{pg}", pg) for pg in drawn] or [(f"ins_{n}_{i}", 1) for i in range(c.qty)]
            out.append(
                DrawnComponent(
                    f"cmp_{n}", c.family, "unknown_symbol", values, c.qty, list(c.designators), 1.0, instances
                )
            )
    return out


def oracle_quote(g: str) -> q.QuoteRead:
    raw = json.loads((GOLDEN / g / "actual_quote.json").read_text(encoding="utf-8"))
    lines = []
    for i, ln in enumerate(raw["lines"], start=1):
        unit, qty = Decimal(str(ln["unit_price"])), Decimal(ln["qty"])
        total = Decimal(str(ln["total"])) if "total" in ln else unit * qty
        lines.append(
            q.QuoteLine(index=i, text=ln.get("text") or ln["description"], qty=qty, unit_price=unit, total=total)
        )
    return q.QuoteRead(source="spreadsheet", lines=lines)


EXPECTED = {
    # 11 §1 and the golden READMEs, confirmed by the factory
    "NEVIS-1": {"missing": {"F11", "C1", "C2", "C3", "C4", "C5", "R1", "R3", "R5", "R6", "R7", "RNV"},
                "doubled": {"FP1"}, "at_risk": "140.00", "missing_items": 12, "unpriced": 11, "over": "42.00"},
    "26-993": {"missing": {"TC-G1", "TC-G2", "MS1", "MS2", "MS3"}, "short": {"QG1", "QG2"},
               "at_risk": "1250.00", "missing_items": 6, "unpriced": 5, "over": "0.00"},
    "NURSERY-1": {"missing": {"FNV", "RNV"}, "at_risk": "185.00", "missing_items": 2, "unpriced": 1, "over": "0.00"},
}  # fmt: skip


@pytest.mark.parametrize("g", sorted(EXPECTED))
def test_the_golden_quotes_against_their_labels(g: str) -> None:
    e = EXPECTED[g]
    o = audit(oracle_quote(g), oracle_components(g), AUX)
    counted = [d for d in o.differences if d.type != "not_a_difference"]
    assert all(d.confidence >= 0.6 for d in counted)  # all shown
    found = {des for d in counted if d.type == "missing_in_quote" for des in d.designators}
    assert found == e["missing"]
    assert {des for d in counted if d.type == "possible_double_count" for des in d.designators} == e.get(
        "doubled", set()
    )
    assert {des for d in counted if d.type == "qty_short" for des in d.designators} == e.get("short", set())
    assert {d.type for d in counted} <= {"missing_in_quote", "qty_short", "possible_double_count"}  # nothing wrong
    s = o.summary
    assert (str(s.value_at_risk), s.missing_items, s.missing_items_without_price, str(s.over_charged)) == (
        e["at_risk"],
        e["missing_items"],
        e["unpriced"],
        e["over"],
    )
    if g == "26-993":  # the CT test terminals: auxiliary material; lines 5 and 15 cover several devices
        assert [d.type for d in o.differences if d.type == "not_a_difference"] == ["not_a_difference"]
        assert {ln.index for ln in o.lines if ln.status != "matched"} == {16}


# --- the rest of the money branches (07 §10.1: money code is fully covered) ----------------------------------------


def test_a_line_s_unit_price_from_its_total() -> None:
    from konboro.pipeline.audit.differences import unit_price

    assert unit_price(line(1, "a", 4, None, "168")) == Decimal(42)
    assert unit_price(line(1, "a", None, None, "168")) is None
    o = audit(
        read(line(16, "מפסק 4X125A", 1, None, "1250")), [comp("qg", "circuit_breaker", qty=2, poles=4, current_a=125)]
    )
    assert o.differences[0].amount == Decimal(1250)


def test_a_mismatch_with_a_line_of_no_quantity_and_one_smaller_than_the_drawing() -> None:
    o = audit(read(line(1, 'מא"ז 3X16A', None, "185")), [comp("f", "circuit_breaker", qty=2, poles=3, current_a=20)])
    assert [(d.type, d.drawing_qty) for d in o.differences] == [("attribute_mismatch", Decimal(2))]
    o = audit(read(line(1, 'מא"ז 3X16A', 1, "185")), [comp("f", "circuit_breaker", qty=3, poles=3, current_a=20)])
    assert sorted((d.type, d.drawing_qty) for d in o.differences) == [
        ("attribute_mismatch", Decimal(1)),
        ("missing_in_quote", Decimal(2)),
    ]
    missing = next(d for d in o.differences if d.type == "missing_in_quote")
    assert missing.amount == Decimal(370)  # same family and poles: the 3X16A line's 185


def test_no_price_from_a_line_whose_poles_the_component_does_not_write() -> None:
    lines = [line(1, 'מא"ז 2X10A', 1, "140")]
    assert find_price(comp("f", "circuit_breaker", current_a=16), lines, {1: sign(lines[0].text)}) is None


def test_a_line_keeps_its_worst_status() -> None:
    o = audit(read(line(1, 'מא"ז 3X16A', 2, "185", "999")), [comp("a", "circuit_breaker", poles=3, current_a=20)])
    assert types(o) == ["arithmetic", "attribute_mismatch", "qty_over"]
    assert o.lines[0].status == "attribute_differs"


def test_a_conflict_on_a_component_no_line_took_is_no_note() -> None:
    o = audit(read(), [comp("x", "relay", conflicts=("coil_voltage_v",))])
    assert types(o) == ["missing_in_quote"]


def test_odd_cells_and_headings() -> None:
    assert q.amount("--") is None
    assert q.price_role(None) is None and q.price_role("") is None
    assert q.heading(["31/13/2026"]) == (None, None)
    assert describe("fuse", "fuse", {"current_a": 50}) == "נתיך 50A"
    assert q.from_answer(quote_answer([(None, None, None, "5")]), (595, 842), 1).lines == []
    rows: list[list[Any]] = [
        ["פירוט", "יח'", "ערך א", "ערך ב"],  # the model calls both money: unit price first, then the total
        ["מגען", 2, 10, 20],
        [None, None, None, None],
    ]
    roles = {"A": "item", "B": "quantity", "C": "price", "D": "price"}
    answer = table_transcription.MappingAnswer.model_validate(
        {"columns": [{"column": k, "role": v} for k, v in roles.items()]}
    )
    [sheet] = sheets.read("xlsx", xlsx(rows))
    r = q.from_sheet(sheet, lambda _c: answer)
    assert [(ln.unit_price, ln.total) for ln in r.lines] == [(Decimal(10), Decimal(20))]
    a = q.from_answer(quote_answer([("מגען", "1", "180", "180"), ("המשך", None, None, None)]), (595, 842), 1)
    a.lines[0].bbox = None
    assert q.join([a]).lines[0].text == "מגען המשך"
    assert q.join([q.QuoteRead(source="image")]).issues == ["quote_no_lines"]


def test_a_difference_is_boxed_on_every_page_its_evidence_names() -> None:
    """S16: "הצג בשרטוט" shows the evidence's instances, on each page they are on; a difference whose evidence names
    no instance shows every instance of its components."""
    cmp = m.Component(
        id="cmp_1",
        instances=[
            {"instance_id": "ins_a", "page_id": "pg_3", "bbox": [1, 2, 3, 4]},
            {"instance_id": "ins_b", "page_id": "pg_5", "bbox": [5, 6, 7, 8]},
            {"instance_id": "ins_c", "page_id": "pg_5", "bbox": None},  # stage 4 found no box: nothing to draw
        ],
    )
    named = m.AuditDifference(component_ids=["cmp_1", "cmp_gone"], evidence=[{"page_no": 5, "instance_ids": ["ins_b"]}])
    assert [(b.page_id, b.bbox) for b in evidence_boxes(named, {"cmp_1": cmp})] == [("pg_5", [5, 6, 7, 8])]
    unnamed = m.AuditDifference(component_ids=["cmp_1"], evidence=[])
    assert [b.page_id for b in evidence_boxes(unnamed, {"cmp_1": cmp})] == ["pg_3", "pg_5"]
