"""Every metric for one drawing (dev-strategy §6). Stages 2 and 3 need span and box labels that don't exist yet:
they are reported as n/a until the labeling work provides them."""

from ..canonical import GoldenDrawing, Prediction
from . import audit, pricing, stage1, stage4
from .score import LOWER_IS_BETTER, Score, Scores, total

NOT_LABELLED = {
    "s2": "אין עדיין תיוג ברמת אריח ומקטע טקסט",
    "s3": "אין עדיין תיוג ברמת תיבת סימן",
}

SECTIONS = ("s1", "s4", "audit", "pricing")


def score_drawing(label: GoldenDrawing, pred: Prediction) -> dict[str, Scores]:
    s4, _ = stage4.score(label, pred)
    return {
        "s1": stage1.score(label, pred),
        "s4": s4,
        "audit": audit.score(label.audit, pred.audit),
        "pricing": pricing.score(label.quote_total, pred.quote_total),
    }


def panel_scores(label: GoldenDrawing, pred: Prediction) -> dict[str, Scores]:
    return stage4.score(label, pred)[1]


__all__ = ["LOWER_IS_BETTER", "NOT_LABELLED", "SECTIONS", "Score", "Scores", "panel_scores", "score_drawing", "total"]
