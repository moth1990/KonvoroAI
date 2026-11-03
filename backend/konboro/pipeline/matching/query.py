"""05 §5.6–5.7: the candidate query, its staged relaxation, the ranking, and the rules that decide without a model.

What a component needs is a set of `Need`s, one per attribute, each with how it compares (`match_mode`, 05 §4.4) and
whether it was read from the drawing. A value read from the drawing is strict: an item that does not state the
attribute fails (a `catalog_gap`, 05 §8). A value filled in (notes, a default, the circuit) applies only to items that
state the attribute, since a default for one class is not an attribute of another (a curve on a moulded-case
breaker).

`exact` is never relaxed. The relaxation only widens where the item may come from: the preferred series, then the
brand's other series, then the factory's allowed alternate brands, then any brand the factory has a price for.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from .catalog import Catalog, Item
from .factory import Factory

Mode = Literal["exact", "gte", "lte", "prefer", "contains"]
# 05 §4.4: an RCD's type compares by order (AC < A < F < B)
ORDERED = {"rcd_type": ("AC", "A", "F", "B")}
# "אלקטרוני" (stage 4's `electronic`) is any electronic trip unit; "LSI" written is that one
ELECTRONIC = frozenset({"LSI", "LSIG", "LI", "ELECTRONIC"})


@dataclass(frozen=True)
class Need:
    name: str  # for `contains`: the value lies within the item's range_min_a..range_max_a
    value: Any
    mode: Mode
    source: str  # a `UsedSource`
    strict: bool  # read from the drawing
    note: str | None = None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b) if isinstance(a, bool) and isinstance(b, bool) else False
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-9
    return str(a).strip().casefold() == str(b).strip().casefold()


def _order(name: str, v: Any) -> float | None:
    if name in ORDERED:
        scale = ORDERED[name]
        return float(scale.index(str(v).upper())) if str(v).upper() in scale else None
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def check(item: Item, need: Need) -> bool | None:
    """True or False; None when the item does not state the attribute."""
    if need.mode == "prefer":
        return True
    if need.mode == "contains":
        lo, hi = item.attributes.get("range_min_a"), item.attributes.get("range_max_a")
        if lo is None or hi is None:
            return None
        return float(lo) <= float(need.value) <= float(hi)
    have = item.attributes.get(need.name)
    if have is None:
        return None
    if need.mode == "exact":
        if need.name == "trip_unit" and str(need.value).casefold() == "electronic":
            return str(have).upper() in ELECTRONIC
        return _same(have, need.value)
    a, b = _order(need.name, have), _order(need.name, need.value)
    if a is None or b is None:
        return _same(have, need.value)
    return a >= b if need.mode == "gte" else a <= b


def passes(item: Item, needs: list[Need]) -> tuple[bool, list[str]]:
    """Whether the item passes every filter, and the strict attributes it fails only by not stating them."""
    gaps: list[str] = []
    ok = True
    for need in needs:
        result = check(item, need)
        if result is None:
            if need.strict:
                gaps.append(need.name)
                ok = False
        elif not result:
            return False, []
    return ok, gaps


@dataclass(frozen=True)
class BrandPlan:
    """05 §5.4's decision: the brand wanted and why, the series wanted, and whether the factory's brand may stand in."""

    brand: str | None
    source: str  # drawing, notes, customer_preference, tenant_preference, priced_brand
    series: str | None = None
    equivalent: bool = False  # "או ש"ע": the factory's own brand is preferred, the change still marked


@dataclass
class Found:
    items: list[Item]
    relaxations: list[str] = field(default_factory=list)
    substituted: bool = False
    gaps: list[str] = field(default_factory=list)


def _pool(catalog: Catalog, family: str, cls: str | None, restrict: list[Item] | None) -> list[Item]:
    if restrict is not None:
        return [i for i in restrict if i.status == "active"]
    items = catalog.by_family.get(family, [])
    classes = catalog.classes(family)
    if cls and cls in classes:
        items = [i for i in items if i.symbol_class in (cls, None)]
    return [i for i in items if i.status == "active"]


def query(
    catalog: Catalog,
    factory: Factory,
    family: str,
    cls: str | None,
    needs: list[Need],
    plan: BrandPlan,
    restrict: list[Item] | None = None,
) -> Found:
    """05 §5.6's filter and staged relaxation."""
    pool = _pool(catalog, family, cls, restrict)
    fit: list[Item] = []
    gaps: list[str] = []
    for item in pool:
        ok, missing = passes(item, needs)
        if ok:
            fit.append(item)
        elif missing:
            gaps.extend(n for n in missing if n not in gaps)
    priced = factory.priced_brands(catalog) or catalog.brands  # a factory with no prices yet: every brand
    steps: list[tuple[list[Item], list[str], bool]] = []
    if plan.brand is not None:
        if plan.series:
            steps.append(([i for i in fit if i.brand == plan.brand and i.series == plan.series], [], False))
            steps.append(([i for i in fit if i.brand == plan.brand], ["series_relaxed"], False))
        else:
            steps.append(([i for i in fit if i.brand == plan.brand], [], False))
        alternates = [b for b in factory.alternates(family) if b != plan.brand]
        steps.append(([i for i in fit if i.brand in alternates], ["substitution"], True))
        steps.append(([i for i in fit if i.brand in priced and i.brand != plan.brand], ["substitution"], True))
    else:
        steps.append(([i for i in fit if i.brand in priced], [], False))
    for items, relaxed, substituted in steps:
        if items:
            return Found(items, relaxed, substituted, gaps)
    return Found([], [], False, gaps)


def alternatives_pool(catalog: Catalog, family: str, cls: str | None, needs: list[Need]) -> list[Item]:
    """Everything that passes the filter, of any brand: where 05 §5.9's alternatives come from."""
    return [i for i in _pool(catalog, family, cls, None) if passes(i, needs)[0]]


# --- ranking (05 §5.6) and the decision (05 §5.7) -------------------------------------------------------------------


@dataclass(frozen=True)
class Ranked:
    item: Item
    key: tuple[Any, ...]  # (criterion 1, 2, 3, 4, 5), lower is better


def _distance(item: Item, need: Need) -> float:
    a, b = _order(need.name, item.attributes.get(need.name)), _order(need.name, need.value)
    if a is None or b is None:
        return 0.0
    return (a - b) / b if b else a  # relative: 10kA over 6kA is nearer than 25kA


def rank(items: list[Item], needs: list[Need], plan: BrandPlan, factory: Factory, family: str) -> list[Ranked]:
    stated = {n.name for n in needs}
    prefers = [n for n in needs if n.mode == "prefer"]
    gtes = [n for n in needs if n.mode == "gte"]
    alternates = factory.alternates(family)

    def key(item: Item) -> tuple[Any, ...]:
        prefer_hits = sum(1 for n in prefers if _same(item.attributes.get(n.name), n.value))
        # a feature nobody asked for (1P+N when the drawing says 1P): a worse fit, as a missed preference is
        unasked = sum(1 for k, v in item.attributes.items() if v is True and k not in stated)
        if plan.brand is None or item.brand == plan.brand:
            brand = 0
        elif item.brand in alternates:
            brand = 1 + alternates.index(item.brand)
        else:
            brand = 1 + len(alternates)
        series = 0 if not plan.series or item.series == plan.series else 1
        c3 = 0 if factory.has_cost(item) else 1
        c4 = tuple(round(_distance(item, n), 6) for n in gtes)
        c5: float = (
            float(factory.costs.get(item.id, 10**12))
            if factory.tie_break == "price"
            else -factory.usage.get(item.id, 0)
        )
        return (unasked - prefer_hits, (brand, series), c3, c4, c5)

    return sorted((Ranked(i, key(i)) for i in items), key=lambda r: (r.key, r.item.brand, r.item.sku))


Decision = Literal["rules_unique", "rules_ranked", "missing_info", "llm"]


def decide(ranked: list[Ranked], needs: list[Need], tie_break: str, exact: frozenset[str] = frozenset()) -> Decision:
    """05 §5.7: one candidate; a clear advantage on criterion 1 or 2; criteria 3–5 only when the factory breaks ties
    by frequency (the default) or price. Two candidates that differ in a filtering attribute the drawing didn't give
    (a curve nobody wrote) are told apart by the estimator, not by a price or a habit, and not by a model either:
    `missing_info` (S20 decision)."""
    if len(ranked) == 1:
        return "rules_unique"
    first, second = ranked[0], ranked[1]
    if first.key[:2] < second.key[:2]:
        return "rules_ranked"
    if unknown_differences(first.item, second.item, needs, exact):
        return "missing_info"
    if tie_break in ("frequency", "price") and first.key < second.key:
        return "rules_ranked"
    return "llm"


def unknown_differences(a: Item, b: Item, needs: list[Need], exact: frozenset[str]) -> list[str]:
    """The family's filtering attributes (`exact`, `gte`, `lte`) the two items differ in and the component doesn't
    give."""
    stated = {n.name for n in needs}
    names = sorted((set(a.attributes) & set(b.attributes) & exact) - stated)
    return [n for n in names if not _same(a.attributes[n], b.attributes[n])]
