"""Stage 6, validation (06 §10, S21).

End to end (`s6`), on the pipeline's own quote, which has reading errors of its own:
- `golden_findings`: the findings the golden drawings call for, from the labels' notes and 06 §6.2's examples on
  them (`EXPECTED`), that fired. A finding the label names is a fact about the drawing; this list is the eval's, the
  golden files are not changed.
- `errors`, `warnings`: per drawing, reported to watch the noise; the pipeline's quote is not correct, so 06 §10.2's
  targets are measured on the labelled quote below.

On the labelled quote (`s6_labelled`, 06 §10.2), correct by definition, rules only:
- `false_errors`, `false_warnings`: per drawing (targets ≤ 0.1 and ≤ 3);
- `bug_net_fired`: category-D safety nets that fired (target 0: each is a bug);
- `injected_caught`: of the injected errors some rule can see (06 §10.1), the share a new warning or error caught
  (target ≥ 95%); `injected_<kind>` the same per kind; `injected_not_applicable` how many no rule could see.
"""

from ..canonical import GoldenDrawing, Prediction
from .score import Score, Scores

# Findings the golden drawings call for: rule ids, from each label's notes and the examples 06 §6.2 gives on them
EXPECTED: dict[str, tuple[str, ...]] = {
    "NURSERY-1": ("FRONT_VIEW_DESIGNATOR_MISSING",),  # front_view_only F26–F29, its `rule`
    "NEVIS-1": ("DATA_MODEL_TEXT_CONFLICT",),  # FNV: "3X6A" with S204M (06 §6.2)
    "26-993": ("DATA_LOAD_CURRENT_GT_RATED", "FRONT_VIEW_DESIGNATOR_NEAR_MATCH"),  # findings 1–2: FC1 INC=20A; SE/SG
    "6199-2-50": ("PANEL_REFERENCED_NOT_DRAWN",),  # referenced_not_drawn: לוח מבנה משרדים
    "BOM-HW-1": ("BOM_ACCESSORY_HOST_COUNT", "BOM_NO_ENCLOSURE"),  # 06 §6.2: 5 shunt trips, 2 breakers; no enclosure
}
KINDS = ("current_up", "qty_minus_2", "sku_poles", "deleted", "load_current", "poles_cable", "designator_family")


def score(label: GoldenDrawing, pred: Prediction) -> Scores:
    if pred.findings is None:
        return {}
    fired = {f.rule_id for f in pred.findings}
    expected = EXPECTED.get(label.id, ())
    return {
        "golden_findings": Score(num=sum(1 for r in expected if r in fired), den=len(expected)),
        "errors": Score(num=sum(1 for f in pred.findings if f.severity == "error"), den=1, kind="average"),
        "warnings": Score(num=sum(1 for f in pred.findings if f.severity == "warning"), den=1, kind="average"),
    }


def score_labelled(pred: Prediction) -> Scores:
    if pred.labelled_findings is None or pred.injected is None:
        return {}
    found = pred.labelled_findings
    applicable = [i for i in pred.injected if i.applicable]
    out: Scores = {
        "false_errors": Score(num=sum(1 for f in found if f.severity == "error"), den=1, kind="average"),
        "false_warnings": Score(num=sum(1 for f in found if f.severity == "warning"), den=1, kind="average"),
        "bug_net_fired": Score(num=sum(1 for f in found if f.bug_net), den=1, kind="count"),
        "injected_caught": Score(num=sum(1 for i in applicable if i.caught), den=len(applicable)),
        "injected_not_applicable": Score(
            num=len(pred.injected) - len(applicable), den=len(pred.injected), kind="count"
        ),
    }
    for kind in KINDS:
        some = [i for i in applicable if i.kind == kind]
        out[f"injected_{kind}"] = Score(num=sum(1 for i in some if i.caught), den=len(some))
    return out
