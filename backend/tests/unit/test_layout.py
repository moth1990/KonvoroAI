"""The package layout from docs/dev-strategy.md §3 exists and imports cleanly."""

import importlib

import pytest

PACKAGES = [
    "konboro",
    "konboro.api",
    "konboro.db",
    "konboro.contracts",
    "konboro.pipeline",
    "konboro.pipeline.stages",
    "konboro.domain",
    "konboro.services",
    "konboro_llm",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


def test_llm_gateway_has_a_route_for_every_stage_key() -> None:
    # Stage keys from specs/00-architecture.md §7.1. A stage without a route would fail at runtime.
    from konboro_llm.config import ROUTES

    expected = {
        "page_classification",
        "context_extraction",
        "table_transcription",
        "ocr_transcription",  # stage 2, interim until S31 (S10 decision)
        "symbol_detection",  # stage 3, interim until the phase-4 family detector (S12 decision)
        "symbol_disambiguation",
        "text_association",
        "catalog_disambiguation",
        "validator_review",
        "chat_command",
        "chat_compaction",
        "chat_bom_extraction",
        "line_explanation",
    }
    assert set(ROUTES) == expected
