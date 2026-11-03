"""Stage 6 in the eval (06 §10, S21): its findings end to end, and its rules on the labelled quote, which is correct
by definition, with and without errors put into it (06 §10.1, S21 decision 3).

The labelled quote is stage 5's labelled run (`labelled.py`): the components built from a golden drawing's labels,
matched by stage 5's own code. Its panels are the label's; the run's stage 1 gives the rest (the front views, notes,
the feed diagram and a designer's BOM), since those are read from the same drawing. No wire graph and no text spans:
the rules that need them are not measured here.

The injected set changes one thing at a time and runs the rules again, as 06 §10.1 lists them, plus one per rule
family where a reading error makes one naturally:
- `current_up`: an outgoing breaker read one size above the main ("63A under a 40A main");
- `qty_minus_2`: a quantity cut by 2, its last two tags with it;
- `sku_poles`: a SKU swapped for one with other poles;
- `deleted`: a component deleted;
- `load_current`: a load current (INC=) read above the device's rating;
- `poles_cable`: a breaker read as 1P on a 5-core cable;
- `designator_family`: one tag given to a device of another family.

A change is caught when a new warning or error points at it: a finding that was not there before, on the changed
component or its panel (a group finding that only lost a member does not count). A change is `applicable` only where
some rule can see it: a quantity or a deleted component needs a front view that shows its tags, or a designer's BOM;
a current needs a main device. The target (≥ 95%, 06 §10.2) is on the applicable ones; the others are reported.
"""

from dataclasses import dataclass

from konboro.contracts.intake import IntakeResult, Panel
from konboro.contracts.matching import ComponentMatch, MatchingResult
from konboro.contracts.merge import AttributeValue, Cable, CircuitContext, Component, MergeResult
from konboro.contracts.validation import ValidationResult
from konboro.pipeline.association.schemas import Schemas
from konboro.pipeline.validation.engine import validate
from konboro.pipeline.validation.model import DrawingModel, build
from konboro.pipeline.validation.pack import Pack

from .canonical import CanonFinding, CanonInjected

SIZES = (6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250, 320, 400, 500, 630, 800, 1000, 1250)
PER_KIND = 2  # targets per kind and drawing


def canon_findings(result: ValidationResult, merge_components: list[Component], pack: Pack) -> tuple[CanonFinding, ...]:
    tags = {c.component_id: c.designators for c in merge_components}
    return tuple(
        CanonFinding(
            rule_id=i.rule_id,
            severity=i.severity,
            source=i.source,
            category=i.category,
            designators=tuple(t for c in i.component_ids for t in tags.get(c, [])),
            bug_net=bool(pack.rules[i.rule_id].params.get("bug_net")) if i.rule_id in pack.rules else False,
        )
        for i in result.issues
    )


def validation_counts(result: ValidationResult) -> dict[str, int]:
    out = {f"severity_{s}": sum(1 for i in result.issues if i.severity == s) for s in ("error", "warning", "info")}
    out |= {
        "agent_calls": result.agent_calls,
        "agent_findings": sum(1 for i in result.issues if i.source == "agent"),
        "checks_run": len(result.checks_run),
        "checks_skipped": len(result.checks_skipped),
    }
    return out


@dataclass
class Labelled:
    intake: IntakeResult
    components: list[Component]
    matches: list[ComponentMatch]
    auxiliary: list[str]
    panel_names: list[str]
    schemas: Schemas
    classes: dict[str, str]

    def model(
        self, components: list[Component] | None = None, matches: list[ComponentMatch] | None = None
    ) -> DrawingModel:
        comps = self.components if components is None else components
        ms = self.matches if matches is None else matches
        panels = [Panel(panel_id=f"pnl_label{n}", name=name, page_ids=[]) for n, name in enumerate(self.panel_names)]
        intake = self.intake.model_copy(update={"panels": panels})
        merge = MergeResult(drawing_id=intake.drawing_id, components=comps, trace_id=intake.trace_id)
        matching = MatchingResult(
            drawing_id=intake.drawing_id, matches=ms, auxiliary=self.auxiliary, trace_id=intake.trace_id
        )
        return build(intake, merge, matching, self.schemas, None, self.classes)


def _keys(result: ValidationResult) -> dict[tuple[str, str | None], list[frozenset[str]]]:
    out: dict[tuple[str, str | None], list[frozenset[str]]] = {}
    for i in result.issues:
        if i.severity in ("error", "warning"):
            out.setdefault((i.rule_id, i.panel_id), []).append(frozenset(i.component_ids))
    return out


def _new(before: ValidationResult, after: ValidationResult, target: str | None, panel_id: str) -> list[str]:
    """The rules of the warnings and errors that are new and point at the target (or at its panel as a whole)."""
    old = _keys(before)
    old_ids = {i.issue_id for i in before.issues}
    found = []
    for i in after.issues:
        if i.severity not in ("error", "warning") or i.panel_id != panel_id:
            continue
        ids = frozenset(i.component_ids)
        if not ids:
            if i.issue_id in old_ids:
                continue  # a panel-level finding that says what it said before
        elif any(ids <= o for o in old.get((i.rule_id, i.panel_id), [])):
            continue  # there before, or a group that only lost a member
        if target is None or not ids or target in ids:
            found.append(i.rule_id)
    return sorted(set(found))


def _next_size(amps: float) -> float:
    return float(next((s for s in SIZES if s > amps), amps * 2))


def _set(c: Component, name: str, value: object) -> Component:
    attrs = dict(c.attributes)
    attrs[name] = AttributeValue(value=value, source="drawing", confidence=1.0)
    return c.model_copy(update={"attributes": attrs})


def _item(x: ComponentMatch, **values: object) -> ComponentMatch:
    """Stage 5 as it would have matched the changed reading: the values it used, and an item that has them."""
    used = {k: (u.model_copy(update={"value": values[k]}) if k in values else u) for k, u in x.attributes_used.items()}
    x = x.model_copy(update={"attributes_used": used})
    if x.catalog_item is None:
        return x
    item = x.catalog_item.model_copy(update={"attributes": {**x.catalog_item.attributes, **values}})
    return x.model_copy(update={"catalog_item": item})


Mutation = tuple[str, str, bool, str | None, list[Component], list[ComponentMatch]]
Pick = tuple[str, bool, str, list[Component], list[ComponentMatch]]  # target, applicable, id, components, matches


def mutations(lab: Labelled, base: DrawingModel) -> list[Mutation]:
    """(kind, target text, applicable, target component id, components, matches) for each change."""
    by_id = {x.component_id: x for x in lab.matches}
    out: list[Mutation] = []

    def swap(
        cid: str, comp: Component | None, x: ComponentMatch | None
    ) -> tuple[list[Component], list[ComponentMatch]]:
        comps = [comp if c.component_id == cid else c for c in lab.components]
        ms = [x if m.component_id == cid else m for m in lab.matches]
        return [c for c in comps if c is not None], [m for m in ms if m is not None]

    def pick(target: str, ok: bool, cid: str, comp: Component | None, x: ComponentMatch | None) -> Pick:
        return (target, ok, cid, *swap(cid, comp, x))

    def add(kind: str, picks: list[Pick]) -> None:
        out.extend((kind, target, ok, cid, comps, ms) for target, ok, cid, comps, ms in picks[:PER_KIND])

    priced = [(p, d) for p in base.panels.values() for d in p.priced]

    picks: list[Pick] = []
    for p, d in priced:
        main = p.main
        if main is None or main.current is None or d is main or d.family != "circuit_breaker":
            continue
        if d.current is None or d.current >= main.current or d.symbol_class != "mcb":
            continue
        amps = _next_size(main.current)
        x = by_id.get(d.id)
        new = _set(d.component, "current_a", amps)
        picks.append(pick(f"{d.tag} → {amps:g}A", True, d.id, new, _item(x, current_a=amps) if x else None))
    add("current_up", picks)

    has_bom = base.bom_available and not base.bom_is_source
    for kind in ("qty_minus_2", "deleted"):
        picks = []
        for p, d in priced:
            c = d.component
            front = p.front.designators if p.front else []
            ok = has_bom or any(t in front for t in c.designators)
            if kind == "qty_minus_2" and c.quantity >= 3:
                fewer = c.model_copy(update={"quantity": c.quantity - 2, "designators": c.designators[:-2]})
                picks.append(pick(f"{d.tag} ×{c.quantity} → ×{c.quantity - 2}", ok, d.id, fewer, by_id.get(d.id)))
            elif kind == "deleted" and c.designators:
                picks.append(pick(f"{d.tag} נמחק", ok, d.id, None, None))
        picks.sort(key=lambda t: not t[1])  # applicable ones first
        add(kind, picks)

    picks = []
    for _, d in priced:
        x = by_id.get(d.id)
        read = d.read.get("poles")
        have = x.catalog_item.attributes.get("poles") if x and x.catalog_item else None
        if x is None or not isinstance(read, int | float) or not isinstance(have, int | float):
            continue
        poles = {1: 3, 2: 1, 3: 4, 4: 3}.get(int(have), 1)
        bad = _item(x, poles=poles).model_copy(update={"chosen_sku": f"{x.chosen_sku}-INJ"})
        picks.append(pick(f'{d.tag}: מק"ט {poles}P', True, d.id, d.component, bad))
    add("sku_poles", picks)

    picks = []
    for _, d in priced:
        if d.family not in ("circuit_breaker", "rcbo") or d.current is None:
            continue
        cc = d.component.circuit_context or CircuitContext()
        load = round(d.current * 1.25, 1)
        new = d.component.model_copy(update={"circuit_context": cc.model_copy(update={"load_current_a": load})})
        picks.append(pick(f"{d.tag}: INC={load:g}A", True, d.id, new, by_id.get(d.id)))
    add("load_current", picks)

    picks = []
    for _, d in priced:
        if d.family != "circuit_breaker" or d.poles not in (3, 4):
            continue
        x = by_id.get(d.id)
        cc = d.component.circuit_context or CircuitContext()
        new = _set(d.component, "poles", 1).model_copy(
            update={"circuit_context": cc.model_copy(update={"cable": Cable(cores=5)})}
        )
        picks.append(pick(f"{d.tag}: 1P, כבל 5 גידים", True, d.id, new, _item(x, poles=1) if x else None))
    add("poles_cable", picks)

    picks = []
    for p in base.panels.values():
        tagged = [d for d in p.priced if d.component.designators]
        for d in tagged:
            donor = next((o for o in tagged if o.family != d.family), None)
            if donor is None:
                continue
            tag = donor.component.designators[0]
            new = d.component.model_copy(update={"designators": [*d.component.designators, tag]})
            picks.append(pick(f"{tag} גם על {d.tag}", True, d.id, new, by_id.get(d.id)))
    add("designator_family", picks)
    return out


def labelled_validation(lab: Labelled, pack: Pack) -> tuple[tuple[CanonFinding, ...], tuple[CanonInjected, ...]]:
    base_model = lab.model()
    base = validate(base_model, pack, lab.schemas)
    findings = canon_findings(base, lab.components, pack)
    panel_of = {d.id: p.panel_id for p in base_model.panels.values() for d in p.devices}
    injected = []
    for kind, target, ok, cid, comps, ms in mutations(lab, base_model):
        after = validate(lab.model(comps, ms), pack, lab.schemas)
        panel_id = panel_of.get(cid or "", next(iter(base_model.panels)))
        new = _new(base, after, None if kind == "deleted" else cid, panel_id)
        injected.append(CanonInjected(kind=kind, target=target, applicable=ok, caught=bool(new), rule_ids=tuple(new)))
    return findings, tuple(injected)
