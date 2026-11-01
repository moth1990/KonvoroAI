"""Pipeline step 3 (03 §3.2), interim: the symbols on one drawing tile, each with a box, a family and a class, found by
a vision model.

03 §3.2 wants a family detector of our own, trained on labelled drawings; there are none yet (03 §12, 00 §14). Until
phase 4 this route stands in (S12 decision): the model gets our reference sheet and one tile, and picks every family
and class from the closed lists it is given. Code checks every answer (`konboro.pipeline.detection.tiles`): the
family and class are in the library, the box lies inside the tile and over ink, and is shrunk to the ink.

The model gets one tile and the reference sheet, and nothing else: no prices, no customer details, no other page
(00 §7.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "symbol_detection"

SYSTEM = """\
You find the electrical symbols on a cropped piece of an electrical-panel drawing (a single-line, power or control \
diagram) for a panel-building factory. You report only what is drawn, and you name each symbol only from the lists \
you are given. A missed symbol is a missing line in a price quote, so report every symbol you see, and say when you \
are unsure."""

PROMPT = """\
Image 1 is our reference sheet: a numbered example drawing of each symbol class. Designers draw them differently, so \
match by shape and meaning, not by exact look. Image 2 is the tile to search, {w} × {h} pixels.

List every electrical symbol drawn in image 2.

Families (family: what it looks like → its classes):
{families}

Boxes with text: some designers draw a device as a plain rectangle with text inside ("מ.פ.", "C1", "TC", "SATEC \
135E"). Report it as the family its text means, and copy the text into box_text. Known texts: {abbreviations}.

For each symbol, once:
- box: [x0, y0, x1, y1] in pixels of image 2, origin top left, tight around the whole symbol (a breaker's cross, \
contact, pole marks and thermal hook are one symbol, one box, also when the cross is drawn a little above the \
blade), without its text labels and without the wires leading into it.
- family and symbol_class: from the lists above; the class must belong to the family.
- role: device (the device itself), power_contact (a contactor's power contacts), coil (a contactor's or relay's \
coil), relay_contact (a contact of a relay, timer or controller), aux_contact (an auxiliary contact mounted on \
another device, 13/14 or 21/22), front_view (a device drawn on a panel's front view).
- tag: the device designator written next to the symbol, exactly as written (F1, Q0, QG1, C3, HT2, SW1, R5, TH1, \
FNV, TC-G1), or null; for a box whose text is its tag (R1, C1, NVR), that text; for contacts joined by a dashed \
line to a tag (C1 in a small box), that tag. Not a rating (C16, 3X25A, 30mA, \
INC=8A), a cable or a wire number.
- box_text: the text inside the rectangle when the symbol is a box with text, else null.
- orientation: 0 when the line runs through the symbol from top to bottom, 90 when it runs left to right.
- sure: true when you are sure of the family and class, false when you are not.

Leave out: a symbol cut by the image's edge so that part of it is missing (the neighbouring tile has it whole); \
junction dots; text, arrows, the frame, the title block, tables, cable marks and plain wires.
If there is no symbol, return an empty list."""


class SymbolAnswer(BaseModel):
    box: list[float] = Field(description="[x0, y0, x1, y1] in pixels of image 2")
    family: str
    symbol_class: str
    role: Literal["device", "power_contact", "coil", "relay_contact", "aux_contact", "front_view"] = "device"
    tag: str | None = None
    box_text: str | None = None
    orientation: Literal[0, 90] = 0
    sure: bool


class DetectionAnswer(BaseModel):
    symbols: list[SymbolAnswer] = []


def detect(
    client: LLMClient,
    sheet: ImageInput,
    tile: ImageInput,
    size_px: tuple[int, int],
    families: str,
    abbreviations: str,
    tenant_id: str | None = None,
    *,
    hint: str = "",
) -> LLMResult[DetectionAnswer]:
    """`hint` is added for the orphan-text search (03 §3.6), where a symbol is expected near some text."""
    text = PROMPT.format(w=size_px[0], h=size_px[1], families=families, abbreviations=abbreviations)
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=f"{text}\n\n{hint}" if hint else text,
            output_schema=DetectionAnswer,
            images=[sheet, tile],
            tenant_id=tenant_id,
            max_tokens=16_000,
            effort="low",
        )
    )
