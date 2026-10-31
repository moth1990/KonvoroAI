"""Pipeline step 4: tie the text written near each detected symbol to that symbol.

Input: one drawing tile + the symbols the detector found in it (id, family, box).
Output: per symbol, the electrical attributes read from the nearby text.
Pricing never happens here, and prices are never sent to the model.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import Example, ImageInput, LLMRequest

SYSTEM = (
    "You read electrical panel drawings. For each detected symbol, read the text written next to it "
    "and return its attributes. Use only what is written on the drawing. If a value is not written, "
    "return null for it and lower the confidence. Never guess a value."
)


class SymbolAttributes(BaseModel):
    symbol_id: str
    family: Literal["mcb", "rcd", "rcbo", "contactor", "main_switch", "other"]
    current_a: float | None = Field(None, description="Rated current in amperes, e.g. 16")
    poles: int | None = Field(None, description="1, 2, 3 or 4")
    curve: Literal["B", "C", "D"] | None = None
    breaking_capacity_ka: float | None = None
    residual_ma: int | None = Field(None, description="For RCD/RCBO, e.g. 30")
    raw_text: str = Field(description="The text exactly as written near the symbol")
    confidence: float = Field(ge=0, le=1)


class TextAssociationResult(BaseModel):
    symbols: list[SymbolAttributes]


def associate_text(
    llm: LLMClient,
    tile: ImageInput,
    detections: list[dict],
    examples: list[Example],
    tenant_id: str,
) -> TextAssociationResult:
    lines = [f"- id={d['id']} family={d['family']} box={d['box']}" for d in detections]
    request = LLMRequest(
        stage="text_association",
        system=SYSTEM,
        user_text="Detected symbols in this tile:\n" + "\n".join(lines),
        output_schema=TextAssociationResult,
        images=[tile],
        examples=examples,
        tenant_id=tenant_id,
    )
    return llm.run(request).data
