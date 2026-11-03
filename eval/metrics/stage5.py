"""Stage 5, catalog matching (05 §10), without SKU labels (S20 decision 2): no golden file holds a SKU, so top-1 and
top-3 accuracy wait for them. What is measured:

End to end (`s5`), on stage 4's output and its pairs with the labels (`stage4.match_panel`):
- `sku_value_accuracy`: of the paired components that got a SKU, the share whose item has the labelled current and
  poles. A miss may be stage 4's (it read 20A for 16A): the labelled run below isolates stage 5.
- `with_sku`: the share of matched components that got a SKU (matched, or ambiguous with a provisional one).
- `consistency`: the share of signatures that got one SKU throughout the drawing (05 §10: 100%).
- `llm_share`: the share of signatures the agent decided (05 §10: at most 15%). Lower is better.

On the labelled attributes (`s5_labelled`, 05 §10, 00 §10.1): stage 5 alone, on components built from the labels.
- `exact_value_accuracy`: a chosen item with a current, poles or neutral other than the label's (05 §10: 0 wrong).
- `unmatched_in_catalog`: components the catalog has an item for (every must-read value labelled, and an active item
  of the family that has them) that came out `unmatched` (05 §10: at most 1%). Lower is better. A `conflict` (FNV:
  "3X6A" with S204M) is the right answer and is not counted.
- `consistency` and `llm_share`, as above.
"""

from collections import defaultdict

from ..canonical import CanonMatch, GoldenDrawing, Prediction
from .score import Score, Scores
from .stage4 import match_panel, pair_panels

CHECKED = ("current_a", "poles")


def _value_ok(label: dict[str, object], item: dict[str, object]) -> bool | None:
    """None when the label states none of the checked values."""
    stated = [k for k in CHECKED if isinstance(label.get(k), int | float)]
    if not stated:
        return None
    ok = all(isinstance(item.get(k), int | float) and float(item[k]) == float(label[k]) for k in stated)  # type: ignore[arg-type]
    if label.get("neutral") is True:
        ok = ok and item.get("neutral") is True
    return ok


def _consistency(matches: list[CanonMatch]) -> Score:
    skus: dict[str, set[str]] = defaultdict(set)
    for m in matches:
        if m.signature and m.sku:
            skus[m.signature].add(m.sku)
    return Score(num=sum(1 for s in skus.values() if len(s) == 1), den=len(skus))


def _llm_share(matches: list[CanonMatch]) -> Score:
    signatures = {m.signature for m in matches if m.signature}
    decided = {m.signature for m in matches if m.signature and m.method == "llm"}
    return Score(num=len(decided), den=len(signatures))


def score(label: GoldenDrawing, pred: Prediction) -> Scores:
    if pred.matches is None:
        return {}
    by_ref = {m.ref: m for m in pred.matches}
    checked: list[bool] = []
    for lab_panel, pred_panel in pair_panels(label.panels, pred.panels):
        if lab_panel is None or pred_panel is None:
            continue
        pm = match_panel(list(lab_panel.components), list(pred_panel.components))
        for lab, p in pm.pairs + pm.key_pairs:
            match = by_ref.get(p.ref or "")
            if match is None or match.sku is None:
                continue
            ok = _value_ok(lab.attributes, match.item)
            if ok is not None:
                checked.append(ok)
    matches = list(pred.matches)
    with_sku = sum(1 for m in matches if m.sku)
    counts = pred.matching
    return {
        "sku_value_accuracy": Score(num=sum(checked), den=len(checked)),
        "with_sku": Score(num=with_sku, den=len(matches)),
        "consistency": _consistency(matches),
        "llm_share": Score(num=counts.get("llm_signatures", 0), den=counts.get("signatures", 0)),
    }


def score_labelled(pred: Prediction) -> Scores:
    if pred.labelled_matches is None:
        return {}
    matches = list(pred.labelled_matches)
    checked = [ok for m in matches if m.sku for ok in [_value_ok(m.label, m.item)] if ok is not None]
    in_catalog = [m for m in matches if m.in_catalog]
    return {
        "exact_value_accuracy": Score(num=sum(checked), den=len(checked)),
        "unmatched_in_catalog": Score(num=sum(1 for m in in_catalog if m.status == "unmatched"), den=len(in_catalog)),
        "consistency": _consistency(matches),
        "llm_share": _llm_share(matches),
    }
