"""Pipeline step 1, the BOM-only path (01 §5.8), and later the quote audit (11 §4): reading a table.

Two calls on one route:
- `transcribe`: a photographed, scanned or handwritten table (a BOM page as an image). Every column with its role
  from a closed list, every row's cells as written with a confidence for each, and each row's box on a 0–1000 grid
  over the image. The form's heading gives the panel's and the project's names. There is no field for the customer
  or their contact details, so they can't come back (00 §7.1).
- `map_columns`: a spreadsheet whose headers code doesn't know. The model sees the header text and a few sample
  cells, with every number replaced by its shape (`<int>`, `<decimal>`) by the caller: no numeric value ever leaves,
  since a price column can't be told from a quantity column before the mapping (CLAUDE.md non-negotiable 6, S14
  decision 2).

Code checks both answers afterwards (konboro.pipeline.bom).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "table_transcription"

Role = Literal["item", "quantity", "panel", "model", "brand", "unit", "row_number", "price", "other"]

Box = tuple[int, int, int, int]  # on a 0–1000 grid; code clamps a value past the edge rather than retrying the call

ROLES = """\
Column roles (pick one per column):
- item: what the product is, as written (e.g. מא"ז 3X16, מגען 3X25, פחת 4X40, Schneider iC60N C16).
- quantity: how many.
- panel: which panel the row belongs to.
- model: a catalog or part number on its own column.
- brand: the manufacturer on its own column.
- unit: the unit of measure (יח', מ').
- row_number: a running row number.
- price: any money column (unit price, total, discount).
- other: anything else."""

SYSTEM = f"""\
You read bills of materials for a panel-building factory in Israel. Text is usually Hebrew, sometimes English, \
often handwritten. You copy what is written; you never correct, complete or guess a value.

{ROLES}"""

TRANSCRIBE = """\
The image is a bill of materials: a table, maybe a filled-in form, maybe handwritten and photographed. Transcribe it.

- columns: the table's columns from right to left as they appear in a Hebrew table, each with its header as written \
(null if none) and its role.
- rows: every row that has anything written in it, top to bottom. cells: one per column, in the columns' order, \
each with its text exactly as written (null when the cell is empty) and your confidence (0 to 1) that you read it \
right. A price column's cells are always null: do not copy money.
- box: the row's box [x0, y0, x1, y1] on a 0–1000 grid over the whole image, origin top left.
- A row that is the second line of the row above it (no quantity, the text continues) is still its own row.
- Leave out the form's printed header, its addresses, phone numbers, the customer's name and any signature.
- panel_name: the panel this list is for, when the form's heading names it (e.g. לוח חשמל קומה ב'); else null.
- project_name: the project, when the heading names it; else null."""

MAP = """\
A spreadsheet's columns, by letter. For each: its header as written, then up to five sample cells from the rows below \
it. Every number in the samples is replaced by its shape: <int> for a whole number, <decimal> for one with a \
fraction. Give each column its role.

{columns}"""


class Column(BaseModel):
    header: str | None
    role: Role


class Cell(BaseModel):
    text: str | None
    confidence: float = Field(description="0 to 1")


class Row(BaseModel):
    cells: list[Cell]
    box: Box


class TableAnswer(BaseModel):
    panel_name: str | None
    project_name: str | None
    columns: list[Column]
    rows: list[Row]


class ColumnRole(BaseModel):
    column: str = Field(description="The column's letter, as given")
    role: Role


class MappingAnswer(BaseModel):
    columns: list[ColumnRole]


def transcribe(client: LLMClient, image: ImageInput, tenant_id: str | None = None) -> LLMResult[TableAnswer]:
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=TRANSCRIBE,
            output_schema=TableAnswer,
            images=[image],
            tenant_id=tenant_id,
            max_tokens=8192,
        )
    )


def map_columns(client: LLMClient, columns: str, tenant_id: str | None = None) -> LLMResult[MappingAnswer]:
    """`columns`: one line per column, already masked by the caller (`konboro.pipeline.bom.mapping`)."""
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=MAP.format(columns=columns),
            output_schema=MappingAnswer,
            tenant_id=tenant_id,
            max_tokens=1024,
        )
    )
