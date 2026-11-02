"""Reading the audited quote (11 §5.2): its lines, its heading and its totals, with the money kept, and the arithmetic
check.

Three sources, as the BOM path reads them (01 §5.8, 11 §4):
- A spreadsheet (XLSX, CSV): code reads it (`bom.sheets`), and the columns are mapped as a BOM's are (`bom.mapping`:
  the header dictionary first, the model only for headers code doesn't know, every number masked, S14 decision 2).
  The money columns are then told apart by their headers: unit price, line total, discount.
- A PDF with a text layer: pdfplumber's table, in code, with no model.
- A picture, or a PDF page with no text: `table_transcription.transcribe_quote`, which copies the amounts as written
  (S15 decision 1). Code drops cells past the columns, clamps confidences and boxes, and parses every amount itself.

Every amount is a `Decimal` parsed in code ("1,250", "14,022.00", "42 ₪"); nothing is computed by a model. Rows that
sum the table (סה"כ, הנחה, מע"מ) are totals, not lines. The customer has no field anywhere (11 §11).

The arithmetic check (11 §5.2 step 3): quantity × unit price = line total, to the agora each side may have been
rounded to, and the lines' sum = the quote's total before VAT. Each break is an `ArithmeticBreak`; the audit turns it
into an `arithmetic` difference.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

from konboro.contracts.common import Bbox
from konboro.pipeline.bom import mapping as bom_mapping
from konboro.pipeline.bom.sheets import Cells, Sheet
from konboro.pipeline.bom.table import GRID, TOTAL
from konboro_llm.stages.table_transcription import QuoteAnswer, QuoteRole

Source = Literal["spreadsheet", "text", "image"]
TotalKind = Literal["subtotal", "discount", "vat", "with_vat"]

AGORA = Decimal("0.01")
HALF_AGORA = Decimal("0.005")

# A money column's kind by its header; checked in this order ("סה"כ מחיר" is a total, "מחיר יחידה" a unit price).
PRICE_HEADERS: tuple[tuple[QuoteRole, tuple[str, ...]], ...] = (
    ("discount", ("הנחה", "discount")),
    ("line_total", ('סה"כ', "סהכ", "סך", "סכום", "total", "amount", "ext")),
    ("unit_price", ("מחיר", "ליחידה", "₪", "price", "unit price", "rate", "cost", "עלות")),
)
_MONEY = re.compile(r"-?\d[\d,.' ]*")
_NUMBER_HEADING = re.compile(
    r"(?:הצעה|הצעת\s+מחיר|quote|quotation)\s*(?:מס(?:פר|'|׳)?|no\.?|#)?\s*[:.]?\s*(\d{3,})", re.I
)
_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")


def amount(text: str | None) -> Decimal | None:
    """A money amount as a quote writes it, or None. "1,250" and "1,250.00" are 1250; "12,5" is 12.5 (a comma
    followed by one or two digits is a decimal comma); "₪", "ש"ח" and spaces are ignored."""
    if not text:
        return None
    m = _MONEY.search(text.replace("₪", " ").replace('ש"ח', " ").replace("״", '"'))
    if m is None:
        return None
    raw = m[0].replace(" ", "").replace("'", "").rstrip(".,")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = raw.replace(",", "") if len(tail) == 3 else f"{head.replace(',', '')}.{tail}"
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def total_kind(label: str) -> TotalKind:
    t = label.replace("״", '"').casefold()
    if "הנחה" in t or "discount" in t:
        return "discount"
    if ("כולל" in t and "מע" in t) or "לתשלום" in t or "incl" in t:
        return "with_vat"
    if ('מע"מ' in t or "מעמ" in t or "vat" in t) and "לפני" not in t and "before" not in t:
        return "vat"
    return "subtotal"


class QuoteLine(BaseModel):
    """One line of the audited quote, numbered from 1 in the quote's order (`quote_line_index`, 11 §6)."""

    index: int
    text: str
    qty: Decimal | None
    unit_price: Decimal | None
    total: Decimal | None
    confidence: float = 1.0
    rows: list[int] = []
    page_no: int | None = None
    bbox: Bbox | None = None
    model: str | None = None
    brand: str | None = None


class QuoteTotal(BaseModel):
    kind: TotalKind
    label: str
    amount: Decimal | None
    confidence: float = 1.0


class QuoteRead(BaseModel):
    source: Source
    number: str | None = None
    date: str | None = None  # ISO when code could read it, else None
    lines: list[QuoteLine] = []
    totals: list[QuoteTotal] = []
    issues: list[str] = []

    def total(self, kind: TotalKind) -> Decimal | None:
        return next((t.amount for t in self.totals if t.kind == kind and t.amount is not None), None)

    @property
    def total_before_vat(self) -> Decimal | None:
        """The quote's own total before VAT: its subtotal less a discount; failing a subtotal row, its lines' sum."""
        sub = self.total("subtotal")
        if sub is None:
            sums = [ln.total for ln in self.lines]
            if not sums or any(s is None for s in sums):
                return None
            sub = sum((s for s in sums if s is not None), Decimal(0))
        discount = self.total("discount")
        return sub - abs(discount) if discount is not None else sub


@dataclass
class _Columns:
    item: int | None = None
    quantity: int | None = None
    unit_price: int | None = None
    line_total: int | None = None
    model: int | None = None
    brand: int | None = None
    other_money: list[int] = field(default_factory=list)


def price_role(header: str | None) -> QuoteRole | None:
    if not header:
        return None
    t = header.replace("״", '"').casefold()
    for role, keys in PRICE_HEADERS:
        if any(k in t for k in keys):
            return role
    return None


def _date(text: str) -> str | None:
    m = _DATE.search(text)
    if m is None:
        return None
    if m[4]:
        return f"{m[4]}-{m[5]}-{m[6]}"
    day, month, year = int(m[1]), int(m[2]), int(m[3])
    year = year + 2000 if year < 100 else year
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def heading(texts: list[str]) -> tuple[str | None, str | None]:
    """The quote's number and date from its heading's text (a spreadsheet's or a PDF's cells above the table)."""
    number = next((m[1] for t in texts if (m := _NUMBER_HEADING.search(t))), None)
    date = next((d for t in texts if (d := _date(t))), None)
    return number, date


def _qty(text: str | None) -> Decimal | None:
    value = amount(text)
    return value if value is not None and value > 0 else None


def _rows_to_read(
    rows: list[Cells], cols: _Columns, start: int, source: Source, number: str | None, date: str | None
) -> QuoteRead:
    """A table's body as cells (a spreadsheet's or a PDF's): lines, then totals; empty rows dropped."""
    out = QuoteRead(source=source, number=number, date=date)

    def cell(r: Cells, i: int | None) -> str | None:
        return r[i] if i is not None and i < len(r) and r[i] else None

    for n, r in enumerate(rows[start:], start=start + 1):
        text = cell(r, cols.item)
        money = cell(r, cols.line_total) or cell(r, cols.unit_price)
        label = text or next((c for c in r if c and amount(c) is None), None)
        if (label and TOTAL.match(label)) or (label and not cell(r, cols.quantity) and money and _is_total(label)):
            out.totals.append(QuoteTotal(kind=total_kind(label), label=label, amount=amount(money)))
            continue
        qty_text = cell(r, cols.quantity)
        if not (text or qty_text):
            continue
        if not qty_text and not money:
            continue  # a section heading
        out.lines.append(
            QuoteLine(
                index=len(out.lines) + 1,
                text=text or "",
                qty=_qty(qty_text),
                unit_price=amount(cell(r, cols.unit_price)),
                total=amount(cell(r, cols.line_total)),
                rows=[n],
                model=cell(r, cols.model),
                brand=cell(r, cols.brand),
            )
        )
    return out


def _is_total(label: str) -> bool:
    t = label.replace("״", '"').casefold()
    return any(k in t for k in ('סה"כ', "סהכ", "הנחה", 'מע"מ', "מעמ", "total", "vat", "discount", "לתשלום"))


def _money_columns(columns: list[bom_mapping.Column], rows: list[Cells], qty: int | None) -> _Columns:
    """Item, quantity and the money columns' kinds. One money column with no telling header is the unit price,
    unless its cells are quantity × another money column."""
    cols = _Columns()
    for c in columns:
        if c.role in ("item", "quantity", "model", "brand") and getattr(cols, c.role) is None:
            setattr(cols, c.role, c.index)
    money = [c for c in columns if c.role == "price"]
    unknown: list[int] = []
    for c in money:
        kind = price_role(c.header)
        if kind == "unit_price" and cols.unit_price is None:
            cols.unit_price = c.index
        elif kind == "line_total" and cols.line_total is None:
            cols.line_total = c.index
        elif kind != "discount":
            unknown.append(c.index)
    for i in unknown:
        if cols.unit_price is None:
            cols.unit_price = i
        elif cols.line_total is None:
            cols.line_total = i
    unit, total = cols.unit_price, cols.line_total
    if unit is not None and total is not None and qty is not None and _swapped(rows, qty, unit, total):
        cols.unit_price, cols.line_total = total, unit
    return cols


def _swapped(rows: list[Cells], qty: int, unit: int, total: int) -> bool:
    """The unit price and total columns are the other way round: on the rows that can tell (a quantity other than
    1), quantity × the "total" gives the "unit price" more often than the other way."""
    straight = reverse = 0
    for r in rows:
        n, u, t = (amount(r[i]) if i < len(r) else None for i in (qty, unit, total))
        if n is None or u is None or t is None or n == 1:
            continue
        straight += abs(n * u - t) <= AGORA
        reverse += abs(n * t - u) <= AGORA
    return reverse > straight


def from_sheet(sheet: Sheet, ask: bom_mapping.Ask | None) -> QuoteRead:
    m = bom_mapping.map_sheet(sheet.rows, ask)
    head = m.header_row if m.header_row is not None else -1
    cols = _money_columns(m.columns, sheet.rows[head + 1 :], _role_index(m.columns, "quantity"))
    above = [c for r in sheet.rows[: max(head, 0)] for c in r if c]
    number, date = heading(above)
    read = _rows_to_read(sheet.rows, cols, head + 1, "spreadsheet", number, date)
    if not m.sure:
        read.issues.append("quote_mapping_unsure")
    return read


def _role_index(columns: list[bom_mapping.Column], role: str) -> int | None:
    return next((c.index for c in columns if c.role == role), None)


def from_text_table(rows: list[Cells], above: list[str]) -> QuoteRead | None:
    """A PDF's own table (pdfplumber), mapped by its headers in code alone. None when it has no item and no
    quantity column the dictionary knows: the page is then read from its picture."""
    m = bom_mapping.map_sheet(rows, None)
    if not m.sure:
        return None
    head = m.header_row if m.header_row is not None else -1
    cols = _money_columns(m.columns, rows[head + 1 :], _role_index(m.columns, "quantity"))
    number, date = heading(above + [c for r in rows[: max(head, 0)] for c in r if c])
    return _rows_to_read(rows, cols, head + 1, "text", number, date)


def _grid(v: int) -> int:
    return max(0, min(GRID, v))


def from_answer(answer: QuoteAnswer, size_pt: tuple[float, float], page_no: int, first_index: int = 1) -> QuoteRead:
    """The model's transcription of one page, checked in code. A row with no quantity and no money right after a
    line continues it (a description on two lines), as on a BOM picture (01 §5.8)."""
    roles = [c.role for c in answer.columns]
    width = len(roles)

    def idx(role: QuoteRole) -> int | None:
        return roles.index(role) if role in roles else None

    i_item, i_qty, i_unit, i_total = idx("item"), idx("quantity"), idx("unit_price"), idx("line_total")
    i_model, i_brand = idx("model"), idx("brand")
    sx, sy = size_pt[0] / GRID, size_pt[1] / GRID
    read = QuoteRead(source="image", number=_clean(answer.quote_number), date=_date(answer.quote_date or ""))
    for n, r in enumerate(answer.rows, start=1):
        cells = [*r.cells, *([None] * width)][:width]

        def text(i: int | None, cells: list = cells) -> tuple[str | None, float]:  # type: ignore[type-arg]
            if i is None or cells[i] is None:
                return None, 1.0
            return _clean(cells[i].text), max(0.0, min(1.0, cells[i].confidence))

        item, c_item = text(i_item)
        qty_text, c_qty = text(i_qty)
        unit_text, c_unit = text(i_unit)
        total_text, c_total = text(i_total)
        if item and TOTAL.match(item) and not qty_text:
            read.totals.append(QuoteTotal(kind=total_kind(item), label=item, amount=amount(total_text or unit_text)))
            continue
        xa, xb = sorted(_grid(v) for v in (r.box[0], r.box[2]))
        ya, yb = sorted(_grid(v) for v in (r.box[1], r.box[3]))
        bbox = (xa * sx, ya * sy, xb * sx, yb * sy)
        if not (qty_text or unit_text or total_text):
            prev = read.lines[-1] if read.lines else None
            if item and prev is not None and prev.rows[-1] == n - 1:
                prev.text = f"{prev.text} {item}"
                prev.rows.append(n)
                prev.confidence = round(min(prev.confidence, c_item), 4)
                prev.bbox = _union(prev.bbox, bbox)
            continue
        if not item and not qty_text:
            continue
        read.lines.append(
            QuoteLine(
                index=first_index + len(read.lines),
                text=item or "",
                qty=_qty(qty_text),
                unit_price=amount(unit_text),
                total=amount(total_text),
                confidence=round(min(c_item, c_qty, c_unit, c_total), 4),
                rows=[n],
                page_no=page_no,
                bbox=bbox,
                model=text(i_model)[0],
                brand=text(i_brand)[0],
            )
        )
    for t in answer.totals:
        label = _clean(t.label) or ""
        read.totals.append(
            QuoteTotal(
                kind=total_kind(label),
                label=label,
                amount=amount(t.amount),
                confidence=max(0.0, min(1.0, t.confidence)),
            )
        )
    return read


def _clean(text: str | None) -> str | None:
    return " ".join((text or "").split()) or None


def _union(a: Bbox | None, b: Bbox | None) -> Bbox | None:
    if a is None or b is None:
        return a or b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def join(pages: list[QuoteRead]) -> QuoteRead:
    """A quote over several pages: lines numbered on across pages, the first heading's number and date, and the
    totals of the last page that has any (a running "מעבר לעמוד הבא" sum on earlier pages is not the quote's)."""
    if not pages:
        return QuoteRead(source="image", issues=["quote_no_lines"])
    lines: list[QuoteLine] = []
    for p in pages:
        for ln in p.lines:
            lines.append(ln.model_copy(update={"index": len(lines) + 1}))
    totals = next((p.totals for p in reversed(pages) if p.totals), [])
    issues = [i for p in pages for i in p.issues]
    out = QuoteRead(
        source=pages[0].source,
        number=next((p.number for p in pages if p.number), None),
        date=next((p.date for p in pages if p.date), None),
        lines=lines,
        totals=totals,
        issues=list(dict.fromkeys(issues)),
    )
    if not lines:
        out.issues.append("quote_no_lines")
    return out


# --- the arithmetic check (11 §5.2 step 3) ----------------------------------------------------------------------


class ArithmeticBreak(BaseModel):
    """`line_index` None: the quote's sum. `expected` is what the numbers give, `written` what the quote says."""

    line_index: int | None
    expected: Decimal
    written: Decimal

    @property
    def delta(self) -> Decimal:
        return self.written - self.expected


def check(read: QuoteRead) -> list[ArithmeticBreak]:
    out: list[ArithmeticBreak] = []
    for ln in read.lines:
        if ln.qty is None or ln.unit_price is None or ln.total is None:
            continue
        expected = ln.qty * ln.unit_price
        # each side may be rounded to the agora: the unit price by up to half an agora per unit
        if abs(expected - ln.total) > HALF_AGORA * ln.qty + HALF_AGORA:
            out.append(ArithmeticBreak(line_index=ln.index, expected=expected, written=ln.total))
    sub = read.total("subtotal")
    totals = [ln.total for ln in read.lines]
    if sub is not None and totals and all(t is not None for t in totals):
        expected = sum((t for t in totals if t is not None), Decimal(0))
        if abs(expected - sub) > AGORA:
            out.append(ArithmeticBreak(line_index=None, expected=expected, written=sub))
    return out
