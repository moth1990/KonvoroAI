"""A stand-in model for E2E, integration tests and `make dev` without an API key: fixed, made-up answers.

Never used by the product's workers when a key is set, and never in the eval (cassettes replay real answers).

Pages are classified like NURSERY-1 (01 §5.7 example): page 1 technical data, pages 2–3 factory templates, page 4 the
front view, the rest single-line diagrams. A file whose name contains "unsure" gets a low-confidence first page, so
stage 1 asks the user to confirm (01 §5.6); one whose name contains "bom" is a BOM table.

OCR (stage 2) reads one word, "Q1", at the top left of each tile's ink, so the stage's ink check keeps it.

Symbol detection (stage 3) finds one breaker on each tile, at the same spot, tagged "Q1"; the search around text
with no symbol finds nothing. The disambiguation call picks the first candidate.

The tile agent (stage 4) answers once for every symbol it is asked about, with no values: nothing is written beside
the stand-in breakers but their tag.

The catalog agent (stage 5) chooses the first candidate it is shown, at 0.7.

The reviewing agent (stage 6) notes one thing about the first component it is shown, at 0.6 (an info, never a
colour), its message marked "stand-in".

The chat coordinator (08, S25) follows a short script on the review screen's suggestions: why lines are yellow
(`query_lines` on yellow), what is missing to send (`query_lines` on red), replacing ABB breakers with Schneider
(`propose_change` `replace_brand`), showing the red lines (`focus_ui`), how many RCDs (`query_lines` on `rcd`),
deleting or setting the quantity of the selected lines (`propose_change`). Anything else gets a fixed answer that
says so. Its answers name the lines and the first line's total by the references the tools gave it.

A picture of a BOM (01 §5.8) reads as a short handwritten form for "לוח קומה 1": quantity and item columns, three
items, the third continued on the next row, and the last row clear of the image's edge. A spreadsheet's unknown
headers map by position: the first column is the item, the second the quantity.
"""

import io
import re
from typing import Any

from PIL import Image

from konboro_llm import LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.catalog_disambiguation import STAGE as CATALOG
from konboro_llm.stages.chat_command import STAGE as CHAT
from konboro_llm.stages.chat_compaction import STAGE as COMPACT
from konboro_llm.stages.context_extraction import GeneralNotes
from konboro_llm.stages.ocr_transcription import STAGE as OCR
from konboro_llm.stages.page_classification import STAGE as CLASSIFY
from konboro_llm.stages.page_classification import TitleBlockAnswer
from konboro_llm.stages.symbol_detection import STAGE as DETECT
from konboro_llm.stages.symbol_disambiguation import STAGE as DISAMBIGUATE
from konboro_llm.stages.table_transcription import STAGE as TABLE
from konboro_llm.stages.table_transcription import MappingAnswer, QuoteAnswer
from konboro_llm.stages.text_association import STAGE as ASSOCIATE
from konboro_llm.stages.validator_review import STAGE as REVIEW

UNSURE = "unsure"
BOM = "bom"  # a picture whose file name has this is a BOM page
LOW_CONFIDENCE = 0.6
TITLE_BLOCK = {"designer": "מפעל הדגמה", "drawing_number": "D-100", "date": "2026-10-05", "panel_name": "לוח ראשי"}
KINDS = {1: "technical_data", 2: "factory_template", 3: "factory_template", 4: "panel_front_view"}
_PAGE = re.compile(r'^Page (\d+) of (\d+), file "(.*)"\.', re.M)


def classification(request: LLMRequest[Any]) -> dict[str, Any]:
    found = _PAGE.search(request.user_text)
    page, file_name = (int(found[1]), found[3]) if found else (1, "")
    kind = "bom_table" if BOM in file_name.lower() else KINDS.get(page, "single_line_diagram")
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


_FIRST_SKU = re.compile(r"^1\. sku: (.+?) \|", re.M)


def catalog_choice(request: LLMRequest[Any]) -> dict[str, Any]:
    first = _FIRST_SKU.search(request.user_text)
    return {
        "chosen_sku": first[1] if first else None,
        "confidence": 0.7,
        "reason": "stand-in",
        "missing_attributes": [],
    }


def review(request: LLMRequest[Any]) -> dict[str, Any]:
    first = re.search(r"^(c\d\d) \|", request.user_text, re.M)
    if first is None:
        return {"issues": []}
    issue = {"type": "other", "component_ids": [first[1]], "bbox": None, "message": "stand-in: בדיקה לדוגמה"}
    return {"issues": [{**issue, "confidence": 0.6}]}


def tile_agent(request: LLMRequest[Any]) -> dict[str, Any]:
    return {"instances": [{"det": d} for d in _OWN.findall(request.user_text)]}


BOM_PANEL = "לוח קומה 1"
BOM_ROWS = [("1", "מפסק 3X63"), ("12", 'מא"ז 1X16'), ("1", "רב מודד SATEC"), (None, "כולל יציאת ממסר")]
_LETTER = re.compile(r"^- ([A-Z]+):", re.M)


# A made-up audited quote (11 §5.2): (item, quantity, unit price, line total). The last line's total is wrong on
# purpose, so the arithmetic check has something to find.
QUOTE_NUMBER = "10999"
QUOTE_ROWS = [('מא"ז 1X16A', "2", "42", "84"), ("מגען 3X25A", "1", "180", "180"), ("שעון שבת", "1", "250", "260")]


def quote_table() -> dict[str, Any]:
    rows = [
        {
            "cells": [{"text": t, "confidence": 0.95} for t in row],
            "box": [80, 300 + 60 * n, 920, 350 + 60 * n],
        }
        for n, row in enumerate(QUOTE_ROWS)
    ]
    return {
        "quote_number": QUOTE_NUMBER,
        "quote_date": "02/11/2026",
        "columns": [
            {"header": "תיאור", "role": "item"},
            {"header": "כמות", "role": "quantity"},
            {"header": "מחיר", "role": "unit_price"},
            {"header": 'סה"כ', "role": "line_total"},
        ],
        "rows": rows,
        "totals": [{"label": 'סה"כ', "amount": "524", "confidence": 0.95}],
    }


def bom_table(request: LLMRequest[Any]) -> dict[str, Any]:
    if request.output_schema is QuoteAnswer:
        return quote_table()
    if request.output_schema is MappingAnswer:
        letters = _LETTER.findall(request.user_text)
        roles = ["item", "quantity"]
        return {"columns": [{"column": x, "role": roles[i] if i < 2 else "other"} for i, x in enumerate(letters)]}
    rows = [
        {
            "cells": [{"text": qty, "confidence": 0.95}, {"text": item, "confidence": 0.9}],
            "box": [100, 300 + 60 * n, 900, 350 + 60 * n],
        }
        for n, (qty, item) in enumerate(BOM_ROWS)
    ]
    return {
        "panel_name": BOM_PANEL,
        "project_name": "פרויקט הדגמה",
        "columns": [{"header": "כמות", "role": "quantity"}, {"header": "פרטים", "role": "item"}],
        "rows": rows,
    }


CHAT_UNKNOWN = "זו תשובה של מודל הדמה: הוא מכיר רק את הפקודות שמתחת לחלון."
_SELECTED = re.compile(r"selected lines ([L0-9, ]+)")
_QTY = re.compile(r"(\d+)")


def _chat_decide(text: str) -> dict[str, Any]:
    found = _SELECTED.search(text)
    selected = [x.strip() for x in (found[1].split(",") if found else []) if x.strip()]
    message = text.split("]\n", 1)[-1]
    qty = _QTY.search(message)
    if re.search(r"שניידר|schneider", message, re.I):
        change: dict[str, Any] = {
            "type": "replace_brand",
            "target": {"manufacturers": ["ABB"], "families": ["circuit_breaker"]},
            "manufacturer": "Schneider Electric",
        }
        return {
            "tool_calls": [
                {"name": "propose_change", "args": {"changes": [change], "summary_he": 'החלפת מא"זי ABB ל-Schneider'}}
            ]
        }
    if re.search(r"מחק|תמחק", message) and selected:
        change = {"type": "delete_lines", "target": {"lines": selected}}
        return {
            "tool_calls": [
                {"name": "propose_change", "args": {"changes": [change], "summary_he": "מחיקת השורות המסומנות"}}
            ]
        }
    if re.search(r"כמות", message) and selected and qty:
        change = {"type": "set_quantity", "target": {"lines": selected}, "qty": int(qty[1])}
        return {"tool_calls": [{"name": "propose_change", "args": {"changes": [change], "summary_he": "שינוי כמות"}}]}
    if re.search(r"צהוב", message):
        return {"tool_calls": [{"name": "query_lines", "args": {"statuses": ["yellow"]}}]}
    if re.search(r"חסר|לשלוח", message):
        return {"tool_calls": [{"name": "query_lines", "args": {"statuses": ["red"]}}]}
    if re.search(r"אדומ", message):
        return {"tool_calls": [{"name": "focus_ui", "args": {"statuses": ["red"]}}]}
    if re.search(r"פחת", message):
        return {"tool_calls": [{"name": "query_lines", "args": {"families": ["rcd"]}}]}
    return {"answer": {"text": CHAT_UNKNOWN, "clarification_options": []}}


def _chat_answer(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if "error" in result:
        return {"answer": {"text": f"לא הצלחתי: {result['error']}"}}
    if name == "query_lines":
        lines = result.get("lines", [])
        refs = ", ".join("{{line:" + ln["line"] + "}}" for ln in lines[:8])
        total = next((ln["line_total"] for ln in lines if ln.get("line_total")), None)
        text = f"מצאתי {result['total_count']} שורות: {refs}." if lines else "לא מצאתי שורות כאלה."
        if total:
            text += " סך השורה הראשונה עם מחיר: {{" + total + "}}."
        return {"answer": {"text": text}}
    if name == "propose_change":
        text = f"הכנתי הצעה ({result['proposal']}) ל-{result['affected_line_count']} שורות. שום דבר לא משתנה עד שתאשר."
        if result.get("not_changed"):
            text += f" {len(result['not_changed'])} שורות לא מתחלפות, הסיבה בכרטיס."
        return {"answer": {"text": text}}
    if name == "focus_ui":
        return {"answer": {"text": "סימנתי את השורות בטבלה."}}
    return {"answer": {"text": "בוצע."}}


def chat_turn(turn: Any) -> dict[str, Any]:
    """The coordinator's next step: the current message is the last user turn with text."""
    turns = turn.turns
    at = max(i for i, t in enumerate(turns) if t.role == "user" and t.text)
    text = turns[at].text or ""
    if text.startswith("Your answer wrote an amount"):
        return {"answer": {"text": "הסכום מופיע בכרטיס."}}
    after = turns[at + 1 :]
    if not after:
        return _chat_decide(text)
    call = after[-2].tool_calls[-1]
    return _chat_answer(call.name, after[-1].tool_results[-1].content)


def answer(request: Any) -> dict[str, Any]:
    if request.stage == CHAT:
        return chat_turn(request)
    if request.stage == COMPACT:
        return {"summary": "סיכום של מודל הדמה."}
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
    if request.stage == TABLE:
        return bom_table(request)
    if request.stage == CATALOG:
        return catalog_choice(request)
    if request.stage == REVIEW:
        return review(request)
    if request.output_schema is TitleBlockAnswer:
        return TITLE_BLOCK
    if request.output_schema is GeneralNotes:
        return {"markdown": "- הערה"}
    return {}


def fake_providers() -> dict[str, Any]:
    return {"anthropic": FakeProvider(answer)}
