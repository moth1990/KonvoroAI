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
   relay). An accessory (a shunt trip) under a device's tag sits on that device. One written tag names one device
   (BUG-081, `one_name_per_tag`): a span nearest a coil or a contact names that one's device, not another family's.
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
    "poles_from_peers": "לא סומנו קטבים: רוב המפסקים הזהים בשורה סומנו {poles}. בדקו.",
    "poles_peer_conflict": "סומן {read}, אבל רוב המפסקים הזהים בשורה סומנו {poles}. בדקו את הקטבים.",
    "poles_corrected": "סומן {read}, אבל הכבל {cable} ורוב המפסקים הזהים בשורה נותנים {poles}: נספר כ-{poles}. בדקו.",
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
    designator_span: tuple[str, Bbox] | None = None  # the span stage 3 linked as its tag, and where it is (BUG-081)


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


SHARED_TOUCH_PT = 6.0  # a symbol this close to the tag's nearest symbol is part of its drawing (S24b decision 4)


def _gap(a: Bbox, b: Bbox) -> float:
    dx, dy = max(a[0] - b[2], 0.0, b[0] - a[2]), max(a[1] - b[3], 0.0, b[1] - a[3])
    return float((dx * dx + dy * dy) ** 0.5)


def one_name_per_tag(built: list[Built]) -> None:
    """BUG-081: one written tag names one device. Stage 3 links each symbol to its nearest tag-shaped span, so one
    "T1" under 25.26.100's clock was also the selector's and C130,131's coil's (the model read it beside them too),
    and the selector became T1's device. A span nearest a coil or a contact names that coil's device (a contactor, a
    relay, a timer): another family's symbol that took it loses it, unless it touches that coil or contact or sits on
    the device (an accessory). A span nearest a device drawing is left to `devices` (S24b decision 4: Q0's ring read
    as a current transformer is a part of Q0). Here, not in stage 3: the tile agent is shown stage 3's tags."""
    takers: dict[tuple[str, str], list[Built]] = defaultdict(list)
    for b in built:
        if b.designator and b.designator_span and b.instance.bbox is not None:
            takers[(b.instance.page_id, b.designator_span[0])].append(b)
    for group in takers.values():
        if len({b.instance.family for b in group}) < 2:
            continue
        where = group[0].designator_span[1]  # type: ignore[index]
        nearest = min(group, key=lambda b: (_gap(b.instance.bbox, where), b.order))  # type: ignore[arg-type]
        if nearest.role not in REPRESENTATIONS:
            continue
        for b in group:
            i = b.instance
            if (
                i.family == nearest.instance.family
                or i.family in ACCESSORIES
                or _gap(i.bbox, nearest.instance.bbox) <= SHARED_TOUCH_PT  # type: ignore[arg-type]
            ):
                continue
            b.designator = None


def devices(built: list[Built], schemas: Schemas, cfg: AssociationConfig = DEFAULT) -> list[Device]:
    """5.8 items 1–3: one device per tag in a panel; an auxiliary contact on its own; an untagged symbol alone."""
    one_name_per_tag(built)
    by_tag: dict[tuple[str, str], list[Built]] = defaultdict(list)
    alone: list[Built] = []
    accessories: list[tuple[Built, str]] = []  # an accessory under another device's tag, and that tag
    for b in sorted(built, key=lambda b: b.order):
        if b.designator and len(tags(b.designator)) == 1 and b.instance.family != "aux_contact" and b.instance.panel_id:
            by_tag[(b.instance.panel_id, b.designator)].append(b)
        else:
            alone.append(b)
    out: list[Device] = []
    device_page: dict[tuple[str, str], int] = {}  # (panel, tag) → the page of the tag's device drawing
    for (panel_id, tag), group in by_tag.items():
        lead = min(group, key=lambda b: (ROLE_RANK.get(b.role, 9), -b.instance.confidence, b.order))
        if lead.role == "device":
            device_page[(panel_id, tag)] = lead.order[0]
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
    _family_by_tag(out, schemas, cfg)
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
    away = _away_contacts(alone, device_page)
    contacts: dict[tuple[str, int], list[Device]] = defaultdict(list)  # (panel, page) → the contacts counted there
    for b in alone:
        i = b.instance
        aux = i.family == "aux_contact"
        if id(b) in away:
            continue
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


PEER_ROW_PT = 3.0  # alike peers (BUG-088), as stage 3's rows (`detection/evidence.py`): tops or middles this close
PEER_WIDTH_SHARE = 0.15
PEER_HEIGHT_SHARE = 0.6


def _alike(a: Bbox, b: Bbox) -> bool:
    level = abs(a[1] - b[1]) <= PEER_ROW_PT or abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2) <= PEER_ROW_PT
    wa, wb, ha, hb = a[2] - a[0], b[2] - b[0], a[3] - a[1], b[3] - b[1]
    return level and abs(wa - wb) <= PEER_WIDTH_SHARE * wa and min(ha, hb) >= PEER_HEIGHT_SHARE * max(ha, hb)


SURE_MARK = 0.85  # a pole mark read at least this sure is never outvoted (00 §6.3's green)


def _row_key(sig: tuple[Any, ...]) -> tuple[Any, ...]:
    """What alike peers share: panel, family, class, scope, multiplicity and every value but the poles."""
    return (*sig[:5], tuple((k, v) for k, v in sig[5] if k != "poles"))


def _touching(a: Device, b: Device) -> bool:
    return any(
        x.instance.page_id == y.instance.page_id
        and x.instance.bbox is not None
        and y.instance.bbox is not None
        and _alike(x.instance.bbox, y.instance.bbox)
        for x in a.built
        for y in b.built
    )


def _join_by_peers(groups: dict[tuple[Any, ...], list[Device]]) -> None:
    """BUG-088 (the user: breakers drawn alike in one row with one rating "are all the same"). The identical protective
    devices of a row, drawn alike, take the poles most of them were read as:
    - one with no poles read, and no cable on its circuit (that is `_join_by_cable`'s evidence), joins their component;
      like `_join_by_cable`, each instance keeps its poles unread (00 §5.3) and carries why it joined;
    - one whose unsure pole mark (`graphic`) disagrees keeps its reading and its own line, flagged for the reviewer
      (`poles_peer_conflict`), unless its own cable backs what was marked. Outvoting it made 6199-2-50's real 1P
      breaker among five 3P a 3P one (the user chose the flag);
    - one whose own cable gives the majority's poles too joins them (`poles_corrected`, S24b decision 12: 25.26.100's
      two 10A "X2" read 3P on 3×1.5 beside thirteen 1P). Its instance keeps the mark as read; stage 5 makes the
      component's poles `inferred` (`matching.match.corrected_poles`).
    A tie, a sure mark or a count written in text that disagrees gives nothing. Peers are the same family, class and
    values: an RCD's 4P beside the breakers never votes."""
    rows: dict[tuple[Any, ...], list[tuple[tuple[Any, ...], Device]]] = defaultdict(list)
    for sig, devs in groups.items():
        if sig[1] in PROTECTIVE:
            rows[_row_key(sig)] += [(sig, d) for d in devs]
    for members in rows.values():
        if len({sig for sig, _ in members}) < 2:
            continue
        for cluster in _clusters(members):
            _vote_poles(groups, cluster)


def _clusters(members: list[tuple[tuple[Any, ...], Device]]) -> list[list[tuple[tuple[Any, ...], Device]]]:
    """The rows among `members`: devices drawn alike side by side, chained."""
    left = list(members)
    out = []
    while left:
        cluster = [left.pop(0)]
        grew = True
        while grew:
            grew = False
            for m in list(left):
                if any(_touching(m[1], c[1]) for c in cluster):
                    cluster.append(m)
                    left.remove(m)
                    grew = True
        if len(cluster) > 1:
            out.append(cluster)
    return out


def _vote_poles(groups: dict[tuple[Any, ...], list[Device]], cluster: list[tuple[tuple[Any, ...], Device]]) -> None:
    def poles(d: Device) -> AttributeValue | None:
        a = d.attributes.get("poles")
        return a if a is not None and a.value is not None else None

    votes: dict[str, int] = defaultdict(int)
    for _, d in cluster:
        if (a := poles(d)) is not None:
            votes[repr(a.value)] += 1
    if not votes:
        return
    ranked = sorted(votes.items(), key=lambda it: -it[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return  # a tie
    winner = ranked[0][0]
    dissent = [(sig, d) for sig, d in cluster if (a := poles(d)) is not None and repr(a.value) != winner]
    implied = _cable_poles()
    flagged: list[Device] = []
    corrected: list[tuple[tuple[Any, ...], Device]] = []
    for sig, d in dissent:
        a = poles(d)
        if a is None or a.source != "graphic" or (a.confidence or 0.0) >= SURE_MARK:
            return  # written in text, or a sure mark: the row is not one product
        cabled = {implied.get(c) for b in d.built if (c := _cable_cores(b)) is not None}
        if a.value in cabled:
            continue  # its own cable backs the mark (25.26.100's kitchen 3P on 5×2.5)
        if cabled and all(p is not None and repr(p) == winner for p in cabled):
            corrected.append((sig, d))  # its cable and the majority agree against the mark (decision 12)
        else:
            flagged.append(d)
    target = next(sig for sig, d in cluster if (a := poles(d)) is not None and repr(a.value) == winner)
    shown = f"{winner}P"
    for d in flagged:  # kept as read, on its own line: 6199-2-50's shed has a real 1P among five 3P (the user's choice)
        for b in d.built:
            b.instance.issues.append(
                issue("poles_peer_conflict", "warning", b.instance.page_id, poles=shown, read=f"{poles(d).value}P")  # type: ignore[union-attr]
            )
    majority = poles(groups[target][0])
    for sig, d in corrected:
        read = f"{poles(d).value}P"  # type: ignore[union-attr]
        for b in d.built:
            cable = b.circuit_context.cable if b.circuit_context else None
            shown_cable = (cable.raw or f"{cable.cores} גידים") if cable else ""
            b.instance.issues.append(
                issue("poles_corrected", "warning", b.instance.page_id, poles=shown, read=read, cable=shown_cable)
            )
        d.attributes = {**d.attributes, "poles": majority.model_copy()}  # type: ignore[union-attr]
        _move(groups, sig, d, target)
    for sig, d in [(sig, d) for sig, d in cluster if sig != target and poles(d) is None and not sig[-1]]:
        for b in d.built:
            b.instance.issues.append(issue("poles_from_peers", "info", b.instance.page_id, poles=shown))
        _move(groups, sig, d, target)


def _move(
    groups: dict[tuple[Any, ...], list[Device]], sig: tuple[Any, ...], d: Device, target: tuple[Any, ...]
) -> None:
    groups[sig] = [x for x in groups[sig] if x is not d]
    if not groups[sig]:
        del groups[sig]
    groups[target].append(d)


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
    found = devices(built, schemas, cfg)
    for d in found:
        groups[_signature(d)].append(d)
    _join_by_cable(groups)
    _join_by_peers(groups)
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
