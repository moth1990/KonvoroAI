"""04 §5.6–5.8, §6.4: instances, missed symbols, and the merge into components. Code only.

An instance is one symbol with what was read for it. The merge, once per drawing:
1. **By tag first** (5.8): instances in one panel with the same tag are one device, on every page and in every
   representation (FP1 on two pages; C1's power contacts and its coil). The device takes the family of its device
   drawing, else its coil, else its contacts (03 §4.5); the attributes join from all of them, and two that disagree
   keep the first representation's value, flagged `attribute_conflict` (× 0.8).
2. An auxiliary contact (family `aux_contact`) is an accessory of its own: its tag is the device it sits on
   (`parent_designators`), not a device of its own tag. An untagged contact or coil of a family that has tagged
   devices in the panel is another drawing of one of them, and joins the nearest (no quantity of its own).
   A symbol tagged with a list ("MS1/MS2/MS3", 03 §3.7 item 5) is one device per tag in the list, so its quantity
   is the list's length (BUG-031).
   - A tag drawn only as terminals, whose letters name devices of one other family in the panel, is a device of that
     family: terminals are numbered, not tagged, and MINHAROT-1's selectors SW2–SW5 were read as their two contact
     points while SW1 was read as a selector (BUG-051). Never green: the family is the tag's, not the drawing's.
   - A contactor drawn as single-pole power contacts on one page, one per circuit, has a pole per contact
     (MINHAROT-1's C1 on F2–F4, BUG-053). Only drawn poles (`graphic`) are counted; poles written as text win.
   - An auxiliary contact tagged with devices drawn on another page is drawn again where it is used (a fault-lamp
     circuit), when the devices' page has at least as many contacts: it joins one of them with no quantity of its own
     (MINHAROT-1's 21/22 contacts on pages 5 and 8, BUG-054). The dashed link (03 §3.7 item 4) is not read in v1.
3. **Then by signature**: devices with the same panel, family, class, supply scope and exactly the same values in
   every attribute (null included) are one component. Quantity: the number of distinct tags, plus the multiplicity
   of the untagged ones. Missing instances, different panels, and a known value against a null never merge.
"""

import re
from collections import Counter, defaultdict
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
from konboro.pipeline.detection.designators import tags

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
    "family_by_tag": "{tags} צוירו כמו מהדקים, והתג שלהם הוא כמו של {kin}. הם נספרו כמו {kin}. בדקו את השורה.",
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
    family_by_tag: str | None = None  # the tag whose family a terminal took (BUG-051)


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
    for b in sorted(built, key=lambda b: b.order):
        if b.designator and len(tags(b.designator)) == 1 and b.instance.family != "aux_contact" and b.instance.panel_id:
            by_tag[(b.instance.panel_id, b.designator)].append(b)
        else:
            alone.append(b)
    out: list[Device] = []
    device_page: dict[tuple[str, str], int] = {}  # (panel, tag) → the page of the tag's device drawing
    for (panel_id, tag), members in by_tag.items():
        lead = min(members, key=lambda b: (ROLE_RANK.get(b.role, 9), -b.instance.confidence, b.order))
        if lead.role == "device":
            device_page[(panel_id, tag)] = lead.order[0]
        family, cls = lead.instance.family, lead.instance.symbol_class
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
    _family_by_tag(out, schemas, cfg)
    tagged: dict[tuple[str, str], list[Device]] = defaultdict(list)
    for d in out:
        tagged[(d.panel_id, d.family)].append(d)
    away = _away_contacts(alone, device_page)
    contacts: dict[tuple[str, int], list[Device]] = defaultdict(list)  # (panel, page) → the contacts counted there
    for b in alone:
        i = b.instance
        aux = i.family == "aux_contact"
        if id(b) in away:
            continue
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
                [] if aux else tags(b.designator),
                tags(b.designator) if aux else [],
                i.multiplicity,
                [b],
                i.confidence,
                b.supply_scope,
                b.multiplicity_inherited,
            )
        )
        if aux:
            contacts[(i.panel_id or "", b.order[0])].append(out[-1])
    for b in (b for b in alone if id(b) in away):
        host = min(contacts[(b.instance.panel_id or "", away[id(b)])], key=lambda d: _distance(d, b))
        host.built.append(b)
        host.parent_designators += [t for t in tags(b.designator) if t not in host.parent_designators]
    for d in out:
        if d.designators and d.family != "aux_contact":
            _poles_from_contacts(d, cfg)
    return out


REPRESENTATIONS = frozenset({"coil", "power_contact", "relay_contact"})
_LETTERS = re.compile(r"^[A-Z]+")
# a terminal named after its conductor (NURSERY-1's L4 and N4, circuit 4's phase and neutral) or its strip (X1):
# terminals' own names, though L1–L3 are lamps on the same drawing (03 §3.7 item 2)
CONDUCTOR_LETTERS = frozenset({"L", "N", "PE", "X"})


def _letters(tag: str) -> str:
    m = _LETTERS.match(tag)
    return m.group(0) if m else ""


def _family_by_tag(devices: list[Device], schemas: Schemas, cfg: AssociationConfig) -> None:
    """BUG-051: a tag drawn only as terminals takes the family its letters name in the panel (SW2 beside SW1, a
    selector), when they name one family. Terminals keep their family when nothing else in the panel shares the
    letters, when two families do, or when the letters are a conductor's or a strip's (`CONDUCTOR_LETTERS`)."""
    kin: dict[tuple[str, str], list[Device]] = defaultdict(list)
    for d in devices:
        if d.family != "terminal" and _letters(d.designators[0]):
            kin[(d.panel_id, _letters(d.designators[0]))].append(d)
    for d in devices:
        if d.family != "terminal" or any(b.instance.family != "terminal" for b in d.built):
            continue
        if _letters(d.designators[0]) in CONDUCTOR_LETTERS:
            continue
        same = kin.get((d.panel_id, _letters(d.designators[0])), [])
        named = Counter((k.family, k.symbol_class) for k in same)
        if len(named) != 1:
            continue
        (family, cls), _ = named.most_common(1)[0]
        d.family, d.symbol_class = family, cls
        d.attributes = {n: attribute(None) for n in schemas.names(family)}
        d.confidence = round(min(d.confidence, cfg.family_by_tag_max), 4)
        d.family_by_tag = same[0].designators[0]


def _away_contacts(alone: list[Built], device_page: dict[tuple[str, str], int]) -> dict[int, int]:
    """BUG-054: id(contact) → the page it joins, for each auxiliary contact tagged with devices drawn on one other
    page. All the contacts bound for a page join it when it has at least as many contacts of its own; else none
    does, and each is counted where it is drawn."""
    bound: dict[tuple[str, int], list[Built]] = defaultdict(list)
    home: Counter[tuple[str, int]] = Counter()
    for b in alone:
        if b.instance.family != "aux_contact":
            continue
        panel_id = b.instance.panel_id or ""
        names = tags(b.designator)
        pages = {device_page[(panel_id, t)] for t in names if (panel_id, t) in device_page}
        if names and len(pages) == 1 and all((panel_id, t) in device_page for t in names) and b.order[0] not in pages:
            bound[(panel_id, pages.pop())].append(b)
        else:
            home[(panel_id, b.order[0])] += b.instance.multiplicity
    out: dict[int, int] = {}
    for (panel_id, page), group in bound.items():
        if home[(panel_id, page)] >= sum(b.instance.multiplicity for b in group):
            out.update({id(b): page for b in group})
    return out


def _poles_from_contacts(d: Device, cfg: AssociationConfig) -> None:
    """BUG-053: a device drawn as two or more power contacts on one page, each drawn single-pole (or not read), has
    a pole per contact. Never over poles written as text, nor over a contact drawn with more than one pole."""
    poles = d.attributes.get("poles")
    if poles is None or (poles.value is not None and poles.source != "graphic"):
        return
    by_page: dict[int, list[Built]] = defaultdict(list)
    for b in d.built:
        if b.role == "power_contact":
            by_page[b.order[0]].append(b)
    best: AttributeValue | None = None
    for drawn in by_page.values():
        read = [a for b in drawn if (a := b.instance.attributes.get("poles")) is not None and a.value is not None]
        if len(drawn) < 2 or not read or any(a.source != "graphic" or a.value != 1 for a in read):
            continue
        if best is None or len(drawn) > best.value:
            confidence = min(min(a.confidence or cfg.graphic_max for a in read), cfg.graphic_max)
            best = AttributeValue(value=len(drawn), source="graphic", confidence=confidence, span_ids=[])
    if best is not None:
        d.attributes["poles"] = best


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
    return (d.panel_id, d.family, d.symbol_class, d.supply_scope, d.multiplicity_inherited, values)


def components(
    drawing_id: str, built: list[Built], schemas: Schemas, cfg: AssociationConfig = DEFAULT
) -> tuple[list[Component], dict[str, str], list[StageIssue]]:
    """5.8: the components, instance id → component id, and the merge's issues."""
    groups: dict[tuple[Any, ...], list[Device]] = defaultdict(list)
    found = devices(built, schemas, cfg)
    for d in found:
        groups[_signature(d)].append(d)
    out: list[Component] = []
    owner: dict[str, str] = {}
    issues: list[StageIssue] = []
    retagged: dict[str, list[str]] = defaultdict(list)
    for d in found:
        if d.family_by_tag:
            retagged[d.family_by_tag] += d.designators
    for kin, named in retagged.items():
        issues.append(issue("family_by_tag", "warning", tags=", ".join(sorted(named, key=_tag_order)), kin=kin))
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
