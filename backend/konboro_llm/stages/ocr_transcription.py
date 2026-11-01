"""Pipeline step 2 (02 §2.3), interim: the words on one drawing tile, each with a box, read by a vision model.

02 §2.3 wants an OCR service, because a language model's word positions are not reliable. Until S31 picks Google
Vision or Azure (keys: roadmap B4), this route stands in (S10 decision), and code checks every answer: a box must lie
inside the image and over ink, and the copies of a word in overlapping tiles are compared
(`konboro.pipeline.extraction.ocr`).

The model gets one tile, or one enlarged crop for a re-read, and nothing else: no prices, no customer details, no
other page (00 §7.1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "ocr_transcription"

SYSTEM = """\
You transcribe the text on a cropped piece of an electrical-panel drawing (a single-line or control diagram) for a \
panel-building factory. You are an OCR engine: copy exactly what is written, character by character. Never correct, \
complete or guess a value; a value that is hard to read is copied as you see it and marked unsure."""

PROMPT = """\
The image is {w} × {h} pixels. List every word written in it.

- One entry per word: a run of characters without a space. Keep electrical tokens whole: C16, 3X25A, 4X16+10mm², \
NYY, 30mA, INC=8A, Q1.2, TC-G1.
- box: [x0, y0, x1, y1] in pixels of this image, origin top left, tight around the word's ink.
- rotation: the direction the word reads, counter-clockwise from left-to-right: 0 normal, 90 reads bottom to top, \
270 reads top to bottom, 180 upside down. Drawings have much vertical text along the lines; read it too.
- legible: "clear" when you are sure of every character, else "unsure".
- Hebrew words in reading order, as a person would type them.
- Skip a word that is cut by the image's edge so that part of it is missing.
- Leave out lines, symbols and hatching that are not letters or digits.
If there is no text, return an empty list."""


class OcrWordAnswer(BaseModel):
    text: str
    box: list[float] = Field(description="[x0, y0, x1, y1] in pixels of the image")
    rotation: Literal[0, 90, 180, 270] = 0
    legible: Literal["clear", "unsure"]


class OcrAnswer(BaseModel):
    words: list[OcrWordAnswer] = []


def transcribe(
    client: LLMClient, image: ImageInput, size_px: tuple[int, int], tenant_id: str | None = None
) -> LLMResult[OcrAnswer]:
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=PROMPT.format(w=size_px[0], h=size_px[1]),
            output_schema=OcrAnswer,
            images=[image],
            tenant_id=tenant_id,
            max_tokens=16_000,
            effort="low",  # copying what is written is perception, not reasoning; thinking is billed as output
        )
    )
