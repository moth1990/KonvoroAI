"""A BOM table as stage 1 stores it (a `bom_table` context artifact, 01 §5.8), and the row rules that turn it into
items for stage 4.

The table keeps the cells as read, by column, with each column's role and who gave it (code, model, user): the
user can change a role on the confirmation step (S14 decision 1) without the file being read again. A price
column's cells are never kept from a picture (the model is told not to copy money, and code drops them anyway).

Row rules (01 §5.8):
- A row with nothing in its item, model or quantity cells is empty; a "סה"כ" / "total" row is a sum. Both are dropped.
- From a picture, a row with no quantity right after a row with one continues it: its text joins the item above
  (BOM-HW-1: "רב מודד SATEC…" and "התראות לצורך הפעלת ממסר" on the next line).
- In a spreadsheet, a row with text and an empty quantity cell is a section heading, not an item. A quantity cell
  with no whole positive number in it keeps the item, with no quantity: none is made up.
- The panel is the row's panel cell; an empty one is the panel of the row above (a merged cell reads as empty);
  else the panel the form's heading names.
- The last row of a picture that touches its bottom edge means the list may go on (`bom_possibly_cropped`).
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from konboro.contracts.common import Bbox
from konboro.pipeline.intake.drawing import name_key
from konboro_llm.stages.table_transcription import Cell, Role, TableAnswer

from .mapping import By, Column, Mapping, is_sure, letter
from .sheets import Sheet

GRID = 1000
CROPPED_FROM = 985  # a last row whose box reaches this far down the 0–1000 grid touches the edge
TOTAL = re.compile(r"^\s*(סה\"?כ|סה״כ|סך\s*הכל|total|sum|subtotal)\b", re.I)
_QTY = re.compile(r"^\D*?(\d+(?:[.,]\d+)?)")


class BomColumn(BaseModel):
    index: int
    letter: str
    header: str | None
    role: Role
    by: By


class BomRow(BaseModel):
    row: int  # the sheet's row number, or the row's place in the picture, from 1
    cells: list[str | None]
    confidence: list[float] | None = None  # per cell, from a picture
    bbox: Bbox | None = None  # PDF points on the page, from a picture


class BomTable(BaseModel):
    source: Literal["spreadsheet", "image"]
    sheet: str | None = None
    panel_name: str | None = None
    project_name: str | None = None
    columns: list[BomColumn]
    header_row: int | None = None  # the sheet's row number of the header
    rows: list[BomRow]
    mapping_sure: bool
    cropped: bool = False


def from_sheet(sheet: Sheet, mapping: Mapping) -> BomTable:
    head = mapping.header_row
    body = range(head + 1 if head is not None else 0, len(sheet.rows))
    return BomTable(
        source="spreadsheet",
        sheet=sheet.name,
        columns=[
            BomColumn(index=c.index, letter=letter(c.index), header=c.header, role=c.role, by=c.by)
            for c in mapping.columns
        ],
        header_row=head + 1 if head is not None else None,
        rows=[BomRow(row=i + 1, cells=sheet.rows[i]) for i in body if any(sheet.rows[i])],
        mapping_sure=mapping.sure,
    )


def _grid(v: int) -> int:
    return max(0, min(GRID, v))


def from_answer(answer: TableAnswer, size_pt: tuple[float, float]) -> BomTable:
    """The model's transcription of a picture, checked: cells padded or cut to the columns, confidences kept in
    0–1, money dropped, boxes from the 0–1000 grid to points."""
    width = len(answer.columns)
    price = {i for i, c in enumerate(answer.columns) if c.role == "price"}
    sx, sy = size_pt[0] / GRID, size_pt[1] / GRID
    rows: list[BomRow] = []
    for n, r in enumerate(answer.rows, start=1):
        cells: list[Cell | None] = [*r.cells, *([None] * width)][:width]
        texts = [
            None if i in price or c is None else (" ".join((c.text or "").split()) or None) for i, c in enumerate(cells)
        ]
        conf = [1.0 if c is None else max(0.0, min(1.0, c.confidence)) for c in cells]
        xa, xb = sorted(_grid(v) for v in (r.box[0], r.box[2]))
        ya, yb = sorted(_grid(v) for v in (r.box[1], r.box[3]))
        if any(texts):
            rows.append(BomRow(row=n, cells=texts, confidence=conf, bbox=(xa * sx, ya * sy, xb * sx, yb * sy)))
    columns = [
        BomColumn(index=i, letter=letter(i), header=c.header, role=c.role, by="model")
        for i, c in enumerate(answer.columns)
    ]
    last = max((_grid(max(r.box[1], r.box[3])) for r in answer.rows), default=0)
    return BomTable(
        source="image",
        panel_name=(answer.panel_name or "").strip() or None,
        project_name=(answer.project_name or "").strip() or None,
        columns=columns,
        rows=rows,
        mapping_sure=True,
        cropped=last >= CROPPED_FROM,
    )


def with_roles(table: BomTable, roles: dict[int, Role]) -> BomTable:
    """The user's mapping: their roles replace the others, and the mapping is settled."""
    columns = [
        c.model_copy(update={"role": roles[c.index], "by": "user"}) if c.index in roles else c for c in table.columns
    ]
    return table.model_copy(update={"columns": columns, "mapping_sure": True})


def mapping_complete(table: BomTable) -> bool:
    return is_sure([Column(c.index, c.header, c.role, c.by) for c in table.columns])


@dataclass
class Item:
    """One product line of the table, after the row rules."""

    rows: list[int]
    text: str
    quantity: int | None
    quantity_text: str | None
    panel: str | None
    model: str | None = None
    brand: str | None = None
    confidence: float = 1.0
    bbox: Bbox | None = None
    issues: list[str] = field(default_factory=list)


def quantity(text: str | None) -> tuple[int | None, bool]:
    """A whole positive number from the cell, and whether the cell had a number at all ("5", "5 יח'", "x5")."""
    if not text:
        return None, False
    m = _QTY.match(text.replace(" ", ""))
    if m is None:
        return None, False
    value = float(m[1].replace(",", "."))
    return (int(value), True) if value.is_integer() and value > 0 else (None, True)


def _union(a: Bbox | None, b: Bbox | None) -> Bbox | None:
    if a is None or b is None:
        return a or b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def items(table: BomTable) -> list[Item]:
    def cell(r: BomRow, role: Role) -> tuple[str | None, float]:
        for c in table.columns:
            if c.role == role and c.index < len(r.cells) and r.cells[c.index]:
                conf = r.confidence[c.index] if r.confidence and c.index < len(r.confidence) else 1.0
                return r.cells[c.index], conf
        return None, 1.0

    out: list[Item] = []
    panel = None
    for r in table.rows:
        text, text_conf = cell(r, "item")
        model, model_conf = cell(r, "model")
        brand, _ = cell(r, "brand")
        qty_text, qty_conf = cell(r, "quantity")
        own_panel, _ = cell(r, "panel")
        panel = own_panel or panel
        if not (text or model or qty_text) or (text and TOTAL.match(text)):
            continue
        qty, _ = quantity(qty_text)
        if not qty_text:
            if (
                text
                and table.source == "image"
                and out
                and out[-1].quantity is not None
                and out[-1].rows[-1] == r.row - 1
            ):
                prev = out[-1]
                prev.text = f"{prev.text} {text}"
                prev.rows.append(r.row)
                prev.confidence = min(prev.confidence, text_conf)
                prev.bbox = _union(prev.bbox, r.bbox)
            continue  # a section heading, or a continuation with nothing to join
        item = Item(
            rows=[r.row],
            text=text or model or "",
            quantity=qty,
            quantity_text=qty_text,
            panel=panel or table.panel_name,
            model=model if text else None,
            brand=brand,
            confidence=round(min(text_conf, qty_conf, model_conf if model and not text else 1.0), 4),
            bbox=r.bbox,
        )
        if qty is None:
            item.issues.append("bom_quantity_unreadable")
        out.append(item)
    return out


DEFAULT_PANEL = "לוח 1"  # as stage 1 names a panel nothing names (intake/drawing.py)


def item_panel(item: Item, fallback: str | None) -> str:
    return item.panel or fallback or DEFAULT_PANEL


def panels(tables: list[tuple[str, BomTable]], fallback: str | None) -> list[tuple[str, list[str]]]:
    """A BOM-only drawing's panels, in the order the rows name them, each with its pages: a row's panel cell, the
    form's heading, the title block's panel (`fallback`), or one panel."""
    out: dict[str, tuple[str, list[str]]] = {}
    for page_id, t in tables:
        found = items(t)
        names = [item_panel(i, t.panel_name or fallback) for i in found] or [t.panel_name or fallback or DEFAULT_PANEL]
        for name in names:
            _, pages = out.setdefault(name_key(name), (name, []))
            if page_id not in pages:
                pages.append(page_id)
    return list(out.values())
