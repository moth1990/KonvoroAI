"""Matching the quote's lines to the drawing's components (11 §5.3), in code only (S15 decision 3).

A line and a component match when:
- the family matches, by `ACCEPTS` (data: "מנתק" is a disconnector or a changeover switch, an untyped "מפסק" any
  breaker, 05 §5.5.1 leaving its class to the current; "פחת" an RCD or an RCBO), and a motor protection is never an
  MCB or a moulded case;
- the poles match and so does the neutral when the line writes poles ("1X16A" has none, "N+16" has one);
- the current is the same, or within the line's range ("עד 100A");
- every other value the line writes agrees with the component's when the component has it. A value the line
  doesn't write never stops a match ("מגע עזר" matches any auxiliary contact). Positions are compared as a set
  ("0-1-2" = "1-0-2": the same three positions);
- an enclosure: by its sides, when both write them.

A motor protection's range bounds the current: a component with a current outside it disagrees.

A pair that agrees on the family but on one value only (3X16A against 3X20A) is `near`: an `attribute_mismatch`
candidate. Two values apart (1X6A against 2X16A) is another product, not a near one.

The assignment: each line takes components up to its quantity. Pairs are taken best first: exact before a range or a
looser class, then the pair that agrees on more written values, then the component with the fewest candidate lines,
then the line with the fewest components, then the quote's order. This keeps the units matched as high as the golden
cases need; it is not a full max-flow.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from konboro.pipeline.association.grammar import same

from .signature import ENCLOSURE, UNTYPED, Signature

# A line's family → the component families it may stand for. A family not listed stands for itself.
ACCEPTS: dict[str, frozenset[str]] = {
    "circuit_breaker": frozenset({"circuit_breaker", "rcbo"}),
    "rcd": frozenset({"rcd", "rcbo"}),  # "פחת 4X40A": a residual-current device, with or without overcurrent
    "switch_disconnector": frozenset({"switch_disconnector", "changeover_switch", "ats"}),
    "changeover_switch": frozenset({"changeover_switch", "ats", "switch_disconnector"}),
    "energy_meter": frozenset({"energy_meter", "measuring_instrument"}),
    "measuring_instrument": frozenset({"measuring_instrument", "energy_meter"}),
    "busbar": frozenset({"busbar", "busbar_block"}),
    "push_button": frozenset({"push_button", "emergency_button"}),
}
# Classes that are different products within one family: written on both sides and different, they never match.
DISTINCT_CLASSES = frozenset({"motor_protection"})
BREAKER_CLASSES = frozenset({"mcb", "mccb", "motor_protection"})

EXACT, LOOSE = 0, 1  # the pair's tier: lower is better


@dataclass
class DrawnComponent:
    """A stage-4 component as the audit sees it: family, written values, units and where it is drawn."""

    component_id: str
    family: str
    cls: str
    values: dict[str, Any]
    quantity: int
    designators: list[str] = field(default_factory=list)
    confidence: float = 1.0
    instances: list[tuple[str, int]] = field(default_factory=list)  # (instance id, page no)
    conflicts: list[str] = field(default_factory=list)  # attribute_conflict names (04 §5.5)
    texts: list[str] = field(default_factory=list)

    @property
    def drawings(self) -> int:
        """How many times it is drawn: its instances, on every page and view."""
        return len(self.instances)

    @property
    def pages(self) -> list[int]:
        return sorted({p for _, p in self.instances})


@dataclass
class Pair:
    line: int  # the line's index
    component: str
    tier: int
    conflicts: list[str] = field(default_factory=list)
    agreed: int = 0  # values both sides write and agree on

    @property
    def near(self) -> bool:
        return bool(self.conflicts)

    @property
    def close(self) -> bool:
        """An attribute-mismatch candidate: one value apart (the neutral counts with the poles)."""
        return len([k for k in self.conflicts if k != "neutral"] or self.conflicts) == 1


def accepts(sig: Signature, component_family: str) -> bool:
    if sig.family is None:
        return False
    if sig.cls == "motor_protection" and component_family == "overload_relay":
        return True  # "הגנת מנוע": a motor protection breaker, or a thermal relay drawn as one
    return component_family in ACCEPTS.get(sig.family, frozenset({sig.family}))


def _positions(v: Any) -> frozenset[str]:
    return frozenset(str(v).replace(" ", "").split("-"))


def _equal(key: str, a: Any, b: Any) -> bool:
    if key == "positions":
        return _positions(a) == _positions(b)
    return same(a, b)


def _within(ranged: dict[str, Any], current: float) -> bool:
    return float(ranged["range_min_a"]) - 1e-6 <= current <= float(ranged["range_max_a"]) + 1e-6


def compare(sig: Signature, c: DrawnComponent) -> Pair | None:
    """The pair's tier and the values that disagree, or None when the family doesn't match."""
    if not accepts(sig, c.family):
        return None
    tier = EXACT
    if sig.cls != UNTYPED and c.cls not in (UNTYPED, "", sig.cls):
        if (sig.cls in DISTINCT_CLASSES or c.cls in DISTINCT_CLASSES) and {sig.cls, c.cls} <= BREAKER_CLASSES:
            return None
        tier = LOOSE
    if c.family != sig.family:
        tier = LOOSE
    conflicts: list[str] = []
    agreed = 0
    values = sig.values
    for key, v in values.items():
        if key in c.values:
            if _equal(key, v, c.values[key]):
                agreed += 1
            else:
                conflicts.append(key)
    for ranged, other in ((values, c.values), (c.values, values)):
        amps = other.get("current_a")
        has_range = "range_min_a" in ranged and "range_max_a" in ranged
        if has_range and amps is not None and not _within(ranged, float(amps)):
            conflicts.append("current_a")
    if "poles" in values and "poles" in c.values and bool(values.get("neutral")) != bool(c.values.get("neutral")):
        conflicts.append("neutral")
    if sig.current_max_a is not None:
        tier = LOOSE
        current = c.values.get("current_a")
        if current is not None and float(current) > sig.current_max_a + 1e-6:
            conflicts.append("current_a")
    dims = c.values.get("dims_mm")
    if sig.family == ENCLOSURE and sig.dims_mm and dims and tuple(sorted(int(x) for x in dims)) != sig.dims_mm:
        conflicts.append("dims_mm")
    return Pair(0, c.component_id, tier, list(dict.fromkeys(conflicts)), agreed)


@dataclass
class Assignment:
    taken: dict[tuple[int, str], int]  # (line, component) → units
    pairs: dict[tuple[int, str], Pair]
    line_left: dict[int, Decimal | None]  # None: the line's quantity was not read
    component_left: dict[str, int]

    def absorbed(self, line: int) -> list[tuple[str, int]]:
        return [(c, n) for (ln, c), n in self.taken.items() if ln == line and n]

    def lines_of(self, component: str) -> list[tuple[int, int]]:
        return [(ln, n) for (ln, c), n in self.taken.items() if c == component and n]


def assign(lines: list[tuple[int, Signature, Decimal | None]], components: list[DrawnComponent]) -> Assignment:
    """`lines`: (index, signature, quantity). A line with no quantity read takes what it matches, and no quantity
    difference is reported for it."""
    pairs: dict[tuple[int, str], Pair] = {}
    for index, sig, _ in lines:
        for c in components:
            p = compare(sig, c)
            if p is not None:
                p.line = index
                pairs[(index, c.component_id)] = p
    good = [p for p in pairs.values() if not p.near]
    per_component: dict[str, int] = defaultdict(int)
    per_line: dict[int, int] = defaultdict(int)
    for p in good:
        per_component[p.component] += 1
        per_line[p.line] += 1
    line_left: dict[int, Decimal | None] = {i: q for i, _, q in lines}
    component_left = {c.component_id: c.quantity for c in components}
    taken: dict[tuple[int, str], int] = {}
    for p in sorted(good, key=lambda p: (p.tier, -p.agreed, per_component[p.component], per_line[p.line], p.line)):
        left = line_left[p.line]
        have = component_left[p.component]
        n = have if left is None else min(have, int(left))
        if n <= 0:
            continue
        taken[(p.line, p.component)] = taken.get((p.line, p.component), 0) + n
        component_left[p.component] -= n
        if left is not None:
            line_left[p.line] = left - n
    return Assignment(taken, pairs, line_left, component_left)
