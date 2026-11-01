"""Stage 2, extraction (02 §10), as far as the labels reach (S10 decision).

No label has text spans or symbol boxes yet, so 02 §10's token accuracy and tile coverage can't be measured. What
the labels do give is every component's designators, and those are written on the drawing: `designator_recall` is
the share of them found among the normalized spans of the drawing's `process` pages, each as one whole word (split
at spaces, `/` and `,`), in any case. A component the label places only on pages that are not `process` (26-993's
RF and WO: on the front view) is left out, since stage 2 never reads those pages. The score falls when OCR misreads,
splits or misses a tag. Tile coverage holds by construction (`konboro/pipeline/extraction/tiles.py`) until S12
labels symbol boxes.
"""

import re

from ..canonical import GoldenDrawing, Prediction
from .score import Score, Scores

_SPLIT = re.compile(r"[\s/,]+")  # "MS1/MS2/MS3" on 26-993 names three tags


def _key(token: str) -> str:
    return token.strip().casefold()


def score(label: GoldenDrawing, pred: Prediction) -> Scores:
    process = {p.no for p in label.pages if p.route == "process"}
    wanted = {
        _key(d)
        for p in label.panels
        for c in p.components
        if not c.pages or not process or set(c.pages) & process
        for d in c.designators
        if d.strip()
    }
    if not wanted or pred.span_texts is None:
        return {"designator_recall": Score.na()}
    found = {_key(t) for text in pred.span_texts for t in _SPLIT.split(text) if t}
    return {"designator_recall": Score(num=len(wanted & found), den=len(wanted))}
