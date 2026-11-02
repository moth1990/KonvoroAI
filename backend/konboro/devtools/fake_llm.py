"""A stand-in model for E2E, integration tests and `make dev` without an API key: fixed, made-up answers.

Never used by the product's workers when a key is set, and never in the eval (cassettes replay real answers).

Pages are classified like NURSERY-1 (01 §5.7 example): page 1 technical data, pages 2–3 factory templates, page 4 the
front view, the rest single-line diagrams. A file whose name contains "unsure" gets a low-confidence first page, so
stage 1 asks the user to confirm (01 §5.6).

OCR (stage 2) reads one word, "Q1", at the top left of each tile's ink, so the stage's ink check keeps it.

Symbol detection (stage 3) finds one breaker on each tile, at the same spot, tagged "Q1"; the search around text
with no symbol finds nothing. The disambiguation call picks the first candidate.

The tile agent (stage 4) answers once for every symbol it is asked about, with no values: nothing is written beside
the stand-in breakers but their tag.
"""

import io
import re
from typing import Any

from PIL import Image

from konboro_llm import LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.context_extraction import GeneralNotes
from konboro_llm.stages.ocr_transcription import STAGE as OCR
from konboro_llm.stages.page_classification import STAGE as CLASSIFY
from konboro_llm.stages.page_classification import TitleBlockAnswer
from konboro_llm.stages.symbol_detection import STAGE as DETECT
from konboro_llm.stages.symbol_disambiguation import STAGE as DISAMBIGUATE
from konboro_llm.stages.text_association import STAGE as ASSOCIATE

UNSURE = "unsure"
LOW_CONFIDENCE = 0.6
TITLE_BLOCK = {"designer": "מפעל הדגמה", "drawing_number": "D-100", "date": "2026-10-05", "panel_name": "לוח ראשי"}
KINDS = {1: "technical_data", 2: "factory_template", 3: "factory_template", 4: "panel_front_view"}
_PAGE = re.compile(r'^Page (\d+) of (\d+), file "(.*)"\.', re.M)


def classification(request: LLMRequest[Any]) -> dict[str, Any]:
    found = _PAGE.search(request.user_text)
    page, file_name = (int(found[1]), found[3]) if found else (1, "")
    kind = KINDS.get(page, "single_line_diagram")
    confidence = LOW_CONFIDENCE if page == 1 and UNSURE in file_name.lower() else 0.95
    diagram = kind == "single_line_diagram"
    return {
        "page_kind": kind,
        "page_kind_confidence": confidence,
        "orientation": 0,
        "component_labels": "tags_and_models" if diagram else "not_applicable",
        "panels": [{"name": None, "bbox": [60, 60, 940, 760], "confidence": 0.9}] if diagram else [],
        "regions": [{"region_kind": "title_block", "bbox": [0, 800, 1000, 1000], "confidence": 0.9}],
        "title_block": TITLE_BLOCK,
        "language": "he",
        "reasoning": "fake",
    }


OCR_SPOT_PX = 48


def ocr_words(request: LLMRequest[Any]) -> dict[str, Any]:
    image = Image.open(io.BytesIO(request.images[0].data)).convert("L")
    ink = image.point(lambda v: 255 if v < 160 else 0).getbbox()
    if ink is None:
        return {"words": []}
    x0, y0 = ink[0], ink[1]
    box = [x0, y0, min(ink[2], x0 + OCR_SPOT_PX), min(ink[3], y0 + OCR_SPOT_PX)]
    return {"words": [{"text": "Q1", "box": box, "rotation": 0, "legible": "clear"}]}


def symbols(request: LLMRequest[Any]) -> dict[str, Any]:
    if "probably drawn next to it" in request.user_text:  # the search around orphan text (03 §3.6)
        return {"symbols": []}
    image = Image.open(io.BytesIO(request.images[1].data)).convert("L")  # [0] is the reference sheet
    ink = image.point(lambda v: 255 if v < 160 else 0).getbbox()
    if ink is None:
        return {"symbols": []}
    x0, y0 = ink[0], ink[1]
    box = [x0, y0, min(ink[2], x0 + OCR_SPOT_PX), min(ink[3], y0 + OCR_SPOT_PX)]
    symbol = {"box": box, "family": "circuit_breaker", "symbol_class": "mcb", "role": "device", "tag": "Q1"}
    return {"symbols": [{**symbol, "box_text": None, "orientation": 0, "sure": True}]}


_CANDIDATE = re.compile(r"^- ([a-z_]+):", re.M)


def decision(request: LLMRequest[Any]) -> dict[str, Any]:
    first = _CANDIDATE.search(request.user_text)
    return {"decision": "choose", "symbol_class": first[1] if first else None, "confidence": 0.9, "reason": "fake"}


_OWN = re.compile(r"^- (d\d+):", re.M)


def tile_agent(request: LLMRequest[Any]) -> dict[str, Any]:
    return {"instances": [{"det": d} for d in _OWN.findall(request.user_text)]}


def answer(request: LLMRequest[Any]) -> dict[str, Any]:
    if request.stage == CLASSIFY:
        return classification(request)
    if request.stage == OCR:
        return ocr_words(request)
    if request.stage == DETECT:
        return symbols(request)
    if request.stage == DISAMBIGUATE:
        return decision(request)
    if request.stage == ASSOCIATE:
        return tile_agent(request)
    if request.output_schema is TitleBlockAnswer:
        return TITLE_BLOCK
    if request.output_schema is GeneralNotes:
        return {"markdown": "- הערה"}
    return {}


def fake_providers() -> dict[str, Any]:
    return {"anthropic": FakeProvider(answer)}
