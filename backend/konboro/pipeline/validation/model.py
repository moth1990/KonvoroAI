"""06 §6.1: one model of each panel, which every check reads. Built from the results of stages 1–5 only, never from
their reasons (06 §1 principle 2).

- Each component as a device: its final values (the chosen catalog item's, else as read), the values as read apart
  (category D compares the two), its stage-5 match, its instances, whether it is priced (not auxiliary, not a
  non-billable family).
- The hierarchy, only when a page of the panel has a built wire graph (`wire_graph.status` = `built`): each device's
  feeder is the `upstream_component_id` stage 4 read from that graph (04 §6.3). Without one, the hierarchy checks are
  skipped and the panel-level checks stand in (06 §6.1).
- The main device (06 §6.1; S21 decision 8): the top of the tree when there is one; else a device the drawing calls
  main ("ראשי", "MAIN"); else the highest current among the feed classes (a switch-disconnector, a moulded-case
  breaker, a changeover); else the highest current among the breakers. A highest current that more than one device
  shares names no main.
- Structural elements (`context_elements`), the panel's missing rows, its front view's designators (stage 1's
  `panel_front_view` artifact, S21 decision 2), the breaking capacity its notes ask for (01 §5.5.1), the designer's BOM
  rows that belong to it (01 §5.8), and its electrical text spans for the coverage check.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import ContextArtifact, IntakeResult
from konboro.contracts.matching import ComponentMatch, MatchingResult
from konboro.contracts.merge import Component, ContextElement, Instance, MergeResult, MissingInstance
from konboro.pipeline.association import bom as bom_rows
from konboro.pipeline.association.schemas import Schemas
from konboro.pipeline.bom.table import BomTable
from konboro.pipeline.detection import library
from konboro.pipeline.intake.drawing import name_key
from konboro.pipeline.matching import text

POWER = ("circuit_breaker", "rcd", "rcbo", "fuse", "switch_disconnector")
FEED_CLASSES = ("switch_disconnector", "mccb", "changeover_switch", "ats")
MAIN_WORDS = re.compile(r"ראשי|\bMAIN\b|\bINCOMER\b", re.I)
BILLABLE = {c.family: c.billable for c in library.CLASSES}
SHORT_NAMES = {"mcb": 'מא"ז', "switch_disconnector": "מנתק", "surge_protector": "מגן ברק"}
_TAG_RANGE = re.compile(r"^([A-Za-z]+)(\d+)\s*[-–]\s*(?:([A-Za-z]+))?(\d+)$")


@dataclass
class Device:
    component: Component
    match: ComponentMatch | None
    values: dict[str, Any]  # final: the catalog item's, else as read
    read: dict[str, Any]  # as stage 4 read them, with their evidence
    symbol_class: str
    billable: bool
    parent_id: str | None = None

    @property
    def id(self) -> str:
        return self.component.component_id

    @property
    def family(self) -> str:
        return self.component.family

    @property
    def current(self) -> float | None:
        v = self.values.get("current_a")
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    @property
    def poles(self) -> int | None:
        v = self.values.get("poles")
        return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    @property
    def in_panel(self) -> bool:
        return self.component.supply_scope == "in_panel"

    @property
    def name(self) -> str:
        """The class in Hebrew: 'מא"ז', 'מפסק פחת'."""
        return SHORT_NAMES.get(self.symbol_class) or text.class_name(self.family, self.symbol_class)

    @property
    def tag(self) -> str:
        """Its designators ("F1, F2"), else its class name."""
        return tags(self.component.designators) or self.name

    @property
    def what(self) -> str:
        """'המא"ז F1', or 'המא"ז' when it has no tag."""
        d = tags(self.component.designators)
        return f"{self.name} {d}" if d else self.name


@dataclass
class FrontView:
    page_id: str | None
    page_no: int | None
    written: list[str]  # as stage 1 read them, ranges kept ("F1-F17")
    designators: list[str]  # ranges spread out ("F1" … "F17"), in order


@dataclass
class Requirement:
    min_breaking_capacity_ka: float
    source: str  # "הערות הלוח", "הנתונים הטכניים"


@dataclass
class PanelModel:
    panel_id: str
    name: str
    page_ids: list[str]
    devices: list[Device] = field(default_factory=list)
    hierarchy: bool = False
    main: Device | None = None
    main_shared: bool = False  # the highest current is shared by more than one unit
    main_tied: list[Device] = field(default_factory=list)  # the devices that share it
    structural: list[ContextElement] = field(default_factory=list)
    missing: list[MissingInstance] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    front: FrontView | None = None
    requirement: Requirement | None = None
    bom: list[Component] | None = None  # the designer's BOM rows for this panel, as stage 4 reads a row
    spans: list[tuple[str, bool]] | None = None  # (span id, assigned to a component) of the panel's electrical spans

    def device(self, component_id: str) -> Device | None:
        return next((d for d in self.devices if d.id == component_id), None)

    @property
    def priced(self) -> list[Device]:
        return [d for d in self.devices if d.billable and d.in_panel]


@dataclass
class DrawingModel:
    drawing_id: str
    input_kind: str | None
    panels: dict[str, PanelModel]
    designators: set[str]  # every component's tag in the drawing
    has_control_plan: bool
    general_notes: list[str]  # the lines of the `general_notes` pages
    feeds: list[dict[str, Any]]  # the feed diagram's entries (01 §5.5.2)
    bom_available: bool  # a `bom_table` artifact the cross-check can read (06 §6.3)
    bom_drawing: list[Component]  # rows of a table that names no panel of a drawing with several: the whole drawing
    bom_is_source: bool  # a BOM-only drawing: the BOM is what the quote is made of
    page_no: dict[str, int]
    matches: dict[str, ComponentMatch]
    auxiliary: set[str]
    catalog_lines: bool = False  # S27b (13 §4.10): a product not in the catalog is a finding

    def devices(self) -> list[Device]:
        return [d for p in self.panels.values() for d in p.devices]


def tags(designators: list[str]) -> str:
    """'F1, F2, F3' with runs of the same prefix written as a range: 'F1–F3'."""
    return compress(designators)


def compress(designators: list[str], limit: int = 6) -> str:
    """ "F26–F29", "R2, R4", or the first ones and how many more."""
    parsed: list[tuple[str, int | None, str]] = []
    for d in designators:
        m = re.match(r"^([A-Za-z]+)(\d+)$", d)
        parsed.append((m.group(1), int(m.group(2)), d) if m else (d, None, d))
    out: list[str] = []
    i = 0
    while i < len(parsed):
        prefix, n, raw = parsed[i]
        j = i
        while (
            n is not None and j + 1 < len(parsed) and parsed[j + 1][0] == prefix and parsed[j + 1][1] == n + (j + 1 - i)
        ):
            j += 1
        out.append(f"{raw}–{parsed[j][2]}" if j - i >= 2 else raw if j == i else f"{raw}, {parsed[j][2]}")
        i = j + 1
    if len(out) > limit:
        return ", ".join(out[:limit]) + f" ועוד {len(out) - limit}"
    return ", ".join(out)


def spread(written: str) -> list[str]:
    """ "F1-F17" → F1 … F17; "R1-R7" → R1 … R7; anything else as it is."""
    w = written.strip()
    m = _TAG_RANGE.match(w)
    if m and (m.group(3) is None or m.group(3) == m.group(1)):
        lo, hi = int(m.group(2)), int(m.group(4))
        if lo <= hi and hi - lo < 200:
            return [f"{m.group(1)}{n}" for n in range(lo, hi + 1)]
    return [w] if w else []


def _values(component: Component, match: ComponentMatch | None) -> tuple[dict[str, Any], dict[str, Any]]:
    read = {k: a.value for k, a in component.attributes.items() if a.value is not None}
    final = dict(read)
    if match is not None:
        for k, used in match.attributes_used.items():
            if used.value is not None:
                final[k] = used.value
        if match.catalog_item is not None:
            final.update({k: v for k, v in match.catalog_item.attributes.items() if v is not None})
    return final, read


def _class(component: Component, match: ComponentMatch | None, classes: dict[str, str]) -> str:
    if match is not None and match.chosen_sku and match.chosen_sku in classes:
        return classes[match.chosen_sku]
    return component.symbol_class


def _main(panel: PanelModel) -> None:
    feeders = [d for d in panel.devices if d.in_panel and d.family in POWER and d.current is not None]
    if panel.hierarchy:
        # the top of the tree: a feeder nothing feeds. A graph that missed a link leaves a lower one parentless too,
        # so the highest current among them is the top
        roots = [d for d in feeders if d.parent_id is None]
        if roots:
            top = max(r.current or 0 for r in roots)
            best = [r for r in roots if r.current == top]
            panel.main, panel.main_tied = best[0], best
            panel.main_shared = len(best) > 1 or best[0].component.quantity > 1
            return
    named = [d for d in feeders if any(MAIN_WORDS.search(t) for t in d.component.explicit_texts)]
    for pool in (named, [d for d in feeders if d.symbol_class in FEED_CLASSES], feeders):
        if not pool:
            continue
        top = max(d.current or 0 for d in pool)
        best = [d for d in pool if d.current == top]
        units = sum(max(d.component.quantity, 1) for d in best)
        panel.main_tied = best
        if units == 1:
            panel.main = best[0]
        else:
            panel.main_shared = True
            panel.main = best[0] if pool is not feeders else None  # a tie among every breaker names no main
        return


def _front_views(
    artifacts: list[ContextArtifact], intake: IntakeResult, page_no: dict[str, int]
) -> dict[str, FrontView]:
    """Each front view goes to the panel whose pages hold it, else to the drawing's only panel; a front view of
    several panels, or of none known, is left out (its designators could belong to either)."""
    out: dict[str, FrontView] = {}
    for a in artifacts:
        if a.kind != "panel_front_view" or a.format != "json":
            continue
        try:
            content = json.loads(a.content)
        except ValueError:
            continue
        written = [str(d) for d in content.get("designators") or [] if str(d).strip()]
        owners = [p.panel_id for p in intake.panels if a.page_id in p.page_ids]
        if len(owners) != 1:
            owners = [intake.panels[0].panel_id] if len(intake.panels) == 1 else []
        if not owners or not written:
            continue
        seen: dict[str, None] = {}
        for w in written:
            for d in spread(w):
                seen.setdefault(d, None)
        view = out.get(owners[0])
        if view is None:
            out[owners[0]] = FrontView(a.page_id, page_no.get(a.page_id or ""), written, list(seen))
        else:
            view.written += written
            view.designators += [d for d in seen if d not in view.designators]
    return out


def _requirements(artifacts: list[ContextArtifact]) -> dict[str | None, Requirement]:
    """01 §5.5.1: a panel's notes block, else the drawing's technical data."""
    out: dict[str | None, Requirement] = {}
    for a in artifacts:
        if a.kind not in ("technical_data", "notes_block") or a.format != "json":
            continue
        try:
            content = json.loads(a.content)
        except ValueError:
            continue
        ka = content.get("min_breaking_capacity_ka")
        if not isinstance(ka, int | float) or ka <= 0:
            continue
        key = content.get("panel_id") if a.kind == "notes_block" else None
        if a.kind == "notes_block" and key is None:
            continue
        out[key] = Requirement(float(ka), "הערות הלוח" if a.kind == "notes_block" else "הנתונים הטכניים")
    return out


def _bom(intake: IntakeResult, sch: Schemas) -> tuple[dict[str | None, list[Component]], bool]:
    """The designer's BOM, read as stage 4 reads a BOM row (04 §5.1, 06 §6.3 item 1): per panel when the table names
    one, else for the drawing (key None)."""
    tables: list[tuple[str, BomTable]] = []
    for a in intake.context_artifacts:
        if a.kind == "bom_table" and a.page_id:
            try:
                tables.append((a.page_id, BomTable.model_validate_json(a.content)))
            except ValueError:
                continue
    if not tables:
        return {}, False
    panel_ids = {name_key(p.name): p.panel_id for p in intake.panels}
    out: dict[str | None, list[Component]] = defaultdict(list)
    for page_id, t in tables:
        named = panel_ids.get(name_key(t.panel_name)) if t.panel_name else None
        key = named if named or len(intake.panels) != 1 else intake.panels[0].panel_id
        found = bom_rows.rows([(page_id, t)], {"_": key} if key else {"_": "pnl_drawing"}, None, sch)
        out[key].extend(bom_rows.components(intake.drawing_id, found))
    return dict(out), True


def _spans(
    extraction: ExtractionResult | None, intake: IntakeResult, merge: MergeResult, tag_keys: tuple[str, ...]
) -> dict[str, list[tuple[str, bool]]]:
    """The electrical spans (those with one of `tag_keys`) inside each panel's box on its process pages, and whether
    an instance's value cites them."""
    if extraction is None:
        return {}
    cited = {s for i in merge.instances for a in i.attributes.values() for s in a.span_ids}
    tags = {t for c in merge.components for t in c.designators}  # "C1" is a contactor's tag, not 1A of curve C
    boxes: dict[str, list[tuple[str, tuple[float, float, float, float]]]] = defaultdict(list)
    for page in intake.pages:
        for pp in page.panels:
            boxes[page.page_id].append((pp.panel_id, pp.bbox))
    only = intake.panels[0].panel_id if len(intake.panels) == 1 else None
    out: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for pe in extraction.pages:
        for s in pe.text_spans:
            if not any(k in s.tags for k in tag_keys) or s.text.strip() in tags:
                continue
            cx, cy = (s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2
            owner = next(
                (pid for pid, b in boxes.get(pe.page_id, []) if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]), only
            )
            if owner is not None:
                out[owner].append((s.span_id, s.span_id in cited))
    return dict(out)


def build(
    intake: IntakeResult,
    merge: MergeResult,
    matching: MatchingResult | None,
    sch: Schemas,
    extraction: ExtractionResult | None = None,
    classes: dict[str, str] | None = None,
    span_tags: tuple[str, ...] = ("current_a",),
) -> DrawingModel:
    classes = classes or {}
    matches = {x.component_id: x for x in matching.matches} if matching else {}
    auxiliary = set(matching.auxiliary) if matching else set()
    page_no = {p.page_id: p.page_no for p in intake.pages}
    built_pages = {
        pe.page_id
        for pe in (extraction.pages if extraction else [])
        if pe.wire_graph and pe.wire_graph.status == "built"
    }
    panels = {p.panel_id: PanelModel(p.panel_id, p.name, list(p.page_ids)) for p in intake.panels}

    def panel(panel_id: str | None) -> PanelModel | None:
        if panel_id in panels:
            return panels[panel_id]
        if panel_id is not None:
            panels[panel_id] = PanelModel(panel_id, panel_id, [])
            return panels[panel_id]
        return next(iter(panels.values()), None)

    for c in merge.components:
        p = panel(c.panel_id)
        if p is None:
            continue
        x = matches.get(c.component_id)
        values, read = _values(c, x)
        billable = BILLABLE.get(c.family, c.family != "unknown") and c.component_id not in auxiliary
        p.devices.append(Device(c, x, values, read, _class(c, x, classes), billable))
    instances_by_page: dict[str, list[Instance]] = defaultdict(list)
    for i in merge.instances:
        instances_by_page[i.page_id].append(i)
        if (p := panel(i.panel_id)) is not None:
            p.instances.append(i)
    for e in merge.context_elements:
        if (p := panel(e.panel_id)) is not None:
            p.structural.append(e)
    for mi in merge.missing:
        if (p := panel(mi.panel_id)) is not None:
            p.missing.append(mi)

    for p in panels.values():
        ids = {d.id for d in p.devices}
        pages = set(p.page_ids) | {i.page_id for i in p.instances}
        p.hierarchy = bool(pages & built_pages)
        if p.hierarchy:
            for d in p.devices:
                cc = d.component.circuit_context
                up = cc.upstream_component_id if cc else None
                d.parent_id = up if up in ids and up != d.id else None
        _main(p)

    for pid, view in _front_views(intake.context_artifacts, intake, page_no).items():
        if pid in panels:
            panels[pid].front = view
    requirements = _requirements(intake.context_artifacts)
    for p in panels.values():
        p.requirement = requirements.get(p.panel_id) or requirements.get(None)
    bom, available = _bom(intake, sch)
    if available:
        for p in panels.values():
            p.bom = bom.get(p.panel_id, [])
    for pid, spans in _spans(extraction, intake, merge, span_tags).items():
        if pid in panels:
            panels[pid].spans = spans

    notes = [
        line.strip().lstrip("-*•· ").strip()
        for a in intake.context_artifacts
        if a.kind == "general_notes"
        for line in a.content.splitlines()
        if line.strip().lstrip("-*•· ").strip()
    ]
    feeds: list[dict[str, Any]] = []
    for a in intake.context_artifacts:
        if a.kind == "feed_diagram" and a.format == "json":
            try:
                feeds += [f for f in json.loads(a.content).get("feeds") or [] if isinstance(f, dict)]
            except ValueError:
                continue
    return DrawingModel(
        drawing_id=intake.drawing_id,
        input_kind=intake.input_kind,
        panels=panels,
        designators={t for c in merge.components for t in c.designators},
        has_control_plan=any(p.page_kind == "control_diagram" for p in intake.pages),
        general_notes=notes,
        feeds=feeds,
        bom_available=available,
        bom_drawing=bom.get(None, []),
        bom_is_source=intake.input_kind == "bom_only",
        page_no=page_no,
        matches=matches,
        auxiliary=auxiliary,
    )
