"""The internal Excel (13 §4.1 "Excel פנימי": every line with its cost, price source, colour, tags and the findings;
12: openpyxl; S26). For work inside the factory, so it has everything the customer PDF leaves out. Three sheets,
right to left: the lines, the findings, the totals. Money is written as numbers from the stored `Decimal`s with a
shekel format, so a sum in Excel is the quote's sum; the words are the review screen's (09 §6.3–6.4).
"""

import io
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from konboro.pipeline.validation.model import compress
from konboro.services import quotes as qs
from konboro.services.export import Document

MONEY = '"₪"#,##0.00'
QTY = "#,##0.###"
RATE = "0.0%"
HEADER = Font(bold=True)
FILLS = {
    "green": PatternFill("solid", fgColor="DCEFE0"),
    "yellow": PatternFill("solid", fgColor="FBF0CC"),
    "red": PatternFill("solid", fgColor="F8DAD6"),
}
STATUS = {"green": "ירוק", "yellow": "צהוב", "red": "אדום"}
LINE_TYPES = {"component": "רכיב", "manual": "נוסף ידנית", "missing": "חסר", "derived": "פריט נלווה", "labor": "עבודה"}
SEVERITY = {"error": "שגיאה", "warning": "אזהרה", "info": "מידע"}
COST_SOURCES = {
    "supplier_price_list": "מחירון ספק",
    "manual_entry": "הוזן ידנית",
    "quote_import": "מהצעה קודמת",
    "brand_discount": "הנחת מותג",
}
# 09 §6.3's chips, as `screens/review/model.ts` words them
REASONS = {
    "explicit_model": "דגם מפורש",
    "memory": "זיכרון התאמות",
    "matched": "הותאם",
    "kit": "ערכה",
    "model_not_written": "דגם לא כתוב",
    "context_page": "עמוד נתונים",
    "enclosure_includes": "כולל פסי צבירה",
    "inferred_attribute": "הוסק מהמעגל",
    "ambiguous": "כמה מוצרים מתאימים",
    "unmatched": 'אין מק"ט מתאים',
    "conflict": "סתירה בין התכונות",
    "not_in_catalog": "אין בקטלוג מוצר עם הערכים האלה",
    "resolved": "נבחר ידנית",
    "missing": "אין מחיר",
    "stale": "מחיר ישן",
    "discount_based": "מחיר לפי הנחת מותג",
    "included": "כלול",
    "approved": "אושר ידנית",
    "manual": "נוסף ידנית",
}

LINE_COLUMNS: tuple[tuple[str, int, str | None], ...] = (
    ("לוח", 16, None),
    ("קבוצה", 12, None),
    ("סוג שורה", 11, None),
    ("תיאור", 46, None),
    ('מק"ט', 22, None),
    ("יצרן", 12, None),
    ("תגים", 18, None),
    ("כמות", 8, QTY),
    ("יחידה", 7, None),
    ("עלות ליחידה", 12, MONEY),
    ("מקור העלות", 14, None),
    ("ספק", 22, None),
    ("מחיר ליחידה", 12, MONEY),
    ('סה"כ', 13, MONEY),
    ("עלות שורה", 13, MONEY),
    ("רווח", 8, RATE),
    ("מקור המחיר", 18, None),
    ("צבע", 8, None),
    ("סיבות", 40, None),
    ("אושרה", 7, None),
)


def _reason(r: dict[str, Any]) -> str | None:
    value = r.get("value")
    if r.get("source") == "validator":
        return None  # the findings sheet has them
    if r.get("source") == "confidence":
        return f"ביטחון {value}"
    if isinstance(value, dict):
        code = value.get("code")
        if code == "defaulted_attribute":
            return f"ברירת מחדל: {value.get('value')}"
        if code == "brand_substituted":
            return f"{value.get('chosen')} במקום {value.get('drawing')}"
        return str(code)
    if r.get("source") == "user" and value == "approved":
        return REASONS["approved"]
    return REASONS.get(str(value), str(value))


def _price_source(ln: qs.LineView) -> str:
    src = ln.price_source or {}
    if src.get("quotes"):
        quotes = src["quotes"]
        return f"{'הצעה' if len(quotes) == 1 else 'הצעות'} {', '.join(quotes)}"
    if src.get("kind") in ("markup", "margin") and src.get("value") is not None:
        return f"חוק רווח {round(Decimal(str(src['value'])) * 100, 1).normalize():f}%"
    if src.get("kind") == "fixed":
        return "מחיר קבוע"
    return "הוזן ידנית" if ln.unit_price is not None else ""


def _write_header(ws: Worksheet, columns: tuple[tuple[str, int, str | None], ...]) -> None:
    ws.sheet_view.rightToLeft = True
    for i, (title, width, _fmt) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=i, value=title)
        cell.font = HEADER
        cell.alignment = Alignment(vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"


def _lines(ws: Worksheet, doc: Document) -> None:
    _write_header(ws, LINE_COLUMNS)
    row = 2
    for panel in doc.view.panels:
        for ln in panel.lines:
            cost = ln.cost_source or {}
            values: list[Any] = [
                panel.name,
                ln.line_group,
                LINE_TYPES.get(ln.line_type, ln.line_type),
                ln.description,
                ln.sku,
                ln.manufacturer,
                compress(list(ln.designators)) or None,
                ln.qty,
                ln.unit,
                ln.unit_cost,
                COST_SOURCES.get(str(cost.get("type")), cost.get("type")),
                cost.get("supplier"),
                ln.unit_price,
                ln.line_total,
                ln.line_cost,
                ln.margin_pct,
                _price_source(ln),
                STATUS.get(ln.status, ln.status),
                ", ".join(x for x in (_reason(r) for r in ln.status_reasons) if x) or None,
                "כן" if ln.approved else None,
            ]
            for col, (value, (_t, _w, fmt)) in enumerate(zip(values, LINE_COLUMNS, strict=True), start=1):
                cell = ws.cell(row=row, column=col, value=value)
                if fmt:
                    cell.number_format = fmt
            ws.cell(row=row, column=18).fill = FILLS.get(ln.status, PatternFill())
            row += 1
    ws.auto_filter.ref = f"A1:{get_column_letter(len(LINE_COLUMNS))}{max(row - 1, 1)}"


FINDING_COLUMNS: tuple[tuple[str, int, str | None], ...] = (
    ("חומרה", 9, None),
    ("כותרת", 40, None),
    ("פירוט", 70, None),
    ("שורות", 40, None),
    ("עמוד", 7, None),
    ("קוד", 30, None),
)


def _findings(ws: Worksheet, doc: Document) -> None:
    _write_header(ws, FINDING_COLUMNS)
    names = {ln.line_id: ln.description for p in doc.view.panels for ln in p.lines}
    for row, f in enumerate(doc.view.findings, start=2):
        values = [
            SEVERITY.get(f.severity, f.severity),
            f.title,
            f.message,
            "; ".join(names[i] for i in f.line_ids if i in names) or None,
            f.page_no,
            f.code,
        ]
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value).alignment = Alignment(wrap_text=col in (2, 3, 4), vertical="top")


def _totals(ws: Worksheet, doc: Document) -> None:
    ws.sheet_view.rightToLeft = True
    q = doc.totals
    s = q.sums
    rows: list[tuple[str, Any, str | None]] = [
        ("הצעה", doc.name, None),
        ("שרטוט", doc.drawing_number, None),
        ("לקוח", doc.customer, None),
        ("גרסה", doc.version, None),
        ("סטטוס", "טיוטה" if doc.draft else "נשלחה", None),
        ("תאריך", doc.quote_date, "dd.mm.yyyy"),
        ("", None, None),
        ('סה"כ לפני הנחה', s.price_total, MONEY),
        ("הנחה", q.discount, MONEY),
        ("אחוז הנחה", q.discount_pct, RATE),
        ('סה"כ לפני מע"מ', q.net_total, MONEY),
        ('מע"מ', q.vat, MONEY),
        ('שיעור מע"מ', q.vat_rate, RATE),
        ("לתשלום", q.gross_total, MONEY),
        ("", None, None),
        ("עלות", s.cost_total, MONEY),
        ("רווח", q.margin_abs, MONEY),
        ("אחוז רווח", q.margin_pct, RATE),
        ("שורות בלי מחיר", s.unpriced_count, None),
        ("שורות בלי עלות", s.uncosted_count, None),
        ("שורות ירוקות", s.line_counts.get("green", 0), None),
        ("שורות צהובות", s.line_counts.get("yellow", 0), None),
        ("שורות אדומות", s.line_counts.get("red", 0), None),
    ]
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 24
    for row, (label, value, fmt) in enumerate(rows, start=1):
        ws.cell(row=row, column=1, value=label or None).font = HEADER
        cell = ws.cell(row=row, column=2, value=value)
        if fmt:
            cell.number_format = fmt


def workbook(doc: Document) -> bytes:
    wb = Workbook()
    lines = wb.active
    assert lines is not None  # noqa: S101  (a new workbook has its first sheet)
    lines.title = "שורות"
    _lines(lines, doc)
    _findings(wb.create_sheet("ממצאים"), doc)
    _totals(wb.create_sheet("סיכום"), doc)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
