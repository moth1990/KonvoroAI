"""Stage 6 (06): the validator in code, with no database and no model.

Each test builds the results of stages 1–5 by hand (`Drawing`), runs the panel model and the rules, and reads the
issues. Every rule fires on a minimal case and stays silent on its near miss; every message it writes fills every
placeholder its wording has.
"""

import json
import string
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from konboro.contracts.common import StageIssue
from konboro.contracts.extraction import ExtractionResult, PageExtraction, Render, TextSpan, WireGraph
from konboro.contracts.intake import ContextArtifact, IntakeResult, Page, PagePanel, Panel
from konboro.contracts.matching import CatalogItemSnapshot, ComponentMatch, MatchingResult, UsedAttribute
from konboro.contracts.merge import (
    AttributeValue,
    Cable,
    CircuitContext,
    Component,
    ContextElement,
    Instance,
    MergeResult,
    MissingInstance,
)
from konboro.contracts.validation import Issue, ValidationResult
from konboro.pipeline.association import schemas
from konboro.pipeline.bom.table import BomColumn, BomRow, BomTable
from konboro.pipeline.validation import agent, checks, crosscheck, engine, model, pack
from konboro.pipeline.validation.checks import CHECKS
from konboro_llm.stages.validator_review import ReviewAnswer, ReviewIssue

SCH = schemas.default()
PACK = pack.default()
PG, PNL, DRW = "pg_1", "pnl_1", "drw_1"
NOW = datetime(2026, 11, 3, tzinfo=UTC)


# --- building stages 1–5 by hand --------------------------------------------------------------------------------


def comp(
    cid: str,
    family: str = "circuit_breaker",
    cls: str = "mcb",
    *,
    tags: tuple[str, ...] = (),
    qty: int = 1,
    panel: str = PNL,
    upstream: str | None = None,
    load: float | None = None,
    cores: int | None = None,
    scope: str = "in_panel",
    texts: tuple[str, ...] = (),
    inherited: bool = False,
    ranges: tuple[str, ...] = (),
    **values: Any,
) -> Component:
    cc = None
    if upstream or load is not None or cores is not None or ranges:
        cc = CircuitContext(
            upstream_component_id=upstream,
            load_current_a=load,
            cable=Cable(cores=cores) if cores else None,
            circuit_numbers=list(ranges),
        )
    return Component(
        component_id=cid,
        drawing_id=DRW,
        panel_id=panel,
        family=family,
        symbol_class=cls,
        attributes={k: AttributeValue(value=v, source="drawing", confidence=1.0) for k, v in values.items()},
        explicit_texts=list(texts),
        quantity=qty,
        designators=list(tags),
        circuit_context=cc,
        multiplicity_inherited=inherited,
        supply_scope=scope,  # type: ignore[arg-type]
        instance_ids=[f"ins_{cid.removeprefix('cmp_')}"],
        confidence=1.0,
        status="accepted",
    )


def match(
    c: Component,
    sku: str | None = "SKU1",
    status: str = "matched",
    *,
    brand: str = "ABB",
    cost: bool = True,
    warnings: tuple[str, ...] = (),
    used: dict[str, tuple[Any, str]] | None = None,
    defaulted: tuple[str, ...] = (),
    signature: str | None = None,
    reason: str = "",
    **item: Any,
) -> ComponentMatch:
    attrs = {k: a.value for k, a in c.attributes.items()} | item
    snapshot = CatalogItemSnapshot(sku=sku, manufacturer=brand, description="item", attributes=attrs) if sku else None
    return ComponentMatch(
        component_id=c.component_id,
        status=status,  # type: ignore[arg-type]
        chosen_sku=sku,
        catalog_item=snapshot,
        method="rules_unique" if sku else None,
        match_confidence=0.95,
        confidence=0.95,
        attributes_used={k: UsedAttribute(value=v, source=s) for k, (v, s) in (used or {}).items()},  # type: ignore[arg-type]
        defaulted_attributes=list(defaulted),
        has_cost_price=cost,
        warnings=list(warnings),
        signature=signature,
        reason=reason,
    )


def page(no: int = 1, pid: str = PG, kind: str = "single_line_diagram", panels: tuple[str, ...] = (PNL,)) -> Page:
    return Page(
        page_id=pid,
        file_id="fil_1",
        page_no=no,
        sha256="abc",
        size_pt=(1000.0, 700.0),
        geometry_source="vector",
        text_source="pdf_text",
        quality="ok",
        page_kind=kind,  # type: ignore[arg-type]
        page_kind_confidence=0.99,
        route="process" if kind in ("single_line_diagram", "control_diagram") else "context",
        panels=[PagePanel(panel_id=p, name=p, bbox=(0.0, 0.0, 1000.0, 700.0), confidence=0.9) for p in panels],
        classified_by="model",
    )


class Drawing:
    """Stages 1–5 for one drawing, with as little as each test needs."""

    def __init__(self, *components: Component, matches: dict[str, ComponentMatch] | None = None) -> None:
        self.components = list(components)
        self.matches = matches if matches is not None else {c.component_id: match(c) for c in components}
        self.pages = [page()]
        self.panels = [Panel(panel_id=PNL, name="לוח ראשי", page_ids=[PG])]
        self.artifacts: list[ContextArtifact] = []
        self.instances: list[Instance] = []
        self.missing: list[MissingInstance] = []
        self.elements: list[ContextElement] = []
        self.graph = False
        self.spans: list[TextSpan] = []
        self.input_kind = "factory_drawing"
        self.auxiliary: list[str] = []

    def artifact(self, kind: str, content: Any, page_id: str | None = PG) -> "Drawing":
        fmt = "markdown" if kind == "general_notes" else "json"
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self.artifacts.append(
            ContextArtifact(
                artifact_id=f"ctx_{len(self.artifacts)}", page_id=page_id, kind=kind, format=fmt, content=text
            )
        )
        return self

    def intake(self) -> IntakeResult:
        return IntakeResult(
            drawing_id=DRW,
            tenant_id="tnt_1",
            project_id=None,
            status="ready",
            created_at=NOW,
            input_kind=self.input_kind,  # type: ignore[arg-type]
            source_files=[],
            pages=self.pages,
            panels=self.panels,
            context_artifacts=self.artifacts,
            trace_id="trc_1",
        )

    def merge(self) -> MergeResult:
        return MergeResult(
            drawing_id=DRW,
            instances=self.instances,
            components=self.components,
            missing=self.missing,
            context_elements=self.elements,
            trace_id="trc_1",
        )

    def matching(self) -> MatchingResult:
        return MatchingResult(
            drawing_id=DRW, matches=list(self.matches.values()), auxiliary=self.auxiliary, trace_id="trc_1"
        )

    def extraction(self) -> ExtractionResult:
        status = "built" if self.graph else "not_supported"
        pe = PageExtraction(
            page_id=PG,
            drawing_id=DRW,
            render=Render(dpi=150, px_per_pt=2.0, width_px=2000, height_px=1400, image_uri="r.png"),
            text_spans=self.spans,
            wire_graph=WireGraph(uri=None, status=status),  # type: ignore[arg-type]
            trace_id="trc_1",
        )
        return ExtractionResult(drawing_id=DRW, pages=[pe], trace_id="trc_1")

    def model(self, classes: dict[str, str] | None = None) -> model.DrawingModel:
        return model.build(self.intake(), self.merge(), self.matching(), SCH, self.extraction(), classes)

    def validate(self, p: pack.Pack = PACK, agent_for: Any = None) -> ValidationResult:
        return engine.validate(self.model(), p, SCH, agent_for)


def fired(result: ValidationResult, rule_id: str) -> list[Issue]:
    return [i for i in result.issues if i.rule_id == rule_id]


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def assert_filled(issue: Issue) -> None:
    """Every placeholder of the rule's title and message has a value (a missing one would read as nothing)."""
    rule = PACK.rules[issue.rule_id]
    missing = (placeholders(rule.title_he) | placeholders(rule.message_he)) - set(issue.values)
    assert not missing, f"{issue.rule_id}: {missing}"
    assert issue.title and "{" not in issue.title and "{" not in issue.message


def main_and(*others: Component, main_a: float = 40, poles: int = 3) -> Drawing:
    q0 = comp("cmp_q0", cls="mccb", tags=("Q0",), current_a=main_a, poles=poles)
    return Drawing(q0, *others)


# --- the rule pack ----------------------------------------------------------------------------------------------


def test_every_rule_has_a_check_and_every_check_a_rule() -> None:
    category_e = {r.rule_id for r in PACK.rules.values() if r.category == "E"}
    assert set(CHECKS) == set(PACK.rules) - category_e
    assert category_e == set(crosscheck.RULES)


def test_the_pack_rows_are_valid_for_the_table() -> None:
    for row in pack.rows():
        assert row["category"] in "ABCDE"
        assert row["requires"] in (None, *pack.REQUIRES)
        assert row["severity"] in ("error", "warning", "info")
        assert row["title_he"] and row["message_he"]
    category_a = [r for r in PACK.rules.values() if r.category == "A"]
    assert category_a and all(r.approval == "pending_expert" for r in category_a)  # S21 decision 7


def test_a_factory_turns_a_rule_off_and_tunes_another() -> None:
    tuned = pack.with_overrides(
        PACK, [("DATA_NO_COST_PRICE", False, {}), ("QTY_MULTIPLICITY_OUTLIER", None, {"max_multiplicity": 2})], "tnt_1"
    )
    assert "DATA_NO_COST_PRICE" not in {r.rule_id for r in tuned.active()}
    assert tuned.rules["QTY_MULTIPLICITY_OUTLIER"].params["max_multiplicity"] == 2
    assert tuned.tenant_version and tuned.tenant_version.startswith("tnt_1-")
    assert pack.with_overrides(PACK, [], "tnt_1").tenant_version is None
    d = main_and(comp("cmp_f1", tags=("F1",), current_a=16, poles=1))
    d.matches["cmp_f1"] = match(d.components[1], cost=False)
    assert fired(d.validate(), "DATA_NO_COST_PRICE")
    assert not fired(d.validate(tuned), "DATA_NO_COST_PRICE")


# --- the panel model --------------------------------------------------------------------------------------------


def test_main_device_without_a_graph_is_the_feed_class_with_the_highest_current() -> None:
    d = main_and(comp("cmp_f1", tags=("F1",), current_a=63, poles=1), main_a=40)
    p = d.model().panels[PNL]
    assert p.main is not None and p.main.id == "cmp_q0"  # an MCCB beats a higher-current MCB
    assert not p.hierarchy


def test_main_device_named_main_in_the_drawing() -> None:
    a = comp("cmp_a", tags=("F1",), current_a=25, poles=3, texts=('מא"ז', "ראשי"))
    b = comp("cmp_b", tags=("F2",), current_a=32, poles=3)
    assert Drawing(a, b).model().panels[PNL].main.id == "cmp_a"  # type: ignore[union-attr]


def test_a_shared_highest_current_among_breakers_names_no_main() -> None:
    d = Drawing(comp("cmp_a", tags=("F1", "F2"), qty=2, current_a=16, poles=1))
    p = d.model().panels[PNL]
    assert p.main is None and p.main_shared


def test_the_tree_comes_from_the_graph_and_its_top_is_the_main() -> None:
    q0 = comp("cmp_q0", cls="mcb", tags=("Q0",), current_a=63, poles=3)
    f1 = comp("cmp_f1", tags=("F1",), current_a=16, poles=1, upstream="cmp_q0")
    d = Drawing(q0, f1)
    assert d.model().panels[PNL].devices[1].parent_id is None  # no graph: no tree
    d.graph = True
    p = d.model().panels[PNL]
    assert p.hierarchy and p.device("cmp_f1").parent_id == "cmp_q0"  # type: ignore[union-attr]
    assert p.main is not None and p.main.id == "cmp_q0"


def test_final_values_are_the_catalog_items_over_what_was_read() -> None:
    c = comp("cmp_f1", tags=("F1",), current_a=16)
    d = Drawing(c, matches={"cmp_f1": match(c, poles=3, curve="C")})
    dev = d.model().panels[PNL].devices[0]
    assert dev.values["poles"] == 3 and dev.values["curve"] == "C"
    assert "poles" not in dev.read


def test_the_catalog_class_types_an_untyped_breaker() -> None:
    c = comp("cmp_x", cls="untyped", current_a=250, poles=3)
    d = Drawing(c)
    assert d.model({"SKU1": "mccb"}).panels[PNL].devices[0].symbol_class == "mccb"


@pytest.mark.parametrize(
    ("written", "spread"),
    [("F1-F3", ["F1", "F2", "F3"]), ("R1–R2", ["R1", "R2"]), ("Q0", ["Q0"]), ("F18-21", ["F18", "F19", "F20", "F21"])],
)
def test_front_view_ranges_spread(written: str, spread: list[str]) -> None:
    assert model.spread(written) == spread


def test_tags_compress_into_ranges() -> None:
    assert model.compress(["F26", "F27", "F28", "F29"]) == "F26–F29"
    assert model.compress(["R2", "R4"]) == "R2, R4"
    assert model.compress(["F1", "F2"]) == "F1, F2"


# --- category A ------------------------------------------------------------------------------------------------


def _graph(*cs: Component) -> Drawing:
    d = Drawing(*cs)
    d.graph = True
    return d


def test_hier_child_current_gt_parent() -> None:
    q = comp("cmp_q", tags=("Q1",), current_a=25, poles=3)
    bad = _graph(q, comp("cmp_f", tags=("F1",), current_a=32, poles=1, upstream="cmp_q")).validate()
    [i] = fired(bad, "HIER_CHILD_CURRENT_GT_PARENT")
    assert i.severity == "error" and set(i.component_ids) == {"cmp_f", "cmp_q"}
    assert_filled(i)
    ok = _graph(q, comp("cmp_f", tags=("F1",), current_a=25, poles=1, upstream="cmp_q")).validate()
    assert not fired(ok, "HIER_CHILD_CURRENT_GT_PARENT")
    assert any(s.rule_id == "HIER_CHILD_CURRENT_GT_PARENT" for s in Drawing(q).validate().checks_skipped)


def test_hier_rcd_underrated() -> None:
    q = comp("cmp_q", tags=("Q1",), current_a=63, poles=4)
    r = _graph(q, comp("cmp_r", "rcd", "rcd", tags=("FR1",), current_a=40, poles=4, upstream="cmp_q")).validate()
    [i] = fired(r, "HIER_RCD_UNDERRATED")
    assert_filled(i)
    ok = _graph(q, comp("cmp_r", "rcd", "rcd", tags=("FR1",), current_a=63, poles=4, upstream="cmp_q")).validate()
    assert not fired(ok, "HIER_RCD_UNDERRATED")


def test_hier_child_poles_gt_parent_by_phases() -> None:
    q = comp("cmp_q", tags=("Q1",), current_a=40, poles=1)
    bad = _graph(q, comp("cmp_f", tags=("F1",), current_a=16, poles=3, upstream="cmp_q")).validate()
    assert_filled(fired(bad, "HIER_CHILD_POLES_GT_PARENT")[0])
    q3 = comp("cmp_q", tags=("Q1",), current_a=40, poles=3)
    four = _graph(q3, comp("cmp_r", "rcd", "rcd", tags=("FR",), current_a=40, poles=4, upstream="cmp_q")).validate()
    assert not fired(four, "HIER_CHILD_POLES_GT_PARENT")  # a 4P RCD is three phases and a neutral


def test_hier_orphan_device() -> None:
    q = comp("cmp_q", tags=("Q1",), current_a=40, poles=3)
    fed = comp("cmp_f", tags=("F1",), current_a=16, poles=1, upstream="cmp_q")
    lone = comp("cmp_l", tags=("F2",), current_a=10, poles=1)
    [i] = fired(_graph(q, fed, lone).validate(), "HIER_ORPHAN_DEVICE")
    assert i.component_ids == ["cmp_l"] and i.severity == "info"
    assert_filled(i)
    assert not fired(_graph(q, fed).validate(), "HIER_ORPHAN_DEVICE")


def test_panel_outgoing_gt_main() -> None:
    bad = main_and(comp("cmp_f", tags=("F9",), current_a=63, poles=1)).validate()
    [i] = fired(bad, "PANEL_OUTGOING_GT_MAIN")
    assert i.severity == "error" and i.values["outgoing_a"] == 63 and i.values["main_a"] == 40
    assert_filled(i)
    assert not fired(main_and(comp("cmp_f", tags=("F9",), current_a=40, poles=1)).validate(), "PANEL_OUTGOING_GT_MAIN")
    rcd = main_and(comp("cmp_r", "rcd", "rcd", tags=("FR",), current_a=63, poles=4)).validate()
    assert not fired(rcd, "PANEL_OUTGOING_GT_MAIN")  # an RCD's rating may be above the breaker before it


def test_panel_poles_gt_main() -> None:
    bad = main_and(comp("cmp_f", tags=("F1",), current_a=16, poles=3), poles=1).validate()
    assert_filled(fired(bad, "PANEL_POLES_GT_MAIN")[0])
    assert not fired(main_and(comp("cmp_f", tags=("F1",), current_a=16, poles=4)).validate(), "PANEL_POLES_GT_MAIN")


# --- category B ------------------------------------------------------------------------------------------------


def test_panel_no_main_device_and_panel_empty() -> None:
    d = Drawing(comp("cmp_a", tags=("F1", "F2", "F3"), qty=3, current_a=16, poles=1))
    [i] = fired(d.validate(), "PANEL_NO_MAIN_DEVICE")
    assert i.component_ids == [] and i.values["count"] == 3
    assert_filled(i)
    assert not fired(main_and(comp("cmp_f", tags=("F1",), current_a=16)).validate(), "PANEL_NO_MAIN_DEVICE")
    empty = Drawing(comp("cmp_t", "terminal", "terminal", qty=10))
    empty.auxiliary = ["cmp_t"]  # the factory's auxiliary material is not priced (S20 decision 3)
    assert_filled(fired(empty.validate(), "PANEL_EMPTY")[0])
    assert not fired(main_and().validate(), "PANEL_EMPTY")


def test_overload_without_contactor() -> None:
    ol = comp("cmp_o", "overload_relay", "overload_relay", tags=("F5",), range_min_a=4, range_max_a=6)
    assert_filled(fired(main_and(ol).validate(), "CTRL_OVERLOAD_WITHOUT_CONTACTOR")[0])
    with_k = main_and(ol, comp("cmp_k", "contactor", "contactor", tags=("K1",)))
    assert not fired(with_k.validate(), "CTRL_OVERLOAD_WITHOUT_CONTACTOR")


def test_contactor_without_control_plan() -> None:
    d = main_and(comp("cmp_k", "contactor", "contactor", tags=("K1",)))
    assert_filled(fired(d.validate(), "CTRL_CONTACTOR_WITHOUT_COIL_CIRCUIT")[0])
    d.pages.append(page(2, "pg_2", "control_diagram"))
    assert not fired(d.validate(), "CTRL_CONTACTOR_WITHOUT_COIL_CIRCUIT")


def _front(d: Drawing, *tags: str) -> Drawing:
    d.pages.append(page(4, "pg_4", "panel_front_view", ()))
    d.panels[0] = Panel(panel_id=PNL, name="לוח ראשי", page_ids=[PG, "pg_4"])
    return d.artifact("panel_front_view", {"designators": list(tags), "panels": []}, "pg_4")


def test_front_view_designator_missing() -> None:
    d = _front(main_and(comp("cmp_f", tags=("F1",), current_a=16)), "Q0", "F1", "F26-F29")
    [i] = fired(d.validate(), "FRONT_VIEW_DESIGNATOR_MISSING")
    assert i.title == "F26–F29 מופיעים בחזית ולא בתוכנית" and i.page_id == "pg_4"
    assert_filled(i)
    ok = _front(main_and(comp("cmp_f", tags=("F1",), current_a=16)), "Q0", "F1")
    assert not fired(ok.validate(), "FRONT_VIEW_DESIGNATOR_MISSING")
    assert any(s.reason == "front_view_unavailable" for s in main_and().validate().checks_skipped)


def test_front_view_near_match_replaces_missing_and_extra() -> None:
    sg = comp("cmp_sg", "changeover_switch", "changeover_switch", tags=("SG",), current_a=125, poles=4)
    d = _front(main_and(sg), "Q0", "SE")
    r = d.validate()
    [i] = fired(r, "FRONT_VIEW_DESIGNATOR_NEAR_MATCH")
    assert i.values["front"] == "SE" and i.values["plan"] == "SG"
    assert_filled(i)
    assert not fired(r, "FRONT_VIEW_DESIGNATOR_MISSING") and not fired(r, "FRONT_VIEW_DESIGNATOR_EXTRA")
    assert not checks._near("F26", "F28")  # a digit apart is another device


def test_front_view_designator_extra() -> None:
    d = _front(main_and(comp("cmp_f", tags=("F1", "F2"), qty=2, current_a=16)), "Q0", "F1")
    [i] = fired(d.validate(), "FRONT_VIEW_DESIGNATOR_EXTRA")
    assert i.severity == "info" and i.values["shown"] == "F2"
    assert_filled(i)
    other = _front(main_and(comp("cmp_k", "contactor", "contactor", tags=("K1",))), "Q0")
    assert not fired(other.validate(), "FRONT_VIEW_DESIGNATOR_EXTRA")  # the front shows no K tags


def test_panel_missing_rows() -> None:
    d = main_and()
    d.missing.append(
        MissingInstance(
            instance_id="ins_m1", page_id=PG, panel_id=PNL, bbox=(1, 1, 5, 5), family="circuit_breaker",
            origin="tile_agent", confidence=0.3,
        )
    )  # fmt: skip
    [i] = fired(d.validate(), "PANEL_MISSING_ROWS")
    assert i.instance_ids == ["ins_m1"] and i.bbox == (1, 1, 5, 5)
    assert_filled(i)


def test_panel_referenced_not_drawn() -> None:
    feeds = {
        "feeds": [
            {"panel": "לוח חשמל ראשי מתחם רכב", "fed_from": "פילר הזנה"},
            {"panel": "לוח מבנה משרדים", "fed_from": "לוח חשמל ראשי מתחם רכב"},
            {"panel": "לוח סככת רכב", "fed_from": "לוח חשמל ראשי מתחם רכב"},
        ]
    }
    d = main_and()
    d.panels.append(Panel(panel_id="pnl_2", name="לוח סככה", page_ids=[PG]))
    [i] = fired(d.artifact("feed_diagram", feeds).validate(), "PANEL_REFERENCED_NOT_DRAWN")
    assert i.values["referenced"] == "לוח מבנה משרדים" and i.panel_id == PNL
    assert_filled(i)


def _bom_only(*cs: Component) -> Drawing:
    d = Drawing(*cs)
    d.input_kind = "bom_only"
    return d.artifact("bom_table", _table(("x", "1")).model_dump_json())


def _table(*rows: tuple[str, str]) -> BomTable:
    return BomTable(
        source="spreadsheet",
        columns=[
            BomColumn(index=0, letter="A", header="פרטים", role="item", by="code"),
            BomColumn(index=1, letter="B", header="כמות", role="quantity", by="code"),
        ],
        rows=[BomRow(row=n, cells=[item, qty]) for n, (item, qty) in enumerate(rows, start=2)],
        mapping_sure=True,
    )


def test_bom_accessory_host_count_and_no_enclosure() -> None:
    trips = comp("cmp_s", "shunt_trip", "shunt_trip", qty=5)
    mccb = comp("cmp_m", cls="mccb", qty=2, current_a=250, poles=3)
    r = _bom_only(trips, mccb).validate()
    [i] = fired(r, "BOM_ACCESSORY_HOST_COUNT")
    assert i.values["accessories"] == 5 and i.values["hosts"] == 2
    assert_filled(i)
    assert_filled(fired(r, "BOM_NO_ENCLOSURE")[0])
    enclosed = _bom_only(
        comp("cmp_s", "shunt_trip", "shunt_trip", qty=2), mccb, comp("cmp_e", "unknown", "unknown", texts=("ארון",))
    )
    r2 = enclosed.validate()
    assert not fired(r2, "BOM_ACCESSORY_HOST_COUNT") and not fired(r2, "BOM_NO_ENCLOSURE")


def test_scope_not_in_panel() -> None:
    d = main_and(comp("cmp_e", "push_button", "emergency_button", tags=("EMS",), scope="prepare_only"))
    [i] = fired(d.validate(), "SCOPE_NOT_IN_PANEL")
    assert i.component_ids == ["cmp_e"] and "הכנה בלבד" in i.message
    assert_filled(i)


# --- category C ------------------------------------------------------------------------------------------------


def _instance(cid: str, mult: int = 1, issues: tuple[str, ...] = ()) -> Instance:
    return Instance(
        instance_id=f"ins_{cid.removeprefix('cmp_')}",
        det_id=None,
        page_id=PG,
        panel_id=PNL,
        bbox=(10.0, 10.0, 20.0, 20.0),
        family="circuit_breaker",
        symbol_class="mcb",
        multiplicity=mult,
        method="geometric",
        status="accepted",
        confidence=0.9,
        component_id=cid,
        issues=[StageIssue(code=c, severity="warning", message="x") for c in issues],
    )


def test_multiplicity_outlier() -> None:
    d = main_and(comp("cmp_f", tags=("F1",), qty=30, current_a=16))
    d.instances.append(_instance("cmp_f", 30))
    [i] = fired(d.validate(), "QTY_MULTIPLICITY_OUTLIER")
    assert i.bbox == (10.0, 10.0, 20.0, 20.0)
    assert_filled(i)
    d.instances[0] = _instance("cmp_f", 24)
    assert not fired(d.validate(), "QTY_MULTIPLICITY_OUTLIER")


def test_single_instance_family() -> None:
    two = Drawing(comp("cmp_q", cls="mccb", tags=("QG1", "QG2"), qty=2, current_a=125, poles=4))
    [i] = fired(two.validate(), "QTY_SINGLE_INSTANCE_FAMILY")
    assert_filled(i)
    ats = Drawing(*two.components, comp("cmp_sg", "changeover_switch", "changeover_switch", tags=("SG",)))
    assert not fired(ats.validate(), "QTY_SINGLE_INSTANCE_FAMILY")  # a changeover: fed twice on purpose


def test_range_mismatch() -> None:
    d = main_and(comp("cmp_f", qty=1, current_a=16, ranges=("67-70",)))
    d.instances.append(_instance("cmp_f", 1, ("range_mismatch",)))
    [i] = fired(d.validate(), "QTY_RANGE_MISMATCH")
    assert i.values["size"] == 4
    assert_filled(i)
    d.instances[0] = _instance("cmp_f", 1)
    assert not fired(d.validate(), "QTY_RANGE_MISMATCH")


def test_inherited_multiplicity() -> None:
    [i] = fired(
        main_and(comp("cmp_f", tags=("F1",), qty=3, inherited=True, current_a=16)).validate(),
        "QTY_INHERITED_MULTIPLICITY",
    )
    assert_filled(i)


def _span(n: int, text: str = "16A") -> TextSpan:
    return TextSpan(
        span_id=f"ts_{n}", text=text, raw_text=text, bbox=(n, 1, n + 1, 2), source="pdf_text", confidence=1.0,
        tags={"current_a": 16},
    )  # fmt: skip


def test_text_coverage_low() -> None:
    d = main_and()
    d.spans = [_span(n) for n in range(12)]
    [i] = fired(d.validate(), "TEXT_COVERAGE_LOW")
    assert i.values["unassigned"] == 12
    assert_filled(i)
    d.spans = [_span(n, "Q0") for n in range(12)]  # a tag the stage-2 dictionary also reads as a current
    assert not fired(d.validate(), "TEXT_COVERAGE_LOW")
    d.input_kind = "bom_only"
    assert not fired(d.validate(), "TEXT_COVERAGE_LOW")


# --- category D ------------------------------------------------------------------------------------------------


def test_sku_attribute_mismatch_is_a_safety_net() -> None:
    c = comp("cmp_f", tags=("F1",), current_a=16, poles=1)
    d = main_and(c)
    d.matches["cmp_f"] = match(c, current_a=20)
    r = d.validate()
    [i] = fired(r, "DATA_SKU_ATTR_MISMATCH")
    assert i.severity == "error"
    assert_filled(i)
    assert any(x.code == "internal_consistency_violation" for x in r.stage_issues)
    e = comp("cmp_m", cls="mccb", trip_unit="electronic", current_a=160, poles=3)
    lsi = Drawing(e, matches={"cmp_m": match(e, trip_unit="LSI")})
    assert not fired(lsi.validate(), "DATA_SKU_ATTR_MISMATCH")  # any electronic trip unit is "אלקטרוני"


def test_same_signature_different_sku() -> None:
    a, b = comp("cmp_a", tags=("F1",), current_a=16), comp("cmp_b", tags=("F2",), current_a=16)
    d = main_and(a, b)
    d.matches["cmp_a"] = match(a, "S201-C16", signature="sig")
    d.matches["cmp_b"] = match(b, "S201-C16X", signature="sig")
    assert_filled(fired(d.validate(), "DATA_SAME_SIGNATURE_DIFF_SKU")[0])
    d.matches["cmp_b"] = match(b, "S201-C16", signature="sig")
    assert not fired(d.validate(), "DATA_SAME_SIGNATURE_DIFF_SKU")


def test_notes_not_applied() -> None:
    c = comp("cmp_f", tags=("F1",), current_a=16, poles=1)
    d = main_and(c).artifact("general_notes", '- כל המא"זים תוצרת שניידר')
    d.matches["cmp_f"] = match(c, brand="ABB")
    [i] = fired(d.validate(), "DATA_NOTES_NOT_APPLIED")
    assert "cmp_f" in i.component_ids
    assert_filled(i)
    equal = main_and(c).artifact("general_notes", '- כל המא"זים תוצרת שניידר או ש"ע')
    equal.matches["cmp_f"] = match(c, brand="ABB")
    assert not fired(equal.validate(), "DATA_NOTES_NOT_APPLIED")


def test_many_defaults() -> None:
    a, b = comp("cmp_a", tags=("F1",), current_a=16), comp("cmp_b", tags=("F2",), current_a=10)
    d = Drawing(a, b, matches={"cmp_a": match(a, defaulted=("curve",)), "cmp_b": match(b)})
    assert_filled(fired(d.validate(), "DATA_MANY_DEFAULTS")[0])
    d.matches["cmp_a"] = match(a)
    assert not fired(d.validate(), "DATA_MANY_DEFAULTS")


def test_designator_in_two_families() -> None:
    d = main_and(comp("cmp_f", tags=("C1",), current_a=16), comp("cmp_k", "contactor", "contactor", tags=("C1",)))
    [i] = fired(d.validate(), "DATA_DESIGNATOR_FAMILY_CONFLICT")
    assert set(i.component_ids) == {"cmp_f", "cmp_k"}
    assert_filled(i)


def test_model_text_conflict_warns_while_open_and_notes_once_resolved() -> None:
    c = comp("cmp_fnv", tags=("FNV",), current_a=6, poles=3)
    d = main_and(c)
    d.matches["cmp_fnv"] = match(c, None, "conflict", warnings=("attribute_conflict",), reason="בשרטוט כתוב 3P")
    [i] = fired(d.validate(), "DATA_MODEL_TEXT_CONFLICT")
    assert i.severity == "warning" and i.message == "בשרטוט כתוב 3P"
    assert_filled(i)
    d.matches["cmp_fnv"] = match(c, warnings=("attribute_conflict_resolved",), reason="נבחר לפי זיכרון ההתאמות")
    [j] = fired(d.validate(), "DATA_MODEL_TEXT_CONFLICT")
    assert j.severity == "info"  # S21 decision 4, prototype line 468


def test_load_current_above_rated() -> None:
    [i] = fired(main_and(comp("cmp_fc", tags=("FC1",), current_a=16, load=20)).validate(), "DATA_LOAD_CURRENT_GT_RATED")
    assert i.values == {"load_a": 20.0, "rated_a": 16.0, "designator": "FC1", "what": 'מא"ז FC1'}
    assert_filled(i)
    assert not fired(main_and(comp("cmp_fc", current_a=16, load=12.8)).validate(), "DATA_LOAD_CURRENT_GT_RATED")


def test_inferred_attribute() -> None:
    c = comp("cmp_k", "contactor", "contactor", tags=("C1", "C2"), qty=2)
    d = main_and(c)
    d.matches["cmp_k"] = match(c, used={"current_ac3_a": (16, "inferred")})
    [i] = fired(d.validate(), "DATA_INFERRED_ATTRIBUTE")
    assert i.severity == "info" and i.values["attribute_he"] == "הזרם"
    assert_filled(i)


def test_poles_cable_conflict() -> None:
    bad = main_and(comp("cmp_f", tags=("F1",), current_a=16, poles=1, cores=5)).validate()
    assert_filled(fired(bad, "POLES_CABLE_CONFLICT")[0])
    ok = main_and(comp("cmp_f", tags=("F1",), current_a=16, poles=1, cores=3)).validate()
    assert not fired(ok, "POLES_CABLE_CONFLICT")


def test_panel_requirement_not_met() -> None:
    c = comp("cmp_f", tags=("F1",), current_a=16, poles=1)
    d = main_and(c).artifact("notes_block", {"panel_id": PNL, "min_breaking_capacity_ka": 10})
    d.matches["cmp_f"] = match(c, breaking_capacity_ka=6)
    [i] = fired(d.validate(), "DATA_PANEL_REQUIREMENT_NOT_MET")
    assert i.severity == "error" and i.values["required_ka"] == 10
    assert_filled(i)
    d.matches["cmp_f"] = match(c, breaking_capacity_ka=10)
    assert not fired(d.validate(), "DATA_PANEL_REQUIREMENT_NOT_MET")


def test_no_cost_price_groups_the_rows() -> None:
    a, b = comp("cmp_a", tags=("F1",), current_a=16), comp("cmp_b", tags=("F2",), current_a=10)
    d = main_and(a, b)
    d.matches["cmp_a"], d.matches["cmp_b"] = match(a, cost=False), match(b, cost=False)
    [i] = fired(d.validate(), "DATA_NO_COST_PRICE")
    assert set(i.component_ids) == {"cmp_a", "cmp_b"}
    assert_filled(i)


# --- the engine -------------------------------------------------------------------------------------------------


def test_a_rule_that_raises_is_skipped_and_the_others_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any) -> list[checks.Hit]:
        raise RuntimeError("bug")

    monkeypatch.setitem(CHECKS, "PANEL_OUTGOING_GT_MAIN", boom)
    r = main_and(comp("cmp_f", tags=("F1",), current_a=63, load=80)).validate()
    assert any(s.rule_id == "PANEL_OUTGOING_GT_MAIN" and s.reason == "rule_execution_failed" for s in r.checks_skipped)
    assert any(x.code == "rule_execution_failed" for x in r.stage_issues)
    assert fired(r, "DATA_LOAD_CURRENT_GT_RATED")


def test_row_caps_and_panel_summaries() -> None:
    d = main_and(comp("cmp_f", tags=("F1",), current_a=63, load=80), comp("cmp_g", tags=("F2",), current_a=16, load=20))
    r = d.validate()
    caps = {c.component_id: c.max_status for c in r.row_status_caps}
    assert caps["cmp_f"] == "red" and caps["cmp_g"] == "yellow"
    [s] = r.panel_summaries
    assert s.main_device_component_id == "cmp_q0" and s.issue_counts["error"] >= 1
    assert [i.severity for i in r.issues] == sorted(
        (i.severity for i in r.issues), key=["error", "warning", "info"].index
    )


def test_panel_level_findings_cap_no_row() -> None:
    r = Drawing(comp("cmp_a", tags=("F1", "F2"), qty=2, current_a=16, poles=1)).validate()
    assert fired(r, "PANEL_NO_MAIN_DEVICE") and not r.row_status_caps


def test_issue_ids_are_stable_across_runs() -> None:
    d = main_and(comp("cmp_f", tags=("F1",), current_a=63))
    assert [i.issue_id for i in d.validate().issues] == [i.issue_id for i in d.validate().issues]


def test_category_e_is_skipped_without_a_bom_and_on_a_bom_only_drawing() -> None:
    reasons = {s.reason for s in main_and().validate().checks_skipped if s.rule_id.startswith("BOM_")}
    assert "bom_table_unavailable" in reasons
    r = _bom_only(comp("cmp_m", cls="mccb", current_a=250, poles=3)).validate()
    assert {s.reason for s in r.checks_skipped if s.rule_id == "BOM_QTY_DIFF"} == {"bom_is_the_source"}
    assert not r.bom_crosscheck.available


# --- BOM cross-check (06 §6.3) ---------------------------------------------------------------------------------


def _row(family: str, qty: int, *texts: str, **values: Any) -> Component:
    return comp(f"cmp_bom_{family}_{qty}", family, "mcb", qty=qty, texts=texts, **values)


def test_crosscheck_outcomes() -> None:
    q0 = comp("cmp_q0", cls="mccb", tags=("Q0",), current_a=63, poles=3)
    f16 = comp("cmp_f16", tags=("F1", "F2", "F3", "F4"), qty=4, current_a=16, poles=3)
    f10 = comp("cmp_f10", tags=("F5",), current_a=10, poles=1)
    d = Drawing(q0, f16, f10)
    devices = d.model().devices()
    rows = [
        _row("circuit_breaker", 6, current_a=16, poles=3),
        _row("circuit_breaker", 2, current_a=25, poles=1),
        _row("circuit_breaker", 1, "S203-C63", current_a=63, poles=3),
    ]
    out = crosscheck.compare(rows, devices)
    assert [h.values["bom_qty"] for h in out.hits["BOM_QTY_DIFF"]] == [6]
    assert [h.values["bom_qty"] for h in out.hits["BOM_MISSING_IN_QUOTE"]] == [2]
    assert [h.values["quote_qty"] for h in out.hits["BOM_EXTRA_IN_QUOTE"]] == [1]
    assert [h.values["bom_sku"] for h in out.hits["BOM_SKU_DIFF"]] == ["S203-C63"]
    assert out.summary.matched_signatures == 2 and out.summary.qty_diffs[0].quote_qty == 4


def test_a_bom_row_without_poles_pairs_with_the_quotes_rows_that_have_them() -> None:
    f16 = comp("cmp_f16", tags=("F1",), current_a=16, poles=3)
    out = crosscheck.compare([_row("circuit_breaker", 1, current_a=16)], Drawing(f16).model().devices())
    assert out.summary.matched_signatures == 1 and not out.hits["BOM_MISSING_IN_QUOTE"]


def test_crosscheck_on_a_drawing_with_a_designer_bom() -> None:
    table = _table(('מא"ז 3X16A', "6")).model_dump_json()
    d = main_and(comp("cmp_f", tags=("F1", "F2", "F3", "F4"), qty=4, current_a=16, poles=3), main_a=63)
    r = d.artifact("bom_table", table).validate()
    assert r.bom_crosscheck.available
    [i] = fired(r, "BOM_QTY_DIFF")
    assert i.source == "bom_crosscheck" and i.category == "E" and i.values["bom_qty"] == 6
    assert_filled(i)


# --- the agent (06 §6.4) ---------------------------------------------------------------------------------------


def _five() -> Drawing:
    return main_and(*(comp(f"cmp_f{n}", tags=(f"F{n}",), current_a=16, poles=1) for n in range(1, 6)))


def _ask(*issues: ReviewIssue, seen: list[str] | None = None) -> Any:
    def agent_for(_: model.PanelModel) -> engine.AgentCall:
        def look(name: str, components: str, tree: str, bom: str, findings: str) -> ReviewAnswer:
            if seen is not None:
                seen.append("\n".join((name, components, tree, bom, findings)))
            return ReviewAnswer(issues=list(issues))

        return engine.AgentCall(look, (800, 600), lambda b: (b[0] / 2, b[1] / 2, b[2] / 2, b[3] / 2), PG)

    return agent_for


def _issue(kind: str = "other", refs: tuple[str, ...] = ("c02",), conf: float = 0.8, bbox: Any = None) -> ReviewIssue:
    return ReviewIssue(type=kind, component_ids=list(refs), bbox=bbox, message="כדאי לבדוק", confidence=conf)  # type: ignore[arg-type]


def test_the_agent_is_asked_once_per_panel_with_five_components() -> None:
    seen: list[str] = []
    r = _five().validate(agent_for=_ask(seen=seen))
    assert r.agent_calls == 1 and len(seen) == 1
    assert main_and().validate(agent_for=_ask()).agent_calls == 0


def test_agent_answers_are_checked() -> None:
    answers = (
        _issue(refs=("c99",)),  # no such row, no box: dropped
        _issue(refs=(), bbox=[900, 0, 950, 10]),  # a box outside the picture: dropped
        _issue("missing_component", refs=(), bbox=[100, 100, 200, 200], conf=0.75),  # kept, on the page
        _issue(refs=("c02",), conf=0.4),  # below 0.5: hidden
        _issue(refs=("c03",), conf=0.6),  # an info
        _issue(refs=("c04",), conf=0.9),  # a warning, never an error
    )
    r = _five().validate(agent_for=_ask(*answers))
    agents = [i for i in r.issues if i.source == "agent"]
    assert sorted(i.severity for i in agents) == ["info", "warning", "warning"]
    boxed = next(i for i in agents if i.rule_id == "AGENT_missing_component")
    assert boxed.bbox == (50.0, 50.0, 100.0, 100.0) and boxed.page_id == PG and boxed.component_ids == []
    assert all(i.title and i.confidence < 1 for i in agents)


def test_at_most_five_agent_findings_and_none_that_repeats_a_rule() -> None:
    many = [_issue(refs=(f"c0{n}",)) for n in range(1, 7)]
    assert sum(1 for i in _five().validate(agent_for=_ask(*many)).issues if i.source == "agent") == 5
    d = _five()
    d.components[1] = comp("cmp_f1", tags=("F1",), current_a=16, poles=1, load=20)  # DATA_LOAD_CURRENT_GT_RATED on c02
    d.matches["cmp_f1"] = match(d.components[1])
    r = d.validate(agent_for=_ask(_issue("inconsistent_attributes", ("c02",))))
    assert not [i for i in r.issues if i.source == "agent"]


def test_an_agent_failure_leaves_the_rules() -> None:
    def agent_for(_: model.PanelModel) -> engine.AgentCall:
        def look(*_: str) -> ReviewAnswer:
            raise RuntimeError("down")

        return engine.AgentCall(look)

    r = _five().validate(agent_for=agent_for)
    assert any(x.code == "agent_unavailable" for x in r.stage_issues) and r.agent_calls == 1


def test_the_agent_is_shown_no_price_cost_or_customer() -> None:
    seen: list[str] = []
    d = _five()
    for c in d.components:
        d.matches[c.component_id] = match(c, cost=False)
    d.validate(agent_for=_ask(seen=seen))
    text = seen[0]
    for word in ("price", "cost", "₪", "margin", "customer", "has_cost_price", "מחיר", "עלות"):
        assert word not in text
    assert "c01 | circuit_breaker/mccb" in text  # rows by short ref, not by id
    assert "cmp_" not in text


# --- re-run after an edit (06 §6.3) ----------------------------------------------------------------------------


def test_revalidate_resolves_what_was_fixed_and_keeps_a_dismissal() -> None:
    bad = comp("cmp_f", tags=("F1",), current_a=63, poles=1)
    d = main_and(bad, comp("cmp_g", tags=("F2",), current_a=16, poles=1, load=20))
    first = d.validate()
    load = fired(first, "DATA_LOAD_CURRENT_GT_RATED")[0]
    first = first.model_copy(
        update={"issues": [i.model_copy(update={"status": "dismissed"}) if i is load else i for i in first.issues]}
    )
    d.components[1] = comp("cmp_f", tags=("F1",), current_a=16, poles=1)  # the user fixed F1
    d.matches["cmp_f"] = match(d.components[1])
    again = engine.revalidate(first, d.model(), PNL, PACK, SCH)
    [outgoing] = fired(again, "PANEL_OUTGOING_GT_MAIN")
    assert outgoing.status == "resolved"
    assert fired(again, "DATA_LOAD_CURRENT_GT_RATED")[0].status == "dismissed"
    assert "cmp_f" not in {c.component_id for c in again.row_status_caps}


def test_the_rules_on_150_components_take_well_under_a_second() -> None:
    cs = [comp("cmp_q0", cls="mccb", tags=("Q0",), current_a=400, poles=3)]
    cs += [comp(f"cmp_{n}", tags=(f"F{n}",), current_a=16, poles=1, load=12, cores=3) for n in range(150)]
    d = Drawing(*cs)
    d.graph = True
    m = d.model()
    start = time.perf_counter()
    engine.validate(m, PACK, SCH)
    assert time.perf_counter() - start < 1.0  # 06 §9
    start = time.perf_counter()
    engine.revalidate(engine.validate(m, PACK, SCH), m, PNL, PACK, SCH)
    assert time.perf_counter() - start < 1.0


def test_fill_writes_numbers_plainly() -> None:
    assert engine.fill("{a}A, {b}", {"a": 16.0, "b": ["F1", "F2", "F3"]}) == "16A, F1–F3"
    assert agent.MAX_ISSUES == 5 and agent.MIN_COMPONENTS == 5
