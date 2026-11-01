"""Stage 4, association and merge (04 §10): component precision and recall per panel, `current_a` and poles accuracy,
quantity accuracy.

Matching, in three passes per panel (S06 decision):
1. **By designators.** A labelled component with designators pairs with the predicted one of the same family that
   shares the most designators. This is how factory drawings are scored.
2. **One by one, by key.** A labelled component with designators that found no pair can still pair with a
   predicted one that has the same family + `current_a` + poles (a stage that lost the tag but read the rest).
3. **Grouped, by key.** Labelled components without designators, and the predicted ones left over, are grouped by
   family + `current_a` + poles with quantities added up; a key on both sides is a match. Designer plans and
   BOM-only inputs have no designators, so this is how they are scored, and merged and unmerged rows score the same.

A labelled component with designators always counts as one item, so recall's denominator doesn't move with what
was predicted. Attribute accuracy is measured on designator pairs only: in passes 2 and 3 the attributes are the
key, so a wrong current shows up as a missed and an extra component instead.

Only `in_panel` components are scored on either side: other locations and "by others" are not in the quote.
"""

from collections import defaultdict
from dataclasses import dataclass

from ..canonical import CanonComponent, CanonPanel, GoldenDrawing, Prediction
from .score import Score, Scores

Key = tuple[str, float | None, int | None]
PanelPair = tuple[CanonPanel | None, CanonPanel | None]


def _key(c: CanonComponent) -> Key:
    return (c.family, c.current_a, c.poles)


def _same(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-9


@dataclass
class PanelMatch:
    pairs: list[tuple[CanonComponent, CanonComponent]]  # (label, predicted), by designators
    key_pairs: list[tuple[CanonComponent, CanonComponent]]  # the second pass
    unpaired: list[CanonComponent]  # labelled, with designators, no pair
    label_groups: dict[Key, int]  # the third pass: key -> quantity
    pred_groups: dict[Key, int]

    @property
    def shared(self) -> list[Key]:
        return sorted(set(self.label_groups) & set(self.pred_groups), key=repr)

    def scores(self) -> Scores:
        one_by_one = self.pairs + self.key_pairs
        tp = len(one_by_one) + len(self.shared)
        current = [(lab, p) for lab, p in self.pairs if lab.current_a is not None]
        poles = [(lab, p) for lab, p in self.pairs if lab.poles is not None]
        qty_ok = sum(1 for lab, p in one_by_one if lab.qty == p.qty)
        qty_ok += sum(1 for k in self.shared if self.label_groups[k] == self.pred_groups[k])
        units = sum(lab.qty for lab, _ in one_by_one) + sum(c.qty for c in self.unpaired)
        units += sum(self.label_groups.values())
        found = sum(min(lab.qty, p.qty) for lab, p in one_by_one)
        found += sum(min(self.label_groups[k], self.pred_groups[k]) for k in self.shared)
        return {
            "component_precision": Score(num=tp, den=len(one_by_one) + len(self.pred_groups)),
            "component_recall": Score(num=tp, den=len(one_by_one) + len(self.unpaired) + len(self.label_groups)),
            "current_a_accuracy": Score(
                num=sum(1 for lab, p in current if _same(lab.current_a, p.current_a)), den=len(current)
            ),
            "poles_accuracy": Score(num=sum(1 for lab, p in poles if lab.poles == p.poles), den=len(poles)),
            "quantity_accuracy": Score(num=qty_ok, den=tp),
            "unit_recall": Score(num=found, den=units),
        }


def _groups(components: list[CanonComponent]) -> dict[Key, int]:
    out: dict[Key, int] = defaultdict(int)
    for c in components:
        out[_key(c)] += c.qty
    return dict(out)


def match_panel(label: list[CanonComponent], pred: list[CanonComponent]) -> PanelMatch:
    label = [c for c in label if c.supply_scope == "in_panel"]
    pred = [c for c in pred if c.supply_scope == "in_panel"]
    used: set[int] = set()
    pairs, left = [], []
    for lab in label:
        best, overlap = None, 0
        for i, p in enumerate(pred):
            shared = len(set(lab.designators) & set(p.designators))
            if i not in used and p.family == lab.family and shared > overlap:
                best, overlap = i, shared
        if best is None:
            left.append(lab)
        else:
            used.add(best)
            pairs.append((lab, pred[best]))
    key_pairs, unpaired = [], []
    for lab in (c for c in left if c.designators):
        same = next((i for i, p in enumerate(pred) if i not in used and _key(p) == _key(lab)), None)
        if same is None:
            unpaired.append(lab)
        else:
            used.add(same)
            key_pairs.append((lab, pred[same]))
    rest = [p for i, p in enumerate(pred) if i not in used]
    return PanelMatch(
        pairs=pairs,
        key_pairs=key_pairs,
        unpaired=unpaired,
        label_groups=_groups([c for c in left if not c.designators]),
        pred_groups=_groups(rest),
    )


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def pair_panels(
    label: tuple[CanonPanel, ...], pred: tuple[CanonPanel, ...]
) -> list[tuple[CanonPanel | None, CanonPanel | None]]:
    """By name; then, for what is left, one to one when each side has one panel left, or else in order."""
    pred_left = list(pred)
    pairs: list[PanelPair] = []
    label_left = []
    for lab in label:
        same = next((p for p in pred_left if _norm(p.name) == _norm(lab.name)), None)
        if same is None:
            label_left.append(lab)
        else:
            pred_left.remove(same)
            pairs.append((lab, same))
    for i, lab in enumerate(label_left):
        pairs.append((lab, pred_left[i] if i < len(pred_left) else None))
    pairs.extend((None, p) for p in pred_left[len(label_left) :])
    return pairs


def evidence(pred: Prediction) -> Scores:
    """04 §10: no value without evidence (0), the agent's citation mismatches (≤ 2%), and the share of tiles that
    needed the agent (≤ 20% on CAD drawings; scanned ones start near all). Lower is better for all three."""
    m = pred.merge
    if not m:
        return {}
    return {
        "values_without_evidence": Score(num=m.get("values_without_evidence", 0), den=1, kind="count"),
        "citation_mismatch_rate": Score(num=m.get("citation_mismatches", 0), den=m.get("cited_values", 0)),
        "agent_tile_share": Score(num=m.get("agent_tiles", 0), den=m.get("tiles", 0)),
    }


def score(label: GoldenDrawing, pred: Prediction) -> tuple[Scores, dict[str, Scores]]:
    """The drawing's total, and each labelled panel's own scores."""
    per_panel: dict[str, Scores] = {}
    total: Scores = {}
    for lab, p in pair_panels(label.panels, pred.panels):
        scores = match_panel(list(lab.components) if lab else [], list(p.components) if p else []).scores()
        if lab is not None:
            per_panel[lab.name] = {k: scores[k] for k in ("component_precision", "component_recall")}
        total = {k: total[k] + v if k in total else v for k, v in scores.items()}
    return total | evidence(pred), per_panel
