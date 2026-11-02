"""Pipeline step 4 (04 §5.4): the tile agent. Which text belongs to which symbol, when code could not decide.

The model gets one tile with a numbered box around every symbol (d1, d2… for the symbols it answers for, c1, c2… for
neighbours it only looks at), the spans in the tile with their ids, code's proposed assignment, and the attributes
each family needs. It answers once per symbol: each value with its evidence (a span id it was read from, or for poles
only, the drawing's pole marks), multiplicity, shared labels, symbols it thinks were missed, and spans it leaves out.

Code checks every value afterwards (`konboro.pipeline.association.agent`): the cited span exists, lies near the
symbol, and really says the value (04 §5.5). A value with no evidence is null; the model never guesses (00 §5.3).

The model gets one tile, its spans and the legend, and nothing else: no prices, no customer details, no title block,
no factory defaults or general notes (04 §5.4, §12).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "text_association"

SYSTEM = """\
You read the text written beside each symbol on an electrical-panel drawing, for a panel-building factory's price \
quote. You decide which text belongs to which symbol, and read from it the values each symbol needs. You use only \
what is written or drawn: a value that is not there is null. Never guess a value from what is common."""

PROMPT = """\
The image is one tile of the drawing, {w} × {h} pixels, origin top left. Each symbol is framed and numbered: \
{own_colour} frames (d1, d2, …) are the symbols you answer for; {context_colour} frames (c1, c2, …) are neighbours, \
shown only to help you decide who a text belongs to. Do not answer for them.

Symbols you answer for (id: family / class, box in pixels, the values to read):
{own}

Neighbours (read only):
{context}

Text in and around the tile (id: "text", box in pixels):
{spans}

Code's proposed assignment, to confirm or correct:
{proposal}

What the values mean:
- current_a: the rated current in A (C16 → 16, 3×16A → 16, 500A/630A beside a moulded-case breaker → 630).
- poles: 1–4 (3×16A → 3, 4P → 4, 16+N and 1P+N → 1 with neutral true): poles, not pins, cores or fuses. A fuse's \
3×100A is three fuses (multiplicity 3, current 100); a socket's 5×16A has 3 poles and neutral true. Poles may also \
be drawn: short slanted strokes across the line (three strokes → 3), or the number of lines feeding the symbol; \
on a single-line diagram that marks poles with strokes, one line with no strokes is 1. Then evidence is \
"graphic", span_ids is empty, and graphic_note says what you saw. Graphic evidence is allowed for poles only.
- curve: B, C or D (C16 → C). breaking_capacity_ka: 6, 10, 10kA. residual_ma: 30mA, 0.03A → 30.
- setting_a: an adjustable breaker's setting, only when written as a pair (500A/630A → 500) or as Ir=500A. \
range_min_a / range_max_a: a motor protector's range (1-2.4A). ratio_primary_a / ratio_secondary_a: a current \
transformer's ratio (800/5A → 800, 5).
- contacts: an auxiliary contact's numbers as written (21/22). positions: a selector's positions as written \
(1-0-2). color: a lamp's or button's colour, written in words (ירוק → green).
- INC=, Ib=: the circuit's load current, never the device's rated current. A cable (5×2.5²) and a circuit number \
are not device values.
{legend}
For each symbol you answer for, exactly once:
- attributes: one entry per value you found, of those listed for it; leave out the ones that are not written. \
value: the number, letter or true/false. evidence: "text" (span_ids: the spans it is written in) or "graphic" \
(poles only). confidence 0–1. A value code proposed that is wrong or not there: give it with value null.
- multiplicity: how many identical devices this one symbol stands for, written beside the device itself ("16A MCB \
(x6)" → 6), with the span; 1 when nothing says so. "(x4)" written on the outgoing line or cable means one device \
feeding 4 outlets: that is 1.
- brand_hint: a brand written beside it (ABB, Schneider), or null. explicit_texts: the ids of the spans that \
belong to it (s3, s7).
- uses_shared_label: true when its values come from one label written for several symbols.
shared_labels: one text that applies to several symbols in a row ("C10" over four breakers), with the symbols.
possible_missed: a device symbol in the tile with no frame (its box in pixels, a family guess, the spans beside it).
unassigned_spans: texts that belong to no symbol you answer for (a circuit number, a cable, a load's name)."""


Evidence = Literal["text", "graphic"]


class AttributeAnswer(BaseModel):
    name: str
    value: float | str | bool | None
    evidence: Evidence | None
    span_ids: list[str] = []
    confidence: float | None = Field(None, ge=0, le=1)
    graphic_note: str | None = None


class MultiplicityAnswer(BaseModel):
    count: int = Field(1, ge=1)
    span_ids: list[str] = []


class InstanceAnswer(BaseModel):
    det: str
    attributes: list[AttributeAnswer] = []
    multiplicity: MultiplicityAnswer = MultiplicityAnswer(count=1)
    brand_hint: str | None = None
    explicit_texts: list[str] = []
    uses_shared_label: bool = False


class SharedLabelAnswer(BaseModel):
    span_ids: list[str]
    applies_to: list[str]
    reason: str = ""


class MissedAnswer(BaseModel):
    bbox_tile_px: list[float]
    family_guess: str
    span_ids: list[str] = []
    reason: str = ""


class UnassignedAnswer(BaseModel):
    span_id: str
    reason: str = ""


class TileAnswer(BaseModel):
    instances: list[InstanceAnswer] = []
    shared_labels: list[SharedLabelAnswer] = []
    possible_missed: list[MissedAnswer] = []
    unassigned_spans: list[UnassignedAnswer] = []


OWN_COLOUR = "Red"
CONTEXT_COLOUR = "Blue"


def associate(
    client: LLMClient,
    tile: ImageInput,
    size_px: tuple[int, int],
    own: str,
    context: str,
    spans: str,
    proposal: str,
    legend: str = "",
    tenant_id: str | None = None,
    *,
    correction: str = "",
    fallback: bool = False,
) -> LLMResult[TileAnswer]:
    """`correction` says what code refused in the last answer (04 §5.5, the retry); `fallback` goes straight to the
    stronger model, after two answers code refused."""
    text = PROMPT.format(
        w=size_px[0],
        h=size_px[1],
        own_colour=OWN_COLOUR,
        context_colour=CONTEXT_COLOUR,
        own=own,
        context=context or "(none)",
        spans=spans or "(none)",
        proposal=proposal or "(none)",
        legend=f"\nThe drawing's legend:\n{legend}\n" if legend else "",
    )
    if correction:
        text += f"\n\nYour last answer was refused: {correction}\nAnswer again, for every symbol d1… once."
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=text,
            output_schema=TileAnswer,
            images=[tile],
            tenant_id=tenant_id,
            max_tokens=16_000,
            effort="low",
            start_at_fallback=fallback,
        )
    )
