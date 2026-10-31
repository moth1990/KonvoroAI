"""Stage contracts (00 §5): each model accepts its spec's §6 example, and its JSON schema is pinned.

A failing snapshot means a contract changed. If that was intended, update the spec that defines it and every spec
that consumes it (00 §5), then rewrite the snapshots:
`KONBORO_UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_contracts.py`.
"""

import json
import os
import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from konboro.contracts import STAGE_OUTPUTS
from konboro.contracts.detection import PageDetections
from konboro.contracts.extraction import PageExtraction
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import ComponentMatch
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult
from konboro.contracts.validation import ValidationResult

SPECS = Path(__file__).resolve().parents[3] / "specs"
SNAPSHOTS = Path(__file__).parent / "snapshots" / "contracts"

# The §6.1 example of each spec, and the model it shows.
EXAMPLES: dict[str, type[BaseModel]] = {
    "01-intake-page-classification.md": IntakeResult,
    "02-extraction-tiling.md": PageExtraction,
    "03-symbol-detection.md": PageDetections,
    "04-text-association-merge.md": MergeResult,
    "05-catalog-matching.md": ComponentMatch,
    "06-validation.md": ValidationResult,
    "07-pricing.md": QuoteVersionResult,
}


def spec_example(name: str) -> dict[str, object]:
    """The first JSON block of the spec's "## 6." section, with its placeholders filled in."""
    text = (SPECS / name).read_text()
    section = text[text.index("\n## 6.") :]
    block = section[section.index("```json") + len("```json") : section.index("```", section.index("```json") + 7)]
    block = block.replace("_01J...", "_01J").replace('"trc_..."', '"trc_example"')
    block = re.sub(r'"<[^"]*>"', '"0"', block)  # 07 §6.1: VAT values "from the system setting"
    return json.loads(block)  # type: ignore[no-any-return]


@pytest.mark.parametrize("spec", EXAMPLES)
def test_the_spec_example_is_a_valid_contract(spec: str) -> None:
    EXAMPLES[spec].model_validate(spec_example(spec))


def test_the_examples_round_trip_without_losing_fields() -> None:
    for spec, model in EXAMPLES.items():
        example = spec_example(spec)
        dumped = model.model_validate(example).model_dump(mode="json")
        assert set(example) <= set(dumped), spec


def test_unknown_fields_are_refused() -> None:
    example = spec_example("05-catalog-matching.md") | {"surprise": 1}
    with pytest.raises(ValidationError, match="surprise"):
        ComponentMatch.model_validate(example)


def test_money_is_a_string_both_ways() -> None:
    example = spec_example("07-pricing.md")
    quote = QuoteVersionResult.model_validate(example)
    line = quote.panels[0].lines[0]
    assert str(line.unit_price) == "182.78"
    assert quote.model_dump(mode="json")["panels"][0]["lines"][0]["unit_price"] == "182.78"
    example["panels"][0]["lines"][0]["unit_price"] = 182.78  # type: ignore[index]
    with pytest.raises(ValidationError, match="string"):
        QuoteVersionResult.model_validate(example)


def test_ids_keep_their_prefix() -> None:
    example = spec_example("03-symbol-detection.md")
    example["detections"][0]["det_id"] = "cmp_0017"  # type: ignore[index]
    with pytest.raises(ValidationError, match="det_id"):
        PageDetections.model_validate(example)


def test_every_stage_has_an_output_contract() -> None:
    assert sorted(STAGE_OUTPUTS) == [1, 2, 3, 4, 5, 6, 7]


@pytest.mark.parametrize("stage", sorted(STAGE_OUTPUTS))
def test_schema_snapshot(stage: int) -> None:
    model = STAGE_OUTPUTS[stage]
    schema = json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path = SNAPSHOTS / f"stage{stage}-{model.__name__}.json"
    if os.environ.get("KONBORO_UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(schema)
        if not os.environ.get("KONBORO_UPDATE_SNAPSHOTS"):
            pytest.fail(f"new snapshot written: {path.name}; review and commit it")
    assert schema == path.read_text(), f"{model.__name__} changed; see this module's docstring"
