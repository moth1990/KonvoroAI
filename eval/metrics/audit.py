"""The quote audit (11 §10): precision of the differences shown (confidence ≥ 0.6) against the ones the factory
confirmed, and recall of those confirmed differences.

A predicted and a labelled difference match when they share a designator, whatever their type; whether the type also
agrees is its own number. The match is not one to one (S15): the factory confirmed NEVIS-1's five contactors as one
omission, and the audit reports one difference per component (11 §6: C1, C2, C5 three-pole, C3, C4 two-pole), so
both of its differences are right and the label is found. A predicted difference with no designator (an arithmetic
one, a line not in the drawing) matches nothing by designator.

A confirmed difference with no designator (25.26.100's untagged breakers) is matched by the quote line it is about,
and an omission with no line by its family. A difference with a designator is matched by designators only, so
these fallbacks never change a score on a tagged drawing. With no audit run, there is nothing predicted: n/a.
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

    def shared(lab: CanonDifference, d: CanonDifference) -> int:
        if lab.designators:
            return len(set(lab.designators) & set(d.designators))
        if lab.quote_lines:
            return len(set(lab.quote_lines) & set(d.quote_lines))
        return int(lab.family is not None and lab.family == d.family and not d.quote_lines)

    right = [d for d in shown if any(shared(lab, d) for lab in label.differences)]
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
