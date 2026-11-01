"""Pipeline step 3 (03 §3.4): pick a symbol class from a short list when the first look can't decide.

The model gets the symbol's crop (with a 50% margin, the symbol framed in red) and a sheet of the candidates, and
chooses one of them, says that none fits, or says it is not a symbol. It never names a class off the list; code
checks that too (`konboro.pipeline.detection.disambiguate`). Only small crops are sent, never a whole page (03 §13).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "symbol_disambiguation"

SYSTEM = """\
You decide what one symbol on an electrical-panel drawing is, for a panel-building factory. You choose only from \
the candidates you are given, or say that none of them fits, or that it is not a symbol at all."""

PROMPT = """\
Image 1 is a crop of the drawing; the symbol in question is framed in red. Image 2 shows the candidates, numbered.

Candidates:
{candidates}

A device is drawn in more than one way: the symbol may be the device itself, its coil, or one of its contacts drawn \
elsewhere (a relay's or timer's contact, a contactor's power contacts, a breaker's neutral pole). Choose the device it \
belongs to.

{context}
Decide:
- "choose": the symbol is one of the candidates; give its symbol_class exactly as listed.
- "none_of_these": it is an electrical symbol, but no candidate fits.
- "not_a_symbol": it is text, an arrow, a frame, a wire or a mark, not a device symbol.
confidence: from 0 to 1, how sure you are of the decision. reason: one short sentence, in Hebrew."""


class DisambiguationAnswer(BaseModel):
    decision: Literal["choose", "none_of_these", "not_a_symbol"]
    symbol_class: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str


def decide(
    client: LLMClient,
    crop: ImageInput,
    candidates_sheet: ImageInput,
    candidates: str,
    context: str,
    tenant_id: str | None = None,
) -> LLMResult[DisambiguationAnswer]:
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=PROMPT.format(candidates=candidates, context=context),
            output_schema=DisambiguationAnswer,
            images=[crop, candidates_sheet],
            tenant_id=tenant_id,
            max_tokens=4_000,
            effort="low",
        )
    )
