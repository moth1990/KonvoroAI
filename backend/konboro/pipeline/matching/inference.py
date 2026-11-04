"""05 §5.5.1: what a device takes from its circuit, by the rules in `inference.json` (data, global, a factory turns a
rule off). An inferred value is `source` = `inferred`, carries its explanation ("נבחר לפי F1 (16A)"), costs × 0.85 and
keeps the line yellow until the estimator approves it. No rule runs without its input: with no known protective device
above a contactor, its current stays missing and the line red (05 §5.5.1).

Two of the table's rows are not here: the aux contact's NO/NC is read from its contact numbers when the attributes are
normalized (`match.normalize`: "21/22" is NC, a reading, not a guess), and a moulded-case breaker's setting is checked
against each candidate's range in the query (`Need` mode `contains`). A current transformer's count of 3 changes a
quantity, which is stage 4's; it waits for stage 6's cross-check (S21).
"""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from konboro.contracts.merge import Component
from konboro.pipeline.association.grammar import parse

from . import text
from .notes import Notes
from .query import Need

RULES = Path(__file__).with_name("inference.json")
FILLED = ("notes", "tenant_default", "system_default")  # 05 §5.5: what a fill-in, not the drawing, gave


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    families: frozenset[str]
    params: dict[str, Any]


@cache
def rules() -> tuple[Rule, ...]:
    data = json.loads(RULES.read_text(encoding="utf-8"))
    out = []
    for r in data["rules"]:
        params = {k: v for k, v in r.items() if k not in ("id", "kind", "families")}
        out.append(Rule(r["id"], r["kind"], frozenset(r["families"]), params))
    return tuple(out)


def outranged(component: Component, have: dict[str, Need], tops: dict[str, float], off: frozenset[str]) -> bool:
    """BUG-070: a component typed as the lower class of a `class_by_current` rule, rated above the catalog's largest
    of that class: typed again by its current, as an untyped one."""
    current = _num(have["current_a"].value) if "current_a" in have else None
    written = {r.value for t in component.explicit_texts for r in parse(t) if r.key == "symbol_class"}
    if component.symbol_class in written:
        return False  # "MCB" written beside it: the class narrows (05 §5.1 item 2), even to nothing
    for rule in rules():
        p = rule.params
        if rule.kind != "class_by_current" or rule.id in off or component.family not in rule.families:
            continue
        top = tops.get(p["below"])
        if p.get("or_above_catalog_range") and component.symbol_class == p["below"] and current and top:
            return current > top
    return False


def class_tops(top_current: Any) -> dict[str, float]:
    """The largest current per lower class of the `class_by_current` rules, by `top_current(family, class)`."""
    out: dict[str, float] = {}
    for rule in rules():
        if rule.kind == "class_by_current" and rule.params.get("or_above_catalog_range"):
            for family in rule.families:
                top = top_current(family, rule.params["below"])
                if top is not None:
                    out[rule.params["below"]] = top
    return out


@dataclass
class Inferred:
    needs: list[Need] = field(default_factory=list)
    symbol_class: str | None = None  # an untyped "מפסק" given a class by its current
    warnings: list[str] = field(default_factory=list)  # poles_cable_conflict, breaker_type_inferred
    used: list[str] = field(default_factory=list)  # rule ids that gave something


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def infer(
    component: Component,
    have: dict[str, Need],
    upstream: Component | None,
    notes: Notes,
    off: frozenset[str] = frozenset(),
    untyped: bool = False,
    tops: dict[str, float] | None = None,
) -> Inferred:
    """What the rules give for the attributes `have` lacks. `upstream` is the protective device above the component,
    from stage 4's `circuit_context`, when it is known. `tops`: the catalog's largest current per class."""
    out = Inferred()
    ctx = component.circuit_context
    for rule in rules():
        if rule.id in off or component.family not in rule.families:
            continue
        p = rule.params
        if rule.kind == "upstream_current" and p["attribute"] not in have:
            if upstream is None or upstream.family not in p["protective_families"]:
                continue
            rated = upstream.attributes.get("current_a")
            current = _num(rated.value if rated else None)
            if current is None:
                continue
            designator = upstream.designators[0] if upstream.designators else ""
            note = p["explain"].format(designator=designator, current=text.number(current))
            out.needs.append(Need(p["attribute"], current, "gte", "inferred", False, note))
            out.used.append(rule.id)
        elif rule.kind == "control_voltage" and p["attribute"] not in have:
            volts = notes.voltage(component.panel_id)
            if volts is None:
                continue
            note = p["explain"].format(volts=text.number(volts))
            out.needs.append(Need(p["attribute"], volts, "exact", "inferred", False, note))
            out.used.append(rule.id)
        elif rule.kind == "range_contains_load" and "range_min_a" not in have and "range_max_a" not in have:
            load = ctx.load_current_a if ctx else None
            if load is None:
                continue
            note = p["explain"].format(load=text.number(load))
            out.needs.append(Need("load_current_a", load, "contains", "inferred", False, note))
            out.used.append(rule.id)
        elif rule.kind == "cable_cores":
            cores = ctx.cable.cores if ctx and ctx.cable else None
            poles = p["cores"].get(str(cores)) if cores else None
            if poles is None:
                continue
            read = have.get(p["attribute"])
            if read is None:
                note = p["explain"].format(cores=cores)
                out.needs.append(Need(p["attribute"], poles, "exact", "inferred", False, note))
                out.used.append(rule.id)
            elif read.source == "graphic" and _num(read.value) != float(poles):
                out.warnings.append("poles_cable_conflict")  # 05 §5.5.1: yellow, `POLES_CABLE_CONFLICT` (06)
        elif rule.kind == "unit_slip":
            read = have.get(p["attribute"])
            if read is not None and read.source not in FILLED:
                continue
            for written in component.explicit_texts:
                if m := re.match(p["pattern"], written):
                    amps = float(f"0.{m['digits']}")
                    value = round(amps * p["factor"])
                    note = p["explain"].format(written=m[0], amps=text.number(amps), value=value)
                    out.needs.append(Need(p["attribute"], value, "exact", "inferred", False, note))
                    out.used.append(rule.id)
                    break
        elif rule.kind == "class_by_current" and untyped:
            current = _num(have["current_a"].value) if "current_a" in have else None
            if current is None:
                continue
            top = (tops or {}).get(p["below"]) if p.get("or_above_catalog_range") else None
            above = current >= p["at_least_a"] or (top is not None and current > top)
            out.symbol_class = p["above"] if above else p["below"]
            out.warnings.append("breaker_type_inferred")
            out.used.append(rule.id)
    return out
