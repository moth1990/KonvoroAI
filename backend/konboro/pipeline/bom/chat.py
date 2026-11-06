"""The chat builder's rows and the code check on what `chat_bom_extraction` answered (13 §4.2, S27 design 3).

The model reads the estimator's message and answers items to add and changes to the draft's lines; it decides
nothing code can't check (00 §3):
- an item: its words (`quote`) are in the message, and every number in its text and its quantity was said, in digits
  or in words (`numbers`). A quantity of 1 needs no word: "פחת 4X40" is one RCD. Its panel is one the build has, or
  is named in the message.
- a change: its words are in the message, its line is one of the draft's (`L1`… by the names the model was shown),
  and a quantity it sets or adds was said. A quantity set to 0 removes the line.
Anything else is dropped and named in the reply. The text that passes is read by stage 4's BOM reading (terms and
the spelling grammar, `association/bom.read_item`): the model never sets a family or a value.

The build's rows are a `bom_table` artifact of source `chat` (columns: item, quantity, panel, and the words said).
A row is never renumbered and a removed row stays, marked: a component is named by its first row, so a line keeps
its key (and whatever the estimator did to it) while other rows come and go.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from konboro.pipeline.bom import terms
from konboro.pipeline.bom.numbers import DIGITS, numbers
from konboro.pipeline.bom.table import BomColumn, BomRow, BomTable

ITEM, QUANTITY, PANEL, SAID = 0, 1, 2, 3
COLUMNS = [
    BomColumn(index=ITEM, letter="A", header="פריט", role="item", by="code"),
    BomColumn(index=QUANTITY, letter="B", header="כמות", role="quantity", by="code"),
    BomColumn(index=PANEL, letter="C", header="לוח", role="panel", by="code"),
    # the estimator's own words for the row ("מפסק ראשי"), for the model to find the line by later (not read by stage 4)
    BomColumn(index=SAID, letter="D", header="נאמר", role="other", by="code"),
]
MAX_QUANTITY = 10000

Action = Literal["set_qty", "add_qty", "remove"]
Reason = Literal["not_in_message", "number_not_said", "unknown_line", "bad_quantity"]


def empty_table(panel_name: str) -> BomTable:
    return BomTable(source="chat", panel_name=panel_name, columns=COLUMNS, rows=[], mapping_sure=True)


_GLUED = re.compile(r"(\d+[Pp])(?=\d)")


def tidy(text: str) -> str:
    """The model's line as the grammar reads it: one space between values ("1P16A" → "1P 16A"). No number changes."""
    return " ".join(_GLUED.sub(r"\1 ", text).split())


def norm(text: str) -> str:
    """For finding the model's quote in the message: quote marks, spaces and case as the BOM words compare them."""
    return terms.norm(text).replace("״", '"')


@dataclass(frozen=True)
class Item:
    text: str
    quantity: int
    panel: str | None
    quote: str


@dataclass(frozen=True)
class Change:
    line: str  # the short name the model was shown (`L2`)
    action: Action
    quantity: int | None
    quote: str


@dataclass(frozen=True)
class Dropped:
    quote: str
    reason: Reason


@dataclass
class Checked:
    items: list[Item] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)


def _said(value: Decimal | int, heard: set[Decimal]) -> bool:
    return Decimal(value).normalize() in heard


def _numbers_of(text: str) -> list[Decimal]:
    return [Decimal(x.replace(",", ".")).normalize() for x in DIGITS.findall(text)]


def check(
    message: str,
    items: Sequence[Item],
    changes: Sequence[Change],
    lines: Mapping[str, object],
    panels: Sequence[str],
) -> Checked:
    """`message`: the text the model was shown. `lines`: the short names it was shown. `panels`: the build's."""
    said = norm(message)
    heard = numbers(message)
    known_panels = {norm(p): p for p in panels}
    out = Checked()
    for it in items:
        quote = it.quote.strip()
        if not quote or norm(quote) not in said:
            out.dropped.append(Dropped(it.quote or it.text, "not_in_message"))
            continue
        if not all(n in heard for n in _numbers_of(it.text)):
            out.dropped.append(Dropped(quote, "number_not_said"))
            continue
        if it.quantity < 1 or it.quantity > MAX_QUANTITY:
            out.dropped.append(Dropped(quote, "bad_quantity"))
            continue
        if it.quantity != 1 and not _said(it.quantity, heard):
            out.dropped.append(Dropped(quote, "number_not_said"))
            continue
        panel = None
        if it.panel and it.panel.strip():
            name = it.panel.strip()
            panel = known_panels.get(norm(name)) or (name if norm(name) in said else None)
        out.items.append(Item(tidy(it.text), it.quantity, panel, quote))
    for ch in changes:
        quote = ch.quote.strip()
        if not quote or norm(quote) not in said:
            out.dropped.append(Dropped(ch.quote or ch.line, "not_in_message"))
            continue
        if ch.line not in lines:
            out.dropped.append(Dropped(quote, "unknown_line"))
            continue
        if ch.action == "remove":
            out.changes.append(Change(ch.line, "remove", None, quote))
            continue
        qty = ch.quantity
        if qty is None or qty < 0 or qty > MAX_QUANTITY or (ch.action == "add_qty" and qty == 0):
            out.dropped.append(Dropped(quote, "bad_quantity"))
            continue
        if not _said(qty, heard):
            out.dropped.append(Dropped(quote, "number_not_said"))
            continue
        if ch.action == "set_qty" and qty == 0:
            out.changes.append(Change(ch.line, "remove", None, quote))
            continue
        out.changes.append(Change(ch.line, ch.action, qty, quote))
    return out


# --- the rows ---------------------------------------------------------------------------------------------------


def next_row(table: BomTable) -> int:
    return max((r.row for r in table.rows), default=0) + 1


def add_items(table: BomTable, items: Sequence[Item], default_panel: str) -> BomTable:
    rows = list(table.rows)
    n = next_row(table)
    for it in items:
        rows.append(BomRow(row=n, cells=[it.text, str(it.quantity), it.panel or default_panel, it.quote]))
        n += 1
    return table.model_copy(update={"rows": rows})


def _quantity(r: BomRow) -> int:
    cell = r.cells[QUANTITY] if len(r.cells) > QUANTITY else None
    return int(cell) if cell and cell.isdigit() else 0


def set_quantity(table: BomTable, rows: Sequence[int], qty: int) -> BomTable:
    """A line's quantity: its first row carries it, the line's other rows are removed (the line keeps its first row,
    so its name and key stay)."""
    first, rest = min(rows), set(rows) - {min(rows)}
    out = []
    for r in table.rows:
        if r.row == first:
            cells = list(r.cells)
            cells[QUANTITY] = str(qty)
            r = r.model_copy(update={"cells": cells})
        elif r.row in rest:
            r = r.model_copy(update={"removed": True})
        out.append(r)
    return table.model_copy(update={"rows": out})


def add_quantity(table: BomTable, rows: Sequence[int], qty: int) -> BomTable:
    live = [r for r in table.rows if r.row in set(rows) and not r.removed]
    return set_quantity(table, rows, sum(_quantity(r) for r in live) + qty)


def remove(table: BomTable, rows: Sequence[int]) -> BomTable:
    gone = set(rows)
    return table.model_copy(
        update={"rows": [r.model_copy(update={"removed": True}) if r.row in gone else r for r in table.rows]}
    )


def panel_names(table: BomTable, default_panel: str) -> list[str]:
    """The build's panels in the order its rows first name them; the default one first."""
    out = [default_panel]
    for r in table.rows:
        name = r.cells[PANEL] if len(r.cells) > PANEL and r.cells[PANEL] else None
        if name and norm(name) not in {norm(x) for x in out}:
            out.append(name)
    return out
