"""Stage 5's flow for one drawing (05 §5), per component:

1. Normalize (5.1): the values stage 4 read become `Need`s, each with its `match_mode` and source; an aux contact's
   contact numbers become NO / NC ("21/22" is NC); a moulded-case breaker's setting is checked against each candidate's
   range.
2. An explicit SKU (5.2) or series (5.2.1) in the component's text. A SKU whose attributes contradict the drawing, or a
   series that fixes a value the text contradicts (FNV: "3X6A" with S204M), is a `conflict`, and nothing is chosen,
   unless the match memory settles it.
3. The brand and series (5.4): written beside the component, the notes (the panel's first), the customer, the
   factory, any brand the factory has a price for. "או ש"ע" lets the factory's brand stand in, marked.
4. Fill-in (5.5): the series' fixed values, then notes, the factory's default, the system default, only where the
   schema allows a default. Current and poles never (05 §4.4).
5. Inference from the circuit (5.5.1, `inference.py`).
6. The signature, then the memory (5.3): this customer's, then the factory's. Never over a SKU, series or brand the
   drawing names, and never with an electrical value the drawing contradicts.
7. The query, its relaxation and ranking (5.6, `query.py`), the decision rules (5.7) and the agent (5.8, `agent.py`).
8. Alternatives (5.9), a kit's parts and an accessory's fit (5.9.1), the confidence (6.3), the status (7), the
   warnings (8) and the reason in Hebrew.

Components with the same inputs (signature, brand, explicit texts, parents' series) are matched once and share the
result (05 §5, §9): the same signature in a drawing always gets the same SKU. Accessories go last, after the devices
they sit on.
"""

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from konboro.contracts.common import StageIssue
from konboro.contracts.matching import (
    Alternative,
    BrandDecision,
    BundleLine,
    ComponentMatch,
    MatchStats,
    Substitution,
    UsedAttribute,
)
from konboro.contracts.merge import Component

from ..association.grammar import parse
from ..association.schemas import NEVER_DEFAULT, Attribute, Schemas
from ..bom.terms import UNTYPED
from . import agent, inference, text
from .agent import Ask
from .catalog import Catalog, Item, norm_sku, norm_token
from .config import DEFAULT, SYSTEM_DEFAULTS, MatchingConfig
from .factory import Factory
from .notes import Notes
from .query import BrandPlan, Need, Ranked, alternatives_pool, check, decide, passes, query, rank, unknown_differences

FILLED = inference.FILLED
ACCESSORY_FAMILIES = frozenset({"aux_contact", "shunt_trip"})
_SIG_NAMES = {"breaking_capacity_ka": "bc_ka"}
_CONTACTS = re.compile(r"^([1-4])\d/[1-4]\d$")
_WORD_TAG = re.compile(r"^[A-Za-z]{3,}$")


@dataclass
class Inputs:
    catalog: Catalog
    factory: Factory
    schemas: Schemas
    notes: Notes
    components: dict[str, Component]  # every component of the drawing, for the circuit and the parents
    ask: Ask | None = None
    cfg: MatchingConfig = DEFAULT


@dataclass
class Result:
    matches: list[ComponentMatch]
    auxiliary: list[str]
    stats: MatchStats
    issues: list[StageIssue] = field(default_factory=list)
    llm_calls: int = 0


# --- 1. normalize -----------------------------------------------------------------------------------------------------


def _contacts(value: Any) -> Any:
    """13/14 and 33/34 are NO, 21/22 and 41/42 NC (05 §5.5.1); the catalog keeps NO, NC, NO+NC."""
    m = _CONTACTS.match(str(value))
    if m is None:
        return value
    return "NO" if m.group(1) in ("1", "3") else "NC"


def normalize(component: Component, attrs: dict[str, Attribute]) -> dict[str, Need]:
    have: dict[str, Need] = {}
    for name, a in component.attributes.items():
        if a.value is None or a.source is None:
            continue
        schema = attrs.get(name)
        if schema is None:
            continue
        v = _contacts(a.value) if name == "contacts" else a.value
        if name == "setting_a":  # 05 §5.5.1: the setting lies within the candidate's range
            have[name] = Need(name, v, "contains", a.source, False)
            continue
        have[name] = Need(name, v, schema.match_mode, a.source, True)
    return have


def signature(component: Component, cls: str | None, needs: dict[str, Need], attrs: dict[str, Attribute]) -> str:
    """05 §5.1 item 3, the shape of 05 §6.1: "circuit_breaker|mcb|current_a=16|poles=3|curve=C|bc_ka>=6"; a stated
    preference as `name:value` ("selector_switch|selector_switch|positions:1-0-2")."""
    parts = [component.family, cls or component.symbol_class]
    order = [*attrs, *(n for n in needs if n not in attrs)]
    for name in order:
        n = needs.get(name)
        if n is None:
            continue
        # a stated preference ("1-0-2" on a selector) changes the choice, so it is part of the signature too
        op = {"exact": "=", "gte": ">=", "lte": "<=", "contains": "~", "prefer": ":"}[n.mode]
        v = text.number(n.value) if not isinstance(n.value, bool) else str(n.value).lower()
        parts.append(f"{_SIG_NAMES.get(name, name)}{op}{v}")
    return "|".join(parts)


# --- 2. explicit sku or series ----------------------------------------------------------------------------------------


@dataclass
class Explicit:
    sku_item: Item | None = None
    replaced: bool = False
    series_items: list[Item] | None = None
    token: str | None = None
    conflicts: list[tuple[str, Any, Any]] = field(default_factory=list)  # (attribute, drawing, item or series)
    unknown_tokens: list[str] = field(default_factory=list)


def _tokens(component: Component, brands: frozenset[str]) -> list[str]:
    out: list[str] = []
    for t in component.explicit_texts:
        for r in parse(t):
            if r.key == "model_token":
                token = norm_token(str(r.value), brands)
                if token not in out:
                    out.append(token)
    return out


def explicit(component: Component, have: dict[str, Need], catalog: Catalog) -> Explicit:
    out = Explicit()
    strict = [n for n in have.values() if n.strict]
    for t in component.explicit_texts:
        items = [i for i in catalog.by_sku.get(norm_sku(t), []) if i.family == component.family]
        if not items:
            continue
        item = items[0]
        active = catalog.active(item)
        out.replaced = active is not None and active.id != item.id
        out.sku_item = active or item
        out.conflicts = [
            (n.name, n.value, out.sku_item.attributes.get(n.name)) for n in strict if check(out.sku_item, n) is False
        ]
        return out
    for token in _tokens(component, catalog.brands):
        items = [i for i in catalog.by_token.get(token, []) if i.family == component.family]
        if not items:
            out.unknown_tokens.append(token)
            continue
        out.series_items, out.token = items, token
        for name, value in fixed(items).items():
            n = have.get(name)
            if n is not None and n.strict and check(items[0], n) is False:
                out.conflicts.append((name, n.value, value))
        return out
    return out


def fixed(items: list[Item]) -> dict[str, Any]:
    """What a series fixes: the values every one of its items has the same (05 §5.2.1 item 1)."""
    names = set.intersection(*(set(i.attributes) for i in items)) if items else set()
    out = {}
    for name in sorted(names):
        values = {repr(i.attributes[name]) for i in items}
        if len(values) == 1:
            out[name] = items[0].attributes[name]
    return out


# --- 3. brand ---------------------------------------------------------------------------------------------------------


def brand_plan(
    component: Component, inp: Inputs, series_items: list[Item] | None
) -> tuple[BrandPlan, str | None, list[str]]:
    """05 §5.4. Returns the plan, the brand the drawing or the customer asked for (the memory's `brand_context`), and
    the note texts it used."""
    family = component.family
    factory = inp.factory
    if series_items:
        brand = Counter(i.brand for i in series_items).most_common(1)[0][0]
        series = Counter(i.series for i in series_items if i.brand == brand).most_common(1)[0][0]
        return BrandPlan(brand, "drawing", series), brand, []
    hint = _known_brand(component.brand_hint, inp.catalog)
    if hint:
        return BrandPlan(hint, "drawing", _series(factory, family, hint)), hint, []
    for rule in inp.notes.applying(family, component.panel_id):
        if rule.brand is None:
            continue
        own = factory.preferred_brand(family)
        if rule.equivalent and own and own != rule.brand:
            return BrandPlan(own, "notes_equivalent", _series(factory, family, own), True), rule.brand, [rule.text]
        return BrandPlan(rule.brand, "notes", _series(factory, family, rule.brand)), rule.brand, [rule.text]
    customer = factory.customer_brand(family)
    if customer:
        return BrandPlan(customer, "customer_preference", _series(factory, family, customer)), customer, []
    own = factory.preferred_brand(family)
    if own:
        return BrandPlan(own, "tenant_preference", _series(factory, family, own)), None, []
    return BrandPlan(None, "priced_brand"), None, []


def _known_brand(hint: str | None, catalog: Catalog) -> str | None:
    if not hint:
        return None
    for b in catalog.brands:
        if b.casefold() == hint.casefold():
            return b
    return hint  # a brand the catalog has none of: the query relaxes from it, marked as a substitution


def _series(factory: Factory, family: str, brand: str) -> str | None:
    own = factory.preferred_brand(family)
    return factory.series.get(family) if own == brand else None


# --- 4–5. fill-in and inference ---------------------------------------------------------------------------------------


def fill(component: Component, have: dict[str, Need], attrs: dict[str, Attribute], inp: Inputs) -> dict[str, Need]:
    """05 §5.5: notes (the panel's first), the factory's default, the system default. Only where the schema allows a
    default, never current or poles."""
    out = dict(have)
    family = component.family
    tenant = inp.factory.attribute_defaults.get(family, {})
    system = SYSTEM_DEFAULTS.get(family, {})
    rules = inp.notes.applying(family, component.panel_id)
    for name, a in attrs.items():
        if name in out or not a.default_allowed or name in NEVER_DEFAULT:
            continue
        rule = next((r for r in rules if name in r.attributes), None)
        if rule is not None:
            out[name] = Need(name, rule.attributes[name], a.match_mode, "notes", False, rule.text)
        elif name in tenant:
            out[name] = Need(name, tenant[name], a.match_mode, "tenant_default", False)
        elif name in system:
            out[name] = Need(name, system[name], a.match_mode, "system_default", False)
    return out


def _upstream(component: Component, inp: Inputs) -> Component | None:
    ctx = component.circuit_context
    if ctx is None:
        return None
    if ctx.upstream_component_id and ctx.upstream_component_id in inp.components:
        return inp.components[ctx.upstream_component_id]
    if ctx.upstream_designator:
        for c in inp.components.values():
            if c.panel_id == component.panel_id and ctx.upstream_designator in c.designators:
                return c
    return None


# --- the match --------------------------------------------------------------------------------------------------------


@dataclass
class Decided:
    """What a cache key decides; the component's own confidence is applied per component."""

    match: ComponentMatch
    base: float  # match confidence × penalties (05 §6.3)
    yellow: bool
    llm: bool


def _used(needs: dict[str, Need]) -> dict[str, UsedAttribute]:
    return {n.name: UsedAttribute(value=n.value, source=n.source, note=n.note) for n in needs.values()}  # type: ignore[arg-type]


def _alternatives(
    chosen: Item, pool: list[Ranked], inp: Inputs, attrs: dict[str, Attribute], first: list[Item] | None = None
) -> list[Alternative]:
    names = tuple(attrs)
    out: list[Alternative] = []
    seen = {chosen.id}
    for item in [*(first or []), *(r.item for r in pool)]:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(
            Alternative(
                sku=item.sku,
                manufacturer=item.brand,
                diff=text.difference(chosen, item, names),
                has_cost_price=inp.factory.has_cost(item),
            )
        )
        if len(out) == inp.cfg.alternatives:
            break
    return out


def _bundle(item: Item, component: Component, inp: Inputs) -> list[BundleLine]:
    written = " ".join(component.explicit_texts)
    return [
        BundleLine(
            sku=k.part.sku,
            manufacturer=k.part.brand,
            description=k.part.description,
            quantity=k.quantity,
            reason=k.reason,
            has_cost_price=inp.factory.has_cost(k.part),
        )
        for k in inp.catalog.kits.get(item.id, [])
        if not k.when_text or k.when_text in written
    ]


def _empty(
    component: Component,
    status: str,
    needs: dict[str, Need],
    sig: str | None,
    reason: str,
    warnings: list[str],
    missing: list[str] | None = None,
    alternatives: list[Alternative] | None = None,
    brand: BrandDecision | None = None,
) -> ComponentMatch:
    return ComponentMatch(
        component_id=component.component_id,
        status=status,  # type: ignore[arg-type]
        chosen_sku=None,
        catalog_item=None,
        method=None,
        match_confidence=0.0,
        confidence=0.0,
        attributes_used=_used(needs),
        defaulted_attributes=[n.name for n in needs.values() if n.source in FILLED],
        brand_decision=brand,
        alternatives=alternatives or [],
        reason=reason,
        missing_attributes=missing or [],
        warnings=warnings,
        signature=sig,
    )


def _parents(component: Component, inp: Inputs) -> list[Component] | None:
    if component.family not in ACCESSORY_FAMILIES or not component.parent_designators:
        return None
    found = [
        c
        for c in inp.components.values()
        if c.panel_id == component.panel_id
        and c.component_id != component.component_id
        and set(c.designators) & set(component.parent_designators)
    ]
    return found or None


@dataclass
class Prepared:
    """Everything a decision depends on, before it is taken: the cache key comes from it (05 §5, §9)."""

    component: Component
    attrs: dict[str, Attribute]
    needs: dict[str, Need]
    ex: Explicit
    plan: BrandPlan
    requested: str | None
    note_texts: list[str]
    warnings: list[str]
    cls: str | None
    sig: str
    parents: list[Component] | None
    parent_fit: tuple[tuple[str, str], ...]
    parent_statuses: frozenset[str]

    kit_phrases: tuple[str, ...] = ()
    has_text: bool = False

    @property
    def key(self) -> tuple[Any, ...]:
        """What the text found, not the text itself: one signature in one context gets one SKU (05 §10: 100%)."""
        ex = self.ex
        return (
            self.sig,
            self.plan,
            ex.sku_item.id if ex.sku_item else None,
            ex.token,
            tuple(ex.conflicts),
            self.component.brand_hint,
            self.kit_phrases,
            self.has_text,
            self.parents is not None,
            self.parent_fit,
            self.parent_statuses,
        )


def prepare(component: Component, inp: Inputs, done: dict[str, ComponentMatch], items: dict[str, str]) -> Prepared:
    """Steps 1–6's inputs for one component: normalized, explicit texts looked up, brand planned, filled in, inferred,
    signed. `items` holds the catalog item each matched component got (for an accessory's parents)."""
    catalog, factory = inp.catalog, inp.factory
    attrs = {a.name: a for a in inp.schemas.attributes(component.family)}
    have = normalize(component, attrs)
    ex = explicit(component, have, catalog)
    warnings: list[str] = []
    if ex.unknown_tokens and ex.series_items is None and ex.sku_item is None:
        warnings.append("catalog_gap")  # 05 §5.2.1 item 6: the catalog team's work list
    series_ok = ex.series_items if ex.series_items is not None and not ex.conflicts else None
    plan, requested, note_texts = brand_plan(component, inp, series_ok)
    needs = dict(have)
    if series_ok:
        for name, value in fixed(series_ok).items():
            if name in attrs and name not in needs:
                needs[name] = Need(name, value, attrs[name].match_mode, "series", False, f"לפי הדגם {ex.token}")
    needs = fill(component, needs, attrs, inp)
    tops = inference.class_tops(catalog.top_current)
    untyped = component.symbol_class in (UNTYPED, "", None) or inference.outranged(
        component, needs, tops, factory.inference_off
    )
    inferred = inference.infer(
        component, needs, _upstream(component, inp), inp.notes, factory.inference_off, untyped, tops
    )
    for n in inferred.needs:  # a unit slip read from the drawing's text replaces a default (BUG-052)
        if n.name not in needs or needs[n.name].source in FILLED:
            needs[n.name] = n
    warnings += inferred.warnings
    if inferred.needs:
        warnings.append("inferred_attribute")
    cls = inferred.symbol_class or (component.symbol_class if not untyped else None)
    sig = signature(component, cls, needs, attrs)
    parents = _parents(component, inp)
    fit: set[tuple[str, str]] = set()
    statuses: set[str] = set()
    for p in parents or []:
        if p.component_id in done:
            statuses.add(done[p.component_id].status)
        item = catalog.items.get(items.get(p.component_id, ""))
        if item is not None:
            fit.add((item.brand, item.series or ""))
    written = " ".join(component.explicit_texts)
    kit_texts = {k.when_text for ks in catalog.kits.values() for k in ks if k.when_text}
    phrases = sorted(t for t in kit_texts if t in written)
    # a tag like L1 or F3 says nothing about the product; one that is a word (EMS: an emergency stop) may
    beside = [t for t in component.explicit_texts if t not in component.designators or _WORD_TAG.match(t)]
    return Prepared(
        component,
        attrs,
        needs,
        ex,
        plan,
        requested,
        note_texts,
        warnings,
        cls,
        sig,
        parents,
        tuple(sorted(fit)),
        frozenset(statuses),
        tuple(phrases),
        bool(beside) or bool(inp.notes.applying(component.family, component.panel_id)),
    )


def decide_prepared(pr: Prepared, inp: Inputs) -> Decided:
    """The decision, with the brand context a memory written for it later belongs to (the chat's "לזכור", 08 §7.4):
    the customer's brand when the customer's preference chose it, so the memory is recalled for that customer's
    drawings in the same context (05 §5.3); otherwise none. A brand the drawing or its notes name wins over the memory
    anyway, so a memory under it would never apply; under none it fills in when the next drawing names no brand."""
    d = _decide(pr, inp)
    context = pr.requested if pr.plan.source == "customer_preference" else None
    return replace(d, match=d.match.model_copy(update={"brand_context": context}))


def _decide(pr: Prepared, inp: Inputs) -> Decided:
    component, attrs, needs, ex, plan = pr.component, pr.attrs, pr.needs, pr.ex, pr.plan
    requested, note_texts, warnings, cls, sig = pr.requested, pr.note_texts, list(pr.warnings), pr.cls, pr.sig
    parents, parent_fit = pr.parents, pr.parent_fit
    cfg, catalog, factory = inp.cfg, inp.catalog, inp.factory
    family = component.family
    need_list = list(needs.values())
    brand = BrandDecision(brand=plan.brand, source=plan.source)

    # required values nothing gave (05 §5.5 last rule): current and poles, a CT's primary, an overload's range
    covered = set(needs) | ({"range_min_a", "range_max_a"} if "load_current_a" in needs else set())
    if {"range_min_a", "range_max_a"} <= set(needs):  # a motor-protection breaker is its range, not a current
        covered.add("current_a")
    must = [a.name for a in attrs.values() if a.required and not a.default_allowed and a.name not in covered]
    if must:
        names = ", ".join(text.NAMES.get(n, n) for n in must)
        reason = f"לא כתוב {names} ליד הרכיב. בחרו ידנית"
        match = _empty(
            component, "unmatched", needs, sig, reason, ["missing_required_attribute", *warnings], must, brand=brand
        )
        return Decided(match, 0.0, False, False)
    open_required = [a.name for a in attrs.values() if a.required and a.name not in covered]

    # 2. an explicit sku
    if ex.sku_item is not None:
        item = ex.sku_item
        if ex.conflicts:
            return Decided(_conflict(component, inp, attrs, needs, cls, sig, ex, brand), 0.0, False, False)
        own = factory.preferred_brand(family)
        first: list[Item] = []
        if own and own != item.brand:  # 05 §5.2 item 5: the factory's own brand, offered
            exact = [
                Need(k, v, "exact", "drawing", True)
                for k, v in item.attributes.items()
                if attrs.get(k) and attrs[k].match_mode == "exact"
            ]
            first = [i for i in alternatives_pool(catalog, family, item.symbol_class, exact) if i.brand == own][:1]
        pool = rank(alternatives_pool(catalog, family, item.symbol_class, need_list), need_list, plan, factory, family)
        w = [*warnings, *(["discontinued_replaced"] if ex.replaced else [])]
        reason = f'המק"ט {item.sku} כתוב בשרטוט.' + (' המק"ט הופסק, נבחר המחליף שלו.' if ex.replaced else "")
        return _matched(
            component,
            inp,
            attrs,
            needs,
            item,
            "explicit_sku",
            cfg.explicit_sku,
            brand,
            None,
            [],
            w,
            reason,
            sig,
            pool,
            first,
        )

    # a series that contradicts the text: the memory may settle it, else a conflict
    restrict: list[Item] | None = ex.series_items if ex.series_items is not None and not ex.conflicts else None

    # 6. memory
    remembered = factory.recall(sig, requested)
    if remembered is not None:
        items = sorted(
            catalog.by_sku.get(norm_sku(remembered.sku), []), key=lambda i: i.brand != (requested or i.brand)
        )
        mem = catalog.active(items[0]) if items else None
        named_brand = plan.source in ("drawing", "notes") and plan.brand
        if (
            mem is not None
            and mem.family == family
            and passes(mem, [n for n in need_list if n.strict])[0]
            and not (named_brand and mem.brand != plan.brand and restrict is None)
            and (restrict is None or mem.id in {i.id for i in restrict})
        ):
            pool = rank(alternatives_pool(catalog, family, cls, need_list), need_list, plan, factory, family)
            reason = "נבחר לפי זיכרון ההתאמות"
            if ex.conflicts:
                reason += ": " + _conflict_text(ex, f"הדגם {ex.token}") + f" נבחר {mem.sku}, כמו שנבחר בעבר."
            else:
                reason += "."
            brand = BrandDecision(brand=mem.brand, source="memory")
            # stage 6 shows a settled conflict as a note, not a warning (S21 decision 4)
            settled = [*warnings, "attribute_conflict_resolved"] if ex.conflicts else warnings
            return _matched(
                component, inp, attrs, needs, mem, "memory", cfg.memory, brand, None, [], settled, reason, sig, pool
            )
    if ex.conflicts:
        return Decided(_conflict(component, inp, attrs, needs, cls, sig, ex, brand), 0.0, False, False)

    # accessories sit on a device: its series decides which fit (05 §5.9.1)
    if parents is not None:
        if pr.parent_statuses != {"matched"} or not parent_fit:
            reason = "המכשיר שעליו מותקן האביזר לא הותאם. בחרו קודם את המכשיר"
            return Decided(
                _empty(component, "ambiguous", needs, sig, reason, warnings, ["parent"], brand=brand), 0.0, True, False
            )
        restrict = [
            i
            for i in catalog.by_family.get(family, [])
            if all(fit in catalog.fits.get(i.id, set()) for fit in parent_fit)
        ]
        plan = BrandPlan(parent_fit[0][0], "parent", None)
        brand = BrandDecision(brand=plan.brand, source="parent")

    # 7. the query
    found = query(catalog, factory, family, cls, need_list, plan, restrict)
    if not found.items and restrict is not None and parents is None:  # nothing in the series: the brand's others
        found = query(catalog, factory, family, cls, need_list, replace(plan, series=None), None)
        found.relaxations.insert(0, "series_relaxed")
    if not found.items:
        what = text.describe(family, cls, "", None, {n.name: n.value for n in need_list if n.mode != "contains"})
        w = ["no_catalog_match", *(["catalog_gap"] if found.gaps else []), *warnings]
        reason = f"לא מצאנו בקטלוג {' '.join(what.split())}"
        return Decided(_empty(component, "unmatched", needs, sig, reason, w, brand=brand), 0.0, False, False)
    ranked = rank(found.items, need_list, plan, factory, family)
    filtering = frozenset(a.name for a in attrs.values() if a.match_mode in ("exact", "gte", "lte"))
    how = decide(ranked, need_list, factory.tie_break, filtering)
    pool = rank(alternatives_pool(catalog, family, cls, need_list), need_list, plan, factory, family)
    substitution = None
    if found.substituted or plan.equivalent:
        requested_brand = requested if plan.equivalent else plan.brand
        said = {"customer_preference": "הלקוח ביקש", "tenant_preference": "המותג המועדף"}.get(plan.source, "בשרטוט")
        substitution = (requested_brand, f"{said}: {requested_brand or '—'}")
    method_conf = {"rules_unique": cfg.rules_unique, "rules_ranked": cfg.rules_ranked}
    in_series = (
        ex.series_items is not None and restrict is ex.series_items and "series_relaxed" not in found.relaxations
    )
    if how in method_conf:
        item = ranked[0].item
        method: str = how
        reason = "מוצר אחד בקטלוג מתאים לתכונות." if how == "rules_unique" else "התאמה לפי תכונות."
        if in_series:  # 05 §5.2.1 item 5
            method, reason = "explicit_series", f"הדגם {ex.token} כתוב בשרטוט. " + reason
            method_conf[method] = cfg.explicit_series
        return _matched(
            component,
            inp,
            attrs,
            needs,
            item,
            method,
            method_conf[method],
            brand,
            substitution,
            found.relaxations,
            warnings,
            reason,
            sig,
            pool,
            notes=note_texts,
        )
    if how == "llm" and not pr.has_text:  # nothing written beside it but its tag: nothing for the agent to read
        how = "missing_info"
    if how == "missing_info" or inp.ask is None:
        every = frozenset(ranked[0].item.attributes) | frozenset(ranked[1].item.attributes)
        missing = (
            unknown_differences(ranked[0].item, ranked[1].item, need_list, filtering)
            or unknown_differences(ranked[0].item, ranked[1].item, need_list, every)
            or open_required
        )
        names = ", ".join(text.NAMES.get(n, n) for n in missing) or "פרט"
        reason = f"כמה מוצרים מתאימים, וחסר {names} כדי לבחור. נבחר זמנית {ranked[0].item.sku}"
        return _ambiguous(
            component,
            inp,
            attrs,
            needs,
            ranked,
            brand,
            substitution,
            found.relaxations,
            warnings,
            reason,
            sig,
            missing,
            pool,
        )
    prefs = [f"preferred brand: {plan.brand}"] if plan.brand else []
    if plan.series:
        prefs.append(f"preferred series: {plan.series}")
    notes = [r.text for r in inp.notes.applying(family, component.panel_id)]
    answer = agent.decide(inp.ask, component, need_list, [r.item for r in ranked], notes, prefs, cfg)
    if answer.item is None or answer.confidence < cfg.agent_min_confidence:
        reason = answer.reason or "המודל לא הכריע בין המוצרים"
        missing = answer.missing or open_required
        decided = _ambiguous(
            component,
            inp,
            attrs,
            needs,
            ranked,
            brand,
            substitution,
            found.relaxations,
            warnings,
            reason,
            sig,
            missing,
            pool,
            "llm",
        )
        decided.match = decided.match.model_copy(update={"llm_decision": answer.answer})
        decided.llm = True
        return decided
    decided = _matched(
        component,
        inp,
        attrs,
        needs,
        answer.item,
        "llm",
        answer.confidence,
        brand,
        substitution,
        found.relaxations,
        warnings,
        f"הכרעת מודל: {answer.reason}",
        sig,
        pool,
        notes=note_texts,
    )
    decided.match = decided.match.model_copy(update={"llm_decision": answer.answer})
    decided.llm = True
    return decided


def _conflict_text(ex: Explicit, what: str) -> str:
    name, drawing, other = ex.conflicts[0]
    return f"בשרטוט כתוב {text.value(name, drawing)}, אבל {what} הוא של {text.value(name, other)}."


def _conflict(
    component: Component,
    inp: Inputs,
    attrs: dict[str, Attribute],
    needs: dict[str, Need],
    cls: str | None,
    sig: str,
    ex: Explicit,
    brand: BrandDecision,
) -> ComponentMatch:
    """05 §5.2 item 3, §5.2.1 item 4: nothing is chosen, red, and both readings are offered: the best item for what
    the text says, and the SKU or series' own."""
    what = f'המק"ט {ex.sku_item.sku}' if ex.sku_item is not None else f"הדגם {ex.token}"
    reason = _conflict_text(ex, what) + " בחרו ידנית"
    need_list = list(needs.values())
    by_text = rank(
        alternatives_pool(inp.catalog, component.family, cls, need_list),
        need_list,
        BrandPlan(None, "-"),
        inp.factory,
        component.family,
    )
    conflicting = {c[0] for c in ex.conflicts}
    rest = [n for n in need_list if n.name not in conflicting]
    by_model = [ex.sku_item] if ex.sku_item is not None else [i for i in (ex.series_items or []) if passes(i, rest)[0]]
    alts = [
        *(
            Alternative(
                sku=r.item.sku,
                manufacturer=r.item.brand,
                diff=f"לפי הטקסט: {r.item.description}",
                has_cost_price=inp.factory.has_cost(r.item),
            )
            for r in by_text[:2]
        ),
        *(
            Alternative(
                sku=i.sku,
                manufacturer=i.brand,
                diff=f"לפי {what}: {i.description}",
                has_cost_price=inp.factory.has_cost(i),
            )
            for i in by_model[:1]
        ),
    ]
    return _empty(component, "conflict", needs, sig, reason, ["attribute_conflict"], sorted(conflicting), alts, brand)


def _penalties(needs: dict[str, Need], substituted: bool, cfg: MatchingConfig) -> float:
    p = 1.0
    for n in needs.values():
        if n.source in ("notes", "tenant_default"):
            p *= cfg.defaulted_penalty
        elif n.source == "inferred":
            p *= cfg.inferred_penalty
    if substituted:
        p *= cfg.substitution_penalty
    return p


def _reason(
    base: str,
    needs: dict[str, Need],
    substitution: tuple[str | None, str] | None,
    chosen: Item,
    relaxations: list[str],
    notes: list[str],
) -> str:
    parts = [base]
    for n in needs.values():
        if n.source in FILLED:
            where = text.SOURCES[n.source]
            parts.append(
                f"{text.NAMES.get(n.name, n.name)} לא נכתב בשרטוט והושלם לפי {where} ({text.value(n.name, n.value)})."
            )
        elif n.source == "inferred" and n.note:
            parts.append(f"{n.note}.")
    if "series_relaxed" in relaxations:
        parts.append("אין מוצר מתאים בסדרה המועדפת, נבחרה סדרה אחרת.")
    if substitution is not None:
        parts.append(f"{substitution[1]}. נבחר: {chosen.brand}.")
    if notes:
        parts.append(f'לפי ההערה: "{notes[0]}".')
    return " ".join(parts)


def _matched(
    component: Component,
    inp: Inputs,
    attrs: dict[str, Attribute],
    needs: dict[str, Need],
    item: Item,
    method: str | None,
    match_conf: float,
    brand: BrandDecision,
    substitution: tuple[str | None, str] | None,
    relaxations: list[str],
    warnings: list[str],
    reason: str,
    sig: str,
    pool: list[Ranked],
    first: list[Item] | None = None,
    notes: list[str] | None = None,
    status: str = "matched",
    missing: list[str] | None = None,
) -> Decided:
    cfg = inp.cfg
    w = list(warnings)
    if any(n.source in FILLED for n in needs.values()):
        w.append("defaulted_attribute")
    sub = None
    if substitution is not None:
        sub = Substitution(requested_brand=substitution[0], chosen_brand=item.brand, reason=substitution[1])
        w.append("substitution")
    has_cost = inp.factory.has_cost(item)
    if not has_cost:
        w.append("no_cost_price")
    base = match_conf * _penalties(needs, substitution is not None, cfg)
    yellow = status == "ambiguous" or any(
        x in w for x in ("inferred_attribute", "poles_cable_conflict", "breaker_type_inferred")
    )
    match = ComponentMatch(
        component_id=component.component_id,
        status=status,  # type: ignore[arg-type]
        chosen_sku=item.sku,
        catalog_item=item.snapshot(),
        method=method,  # type: ignore[arg-type]
        match_confidence=round(match_conf, 4),
        confidence=0.0,  # per component, below
        attributes_used=_used(needs),
        defaulted_attributes=[n.name for n in needs.values() if n.source in FILLED],
        brand_decision=BrandDecision(brand=item.brand, source=brand.source),
        substitution=sub,
        relaxations=relaxations,
        has_cost_price=has_cost,
        alternatives=_alternatives(item, pool, inp, attrs, first),
        bundle_lines=_bundle(item, component, inp),
        reason=_reason(reason, needs, substitution, item, relaxations, notes or []),
        missing_attributes=missing or [],
        warnings=list(dict.fromkeys(w)),
        signature=sig,
    )
    return Decided(match, base, yellow, False)


def _ambiguous(
    component: Component,
    inp: Inputs,
    attrs: dict[str, Attribute],
    needs: dict[str, Need],
    ranked: list[Ranked],
    brand: BrandDecision,
    substitution: tuple[str | None, str] | None,
    relaxations: list[str],
    warnings: list[str],
    reason: str,
    sig: str,
    missing: list[str],
    pool: list[Ranked],
    method: str | None = None,
) -> Decided:
    """05 §7: candidates, no decision. The first is kept as a provisional choice, yellow, so the line can be priced and
    the estimator picks from the alternatives (S20 decision)."""
    item = ranked[0].item
    first = [r.item for r in ranked[1 : inp.cfg.alternatives + 1]]
    return _matched(
        component,
        inp,
        attrs,
        needs,
        item,
        method,
        inp.cfg.rules_ranked,
        brand,
        substitution,
        relaxations,
        warnings,
        reason,
        sig,
        pool,
        first,
        status="ambiguous",
        missing=missing,
    )


def finish(component: Component, decided: Decided, cfg: MatchingConfig) -> ComponentMatch:
    """05 §6.3: the component's confidence × the match's, kept below green when the line must stay yellow."""
    m = decided.match
    if m.chosen_sku is None:
        return m.model_copy(update={"component_id": component.component_id})
    confidence = component.confidence * decided.base
    if decided.yellow:
        confidence = min(confidence, cfg.yellow_max)
    return m.model_copy(update={"component_id": component.component_id, "confidence": round(confidence, 4)})


def match_all(components: list[Component], inp: Inputs) -> Result:
    auxiliary = [c.component_id for c in components if c.family in inp.factory.auxiliary_families]
    todo = [c for c in components if c.family not in inp.factory.auxiliary_families]
    devices = [c for c in todo if not (c.family in ACCESSORY_FAMILIES and c.parent_designators)]
    accessories = [c for c in todo if c not in devices]
    cache: dict[tuple[Any, ...], Decided] = {}
    done: dict[str, ComponentMatch] = {}
    items: dict[str, str] = {}  # component id → catalog item id
    for c in [*devices, *accessories]:
        pr = prepare(c, inp, done, items)
        decided = cache.get(pr.key)
        if decided is None:
            decided = cache[pr.key] = decide_prepared(pr, inp)
        match = finish(c, decided, inp.cfg)
        done[c.component_id] = match
        item_id = item_of(match, inp.catalog)
        if item_id is not None:
            items[c.component_id] = item_id
    matches = [done[c.component_id] for c in todo]
    stats = MatchStats(
        components=len(components),
        signatures=len(cache),
        by_status=dict(sorted(Counter(m.status for m in matches).items())),
        by_method=dict(sorted(Counter(m.method or "none" for m in matches).items())),
        llm_signatures=sum(1 for d in cache.values() if d.llm),
        auxiliary=len(auxiliary),
    )
    issues: list[StageIssue] = []
    unmatched = sum(1 for m in matches if m.status in ("unmatched", "conflict"))
    if matches and unmatched / len(matches) > inp.cfg.high_unmatched_ratio:
        share = round(100 * unmatched / len(matches))
        issues.append(
            StageIssue(
                code="high_unmatched_ratio",
                severity="warning",
                message=f"{share}% מהרכיבים לא הותאמו לקטלוג. כנראה חסרים בקטלוג מותג או משפחה",
            )
        )
    return Result(matches, auxiliary, stats, issues)


def item_of(match: ComponentMatch, catalog: Catalog) -> str | None:
    """The catalog item a match chose (its snapshot keeps sku and manufacturer; the pair is unique)."""
    if match.catalog_item is None:
        return None
    for i in catalog.by_sku.get(norm_sku(match.catalog_item.sku), []):
        if i.brand == match.catalog_item.manufacturer and i.sku == match.catalog_item.sku:
            return i.id
    return None
