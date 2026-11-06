"""06 §6.2: each rule's check, one function per `rule_id`. A check reads one panel's model and returns its hits; the
rule's data (`rules.json`) gives its families, parameters, severity and wording. A check never changes a value
(06 §1 principle 1).

Where many devices share one cause (no cost price, missing from the front view), one hit names them all, as the
prototype's findings do ("5 שורות בלי מחיר", "F26–F29 מופיעים בחזית"): the rows are capped one by one, the reader
reads one message.

Poles are compared as phases (S21 decision 9): a 4P RCD is three phases and a neutral, under a 3P main with its
neutral link, and is not "more poles" than it.
"""

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from konboro.pipeline.association.grammar import same
from konboro.pipeline.association.schemas import Schemas
from konboro.pipeline.matching import catalog, notes, text
from konboro.pipeline.matching.query import ELECTRONIC

from .model import POWER, Device, DrawingModel, PanelModel, compress
from .pack import Rule

READ_SOURCES = ("drawing", "cad_attrib", "graphic", "shared_label", "bom")
PROTECTIVE = ("circuit_breaker", "rcbo", "fuse")
SCOPES = {"other_location": "במקום אחר", "prepare_only": "הכנה בלבד", "by_others": "על ידי אחרים"}
ATTRIBUTE_NAMES = {
    "current_a": "הזרם",
    "current_ac3_a": "הזרם",
    "current_ac3_min_a": "הזרם",
    "poles": "מספר הקטבים",
    "coil_voltage_v": "מתח הסליל",
    "range_min_a": "תחום הכיול",
    "range_max_a": "תחום הכיול",
    "contacts": "המגעים",
    "breaking_capacity_ka": "כושר הניתוק",
    "residual_ma": "זרם הזליגה",
}


@dataclass
class Hit:
    component_ids: list[str] = field(default_factory=list)
    instance_ids: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    page_id: str | None = None
    severity: str | None = None  # a check may lower its rule's severity (DATA_MODEL_TEXT_CONFLICT, S21 decision 4)


@dataclass
class Ctx:
    drawing: DrawingModel
    schemas: Schemas


Check = Callable[[PanelModel, Rule, Ctx], list[Hit]]
CHECKS: dict[str, Check] = {}


def check(rule_id: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS[rule_id] = fn
        return fn

    return register


def phases(poles: int | None) -> int | None:
    return None if poles is None else {1: 1, 2: 1, 3: 3, 4: 3}.get(poles, poles)


def count_text(devices: list[Device]) -> str:
    """ "4 מא"זים (F22–F25)" or 'מא"ז F1'."""
    units = sum(max(d.component.quantity, 1) for d in devices)
    tagged = [t for d in devices for t in d.component.designators]
    if units == 1:
        return devices[0].what
    names = {d.name for d in devices}
    name = f"{units} {_plural(next(iter(names)))}" if len(names) == 1 else f"{units} רכיבים"
    return f"{name} ({compress(tagged)})" if tagged else name


def _plural(name: str) -> str:
    return {
        'מא"ז': 'מא"זים',
        "מפסק בתיבה יצוקה": "מפסקים בתיבה יצוקה",
        "מפסק פחת": "מפסקי פחת",
        "מגען": "מגענים",
        "מפסק מגן מנוע": "מפסקי מגן מנוע",
        "מנתק": "מנתקים",
        "ממסר": "ממסרים",
        "ממסר תרמי": "ממסרים תרמיים",
        "נורת סימון": "נורות סימון",
        "לחצן": "לחצנים",
        "בורר": "בוררים",
        "מגע עזר": "מגעי עזר",
        "סליל הפסקה": "סלילי הפסקה",
    }.get(name, name)


def _ids(devices: list[Device]) -> list[str]:
    return [d.id for d in devices]


def _tags(devices: list[Device]) -> str:
    return compress([t for d in devices for t in d.component.designators]) or ", ".join(
        sorted({d.name for d in devices})
    )


# --- A: hierarchy and coordination -------------------------------------------------------------------------------


def _with_parent(panel: PanelModel, rule: Rule) -> list[tuple[Device, Device]]:
    out = []
    for d in panel.devices:
        if not rule.applies(d.family) or d.parent_id is None:
            continue
        parent = panel.device(d.parent_id)
        if parent is not None and parent.family in POWER:
            out.append((d, parent))
    return out


@check("HIER_CHILD_CURRENT_GT_PARENT")
def child_current(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    return [
        Hit(
            [d.id, p.id],
            values={"child_a": d.current, "parent_a": p.current, "designator": d.tag, "what": d.what, "parent": p.tag},
        )
        for d, p in _with_parent(panel, rule)
        if d.current is not None and p.current is not None and d.current > p.current
    ]


@check("HIER_RCD_UNDERRATED")
def rcd_underrated(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    return [
        Hit([d.id, p.id], values={"child_a": d.current, "parent_a": p.current, "designator": d.tag, "parent": p.tag})
        for d, p in _with_parent(panel, rule)
        if p.family in PROTECTIVE and d.current is not None and p.current is not None and d.current < p.current
    ]


@check("HIER_CHILD_POLES_GT_PARENT")
def child_poles(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = []
    for d, p in _with_parent(panel, rule):
        a, b = phases(d.poles), phases(p.poles)
        if a is not None and b is not None and a > b:
            v = {"child_poles": d.poles, "parent_poles": p.poles, "designator": d.tag, "what": d.what, "parent": p.tag}
            out.append(Hit([d.id, p.id], values=v))
    return out


@check("HIER_ORPHAN_DEVICE")
def orphans(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    fed = {d.parent_id for d in panel.devices if d.parent_id}
    lone = [
        d
        for d in panel.priced
        if rule.applies(d.family) and d.parent_id is None and d.id not in fed and d is not panel.main
    ]
    if not lone:
        return []
    return [Hit(_ids(lone), values={"designators": _tags(lone), "count_text": count_text(lone)})]


@check("PANEL_OUTGOING_GT_MAIN")
def outgoing_gt_main(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    main = panel.main
    if main is None or main.current is None:
        return []
    return [
        Hit(
            [d.id, main.id],
            values={
                "outgoing_a": d.current,
                "main_a": main.current,
                "designator": d.tag,
                "what": d.what,
                "main": main.tag,
            },
        )
        for d in panel.priced
        if d is not main and rule.applies(d.family) and d.current is not None and d.current > main.current
    ]


@check("PANEL_POLES_GT_MAIN")
def poles_gt_main(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    main = panel.main
    if main is None or phases(main.poles) is None:
        return []
    out = []
    for d in panel.priced:
        a = phases(d.poles)
        if d is not main and rule.applies(d.family) and a is not None and a > phases(main.poles):  # type: ignore[operator]
            v = {"poles": d.poles, "main_poles": main.poles, "designator": d.tag, "what": d.what, "main": main.tag}
            out.append(Hit([d.id, main.id], values=v))
    return out


# --- B: completeness and structure -------------------------------------------------------------------------------


@check("PANEL_NO_MAIN_DEVICE")
def no_main(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    outgoing = [d for d in panel.priced if rule.applies(d.family)]
    units = sum(max(d.component.quantity, 1) for d in outgoing)
    if panel.main is not None or units < int(rule.params.get("min_outgoing", 2)):
        return []
    return [Hit(values={"count": units})]


@check("PANEL_EMPTY")
def empty(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    if panel.priced or panel.missing:
        return []
    return [Hit(values={"panel": panel.name})]


@check("CTRL_OVERLOAD_WITHOUT_CONTACTOR")
def overload_without_contactor(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    overloads = [d for d in panel.priced if rule.applies(d.family)]
    if not overloads or any(d.family == "contactor" for d in panel.devices):
        return []
    return [Hit(_ids(overloads), values={"designators": _tags(overloads), "count_text": count_text(overloads)})]


@check("CTRL_CONTACTOR_WITHOUT_COIL_CIRCUIT")
def contactor_without_control(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    if ctx.drawing.has_control_plan or ctx.drawing.bom_is_source:
        return []
    found = [d for d in panel.priced if rule.applies(d.family)]
    return [Hit(_ids(found), values={"count_text": count_text(found)})] if found else []


@dataclass
class FrontCompare:
    missing: list[str]
    extra: list[Device]
    near: list[tuple[str, str, Device]]  # (front tag, plan tag, the plan's device)


def _near(a: str, b: str) -> bool:
    """One letter apart, the same length: "SE" and "SG" (06 §6.2, 26/993)."""
    if len(a) != len(b) or a == b:
        return False
    diff = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    return len(diff) == 1 and diff[0][0].isalpha() and diff[0][1].isalpha()


def _prefix(tag: str) -> str:
    return re.match(r"^[A-Za-z]*", tag).group(0)  # type: ignore[union-attr]


def front_compare(panel: PanelModel, ctx: Ctx) -> FrontCompare:
    front = panel.front
    assert front is not None  # noqa: S101 (the engine runs these rules only with a front view)
    shown = set(front.designators)
    missing = [t for t in front.designators if t not in ctx.drawing.designators]
    plan = [(t, d) for d in panel.devices if d.in_panel for t in d.component.designators if t not in shown]
    near: list[tuple[str, str, Device]] = []
    used: set[str] = set()
    for m in missing:
        for t, d in plan:
            if t not in used and _near(m, t):
                near.append((m, t, d))
                used.add(t)
                break
    paired = {m for m, _, _ in near}
    prefixes = {_prefix(t) for t in front.designators}
    extra: list[Device] = []
    for t, d in plan:
        if t not in used and _prefix(t) in prefixes and d not in extra:
            extra.append(d)
    return FrontCompare([m for m in missing if m not in paired], extra, near)


@check("FRONT_VIEW_DESIGNATOR_MISSING")
def front_missing(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    fc = front_compare(panel, ctx)
    if not fc.missing:
        return []
    front = panel.front
    page = {"page_no": front.page_no} if front else {}
    return [
        Hit(
            values={"shown": compress(fc.missing), "designators": fc.missing, **page},
            page_id=front.page_id if front else None,
        )
    ]


@check("FRONT_VIEW_DESIGNATOR_EXTRA")
def front_extra(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    fc = front_compare(panel, ctx)
    if not fc.extra:
        return []
    front = panel.front
    tagged = [t for d in fc.extra for t in d.component.designators if t not in set(front.designators)]  # type: ignore[union-attr]
    return [Hit(_ids(fc.extra), values={"shown": compress(tagged), "page_no": front.page_no})]  # type: ignore[union-attr]


@check("FRONT_VIEW_DESIGNATOR_NEAR_MATCH")
def front_near(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    front = panel.front
    return [
        Hit([d.id], values={"front": m, "plan": t, "page_no": front.page_no})  # type: ignore[union-attr]
        for m, t, d in front_compare(panel, ctx).near
    ]


@check("PANEL_MISSING_ROWS")
def missing_rows(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    if not panel.missing:
        return []
    n = len(panel.missing)
    words = "רכיב אחד" if n == 1 else f"{n} רכיבים"
    return [Hit(instance_ids=[m.instance_id for m in panel.missing], values={"count": n, "count_text": words})]


@check("PRODUCT_NOT_IN_CATALOG")
def not_in_catalog(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    """S27b (06 decision 1): the panel's components with no product, in the catalog or the factory's, one finding
    with all of them. Only with `catalog_lines` on (13 §4.10)."""
    if not ctx.drawing.catalog_lines:
        return []
    none = [
        d for d in panel.devices if d.match is not None and d.match.chosen_sku is None and d.match.product_id is None
    ]
    if not none:
        return []
    return [Hit(_ids(none), values={"count_text": count_text(none), "tags": _tags(none), "count": len(none)})]


_STRUCTURAL = {"לוח", "חשמל", "panel", "board", "electrical"}
_QUALIFIERS = {"ראשי", "main"}


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[\s\-_/,.()\"״]+", name.casefold()) if len(w) >= 3]


def same_panel(a: str, b: str) -> bool:
    """ "לוח סככת רכב" and "לוח סככה" are one panel: a word they share, by its first three letters, beside "לוח" and
    "חשמל". "לוח ראשי" names no place, so "ראשי" counts: it is "לוח חשמל ראשי מתחם רכב", not "לוח מבנה משרדים"."""
    wa, wb = [w for w in _words(a) if w not in _STRUCTURAL], [w for w in _words(b) if w not in _STRUCTURAL]
    sa, sb = [w for w in wa if w not in _QUALIFIERS], [w for w in wb if w not in _QUALIFIERS]
    if not (sa and sb):
        sa, sb = wa, wb
    return any(x[:3] == y[:3] for x in sa for y in sb)


@check("PANEL_REFERENCED_NOT_DRAWN")
def referenced_not_drawn(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    names = [p.name for p in ctx.drawing.panels.values()]
    out = []
    for f in ctx.drawing.feeds:
        target, source = str(f.get("panel") or ""), str(f.get("fed_from") or "")
        if not target or not source or not same_panel(source, panel.name):
            continue
        if any(same_panel(target, n) for n in names):
            continue
        out.append(Hit(values={"referenced": target, "fed_from": f"מ{panel.name}"}))
    return out


def _bom_rows(panel: PanelModel, ctx: Ctx) -> list[tuple[str, str, int, list[str]]]:
    """(family, class, quantity, words) of each BOM item: the components themselves on a BOM-only drawing (its class
    as stage 5 typed it), else the designer's rows."""
    if ctx.drawing.bom_is_source:
        return [(d.family, d.symbol_class, d.component.quantity, d.component.explicit_texts) for d in panel.devices]
    return [(c.family, c.symbol_class, c.quantity, c.explicit_texts) for c in panel.bom or []]


@check("BOM_ACCESSORY_HOST_COUNT")
def accessory_hosts(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    rows = _bom_rows(panel, ctx)
    out = []
    for accessory, classes in (rule.params.get("hosts") or {}).items():
        acc = sum(q for f, _, q, _ in rows if f == accessory)
        hosts = sum(q for _, c, q, _ in rows if c in classes)
        if acc > hosts:
            name = _plural(text.class_name(accessory, accessory))
            ids = [d.id for d in panel.devices if d.family == accessory] if ctx.drawing.bom_is_source else []
            out.append(Hit(ids, values={"accessories": acc, "hosts": hosts, "accessory_name": name}))
    return out


@check("BOM_NO_ENCLOSURE")
def no_enclosure(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    rows = _bom_rows(panel, ctx)
    if not rows:
        return []
    words = [w.casefold() for w in rule.params.get("words", [])]
    if any(f == "enclosure" or any(w in t.casefold() for t in ts for w in words) for f, _, _, ts in rows):
        return []
    return [Hit()]


@check("SCOPE_NOT_IN_PANEL")
def scope_not_in_panel(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = [d for d in panel.devices if not d.in_panel and d.billable]
    if not out:
        return []
    scopes = ", ".join(dict.fromkeys(SCOPES.get(d.component.supply_scope, d.component.supply_scope) for d in out))
    return [Hit(_ids(out), values={"count_text": count_text(out), "scopes": scopes})]


# --- C: quantities -----------------------------------------------------------------------------------------------


@check("QTY_MULTIPLICITY_OUTLIER")
def multiplicity_outlier(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    top = int(rule.params.get("max_multiplicity", 24))
    out = []
    for i in panel.instances:
        if i.multiplicity > top and i.component_id:
            d = panel.device(i.component_id)
            what = d.what if d else text.class_name(i.family, i.symbol_class)
            v = {
                "multiplicity": i.multiplicity,
                "max_multiplicity": top,
                "designator": d.tag if d else what,
                "what": what,
            }
            out.append(Hit([i.component_id], [i.instance_id], v, i.page_id))
    return out


@check("QTY_SINGLE_INSTANCE_FAMILY")
def single_instance(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    if panel.main is None or not panel.main_shared or not rule.applies(panel.main.family):
        return []
    if any(d.family in rule.params.get("multi_feed_families", []) for d in panel.devices):
        return []
    tied = panel.main_tied
    units = sum(max(d.component.quantity, 1) for d in tied)
    return [Hit(_ids(tied), values={"count": units, "what": count_text(tied)})]


@check("QTY_RANGE_MISMATCH")
def range_mismatch(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    """Stage 4's reading of the range against the count it read (04 §5.1.1): the instance's own result."""
    out = []
    for i in panel.instances:
        if not i.component_id or not any(x.code == "range_mismatch" for x in i.issues):
            continue
        d = panel.device(i.component_id)
        cc = d.component.circuit_context if d else None
        ranges = cc.circuit_numbers if cc else []
        m = re.match(r"^(\d+)-(\d+)$", ranges[0]) if ranges else None
        if d is None or m is None:
            continue
        lo, hi = int(m.group(1)), int(m.group(2))
        v = {"range": f"{lo}–{hi}", "size": hi - lo + 1, "count": i.multiplicity, "designator": d.tag, "what": d.what}
        out.append(Hit([d.id], [i.instance_id], v, i.page_id))
    return out


@check("QTY_INHERITED_MULTIPLICITY")
def inherited(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    return [
        Hit([d.id], values={"designator": d.tag, "what": d.what, "count": d.component.quantity})
        for d in panel.devices
        if d.component.multiplicity_inherited
    ]


@check("TEXT_COVERAGE_LOW")
def text_coverage(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    spans = panel.spans or []
    total = len(spans)
    lone = sum(1 for _, assigned in spans if not assigned)
    if total < int(rule.params.get("min_spans", 10)) or lone / total <= float(
        rule.params.get("max_unassigned_share", 0.1)
    ):
        return []
    return [Hit(values={"unassigned": lone, "total": total, "pct": round(100 * lone / total)})]


# --- D: consistency between the stages ---------------------------------------------------------------------------


def fits(name: str, read: Any, item: Any) -> bool:
    """A value as read against the item's: "אלקטרוני" (`electronic`) is any electronic trip unit (05 §5.6)."""
    if name == "trip_unit" and str(read).casefold() == "electronic":
        return str(item).upper() in ELECTRONIC
    return same(read, item)


@check("DATA_SKU_ATTR_MISMATCH")
def sku_attr_mismatch(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = []
    for d in panel.devices:
        x = d.match
        if x is None or x.catalog_item is None or x.status == "conflict":
            continue
        for a in ctx.schemas.attributes(d.family):
            av = d.component.attributes.get(a.name)
            if a.match_mode != "exact" or av is None or av.value is None or av.source not in READ_SOURCES:
                continue
            item = x.catalog_item.attributes.get(a.name)
            if item is not None and not fits(a.name, av.value, item):
                v = {
                    "attribute": a.name,
                    "read": av.value,
                    "item": item,
                    "sku": x.chosen_sku,
                    "designator": d.tag,
                }
                out.append(Hit([d.id], values=v))
                break
    return out


@check("DATA_SAME_SIGNATURE_DIFF_SKU")
def same_signature(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    by_sig: dict[str, list[Device]] = defaultdict(list)
    for d in panel.devices:
        if d.match is not None and d.match.signature and d.match.chosen_sku:
            by_sig[d.match.signature].append(d)
    out = []
    for sig, ds in by_sig.items():
        skus = sorted({d.match.chosen_sku for d in ds if d.match and d.match.chosen_sku})
        if len(skus) > 1:
            out.append(Hit(_ids(ds), values={"signature": sig, "skus": ", ".join(skus)}))
    return out


def _brand(d: Device) -> str | None:
    return d.match.catalog_item.manufacturer if d.match and d.match.catalog_item else None


@check("DATA_NOTES_NOT_APPLIED")
def notes_not_applied(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    """A general note (a brand, or a value like 10kA) that a component of its family did not get, when the drawing
    did not write that component's own (the drawing wins over a note, 05 §5.4)."""
    out = []
    for line in ctx.drawing.general_notes:
        note = notes.line_rule(line)
        if note is None:
            continue
        families = (note.family,) if note.family else POWER
        bad: list[Device] = []
        chosen: list[str] = []
        for d in panel.priced:
            if d.family not in families or d.match is None or d.match.catalog_item is None:
                continue
            brand = _brand(d)
            if note.brand and not note.equivalent and brand and brand != note.brand and not d.component.brand_hint:
                bad.append(d)
                chosen.append(brand)
                continue
            for k, want in note.attributes.items():
                if k in d.read:
                    continue
                got = d.match.catalog_item.attributes.get(k)
                if got is None:
                    continue
                short = k == "breaking_capacity_ka" and isinstance(got, int | float) and got < want
                if short or (k != "breaking_capacity_ka" and not same(got, want)):
                    bad.append(d)
                    chosen.append(text.value(k, got))
                    break
        if bad:
            what = ", ".join(dict.fromkeys(chosen))
            out.append(
                Hit(
                    _ids(bad),
                    values={
                        "note": note.text,
                        "designators": _tags(bad),
                        "count_text": count_text(bad),
                        "chosen": what,
                    },
                )
            )
    return out


@check("DATA_MANY_DEFAULTS")
def many_defaults(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    priced = [d for d in panel.priced if d.match is not None]
    filled = [d for d in priced if d.match and d.match.defaulted_attributes]
    if not priced or len(filled) / len(priced) <= float(rule.params.get("max_share", 0.3)):
        return []
    return [Hit(values={"count": len(filled), "total": len(priced), "pct": round(100 * len(filled) / len(priced))})]


@check("DATA_DESIGNATOR_FAMILY_CONFLICT")
def designator_family(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    by_tag: dict[str, list[Device]] = defaultdict(list)
    for d in panel.devices:
        for t in d.component.designators:
            by_tag[t].append(d)
    out = []
    for t, ds in by_tag.items():
        families = sorted({d.family for d in ds})
        if len(families) > 1:
            names = " וגם כ".join(dict.fromkeys(d.name for d in ds))
            out.append(Hit(_ids(ds), values={"designator": t, "families": names}))
    return out


@check("DATA_MODEL_TEXT_CONFLICT")
def model_text_conflict(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = []
    for d in panel.devices:
        x = d.match
        if x is None:
            continue
        if x.status == "conflict" and "attribute_conflict" in x.warnings:
            out.append(Hit([d.id], values={"designator": d.tag, "reason": x.reason}))
        elif "attribute_conflict_resolved" in x.warnings:
            sev = str(rule.params.get("resolved_severity", "info"))
            out.append(Hit([d.id], values={"designator": d.tag, "reason": x.reason}, severity=sev))
    return out


@check("DATA_LOAD_CURRENT_GT_RATED")
def load_gt_rated(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = []
    for d in panel.devices:
        cc = d.component.circuit_context
        load = cc.load_current_a if cc else None
        if rule.applies(d.family) and load is not None and d.current is not None and load > d.current:
            v = {"load_a": load, "rated_a": d.current, "designator": d.tag, "what": d.what}
            out.append(Hit([d.id], values=v))
    return out


@check("DATA_INFERRED_ATTRIBUTE")
def inferred(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    out = []
    for d in panel.devices:
        if d.match is None:
            continue
        names = [k for k, u in d.match.attributes_used.items() if u.source == "inferred"]
        if not names:
            continue
        said = list(dict.fromkeys(ATTRIBUTE_NAMES.get(k, k) for k in names))
        note = " ".join(dict.fromkeys(u.note for k, u in d.match.attributes_used.items() if k in names and u.note))
        v = {"designator": d.tag, "attribute_he": " ו".join(said), "attributes": names, "note": note}
        out.append(Hit([d.id], values=v))
    return out


@check("POLES_CABLE_CONFLICT")
def poles_cable(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    table: dict[str, list[int]] = rule.params.get("cores_to_poles", {})
    out = []
    for d in panel.devices:
        av = d.component.attributes.get("poles")
        cc = d.component.circuit_context
        cores = cc.cable.cores if cc and cc.cable else None
        if (
            not rule.applies(d.family)
            or av is None
            or av.value is None
            or av.source not in READ_SOURCES
            or cores is None
        ):
            continue
        allowed = table.get(str(cores))
        if allowed is not None and int(av.value) not in allowed:
            out.append(Hit([d.id], values={"poles": av.value, "cores": cores, "designator": d.tag, "what": d.what}))
    return out


@check("DATA_PANEL_REQUIREMENT_NOT_MET")
def requirement(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    req = panel.requirement
    if req is None:
        return []
    short: list[Device] = []
    lowest: float | None = None
    for d in panel.priced:
        item = d.match.catalog_item if d.match else None
        ka = item.attributes.get("breaking_capacity_ka") if item else None
        if rule.applies(d.family) and isinstance(ka, int | float) and ka < req.min_breaking_capacity_ka:
            short.append(d)
            lowest = ka if lowest is None else min(lowest, ka)
    if not short:
        return []
    v = {
        "required_ka": req.min_breaking_capacity_ka,
        "item_ka": lowest,
        "source": req.source,
        "designators": _tags(short),
        "count_text": count_text(short),
    }
    return [Hit(_ids(short), values=v)]


@check("DATA_NO_COST_PRICE")
def no_cost(panel: PanelModel, rule: Rule, ctx: Ctx) -> list[Hit]:
    """06 §12: only whether a cost exists; no price is read here."""
    found = [d for d in panel.priced if d.match and d.match.chosen_sku and not d.match.has_cost_price]
    return [Hit(_ids(found), values={"count_text": count_text(found)})] if found else []


def sku_like(token: str) -> bool:
    t = catalog.norm_sku(token)
    return len(t) >= 5 and any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t)
