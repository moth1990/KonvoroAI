"""Stage 4 (04): which text belongs to which symbol, what it says, and the merge into components.

For each page stage 3 searched, in this order:
1. The neutral pole drawn on its own line joins its breaker (S13 decision, `association/assign.py`).
2. Every span is read through the spelling grammar (5.1, `association/grammar.json`); a span that is a device's tag
   reads as nothing.
3. Geometric association on the whole page (5.2): each span to the symbol that scores it highest; shared labels
   over a row of symbols; what each symbol's text says; whether it is resolved.
4. Supply scope (5.1.2) and the ranges of circuit numbers (5.1.1) from the lines of text.
5. The tile agent (5.3–5.5) for the tiles code could not resolve, its tiles in parallel, every answer checked.
6. Instances (5.6), with the multiplicity, the circuit around them from the wire graph, and their confidence (6.4);
   missed symbols (5.7) from the agent and from stage 3's orphan texts.
Then, once for the drawing, the chains (5.1.1 rule 3) and the merge (5.8), and the components are written to the
`components` table (they outlive the contract: quote lines and audits point at them).
"""

import io
import logging
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from PIL import Image
from sqlalchemy import delete

from konboro.contracts.common import StageIssue
from konboro.contracts.detection import Detection, DetectionResult, PageDetections
from konboro.contracts.extraction import ExtractionResult, PageExtraction
from konboro.contracts.intake import IntakeResult, Page
from konboro.contracts.merge import (
    Cable,
    CircuitContext,
    ContextElement,
    Instance,
    MergeResult,
    MergeStats,
    MissingInstance,
)
from konboro.db import models as m

from ..association import agent, assign, circuits, quantity, schemas
from ..association.assign import Value
from ..association.config import DEFAULT, AssociationConfig
from ..association.merge import Built, attribute, components, instance_confidence, issue, missing_instance, status
from ..context import StageContext
from ..detection import library
from ..extraction.geometry import contains

log = logging.getLogger("konboro.pipeline.s4")

Image.MAX_IMAGE_PIXELS = None

PAGE_ISSUES = {
    "citation_mismatch": "בעמוד {page} הסוכן ציטט {count} ערכים שלא כתובים בטקסט. הערכים נדחו.",
    "agent_invalid_output": "בעמוד {page} לא הצלחנו לשייך טקסט ב-{count} אריחים. השיוך לפי מיקום בלבד, בדקו את השורות.",
    "high_missing_ratio": "בעמוד {page} יש {count} רכיבים שנראים חסרים. ייתכן שפספסנו סימנים, בדקו את השורות האדומות.",
}


def _page_issue(code: str, page: Page, **values: Any) -> StageIssue:
    message = PAGE_ISSUES[code].format(page=page.page_no, **values)
    return StageIssue(code=code, severity="warning", page_id=page.page_id, message=message)


@dataclass
class PageWork:
    built: list[Built] = field(default_factory=list)
    missing: list[MissingInstance] = field(default_factory=list)
    context: list[ContextElement] = field(default_factory=list)
    issues: list[StageIssue] = field(default_factory=list)
    tiles_total: int = 0
    tiles_with_agent: int = 0
    agent_calls: int = 0
    citation_mismatches: int = 0
    values_cited: int = 0
    shared_labels: int = 0
    # what the chains need, per page
    detections: list[Detection] = field(default_factory=list)
    wires: circuits.Wires | None = None
    multiplicity: dict[str, quantity.Multiplicity] = field(default_factory=dict)


def _panel(d: Detection, page: Page, drawing_panels: list[str]) -> str | None:
    if d.panel_id:
        return d.panel_id
    if len(page.panels) == 1:
        return page.panels[0].panel_id
    if page.panels:
        return min(page.panels, key=lambda p: (assign.gap(p.bbox, d.bbox), p.panel_id)).panel_id
    return drawing_panels[0] if drawing_panels else None


def _agent_tiles(
    pe: PageExtraction,
    page: Page,
    owned: dict[str, list[Detection]],
    unresolved: set[str],
    orphan_spans: list[assign.Text],
) -> list[str]:
    """5.3: the tiles the agent decides."""
    out = []
    for t in pe.tiles:
        if t.is_blank or not owned.get(t.tile_id):
            continue
        low_res = page.text_source == "ocr" and page.quality == "low_resolution"
        orphan = any(contains(t.bbox_pt, x.span.bbox) for x in orphan_spans)
        if low_res or orphan or any(d.det_id in unresolved for d in owned[t.tile_id]):
            out.append(t.tile_id)
    return out


def associate_page(
    ctx: StageContext,
    page: Page,
    pe: PageExtraction,
    pd: PageDetections,
    seq: int,
    sch: schemas.Schemas,
    lib: library.Library,
    ask: agent.Ask,
    drawing_panels: list[str],
    cfg: AssociationConfig = DEFAULT,
) -> PageWork:
    work = PageWork(detections=pd.detections)
    dets = pd.detections
    absorbed = assign.absorb_neutral(dets, pe.text_spans, cfg)
    live = [d for d in dets if d.det_id not in absorbed]
    by_det = {d.det_id: d for d in dets}
    tags = {d.designator for d in dets if d.designator}
    texts = assign.texts(pe.text_spans, tags)
    by_span = {t.id: t for t in texts}
    class_family = {c.symbol_class: c.family for c in lib.classes.values()}
    families = {f for f, cs in lib.families.items() if any(c.billable for c in cs)}

    # 3. geometric association
    a = assign.associate(live, texts, sch, cfg)
    near_shared = {det for label in a.shared_labels for det in label.applies_to}
    reads = {d.det_id: assign.read(d, a.links[d.det_id], by_span, sch, class_family) for d in live if d.billable}
    unresolved = {
        det_id
        for det_id, r in reads.items()
        if not assign.resolved(by_det[det_id], r, a.links[det_id], sch, det_id in near_shared, cfg)
    }

    # 4. scope and ranges
    page_lines = quantity.lines(texts, cfg)
    scopes = quantity.supply_scopes(live, page_lines, cfg)
    protective = [d for d in live if d.billable and d.family in circuits.PROTECTIVE]
    ranges = quantity.circuit_ranges(protective, texts, cfg)
    if pe.wire_graph and pe.wire_graph.status == "built" and pe.wire_graph.uri:
        work.wires = circuits.Wires.from_json(ctx.storage.get(ctx.tenant_id, pe.wire_graph.uri))

    # 5. the tile agent
    owned: dict[str, list[Detection]] = defaultdict(list)
    for d in live:
        if d.billable:
            owned[d.owner_tile_id].append(d)
    assigned_spans = {lk.span_id for ls in a.links.values() for lk in ls}
    orphan_spans = [by_span[o.span_id] for o in pd.orphan_texts if o.span_id in by_span]
    tile_ids = _agent_tiles(pe, page, owned, unresolved, orphan_spans)
    work.tiles_total = sum(1 for t in pe.tiles if not t.is_blank)
    work.tiles_with_agent = len(tile_ids)
    checked: dict[str, agent.Checked | None] = {}
    if tile_ids and pe.render is not None:
        render = Image.open(io.BytesIO(ctx.storage.get(ctx.tenant_id, pe.render.image_uri))).convert("RGB")
        page_key = f"{page.sha256 or page.page_id}:{page.rotation_applied}:{pe.render.dpi}"
        tiles = {t.tile_id: t for t in pe.tiles}
        jobs = []
        for tile_id in tile_ids:
            t = tiles[tile_id]
            own = sorted(owned[tile_id], key=lambda d: (round(d.bbox[1]), d.bbox[0], d.det_id))
            own_ids = {d.det_id for d in own}
            context = [d for d in dets if d.det_id not in own_ids and assign.gap(d.bbox, t.bbox_pt) == 0]
            context.sort(key=lambda d: (round(d.bbox[1]), d.bbox[0], d.det_id))
            shown = [
                x
                for x in texts
                if assign.gap(x.span.bbox, t.bbox_pt) == 0
                or any(assign.gap(x.span.bbox, d.bbox) <= assign.radius(d, cfg) for d in own)
            ]
            shown.sort(key=lambda x: (round(x.span.bbox[1]), x.span.bbox[0], x.id))
            job = agent.TileJob(
                t,
                own,
                context,
                shown,
                {d.det_id: reads[d.det_id] for d in own},
                (t.bbox_px[0], t.bbox_px[1]),
                pe.render.px_per_pt,
            )
            job.image_key = agent.image_key(page_key, job)
            jobs.append(job)

        def one(job: agent.TileJob) -> tuple[str, agent.TileResult]:
            return job.tile.tile_id, agent.run_tile(job, agent.cut_tile(render, job.tile), ask, sch, families, cfg)

        with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            for tile_id, result in pool.map(one, jobs):
                checked[tile_id] = result.checked
                work.agent_calls += result.calls
    failed = [t for t, c in checked.items() if c is None]
    if failed:
        work.issues.append(_page_issue("agent_invalid_output", page, count=len(failed)))

    # what the agent says, joined over the page's tiles
    agent_values: dict[str, dict[str, Value]] = {}
    agent_nulls: dict[str, set[str]] = {}
    agent_mult: dict[str, tuple[int, list[str]]] = {}
    agent_brand: dict[str, str] = {}
    agent_texts: dict[str, list[str]] = {}
    unassigned: set[str] = set()
    labels = list(a.shared_labels)
    missed: list[dict[str, Any]] = []
    for c in checked.values():
        if c is None:
            continue
        agent_values.update(c.values)
        agent_nulls.update(c.nulls)
        agent_mult.update(c.multiplicity)
        agent_brand.update(c.brand_hint)
        agent_texts.update(c.explicit_texts)
        unassigned |= c.unassigned
        missed += c.missed
        work.citation_mismatches += c.citation_mismatches
        work.values_cited += c.values_cited
        labels += [x for x in c.shared_labels if all(x.span_ids != y.span_ids for y in labels)]
    work.shared_labels = len(labels)
    if work.citation_mismatches:
        work.issues.append(_page_issue("citation_mismatch", page, count=work.citation_mismatches))
    tile_of_det = {d.det_id: d.owner_tile_id for d in live}

    # 6. instances
    for d in live:
        if not d.billable:
            work.context.append(
                ContextElement(det_id=d.det_id, family=d.family, panel_id=_panel(d, page, drawing_panels), bbox=d.bbox)
            )
            continue
        r = reads[d.det_id]
        in_agent = tile_of_det[d.det_id] in checked
        ok = in_agent and checked[tile_of_det[d.det_id]] is not None
        method = "agent" if ok else ("fallback_geometric" if in_agent else "geometric")
        values, conflicts = _final_values(d, r, agent_values.get(d.det_id), agent_nulls.get(d.det_id, set()), ok)
        for label in labels:  # 5.6 item 2: a shared label fills what the symbol has no value of its own for
            if d.det_id in label.applies_to:
                for span_id in label.span_ids:
                    for rd in by_span[span_id].readings:
                        if rd.key in label.keys and rd.fits(d.family) and rd.key not in values:
                            values[rd.key] = Value(
                                rd.value,
                                "shared_label",
                                [span_id],
                                rd.confidence,
                                cfg.near_competitor,
                                by_span[span_id].span.confidence,
                            )
        mult = _multiplicity(d, r, agent_mult.get(d.det_id) if ok else None, page_lines)
        if d.det_id in ranges:
            mult.circuit_range, rid = ranges[d.det_id]
            mult.range_span_ids = [rid]
        work.multiplicity[d.det_id] = mult
        conf = instance_confidence(d.confidence, values, sch.required(d.family))
        issues: list[StageIssue] = []
        if conflicts:
            conf = round(conf * cfg.conflict_penalty, 4)
            chosen = ", ".join(f"{k}={values[k].value}" for k in conflicts if k in values)
            names = ", ".join(conflicts)
            issues.append(issue("attribute_conflict", "warning", page.page_id, names=names, chosen=chosen))
        if method == "fallback_geometric":
            conf = min(conf, cfg.fallback_max)
        if mult.mismatch:
            conf = min(conf, cfg.accepted_from - 0.01)
            issues.append(
                issue(
                    "range_mismatch",
                    page_id=page.page_id,
                    range=f"{mult.circuit_range[0]}–{mult.circuit_range[1]}",  # type: ignore[index]
                    count=mult.outputs or mult.count,
                )
            )
        missing_names = [n for n in sch.required(d.family) if n not in values]
        if missing_names:
            issues.append(issue("missing_required", page_id=page.page_id, names=", ".join(missing_names)))
        if any(lk.margin < cfg.resolved_gap and not lk.shared for lk in a.links[d.det_id]) and not ok:
            issues.append(issue("ambiguous_association", page_id=page.page_id))
        explicit = (agent_texts.get(d.det_id) if ok else None) or r.explicit_texts
        model_tokens = [str(v.value) for v in r.context.get("model_token", [])]
        brand = agent_brand.get(d.det_id) if ok else None
        brand = brand or next((str(v.value) for v in r.context.get("brand", [])), None)
        cls = r.symbol_class or d.symbol_class
        if cls == library.UNKNOWN and lib.families.get(d.family):  # the family is known, its look wasn't
            cls = lib.families[d.family][0].symbol_class
        instance = Instance(
            instance_id=f"ins_{d.det_id.removeprefix('det_')}",
            det_id=d.det_id,
            page_id=page.page_id,
            panel_id=_panel(d, page, drawing_panels),
            bbox=d.bbox,
            family=d.family,
            symbol_class=cls,
            attributes={n: attribute(values.get(n)) for n in sch.names(d.family)},
            multiplicity=mult.count,
            explicit_texts=_unique(explicit + [t for t in model_tokens if t not in explicit]),
            brand_hint=brand,
            method=method,  # type: ignore[arg-type]
            status=status(conf, cfg),  # type: ignore[arg-type]
            confidence=conf,
            issues=issues,
        )
        load = r.context.get("load_current_a")
        cable = [t for t in r.context.get("cable_cores", [])]
        circuit = CircuitContext(
            load_current_a=float(load[0].value) if load else None,
            cable=Cable(cores=int(cable[0].value), raw=None) if cable else None,
            circuit_numbers=[f"{mult.circuit_range[0]}-{mult.circuit_range[1]}"] if mult.circuit_range else [],
            outputs=[str(mult.outputs)] if mult.outputs else [],
        )
        work.built.append(
            Built(
                instance,
                d.designator,
                d.role,
                scopes[d.det_id].scope if d.det_id in scopes else "in_panel",
                circuit_context=circuit,
                extra_det_ids=sorted(x for x, host in absorbed.items() if host == d.det_id),
                order=(seq, round(d.bbox[1], 1), round(d.bbox[0], 1)),
            )
        )

    # 5.7 missed symbols: the agent's, then orphan texts no symbol took
    n = 0
    for x in missed:
        n += 1
        vals = _values_of(x["span_ids"], x["family"], by_span)
        panel = _panel_at(x["bbox"], page, drawing_panels)
        work.missing.append(
            missing_instance(f"ins_m{seq:03d}_{n:04d}", page.page_id, panel, x["bbox"], x["family"], vals, "agent")
        )
    for o in pd.orphan_texts:
        if o.span_id in assigned_spans and o.span_id not in unassigned:
            continue
        orphan = by_span.get(o.span_id)
        if orphan is None or any(o.span_id in x["span_ids"] for x in missed):
            continue
        family = _family_guess(orphan)
        if family is None:
            continue
        n += 1
        vals = _values_of([o.span_id], family, by_span)
        work.missing.append(
            missing_instance(
                f"ins_m{seq:03d}_{n:04d}",
                page.page_id,
                _panel_at(o.bbox, page, drawing_panels),
                o.bbox,
                family,
                vals,
                "orphan_text",
            )
        )
    if work.built and len(work.missing) > cfg.high_missing_share * (len(work.built) + len(work.missing)):
        work.issues.append(_page_issue("high_missing_ratio", page, count=len(work.missing)))
    return work


def _unique(xs: list[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def _final_values(
    d: Detection, r: assign.Read, from_agent: dict[str, Value] | None, nulls: set[str], ok: bool
) -> tuple[dict[str, Value], list[str]]:
    """5.6 item 1: the agent's checked values; where it gave none, code's when code was sure of it. Poles from the
    drawing's marks lose to poles in text (5.5, `attribute_conflict`)."""
    conflicts: list[str] = []
    if not ok or from_agent is None:
        return dict(r.values), list(r.conflicts)
    out = dict(from_agent)
    for name, v in r.values.items():
        if name in out or name in r.conflicts:
            continue
        if name not in nulls or v.association_confidence >= 0.9:
            out[name] = v
    poles_text = r.values.get("poles")
    if poles_text is not None and out.get("poles") is not None and out["poles"].source == "graphic":
        if poles_text.value != out["poles"].value:
            conflicts.append("poles")
        out["poles"] = poles_text
    return out, conflicts


def _multiplicity(
    d: Detection, r: assign.Read, from_agent: tuple[int, list[str]] | None, page_lines: list[quantity.Line]
) -> quantity.Multiplicity:
    if from_agent is not None:
        count, spans = from_agent
        return quantity.Multiplicity(count=count, span_ids=spans)
    marks = r.context.get("multiplicity", [])
    if not marks:
        return quantity.Multiplicity()
    v = marks[0]
    if any(quantity.on_cable_line(s, page_lines) for s in v.span_ids):
        return quantity.Multiplicity(count=1, span_ids=v.span_ids, outputs=int(v.value))
    return quantity.Multiplicity(count=int(v.value), span_ids=v.span_ids)


def _values_of(span_ids: list[str], family: str, by_span: dict[str, assign.Text]) -> dict[str, Value]:
    out: dict[str, Value] = {}
    names = set(schemas.default().names(family))
    for s in span_ids:
        t = by_span.get(s)
        if t is None:
            continue
        for rd in t.readings:
            if rd.key in names and rd.fits(family) and rd.key not in out:
                out[rd.key] = Value(rd.value, "drawing", [s], rd.confidence, 1.0, t.span.confidence)
    return out


def _family_guess(t: assign.Text) -> str | None:
    """5.7: "C20" → a breaker; "30mA" → a residual-current device."""
    keys = {r.key for r in t.readings}
    if "residual_ma" in keys:
        return "rcd"
    if keys & {"curve", "current_a", "breaking_capacity_ka"}:
        return "circuit_breaker"
    return None


def _panel_at(b: Any, page: Page, drawing_panels: list[str]) -> str | None:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    for p in page.panels:
        if contains(p.bbox, (cx, cy, cx, cy)):
            return p.panel_id
    if len(page.panels) == 1:
        return page.panels[0].panel_id
    return drawing_panels[0] if drawing_panels else None


def chains(works: list[PageWork], cfg: AssociationConfig = DEFAULT) -> None:
    """5.1.1 rule 3 and 5.8 item 4, on each page's wire graph: a device right below a device with a count takes
    it; every device learns the protective device above it."""
    built_by_det = {b.instance.det_id: b for w in works for b in w.built}
    for w in works:
        if w.wires is None:
            continue
        for d in w.detections:
            b = built_by_det.get(d.det_id)
            if b is None:
                continue
            up = circuits.upstream(w.wires, d, w.detections)
            if up is not None and b.circuit_context is not None:
                b.circuit_context.upstream_designator = up.designator
            mult = w.multiplicity.get(d.det_id)
            if mult is None or mult.count <= 1 or d.family not in circuits.PROTECTIVE:
                continue
            below, _ = circuits.downstream(w.wires, d, w.detections)
            for x in below:
                if x.family in circuits.PROTECTIVE:
                    break  # a bus feeding breakers is not a chain
                child = built_by_det.get(x.det_id)
                if child is None or child.instance.multiplicity > 1 or x.family == d.family:
                    continue
                child.instance.multiplicity = mult.count
                child.multiplicity_inherited = True
                conf = round(child.instance.confidence * cfg.inherited_penalty, 4)
                child.instance.confidence = conf
                child.instance.status = status(conf, cfg)  # type: ignore[assignment]
                child.instance.issues.append(
                    issue(
                        "multiplicity_inherited",
                        page_id=child.instance.page_id,
                        count=mult.count,
                        upstream=d.designator or 'המא"ז',
                    )
                )


def run(ctx: StageContext, cfg: AssociationConfig = DEFAULT) -> MergeResult:
    intake = ctx.output(1, IntakeResult)
    extraction = ctx.output(2, ExtractionResult)
    detection = ctx.output(3, DetectionResult)
    designer = intake.title_block.designer if intake.title_block else None
    lib = library.load(ctx.session, designer)
    sch = schemas.load(ctx.session)
    legend = "\n\n".join(a.content for a in intake.context_artifacts if a.kind == "legend")
    ask = agent.model_asker(ctx.llm, legend, ctx.tenant_id)
    pages = {p.page_id: p for p in intake.pages}
    extracted = {p.page_id: p for p in extraction.pages}
    drawing_panels = [p.panel_id for p in intake.panels]

    works: list[PageWork] = []
    for seq, pd in enumerate(detection.pages, start=1):
        pe = extracted.get(pd.page_id)
        if pe is None:
            continue
        works.append(associate_page(ctx, pages[pd.page_id], pe, pd, seq, sch, lib, ask, drawing_panels, cfg))
    chains(works, cfg)

    built = [b for w in works for b in w.built]
    for b in built:  # a device whose upstream device has a tag points at its component after the merge
        if b.instance.panel_id is None and drawing_panels:
            b.instance.panel_id = drawing_panels[0]
    comps, owner, merge_issues = components(ctx.drawing.id, built, sch, cfg)
    by_tag = {(c.panel_id, t): c.component_id for c in comps for t in c.designators}
    for c in comps:
        if c.circuit_context and c.circuit_context.upstream_designator:
            c.circuit_context.upstream_component_id = by_tag.get((c.panel_id, c.circuit_context.upstream_designator))
    instances = [b.instance.model_copy(update={"component_id": owner.get(b.instance.instance_id)}) for b in built]
    missing = [x for w in works for x in w.missing]
    _store(ctx, comps, built)

    by_method = Counter(i.method for i in instances)
    stats = MergeStats(
        instance_count=len(instances),
        component_count=len(comps),
        missing_count=len(missing),
        tiles_total=sum(w.tiles_total for w in works),
        tiles_with_agent=sum(w.tiles_with_agent for w in works),
        by_method=dict(sorted(by_method.items())),
        citation_mismatches=sum(w.citation_mismatches for w in works),
        shared_labels=sum(w.shared_labels for w in works),
    )
    log.info(
        "%d instances → %d components, %d missing; %d of %d tiles to the agent (%d calls), %d citation mismatches "
        "in %d cited values",
        stats.instance_count,
        stats.component_count,
        stats.missing_count,
        stats.tiles_with_agent,
        stats.tiles_total,
        sum(w.agent_calls for w in works),
        stats.citation_mismatches,
        sum(w.values_cited for w in works),
    )
    return MergeResult(
        drawing_id=ctx.drawing.id,
        instances=instances,
        components=comps,
        missing=missing,
        context_elements=[x for w in works for x in w.context],
        stats=stats,
        issues=[i for w in works for i in w.issues] + merge_issues,
        trace_id=ctx.trace_id,
    )


def _store(ctx: StageContext, comps: list[Any], built: list[Built]) -> None:
    """The components, for quote lines and audits to point at (`components`, 04 §6.3). A rerun replaces them."""
    s = ctx.session
    s.execute(delete(m.Component).where(m.Component.drawing_id == ctx.drawing.id))
    by_instance = {b.instance.instance_id: b for b in built}
    for c in comps:
        s.add(
            m.Component(
                id=c.component_id,
                tenant_id=ctx.tenant_id,
                drawing_id=ctx.drawing.id,
                panel_id=c.panel_id,
                family=c.family,
                attributes={k: v.model_dump(mode="json") for k, v in c.attributes.items()},
                quantity=c.quantity,
                designators=c.designators,
                instances=[
                    {
                        "instance_id": i,
                        "page_id": by_instance[i].instance.page_id,
                        "bbox": list(by_instance[i].instance.bbox),
                        "role": by_instance[i].role,
                    }
                    for i in c.instance_ids
                ],
                confidence=c.confidence,
                brand_hint=c.brand_hint,
                explicit_texts=c.explicit_texts,
                supply_scope=c.supply_scope,
            )
        )
    s.flush()
