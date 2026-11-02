"""The quote audit (11 §10): precision of the differences shown (confidence ≥ 0.6) against the ones the factory
confirmed, and recall of those confirmed differences.

A predicted and a labelled difference match when they share a designator, whatever their type; whether the type also
agrees is its own number. The match is not one to one (S15): the factory confirmed NEVIS-1's five contactors as one
omission, and the audit reports one difference per component (11 §6: C1, C2, C5 three-pole, C3, C4 two-pole), so
both of its differences are right and the label is found. A predicted difference with no designator (an arithmetic
one, a line not in the drawing) matches nothing. With no audit run, there is nothing predicted: n/a.
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

    def shared(a: CanonDifference, b: CanonDifference) -> int:
        return len(set(a.designators) & set(b.designators))

    right = [d for d in shown if any(shared(d, lab) for lab in label.differences)]
    pairs = []
    for lab in label.differences:
        best = max(shown, key=lambda d: shared(lab, d), default=None)
        if best is not None and shared(lab, best):
            pairs.append((lab, best))
    return {
        "difference_precision": Score(num=len(right), den=len(shown)),
        "difference_recall": Score(num=len(pairs), den=len(label.differences)),
        "type_agreement": Score(num=sum(1 for lab, d in pairs if lab.type == d.type), den=len(pairs)),
    }
