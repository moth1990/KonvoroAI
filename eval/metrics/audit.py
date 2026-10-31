"""The quote audit (11 §10): precision of the differences shown (confidence ≥ 0.6) against the ones the factory
confirmed, and recall of those confirmed differences.

A predicted and a labelled difference match when they share designators, one to one, whatever their type; whether
the type also agrees is its own number. Until the audit flow is built (11), there is nothing predicted: n/a.
"""

from ..canonical import CanonAudit, CanonDifference
from .score import Score, Scores

SHOWN_FROM = 0.6  # 11 §10


def score(label: CanonAudit | None, pred: tuple[CanonDifference, ...] | None) -> Scores:
    if label is None:
        return {}
    if pred is None:
        return {"difference_precision": Score.na(), "difference_recall": Score.na(), "type_agreement": Score.na()}
    shown = [d for d in pred if d.confidence is None or d.confidence >= SHOWN_FROM]
    used: set[int] = set()
    pairs = []
    for lab in label.differences:
        best, overlap = None, 0
        for i, d in enumerate(shown):
            shared = len(set(lab.designators) & set(d.designators))
            if i not in used and shared > overlap:
                best, overlap = i, shared
        if best is not None:
            used.add(best)
            pairs.append((lab, shown[best]))
    return {
        "difference_precision": Score(num=len(pairs), den=len(shown)),
        "difference_recall": Score(num=len(pairs), den=len(label.differences)),
        "type_agreement": Score(num=sum(1 for lab, d in pairs if lab.type == d.type), den=len(pairs)),
    }
