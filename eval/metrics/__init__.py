"""Every metric for one drawing (dev-strategy §6). Stage 2 is scored by its designator recall (S10), stage 3 by
designators and family counts (S12); stage 2's token accuracy and tile coverage, and stage 3's precision, need span
and box labels that don't exist yet."""

from ..canonical import GoldenDrawing, Prediction
from . import audit, pricing, stage1, stage2, stage3, stage4, stage5, stage6
from .score import LOWER_IS_BETTER, Score, Scores, total

NOT_LABELLED = {
    "s2": "אין עדיין תיוג ברמת אריח ומקטע טקסט: דיוק אסימונים וכיסוי אריחים לא נמדדים, רק איתור התגים",
    "s3": "אין עדיין תיוג ברמת תיבת סימן: precision לא נמדד, ה-recall לפי תגים וספירת משפחות",
    "s4": "נמדד מקצה לקצה על הפלט של שלב 3, לא על זיהויים מתויגים (04 §10, S13)",
    "s5": 'אין עדיין מק"טים בתיוג: דיוק top-1 ו-top-3 לא נמדדים. נמדדים ערכים חשמליים, עקביות וחלק המודל (S20)',
    "s6_labelled": "כללים בלבד, בלי גרף חיבורים ובלי מקטעי טקסט: כללי ההיררכיה וכיסוי הטקסט לא נמדדים כאן (S21)",
}

SECTIONS = ("s1", "s2", "s3", "s3_family", "s4", "s5", "s5_labelled", "s6", "s6_labelled", "audit", "pricing")


def score_drawing(label: GoldenDrawing, pred: Prediction) -> dict[str, Scores]:
    s4, _ = stage4.score(label, pred)
    s3, s3_family = stage3.score(label, pred)
    return {
        "s1": stage1.score(label, pred),
        "s2": stage2.score(label, pred),
        "s3": s3,
        "s3_family": s3_family,
        "s4": s4,
        "s5": stage5.score(label, pred),
        "s5_labelled": stage5.score_labelled(pred),
        "s6": stage6.score(label, pred),
        "s6_labelled": stage6.score_labelled(pred),
        "audit": audit.score(label.audit, pred.audit),
        "pricing": pricing.score(label.quote_total, pred.quote_total, pred.backtest),
    }


def panel_scores(label: GoldenDrawing, pred: Prediction) -> dict[str, Scores]:
    return stage4.score(label, pred)[1]


__all__ = ["LOWER_IS_BETTER", "NOT_LABELLED", "SECTIONS", "Score", "Scores", "panel_scores", "score_drawing", "total"]
