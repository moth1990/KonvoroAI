"""Stage 1, intake and page classification (01 §10): page kinds, routes, missed process pages, input kind, panels,
title-block fields (one metric per field), and how often the user had to confirm.

The most important number is `missed_process_pages`, target 0 (00 §10.2): a process page that was skipped, or not
found at all, loses every component on it.
"""

import re

from ..canonical import GoldenDrawing, Prediction
from .score import Score, Scores


def _same(a: str | None, b: str) -> bool:
    """Spacing, case and separators don't count: "26/952-5" is "26 / 952-5"."""
    if a is None:
        return False
    return re.sub(r"[\s\-_/.,'\"]+", "", a).casefold() == re.sub(r"[\s\-_/.,'\"]+", "", b).casefold()


def score(label: GoldenDrawing, pred: Prediction) -> Scores:
    by_no = {p.no: p for p in pred.pages}
    kinds = [(p, by_no.get(p.no)) for p in label.pages]
    routed = [(p, q) for p, q in kinds if p.route is not None]
    process = [(p, q) for p, q in routed if p.route == "process"]
    return {
        "page_kind_accuracy": Score(num=sum(1 for p, q in kinds if q and q.kind == p.kind), den=len(kinds)),
        "route_accuracy": Score(num=sum(1 for p, q in routed if q and q.route == p.route), den=len(routed)),
        "missed_process_pages": Score(
            num=sum(1 for _, q in process if q is None or q.route == "skip"), den=len(process), kind="count"
        ),
        "input_kind_accuracy": Score.of(pred.input_kind == label.input_kind),
        "panel_count_accuracy": Score.of(len(pred.panels) == len(label.panels)),
        "confirmation_rate": Score.of(bool(pred.needs_confirmation))
        if pred.needs_confirmation is not None and label.pages
        else Score.na(),
        **{
            f"title_block_{field}": Score.of(_same(pred.title_block.get(field), value))
            for field, value in label.title_block.items()
        },
    }
