"""Read `golden/<id>/` into the canonical schema. The shape is recognised from the label file's keys, not its
folder name, so a new drawing in a known shape needs no code."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..canonical import GoldenDrawing
from . import shapes

GOLDEN = Path(__file__).resolve().parents[2] / "golden"

Normalizer = Callable[[str, dict[str, Any], dict[str, Any] | None], GoldenDrawing]


def normalizer_for(labels: dict[str, Any]) -> Normalizer:
    if "panels" in labels:
        return shapes.panel_list
    if "components" in labels:
        return shapes.component_list
    if "bom" in labels:
        return shapes.bom_list
    if "rows" in labels:
        handwritten = any("transcription_confidence" in row for row in labels["rows"])
        return shapes.handwritten_rows if handwritten else shapes.priced_rows
    raise ValueError(f"unknown label shape: {sorted(labels)}")


def load(folder: Path) -> GoldenDrawing:
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    quote_file = folder / "actual_quote.json"
    quote = json.loads(quote_file.read_text(encoding="utf-8")) if quote_file.exists() else None
    return normalizer_for(labels)(folder.name, labels, quote)


def load_all(root: Path = GOLDEN) -> list[GoldenDrawing]:
    return [load(folder) for folder in sorted(root.iterdir()) if (folder / "labels.json").exists()]
