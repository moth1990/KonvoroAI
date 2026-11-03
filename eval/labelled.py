"""Stage 5 on the labelled attributes (05 §10, 00 §10.1): components built from a golden drawing's labels, matched
with the same code as the stage (`pipeline/matching`), for the same tenant and through the same model gateway (its
cassettes). A reading error of stage 4 never counts against stage 5 here.

A labelled component becomes stage 4's contract as the stage would have read it: its family, the labelled values the
family's schema has, the label's words as the text beside it (a model code, a brand), and its designators. Families
the catalog does not hold (an enclosure, a busbar block) are stage 7's and are left out.
"""

import re
from typing import Any

from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import AttributeValue, CircuitContext, Component
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.pipeline.association import schemas as schemas_mod
from konboro.pipeline.association.grammar import parse
from konboro.pipeline.bom.terms import UNTYPED
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.detection import library
from konboro.pipeline.extraction import normalize
from konboro.pipeline.matching import catalog, factory
from konboro.pipeline.matching.match import Inputs, match_all
from konboro.pipeline.matching.notes import Notes
from konboro.pipeline.matching.query import Need, passes
from konboro.services.llm import usage_recorder
from konboro_llm import LLMClient
from konboro_llm.stages import catalog_disambiguation

from .canonical import CanonComponent, CanonMatch, GoldenDrawing
from .predict import canon_match
from .validation import Labelled

_RANGE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)$")
_RATIO = re.compile(r"^(\d+)/(\d+)$")
FIRST_CLASS = {f.family: f.classes[0][0] for f in library.FAMILIES}


def _class(c: CanonComponent) -> str:
    if c.family != "circuit_breaker":
        return FIRST_CLASS.get(c.family, c.family)
    text = f"{c.label} {c.attributes.get('model_token', '')} {c.attributes.get('model', '')}"
    if "מגן מנוע" in text or "MS116" in text or "PKZM" in text or "GV2" in text:
        return "motor_protection"
    if "תיבה יצוקה" in text or "XT" in text or "LSI" in text or "NSX" in text:
        return "mccb"
    if 'מא"ז' in text or "S20" in text or "SN20" in text:
        return "mcb"
    return UNTYPED  # an untyped "מפסק": stage 5 types it by its current (05 §5.5.1)


def _values(c: CanonComponent, names: tuple[str, ...]) -> dict[str, Any]:
    raw = dict(c.attributes)
    out: dict[str, Any] = {k: v for k, v in raw.items() if k in names and v is not None}
    if isinstance(raw.get("range_a"), str) and (m := _RANGE.match(raw["range_a"])):
        out["range_min_a"], out["range_max_a"] = float(m.group(1)), float(m.group(2))
    if isinstance(raw.get("ratio"), str) and (m := _RATIO.match(raw["ratio"])):
        out["ratio_primary_a"], out["ratio_secondary_a"] = int(m.group(1)), int(m.group(2))
    if "class" in raw and "spd_class" in names:
        out["spd_class"] = raw["class"]
    written = normalize.normalize(
        normalize.Text(raw_text=c.label, bbox=(0, 0, 0, 0), rotation=0, confidence=1.0, source="bom")
    ).text
    for r in parse(written):  # what the label's words say, normalized and read as stages 2 and 4 read text
        if r.key in names and r.key not in out and r.fits(c.family):
            out[r.key] = r.value
    return {k: v for k, v in out.items() if k in names}


def _upstream(c: CanonComponent, panel_id: str, drawing_id: str) -> Component | None:
    """A contactor labelled "16A לפחות" (`current_ac3_min_a`): the label states what 05 §5.5.1 infers from the breaker
    above it, so the labelled run gives it that breaker."""
    amps = c.attributes.get("current_ac3_min_a")
    if not isinstance(amps, int | float):
        return None
    return Component(
        component_id=new_id("cmp"),
        drawing_id=drawing_id,
        panel_id=panel_id,
        family="circuit_breaker",
        symbol_class="mcb",
        attributes={"current_a": AttributeValue(value=amps, source="drawing", confidence=1.0)},
        quantity=1,
        designators=["F_UP"],
        confidence=1.0,
        status="accepted",
    )


def components(
    label: GoldenDrawing, drawing_id: str, upstream: dict[str, Component] | None = None
) -> list[tuple[Component, dict[str, Any]]]:
    """The labelled components, each with the labelled values it is checked against; `upstream` collects the protective
    devices given to contactors (they are context, not matched)."""
    sch = schemas_mod.default()
    out: list[tuple[Component, dict[str, Any]]] = []
    for n, panel in enumerate(label.panels):
        panel_id = f"pnl_label{n}"
        for c in panel.components:
            if c.family not in schemas_mod.SCHEMAS or c.supply_scope != "in_panel":
                continue
            names = sch.names(c.family)
            values = _values(c, names)
            texts = [w for w in c.label.split() if w]
            for key in ("model_token", "model"):
                if isinstance(c.attributes.get(key), str) and c.attributes[key] not in texts:
                    texts.append(c.attributes[key])
            brand = c.attributes.get("brand") or c.attributes.get("brand_hint") or ("ABB" if "ABB" in texts else None)
            load = c.attributes.get("load_current_a")
            above = _upstream(c, panel_id, drawing_id)
            if above is not None and upstream is not None:
                upstream[above.component_id] = above
            circuit = None
            if isinstance(load, int | float) or above is not None:
                circuit = CircuitContext(
                    load_current_a=float(load) if isinstance(load, int | float) else None,
                    upstream_component_id=above.component_id if above else None,
                    upstream_designator=above.designators[0] if above else None,
                )
            component = Component(
                component_id=new_id("cmp"),
                drawing_id=drawing_id,
                panel_id=panel_id,
                family=c.family,
                symbol_class=_class(c),
                attributes={k: AttributeValue(value=v, source="drawing", confidence=1.0) for k, v in values.items()},
                explicit_texts=texts,
                brand_hint=brand,
                quantity=c.qty,
                designators=list(c.designators),
                circuit_context=circuit,
                confidence=1.0,
                status="accepted",
            )
            out.append((component, {k: v for k, v in c.attributes.items() if k in ("current_a", "poles", "neutral")}))
    return out


def _in_catalog(cat: catalog.Catalog, c: Component, sch: schemas_mod.Schemas) -> bool:
    """Every must-read value labelled, and an active item of the family (and class, when typed) that has them."""
    values = {k: a.value for k, a in c.attributes.items()}
    if any(values.get(n) is None for n in sch.must_read(c.family)):
        return False
    modes = {a.name: a.match_mode for a in sch.attributes(c.family)}
    needs = [Need(k, v, modes.get(k, "exact"), "drawing", True) for k, v in values.items() if modes.get(k) != "prefer"]
    classes = cat.classes(c.family)
    for item in cat.by_family.get(c.family, []):
        if item.status != "active":
            continue
        if c.symbol_class in classes and item.symbol_class not in (c.symbol_class, None):
            continue
        if passes(item, needs)[0]:
            return True
    return False


def labelled_matches(
    pipeline: Pipeline, tenant_id: str, drawing_id: str, label: GoldenDrawing, intake: IntakeResult
) -> tuple[tuple[CanonMatch, ...], Labelled]:
    """Stage 5 on the labelled components, and what stage 6 needs to check the same quote (`validation.py`)."""
    upstream: dict[str, Component] = {}
    built = components(label, drawing_id, upstream)
    llm = LLMClient(pipeline.llm_providers, on_call=usage_recorder(pipeline.engine, tenant_id, drawing_id))

    def ask(who: str, what: str, where: str, error: str | None) -> catalog_disambiguation.CatalogAnswer:
        return catalog_disambiguation.choose(llm, who, what, where, tenant_id, error).data

    with tenant_session(tenant_id, pipeline.engine) as s:
        cat = catalog.load(s)
        fac = factory.load(s, tenant_id, cat, None)
        sch = schemas_mod.load(s)
        comps = [c for c, _ in built]
        known = {c.component_id: c for c in comps} | upstream
        result = match_all(comps, Inputs(cat, fac, sch, Notes(), known, ask))
        labelled = {c.component_id: (lab, _in_catalog(cat, c, sch)) for c, lab in built}
    families = {c.component_id: c.family for c in comps}
    classes = {i.sku: i.symbol_class for i in cat.items.values() if i.symbol_class}
    lab = Labelled(intake, comps, result.matches, result.auxiliary, [p.name for p in label.panels], sch, classes)
    return tuple(
        canon_match(
            x,
            families[x.component_id],
            label=labelled[x.component_id][0],
            in_catalog=labelled[x.component_id][1],
        )
        for x in result.matches
    ), lab
