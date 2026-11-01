"""Stage 3, symbol detection (03 §10), as far as the labels reach (S12 decision).

No label has symbol boxes yet, so precision and true recall can't be measured. What the labels give:
- On factory drawings, every component's designators. `designator_recall` is the share of them found as the
  designator of some detection on a `process` page (ranges like "F1–F17" expanded), and `family_accuracy` the share of
  those found whose detection has the label's family (any role: a contactor is found by its coil or its contacts).
  A component the label places only on pages that are not `process` is left out, as in stage 2's metric.
- On a designer's plan without designators (6199-2-50), `family_count_recall`: per family, the billable symbols
  detected (any role but a contact: a contactor drawn only as its coil box still counts) against the label's rows
  of that family, at most 1 a family. A row can stand for several units ("×6"), but is drawn at least once, so the
  rows are a floor on the symbols.
A drawing with no `process` page (a photographed BOM) has nothing to detect: n/a.
- Everywhere: `duplicates_left`, pairs of detections of one family on one page with IoU above 0.5 (03 §10: 0), and
  `llm_share`, the share of detections that went to the disambiguation call (03 §10: at most 10%).

`by_family` gives recall per family (03 §10: "a 98% average can hide a family at 70%"), from the designators where
there are any, else from the counts.
"""

from collections import Counter

from konboro.pipeline.extraction.geometry import iou

from ..canonical import CanonComponent, GoldenDrawing, Prediction
from ..normalizers.common import designators
from .score import Score, Scores

NOT_SYMBOLS = frozenset({"enclosure", "accessory", "enclosure_accessory", "busbar_block"})  # labelled, never drawn
DUPLICATE_IOU = 0.5


def _wanted(label: GoldenDrawing) -> list[CanonComponent]:
    process = {p.no for p in label.pages if p.route == "process"}
    return [
        c
        for p in label.panels
        for c in p.components
        if c.family not in NOT_SYMBOLS and (not c.pages or not process or set(c.pages) & process)
    ]


def _duplicates(pred: Prediction) -> int:
    dets = pred.detections or ()
    return sum(
        1
        for i, a in enumerate(dets)
        for b in dets[i + 1 :]
        if a.page_no == b.page_no and a.family == b.family and iou(a.bbox, b.bbox) > DUPLICATE_IOU
    )


def score(label: GoldenDrawing, pred: Prediction) -> tuple[Scores, Scores]:
    """(the drawing's scores, recall by family)."""
    if pred.detections is None or not any(p.route == "process" for p in label.pages):
        return {"designator_recall": Score.na()}, {}
    wanted = _wanted(label)
    found: dict[str, set[str]] = {}  # designator → families detected with it
    for d in pred.detections:
        for tag in designators([d.designator] if d.designator else []):
            found.setdefault(tag.casefold(), set()).add(d.family)
    out: Scores = {}
    by_family: dict[str, Score] = {}
    tagged = [(c.family, t.casefold()) for c in wanted for t in c.designators if t.strip()]
    if tagged:
        hits = [(family, tag) for family, tag in tagged if tag in found]
        out["designator_recall"] = Score(num=len(hits), den=len(tagged))
        out["family_accuracy"] = Score(num=sum(1 for f, t in hits if f in found[t]), den=len(hits))
        for family, tag in tagged:
            ok = tag in found and family in found[tag]
            by_family[family] = by_family.get(family, Score(num=0, den=0)) + Score(num=int(ok), den=1)
    untagged = Counter(c.family for c in wanted if not c.designators)
    if untagged and not tagged:  # a plan without designators
        detected = Counter(d.family for d in pred.detections if d.billable and d.role in ("device", "coil"))
        num = sum(min(n, detected.get(f, 0)) for f, n in untagged.items())
        out["family_count_recall"] = Score(num=num, den=sum(untagged.values()))
        for f, n in untagged.items():
            by_family[f] = Score(num=min(n, detected.get(f, 0)), den=n)
    out["duplicates_left"] = Score(num=_duplicates(pred), den=1, kind="count")
    total = pred.detection.get("detections", 0)
    out["llm_share"] = Score(num=pred.detection.get("disambiguation_calls", 0), den=total)
    return out, by_family
