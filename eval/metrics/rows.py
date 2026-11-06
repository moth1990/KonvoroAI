"""The overall metric (00 §10.2, phase 2's exit: 85%, S28 decision 2): the golden rows that need no edit, and the
wrong green rows (≤ 1%).

A labelled row is one component of a checked panel, in the panel (00 §10.2 counts quote lines; a component is one).
It needs no edit when the pipeline's quote has a line for it, end to end, with
- the label's family, paired the way stage 4 is scored (`stage4.match_panel`: designators, then the key, then
  groups by key for rows with no designators);
- the labelled quantity (a group's quantities added up);
- every labelled value right: the values the family's attribute schema has (current, poles, a curve, a ratio…),
  taken from the chosen catalog item when it has the value, else from what stage 4 read. A label's other notes
  (`model_token`, `brand`, `dims_mm`) name no value of the line;
- a SKU from stage 5: a line with no product has no price, so the estimator edits it.
Rows with no designators are paired as a group (family, current, poles): the group needs no edit when both sides
have its quantity and each of its components a SKU; its other values are not compared.

The factory's auxiliary families (terminals) are no line of their own (stage 7 counts them as derived material), so
they are left out of both sides.

A wrong green row is a line the pipeline vouched for that needs an edit: of the component lines green apart from
their price, the share whose component is not a row that needs no edit (an extra component counts). Apart from the
price, because the eval's factory has no price list (S20), so every line's price reason is red there; in a factory
with prices, the colour is the same plus the price's reason (07 §7.5). Lower is better.
"""

from typing import Any

from konboro.pipeline.association import schemas

from ..canonical import CanonComponent, CanonMatch, GoldenDrawing, Prediction
from .score import Score, Scores
from .stage4 import Key, PanelMatch, _key, match_panel, pair_panels

SCHEMAS = schemas.default()


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    if isinstance(want, int | float) and isinstance(got, int | float):
        return abs(float(want) - float(got)) < 1e-9
    if isinstance(want, str) and isinstance(got, str):
        return " ".join(want.casefold().split()) == " ".join(got.casefold().split())
    return bool(want == got) and want is not None


def values_right(label: CanonComponent, pred: CanonComponent, match: CanonMatch | None) -> bool:
    names = set(SCHEMAS.names(label.family))
    item = match.item if match is not None and match.sku else {}
    for name, want in label.attributes.items():
        if name not in names:
            continue
        got = item[name] if item.get(name) is not None else pred.attributes.get(name)
        if not _same(want, got):
            return False
    return True


def _has_sku(pred: CanonComponent, by_ref: dict[str, CanonMatch]) -> bool:
    match = by_ref.get(pred.ref or "")
    return match is not None and match.sku is not None


def _row_ok(label: CanonComponent, pred: CanonComponent, by_ref: dict[str, CanonMatch]) -> bool:
    match = by_ref.get(pred.ref or "")
    return label.qty == pred.qty and _has_sku(pred, by_ref) and values_right(label, pred, match)


def _auxiliary(c: CanonComponent, auxiliary: frozenset[str]) -> bool:
    return c.ref in auxiliary if c.ref else c.family == "terminal"  # the eval factory's default list (11 §5.4)


def _groups_ok(pm: PanelMatch, rest: list[CanonComponent], by_ref: dict[str, CanonMatch]) -> dict[Key, bool]:
    """A key shared by both sides, with the same quantity, every predicted component of it with a SKU."""
    return {
        k: pm.label_groups[k] == pm.pred_groups[k] and all(_has_sku(p, by_ref) for p in rest if _key(p) == k)
        for k in pm.shared
    }


def score(label: GoldenDrawing, pred: Prediction) -> Scores:
    if pred.matches is None:
        return {}
    by_ref = {m.ref: m for m in pred.matches}
    auxiliary = frozenset(pred.auxiliary)
    rows, ok_rows = 0, 0
    green, wrong_green = 0, 0
    for lab_panel, pred_panel in pair_panels(label.panels, pred.panels):
        if lab_panel is None or not lab_panel.verified:
            continue  # nobody checked it (25.26.100's sub-panel): neither a row nor an extra
        labelled = [c for c in lab_panel.components if c.supply_scope == "in_panel" and not _auxiliary(c, frozenset())]
        predicted = [
            c
            for c in (pred_panel.components if pred_panel else ())
            if c.supply_scope == "in_panel" and not _auxiliary(c, auxiliary)
        ]
        pm = match_panel(labelled, predicted)
        paired = {id(p) for _, p in pm.pairs + pm.key_pairs}
        rest = [p for p in predicted if id(p) not in paired]
        groups = _groups_ok(pm, rest, by_ref)
        ok_pred: dict[int, bool] = {}
        for lab, p in pm.pairs + pm.key_pairs:
            ok = _row_ok(lab, p, by_ref)
            rows, ok_rows = rows + 1, ok_rows + ok
            ok_pred[id(p)] = ok
        rows += len(pm.unpaired)
        for c in (c for c in labelled if not c.designators):
            rows += 1
            ok_rows += groups.get(_key(c), False)
        for p in rest:
            ok_pred[id(p)] = groups.get(_key(p), False)
        for p in predicted:
            if pred.line_colours.get(p.ref or "") == "green":
                green += 1
                wrong_green += not ok_pred.get(id(p), False)
    return {
        "rows_without_edit": Score(num=ok_rows, den=rows),
        "wrong_green_rows": Score(num=wrong_green, den=green),
    }
