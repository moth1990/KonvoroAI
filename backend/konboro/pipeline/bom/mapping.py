"""Which spreadsheet column is the item, the quantity, the panel… (01 §5.8; S14 decisions 1 and 2).

1. Code finds the header row and reads each header through `HEADERS`, Hebrew and English. A mapping code made, with
   one item column and one quantity column, is sure.
2. For headers code doesn't know, `table_transcription` picks a role from a closed list. It sees the header text and
   up to 5 sample cells per column, every number in them replaced by its shape (`masked`): a price column can't be
   told from a quantity column before the mapping, so no numeric value leaves (CLAUDE.md non-negotiable 6). Columns
   go by letter, so the request has no digit at all.
3. A mapping the model touched, or one with no item or no quantity column, is unsure: the user confirms it on the
   confirmation step when `bom_column_mapping` is on (S14 decision 1).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from konboro_llm.stages.table_transcription import MappingAnswer, Role

from .sheets import Cells

By = Literal["code", "model", "user"]

HEADER_SCAN_ROWS = 15  # the header row is one of the first rows
SAMPLES = 5

# Checked in this order: "מחיר יחידה" is a price before it is a unit, "שם לוח" a panel before an item.
HEADERS: tuple[tuple[Role, tuple[str, ...]], ...] = (
    ("price", ("מחיר", 'סה"כ', "סהכ", "סך", "עלות", "הנחה", "₪", "price", "total", "amount", "cost", "discount")),
    ("quantity", ("כמות", "כמ'", "qty", "quantity", "quan", "pcs")),
    ("panel", ("לוח", "panel", "board", "switchboard")),
    ("model", ('מק"ט', "מקט", "דגם", "קטלוגי", "model", "part", "catalog", "cat.", "p/n", "sku", "ordering")),
    ("brand", ("יצרן", "מותג", "brand", "manufacturer", "make")),
    ("unit", ("יחידה", "יח'", "יח", "unit", "uom")),
    ("row_number", ("מס'", "מס", "מספר", "#", "no.", "no", "item no", "row")),
    ("item", ("תיאור", "תאור", "פריט", "פרטים", "מוצר", "רכיב", "שם", "description", "item", "desc", "product")),
)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[^\w\"'#₪./]+")


def _words(header: str) -> list[str]:
    return [w for w in _WORD.split(header.replace("״", '"').replace("׳", "'").casefold()) if w]


def role_of(header: str | None) -> Role | None:
    """The role a header names, by the dictionary: a keyword that is one of its words, or that it begins with."""
    if not header:
        return None
    words = _words(header)
    joined = " ".join(words)
    for role, keys in HEADERS:
        for key in keys:
            if key in words or joined.startswith(key) or (" " in key and key in joined):
                return role
    return None


def letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA: the column as Excel names it."""
    out = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def masked(text: str) -> str:
    """Every number replaced by its shape: `מא"ז 3X16` → `מא"ז <int>X<int>`, `12.50` → `<decimal>`."""
    return _NUMBER.sub(lambda m: "<decimal>" if any(c in m[0] for c in ".,") else "<int>", text)


def _is_number(cell: str | None) -> bool:
    return bool(cell) and _NUMBER.fullmatch(cell.replace(" ", "")) is not None  # type: ignore[union-attr]


def header_row(rows: list[Cells]) -> int | None:
    """The 0-based index of the header row: the early row with the most headers the dictionary knows (two at
    least); failing that, a row of two or more text cells right above a row with a number. None: no header."""
    best, best_known = None, 1
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        known = sum(1 for c in row if role_of(c) is not None)
        if known > best_known:
            best, best_known = i, known
    if best is not None:
        return best
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cells = [c for c in row if c]
        if len(cells) >= 2 and not any(_is_number(c) for c in cells):
            below = rows[i + 1] if i + 1 < len(rows) else []
            if any(_is_number(c) for c in below):
                return i
            return None
    return None


@dataclass
class Column:
    index: int
    header: str | None
    role: Role
    by: By


@dataclass
class Mapping:
    columns: list[Column]
    header_row: int | None  # 0-based
    sure: bool


def is_sure(columns: list[Column]) -> bool:
    roles = [c.role for c in columns]
    return roles.count("item") == 1 and roles.count("quantity") == 1


def describe(rows: list[Cells], width: int, head: int | None) -> str:
    """The model's view of the columns: letter, header and masked samples, one line each. No digit is left."""
    body = rows[head + 1 :] if head is not None else rows
    lines = []
    for i in range(width):
        header = rows[head][i] if head is not None and i < len(rows[head]) else None
        samples = [c for r in body if i < len(r) and (c := r[i])][:SAMPLES]
        shown = "; ".join(masked(s) for s in samples) or "(empty)"
        name = repr(masked(header)) if header else "(none)"
        lines.append(f"- {letter(i)}: header {name}; samples: {shown}")
    return "\n".join(lines)


Ask = Callable[[str], MappingAnswer]


def map_sheet(rows: list[Cells], ask: Ask | None) -> Mapping:
    """Code first; the model only when code didn't find one item and one quantity column, and only for the
    columns code doesn't know. `ask` None (no route, e.g. in a test) leaves them `other`."""
    head = header_row(rows)
    width = max((len(r) for r in rows), default=0)
    headers = [rows[head][i] if head is not None and i < len(rows[head]) else None for i in range(width)]
    columns = [Column(i, h, role_of(h) or "other", "code") for i, h in enumerate(headers)]
    if is_sure(columns) or ask is None or not width:
        return Mapping(columns, head, is_sure(columns))
    known = {c.index for c in columns if role_of(c.header) is not None}
    answer = ask(describe(rows, width, head))
    by_letter = {letter(c.index): c for c in columns}
    for a in answer.columns:
        c = by_letter.get(a.column.strip().upper())
        if c is not None and c.index not in known:
            c.role, c.by = a.role, "model"
    return Mapping(columns, head, False)
