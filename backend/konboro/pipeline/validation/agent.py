"""06 §6.4: what the reviewing agent is shown, and the code that checks what it says.

What goes out is built here, one place to check that no price, cost or customer detail does (06 §12): each component
as a short ref (`c01`, so a request does not depend on ids and replays the same), its family and class, its final
values, quantity, tags and the catalog description; the feed tree; the BOM's rows in short; the rules' findings by
title. The picture is the panel's area of one page, its long side 1568 px.

An answer is kept only when (06 §6.4 rules, §7):
- it names a known ref, or a box inside the picture (a missing component);
- its confidence is at least 0.5; at 0.7 and above it is a warning, below an info: the agent never makes an error
  (06 §6.4), and an unsure look should not turn a row yellow (S21 decision 10);
- it does not repeat a rule's finding on the same components and subject (06 §6.5 item 1);
- it is among the first five.
"""

from collections.abc import Callable
from dataclasses import dataclass

from konboro_llm.stages.validator_review import ReviewAnswer

from .checks import Hit
from .model import Device, PanelModel
from .pack import Rule

MAX_ISSUES = 5
MIN_CONFIDENCE = 0.5
WARNING_FROM = 0.7
MIN_COMPONENTS = 5  # 06 §6.4: one call per panel with five components or more
LONG_SIDE = 1568

# 06 §6.5 item 1: the rule categories and ids an agent issue of each type would repeat
SUBJECTS: dict[str, tuple[set[str], set[str]]] = {
    "suspicious_quantity": ({"C"}, {"BOM_QTY_DIFF", "BOM_ACCESSORY_HOST_COUNT"}),
    "missing_component": (set(), {"FRONT_VIEW_DESIGNATOR_MISSING", "PANEL_MISSING_ROWS", "BOM_MISSING_IN_QUOTE"}),
    "inconsistent_attributes": ({"A", "D"}, set()),
    "wrong_family": (set(), {"DATA_DESIGNATOR_FAMILY_CONFLICT"}),
    "other": (set(), set()),
}

# (panel text, components, tree, bom, findings) → the answer; the stage binds the picture and the gateway
Look = Callable[[str, str, str, str, str], ReviewAnswer]


@dataclass
class Shown:
    refs: dict[str, Device]
    components: str
    tree: str
    bom: str


def _values(d: Device) -> str:
    keep = {k: v for k, v in sorted(d.values.items()) if v is not None and not isinstance(v, dict | list)}
    return ", ".join(f"{k}={v}" for k, v in keep.items()) or "-"


def shown(panel: PanelModel) -> Shown:
    devices = [d for d in panel.devices if d.billable]
    refs = {f"c{n:02d}": d for n, d in enumerate(devices, start=1)}
    rows = []
    for ref, d in refs.items():
        item = d.match.catalog_item.description if d.match and d.match.catalog_item else "-"
        scope = "" if d.in_panel else f" (supply scope: {d.component.supply_scope})"
        rows.append(
            f"{ref} | {d.family}/{d.symbol_class} | {_values(d)} | {d.component.quantity} | "
            f"{', '.join(d.component.designators) or '-'} | {item}{scope}"
        )
    back = {d.id: ref for ref, d in refs.items()}
    tree = ""
    if panel.hierarchy:
        children: dict[str | None, list[Device]] = {}
        for d in devices:
            children.setdefault(d.parent_id if d.parent_id in back else None, []).append(d)
        lines: list[str] = []

        def walk(parent: str | None, depth: int) -> None:
            for d in children.get(parent, []):
                lines.append("  " * depth + f"{back[d.id]} {d.tag}")
                if depth < 8:
                    walk(d.id, depth + 1)

        walk(None, 0)
        tree = "\n".join(lines)
    bom = ""
    if panel.bom:
        bom = "\n".join(
            f"- {c.quantity} × {c.family}: "
            + ", ".join(f"{k}={a.value}" for k, a in sorted(c.attributes.items()) if a.value is not None)
            for c in panel.bom[:40]
        )
    return Shown(refs, "\n".join(rows), tree, bom)


def eligible(panel: PanelModel) -> bool:
    return len(panel.priced) >= MIN_COMPONENTS


@dataclass
class Kept:
    type: str
    hit: Hit
    confidence: float
    message: str


def _repeats(kind: str, ids: list[str], rule_hits: list[tuple[Rule, Hit]]) -> bool:
    categories, rule_ids = SUBJECTS.get(kind, (set(), set()))
    for rule, h in rule_hits:
        if rule.category not in categories and rule.rule_id not in rule_ids:
            continue
        if not ids and not h.component_ids:
            return True
        if ids and set(ids) & set(h.component_ids):
            return True
        if kind == "missing_component" and not ids:
            return True
    return False


def check_answer(
    answer: ReviewAnswer,
    sh: Shown,
    rule_hits: list[tuple[Rule, Hit]],
    picture: tuple[int, int] | None,
    to_points: Callable[[list[float]], tuple[float, float, float, float]] | None,
    page_id: str | None,
) -> list[Kept]:
    kept: list[Kept] = []
    for issue in answer.issues:
        if issue.confidence < MIN_CONFIDENCE or not issue.message.strip():
            continue
        ids = [sh.refs[r].id for r in dict.fromkeys(issue.component_ids) if r in sh.refs]
        bbox = None
        if issue.bbox is not None and picture is not None and to_points is not None and len(issue.bbox) == 4:
            x0, y0, x1, y1 = issue.bbox
            if 0 <= x0 < x1 <= picture[0] and 0 <= y0 < y1 <= picture[1]:
                bbox = to_points(issue.bbox)
        if not ids and bbox is None:
            continue  # 06 §7: no component and no box in the panel
        if _repeats(issue.type, ids, rule_hits):
            continue
        hit = Hit(ids, values={"type": issue.type}, page_id=page_id if bbox else None)
        if bbox is not None:
            hit.values["bbox"] = list(bbox)
        hit.severity = "warning" if issue.confidence >= WARNING_FROM else "info"
        kept.append(Kept(issue.type, hit, issue.confidence, issue.message.strip()))
        if len(kept) == MAX_ISSUES:
            break
    return kept
