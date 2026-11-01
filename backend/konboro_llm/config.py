"""Which provider and model each pipeline stage uses.

Changing a model for one stage is a one-line change here, then a run of the golden set.

Version 1.0 uses Claude only, including fallbacks. Other providers plug in by implementing
LLMProvider (base.py) and registering it in LLMClient.providers; no stage code changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageRoute:
    provider: str  # key in LLMClient.providers
    model: str
    max_attempts: int = 2  # schema-validation retries (network retries are the SDK's job)
    fallback: StageRoute | None = None


# Model IDs are examples. Pick per stage by running the golden set, not by intuition.
# Stage keys match specs/00-architecture.md section 7.1.
ROUTES: dict[str, StageRoute] = {
    # Step 1: classify each page (single-line, legend, notes...) from a thumbnail.
    "page_classification": StageRoute(provider="anthropic", model="claude-haiku-5-5"),
    # Step 2: read the words on one drawing tile, with a box for each. Interim, until S31 picks Google Vision or
    # Azure (S10 decision; 02 §2.3).
    "ocr_transcription": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Step 3: find the symbols on one drawing tile, from the closed family and class lists. Interim, until the
    # phase-4 family detector (S12 decision; 03 §3.2).
    "symbol_detection": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Step 3: pick a symbol class from a short list when the first look can't decide.
    "symbol_disambiguation": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Step 4: read text near each symbol and tie it to the symbol (vision + reasoning).
    "text_association": StageRoute(
        provider="anthropic",
        model="claude-sonnet-5-5",
        fallback=StageRoute(provider="anthropic", model="claude-opus-5-5"),
    ),
    # Step 5: choose between a few catalog candidates when the rules can't decide.
    "catalog_disambiguation": StageRoute(provider="anthropic", model="claude-haiku-5-5"),
    # Step 6: independent per-panel review for issues the rule engine doesn't cover.
    "validator_review": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Step 1: structured extraction from context pages (technical data, front view, legend).
    "context_extraction": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Step 1 (BOM-only path) and spec 11 (quote audit): transcribe tables from images or handwriting.
    "table_transcription": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Chat command layer: turn "replace all MCBs with Schneider" into a structured action.
    "chat_command": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Chat layer: summarize old turns when the conversation exceeds its token budget (spec 08 §5.2.1).
    "chat_compaction": StageRoute(provider="anthropic", model="claude-haiku-5-5"),
    # Behind the chat_quote_builder flag (version 1.0): turn chat or transcribed speech into BOM lines (spec 13 §4.2).
    "chat_bom_extraction": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
    # Chat sub-agent: answer "why" about one quote line from its trace and a drawing crop.
    "line_explanation": StageRoute(provider="anthropic", model="claude-sonnet-5-5"),
}
