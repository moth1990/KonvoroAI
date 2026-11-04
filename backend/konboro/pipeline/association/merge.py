"""04 §5.6–5.8, §6.4: instances, missed symbols, and the merge into components. Code only.

An instance is one symbol with what was read for it. The merge, once per drawing:
1. **By tag first** (5.8): instances in one panel with the same tag are one device, on every page and in every
   representation (FP1 on two pages; C1's power contacts and its coil). The device takes the family of its device
   drawing, else its coil, else its contacts (03 §4.5); the attributes join from all of them, and two that disagree
   keep the first representation's value, flagged `attribute_conflict` (× 0.8).
   A tag merges one device's drawings only (BUG-066): a device drawing of another family under the same tag stays a
   device of its own, untagged and yellow, flagged `tag_conflict` (25.26.100's "X2" took 16A breakers and two RCDs
   into one terminal × 76). Unless it is unsure and beside one of the device's drawings, within its length: then it
   is a misread part of that drawing (Q0's ring read as a current transformer, QLG1's thermal release as an overload
   relay). An accessory (a shunt trip) under a device's tag sits on that device.
2. An auxiliary contact (family `aux_contact`) is an accessory of its own: its tag is the device it sits on
   (`parent_designators`), not a device of its own tag. An untagged contact or coil of a family that has tagged
   devices in the panel is another drawing of one of them, and joins the nearest (no quantity of its own).
   A symbol tagged with a list ("MS1/MS2/MS3", 03 §3.7 item 5) is one device per tag in the list, so its quantity
   is the list's length (BUG-031).
3. **Then by signature**: devices with the same panel, family, class, supply scope and exactly the same values in
   every attribute (null included) are one component. Quantity: the number of distinct tags, plus the multiplicity
   of the untagged ones. Missing instances, different panels, and a known value against a null never merge.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import Bbox, StageIssue
from konboro.contracts.merge import (
    AttributeValue,
    CircuitContext,
    Component,
    Instance,
    MissingInstance,
)
from konboro.pipeline.detection.designators import PROTECTIVE, tags
from konboro.pipeline.detection.library import FAMILIES

from .assign import Value
from .config import DEFAULT, AssociationConfig
from .grammar import same
from .schemas import Schemas

ROLE_RANK = {"device": 0, "coil": 1, "power_contact": 2, "relay_contact": 3, "front_view": 4, "aux_contact": 5}

INSTANCE_ISSUES = {
    "missing_required": "חסר בשרטוט: {names}. השלב הבא ינסה להשלים, או שהשורה תסומן לבדיקה.",
    "attribute_conflict": "ערכים סותרים בשרטוט עבור {names}. נבחר: {chosen}.",
    "ambiguous_association": "טקסט אחד קרוב לשני רכיבים. בדקו שהערכים שויכו נכון.",
    "multiplicity_inherited": "×{count} לפי {upstream} שמעליו",
    "range_mismatch": "טווח המעגלים {range} לא תואם לכמות {count}. בדקו את הכמות.",
    "brand_conflict": "שני מותגים שונים ברכיבים זהים: {brands}.",
    "tag_conflict": "התג {tag} כתוב גם ליד רכיב מסוג אחר ({family}). בדקו לאיזה רכיב הוא שייך.",
}


def issue(code: str, severity: str = "info", page_id: str | None = None, **values: Any) -> StageIssue:
    return StageIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        page_id=page_id,
        message=INSTANCE_ISSUES[code].format(**values),
    )


def attribute(v: Value | None) -> AttributeValue:
    if v is None:
        return AttributeValue(value=None, source=None, confidence=None, span_ids=[])
    return AttributeValue(
        value=v.value,
        source=v.source,  # type: ignore[arg-type]
        confidence=min(1.0, v.confidence),
        span_ids=sorted(set(v.span_ids)),
    )


def instance_confidence(detection_confidence: float, values: dict[str, Value], required: tuple[str, ...]) -> float:
    """6.4: the detection's confidence × the lowest of the required attributes found."""
    found = [values[n].confidence for n in required if n in values]
    return round(detection_confidence * (min(found) if found else 1.0), 4)


def status(confidence: float, cfg: AssociationConfig = DEFAULT) -> str:
    return "accepted" if confidence >= cfg.accepted_from else "uncertain"


@dataclass
class Built:
    """An instance and what the merge needs that the contract doesn't carry."""

    instance: Instance
    designator: str | None
    role: str
    supply_scope: str = "in_panel"
    multiplicity_inherited: bool = False
    circuit_context: CircuitContext | None = None
    extra_det_ids: list[str] = field(default_factory=list)  # absorbed symbols (the neutral pole)
    order: tuple[int, float, float] = (0, 0.0, 0.0)  # page, y, x: the merge keeps the drawing's order


@dataclass
class Device:
    family: str
    symbol_class: str
    panel_id: str
    attributes: dict[str, AttributeValue]
    designators: list[str]
    parent_designators: list[str]
    quantity: int
    built: list[Built]
    confidence: float
    supply_scope: str
    multiplicity_inherited: bool
    conflicts: list[str] = field(default_factory=list)


def _join_attributes(
    members: list[Built], names: tuple[str, ...], cfg: AssociationConfig
) -> tuple[dict[str, AttributeValue], list[str], float]:
    out: dict[str, AttributeValue] = {}
    conflicts: list[str] = []
    penalty = 1.0
    for name in names:
        chosen: AttributeValue | None = None
        for b in members:
            a = b.instance.attributes.get(name)
            if a is None or a.value is None:
                continue
            if chosen is None:
                chosen = a.model_copy()
            elif same(chosen.value, a.value):
                chosen.span_ids = sorted(set(chosen.span_ids) | set(a.span_ids))
                chosen.confidence = min(chosen.confidence or 1.0, a.confidence or 1.0)
            elif name not in conflicts:
                conflicts.append(name)
                penalty = cfg.conflict_penalty
        out[name] = chosen or AttributeValue(value=None, source=None, confidence=None, span_ids=[])
    if conflicts:
        for name in conflicts:
            a = out[name]
            a.confidence = round((a.confidence or 1.0) * cfg.conflict_penalty, 4)
    return out, conflicts, penalty


def devices(built: list[Built], schemas: Schemas, cfg: AssociationConfig = DEFAULT) -> list[Device]:
    """5.8 items 1–3: one device per tag in a panel; an auxiliary contact on its own; an untagged symbol alone."""
    by_tag: dict[tuple[str, str], list[Built]] = defaultdict(list)
    alone: list[Built] = []
    accessories: list[tuple[Built, str]] = []  # an accessory under another device's tag, and that tag
    for b in sorted(built, key=lambda b: b.order):
        if b.designator and len(tags(b.designator)) == 1 and b.instance.family != "aux_contact" and b.instance.panel_id:
            by_tag[(b.instance.panel_id, b.designator)].append(b)
        else:
            alone.append(b)
    out: list[Device] = []
    for (panel_id, tag), group in by_tag.items():
        lead = min(group, key=lambda b: (ROLE_RANK.get(b.role, 9), -b.instance.confidence, b.order))
        family, cls = lead.instance.family, lead.instance.symbol_class
        members = []
        for b in group:
            if b.instance.family == family or b.role != "device":
                members.append(b)  # the device's own drawings: its coil, its contacts, its front view (03 §4.5)
            elif b.instance.family in ACCESSORIES:
                accessories.append((b, tag))  # sits on the tag's device, like an auxiliary contact
            elif b.instance.confidence < cfg.accepted_from and _part_of(
                b, [x for x in group if x.instance.family == family]
            ):
                members.append(b)  # an unsure reading of a part of the device's own drawing (Q0's ring, a CT)
            else:
                _conflict(b, tag, family, cfg)  # BUG-066: another device under one tag is a conflict, not a merge
                alone.append(b)
        same_family = [b for b in members if b.instance.family == family]
        ordered = [lead] + [b for b in same_family if b is not lead]
        attrs, conflicts, penalty = _join_attributes(ordered, schemas.names(family), cfg)
        conf = round(min(b.instance.confidence for b in members) * penalty, 4)
        out.append(
            Device(
                family,
                cls,
                panel_id,
                attrs,
                [tag],
                [],
                1,
                members,
                conf,
                lead.supply_scope,
                lead.multiplicity_inherited,
                conflicts,
            )
        )
    tagged: dict[tuple[str, str], list[Device]] = defaultdict(list)
    for d in out:
        tagged[(d.panel_id, d.family)].append(d)
    for b, tag in accessories:
        i = b.instance
        out.append(
            Device(
                i.family,
                i.symbol_class,
                i.panel_id or "",
                {n: i.attributes.get(n) or attribute(None) for n in schemas.names(i.family)},
                [],
                [tag],
                i.multiplicity,
                [b],
                i.confidence,
                b.supply_scope,
                b.multiplicity_inherited,
            )
        )
    for b in alone:
        i = b.instance
        aux = i.family == "aux_contact"
        own = [] if aux or _conflicted(b) else tags(b.designator)
        # An untagged contact or coil of a family that has tagged devices in the panel is another drawing of one of
        # them (03 §4.5), not a device of its own: it joins the nearest one on its page, else the first.
        hosts = tagged.get((i.panel_id or "", i.family), [])
        if not aux and not b.designator and b.role in REPRESENTATIONS and hosts:
            host = min(hosts, key=lambda d: _distance(d, b))
            host.built.append(b)
            continue
        out.append(
            Device(
                i.family,
                i.symbol_class,
                i.panel_id or "",
                {n: i.attributes.get(n) or attribute(None) for n in schemas.names(i.family)},
                own,
                tags(b.designator) if aux else [],
                i.multiplicity,
                [b],
                i.confidence,
                b.supply_scope,
                b.multiplicity_inherited,
            )
        )
    return out


REPRESENTATIONS = frozenset({"coil", "power_contact", "relay_contact"})
ACCESSORIES = frozenset({"aux_contact", "shunt_trip"})  # mounted on the device whose tag they carry (03 §4.5)


def _conflict(b: Built, tag: str, family: str, cfg: AssociationConfig) -> None:
    """BUG-066: a device of another family under a tag. It keeps its own family and values, loses the tag (one tag
    names one device), and stays yellow with the reason, for the user to decide."""
    i = b.instance
    name = next((f.classes[0][1] for f in FAMILIES if f.family == family), family)
    i.issues.append(issue("tag_conflict", "warning", i.page_id, tag=tag, family=name))
    i.confidence = round(min(i.confidence, cfg.accepted_from - 0.01), 4)
    i.status = status(i.confidence, cfg)  # type: ignore[assignment]


def _part_of(b: Built, drawings: list[Built]) -> bool:
    """Within one of the device's drawings' reach on its page: no farther than that drawing is long."""
    x0, y0, x1, y1 = b.instance.bbox or (0, 0, 0, 0)
    for d in drawings:
        if d.instance.page_id != b.instance.page_id or d.instance.bbox is None:
            continue
        a0, b0, a1, b1 = d.instance.bbox
        dx, dy = max(a0 - x1, 0.0, x0 - a1), max(b0 - y1, 0.0, y0 - b1)
        if (dx * dx + dy * dy) ** 0.5 <= max(a1 - a0, b1 - b0):
            return True
    return False


def _conflicted(b: Built) -> bool:
    return any(x.code == "tag_conflict" for x in b.instance.issues)


def _distance(d: Device, b: Built) -> tuple[int, float]:
    """Pages apart, then points apart on the page: what is nearest to `b` among `d`'s drawings."""
    best = (10**6, 0.0)
    for x in d.built:
        pages_apart = abs(x.order[0] - b.order[0])
        dist = abs(x.order[1] - b.order[1]) + abs(x.order[2] - b.order[2])
        best = min(best, (pages_apart, dist))
    return best


def _signature(d: Device) -> tuple[Any, ...]:
    values = tuple((k, repr(v.value)) for k, v in sorted(d.attributes.items()))
    return (d.panel_id, d.family, d.symbol_class, d.supply_scope, d.multiplicity_inherited, values, _cores(d))


def _cable_poles() -> dict[int, int]:
    """05 §5.5.1's cores → poles, from stage 5's rule data (`matching/inference.json`, `poles_from_cable_cores`)."""
    from konboro.pipeline.matching.inference import rules  # the rule's data; stage 5 does the filling in

    rule = next((r for r in rules() if r.kind == "cable_cores"), None)
    return {int(k): int(v) for k, v in (rule.params["cores"] if rule else {}).items()}


def _join_by_cable(groups: dict[tuple[Any, ...], list[Device]]) -> None:
    """BUG-072: protective devices whose poles are not written join the identical component whose poles are what
    their own cable's cores give (25.26.100: three 10A breakers on 3×1.5 beside ten read as 1P). Their instances
    keep the poles unread; the component's come from the ones that were read."""
    implied = _cable_poles()
    for sig in list(groups):
        cores = sig[-1]
        if len(cores) != 1 or cores[0] not in implied:
            continue
        values = tuple((k, repr(implied[cores[0]]) if k == "poles" else v) for k, v in sig[5])
        target = (*sig[:5], values, ())
        if target == sig or target not in groups:
            continue
        cables = {c for d in groups[target] for b in d.built if (c := _cable_cores(b)) is not None}
        if cables <= {cores[0]}:
            groups[target].extend(groups.pop(sig))


def _cable_cores(b: Built) -> int | None:
    cable = b.circuit_context.cable if b.circuit_context else None
    return cable.cores if cable else None


def _cores(d: Device) -> tuple[int, ...]:
    """With the poles not written, a protective device's cable cores tell 1P from 3P (05 §5.5.1): devices on
    cables of different cores are not one component (BUG-072)."""
    poles = d.attributes.get("poles")
    if poles is None or poles.value is not None or d.family not in PROTECTIVE:
        return ()
    cables = {b.circuit_context.cable.cores for b in d.built if b.circuit_context and b.circuit_context.cable}
    return tuple(sorted(c for c in cables if c is not None))


def components(
    drawing_id: str, built: list[Built], schemas: Schemas, cfg: AssociationConfig = DEFAULT
) -> tuple[list[Component], dict[str, str], list[StageIssue]]:
    """5.8: the components, instance id → component id, and the merge's issues."""
    groups: dict[tuple[Any, ...], list[Device]] = defaultdict(list)
    for d in devices(built, schemas, cfg):
        groups[_signature(d)].append(d)
    _join_by_cable(groups)
    out: list[Component] = []
    owner: dict[str, str] = {}
    issues: list[StageIssue] = []
    prefix = drawing_id.removeprefix("drw_")
    for n, group in enumerate(groups.values(), start=1):
        component_id = f"cmp_{prefix}_{n:04d}"
        first = group[0]
        members = [b for d in group for b in d.built]
        designators = sorted({t for d in group for t in d.designators}, key=_tag_order)
        untagged = sum(d.quantity for d in group if not d.designators)
        quantity = len(designators) + untagged
        brands = sorted({b.instance.brand_hint for b in members if b.instance.brand_hint})
        brand = brands[0] if len(brands) == 1 else None
        if len(brands) > 1:
            issues.append(issue("brand_conflict", brands=", ".join(brands)))
        attrs: dict[str, AttributeValue] = {}
        for name in schemas.names(first.family):
            vals = [d.attributes.get(name) for d in group]
            a = vals[0].model_copy() if vals[0] is not None else attribute(None)
            if a.value is not None:
                a.span_ids = sorted({s for v in vals if v is not None for s in v.span_ids})
                a.confidence = min((v.confidence or 1.0) for v in vals if v is not None and v.value is not None)
            attrs[name] = a
        confidence = round(min(d.confidence for d in group), 4)
        contexts = [b.circuit_context for b in members if b.circuit_context is not None]
        context = _join_contexts(contexts)
        texts: list[str] = []
        for b in members:
            texts += [t for t in b.instance.explicit_texts if t not in texts]
        det_ids: list[str] = []
        for b in members:
            det_ids += [x for x in (b.instance.det_id, *b.extra_det_ids) if x and x not in det_ids]
        out.append(
            Component(
                component_id=component_id,
                drawing_id=drawing_id,
                panel_id=first.panel_id,
                family=first.family,
                symbol_class=first.symbol_class,
                attributes=attrs,
                explicit_texts=texts,
                brand_hint=brand,
                quantity=quantity,
                designators=designators,
                parent_designators=sorted({t for d in group for t in d.parent_designators}, key=_tag_order),
                circuit_context=context,
                multiplicity_inherited=first.multiplicity_inherited,
                supply_scope=first.supply_scope,  # type: ignore[arg-type]
                source_det_ids=det_ids,
                instance_ids=[b.instance.instance_id for b in members],
                confidence=confidence,
                status=status(confidence, cfg),  # type: ignore[arg-type]
            )
        )
        for b in members:
            owner[b.instance.instance_id] = component_id
    return out, owner, issues


def _join_contexts(contexts: list[CircuitContext]) -> CircuitContext | None:
    if not contexts:
        return None
    first = contexts[0].model_copy(deep=True)
    for c in contexts[1:]:
        first.circuit_numbers += [n for n in c.circuit_numbers if n not in first.circuit_numbers]
        first.outputs += [o for o in c.outputs if o not in first.outputs]
        for key in ("upstream_designator", "upstream_component_id", "load_current_a", "cable"):
            if getattr(first, key) is None:
                setattr(first, key, getattr(c, key))
    return first


def _tag_order(tag: str) -> tuple[str, int, str]:
    letters = "".join(ch for ch in tag if ch.isalpha())
    digits = "".join(ch for ch in tag if ch.isdigit())
    return (letters, int(digits) if digits else 0, tag)


def missing_instance(
    instance_id: str,
    page_id: str,
    panel_id: str | None,
    bbox: Bbox,
    family: str,
    values: dict[str, Value],
    origin: str,
    cfg: AssociationConfig = DEFAULT,
) -> MissingInstance:
    """5.7: a symbol we think was missed. Always red (≤ 0.4): the user confirms or deletes it."""
    found = [v.confidence for v in values.values()]
    confidence = round(min(cfg.missing_max, min(found) if found else cfg.missing_max), 4)
    return MissingInstance(
        instance_id=instance_id,
        page_id=page_id,
        panel_id=panel_id,
        bbox=bbox,
        family=family,
        attributes={k: attribute(v) for k, v in values.items()},
        origin=origin,
        confidence=confidence,
    )
