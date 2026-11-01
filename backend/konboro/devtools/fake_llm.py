"""A stand-in model for E2E, integration tests and `make dev` without an API key: fixed, made-up answers.

Never used by the product's workers when a key is set, and never in the eval (cassettes replay real answers).

Pages are classified like NURSERY-1 (01 §5.7 example): page 1 technical data, pages 2–3 factory templates, page 4 the
front view, the rest single-line diagrams. A file whose name contains "unsure" gets a low-confidence first page, so
stage 1 asks the user to confirm (01 §5.6).
"""

import re
from typing import Any

from konboro_llm import LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.context_extraction import GeneralNotes
from konboro_llm.stages.page_classification import STAGE as CLASSIFY
from konboro_llm.stages.page_classification import TitleBlockAnswer

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


def answer(request: LLMRequest[Any]) -> dict[str, Any]:
    if request.stage == CLASSIFY:
        return classification(request)
    if request.output_schema is TitleBlockAnswer:
        return TITLE_BLOCK
    if request.output_schema is GeneralNotes:
        return {"markdown": "- הערה"}
    return {}


def fake_providers() -> dict[str, Any]:
    return {"anthropic": FakeProvider(answer)}
