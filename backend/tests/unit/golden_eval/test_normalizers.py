"""The normalizers reproduce the counts each golden drawing documents (S06 acceptance), and map the known quirks."""

import json
from decimal import Decimal

import pytest

from eval.canonical import GoldenDrawing
from eval.normalizers import GOLDEN, load, normalizer_for, shapes
from eval.normalizers.common import attributes_from_text, designators, pages


def golden(folder: str) -> GoldenDrawing:
    return load(GOLDEN / folder)


@pytest.mark.parametrize(
    ("folder", "products", "units"),
    [
        ("NEVIS-1", 21, 47),
        ("26-993", 22, 47),
        ("NURSERY-1", 13, 42),
        ("BOM-HW-1", 19, 91),
    ],
)
def test_product_and_unit_counts(folder: str, products: int, units: int) -> None:
    drawing = golden(folder)
    assert (drawing.products, drawing.units) == (products, units)
    if drawing.checksums is not None:  # the label's own summary agrees
        assert (drawing.checksums.products, drawing.checksums.units) == (products, units)


def test_6199_scores_components_and_checks_the_merged_bom() -> None:
    drawing = golden("6199-2-50")
    assert [p.name for p in drawing.panels] == ["לוח ראשי", "לוח סככה", "לוח ביתן שומר"]
    assert drawing.checksums is not None
    assert (drawing.checksums.products, drawing.checksums.units) == (84, 184)  # from bom[]
    assert drawing.units == 184  # components[] adds up to the same units
    assert drawing.products == 109  # unmerged rows, grouped by family + attributes when scored
    assert all(not c.designators for p in drawing.panels for c in p.components)
    assert any(c.supply_scope == "by_others" for p in drawing.panels for c in p.components)


def test_each_shape_has_its_normalizer() -> None:
    expected = {
        "26-993": shapes.bom_list,
        "NEVIS-1": shapes.component_list,
        "6199-2-50": shapes.panel_list,
        "BOM-HW-1": shapes.handwritten_rows,
        "NURSERY-1": shapes.priced_rows,
    }
    for folder, normalizer in expected.items():
        labels = json.loads((GOLDEN / folder / "labels.json").read_text(encoding="utf-8"))
        assert normalizer_for(labels) is normalizer


def test_unknown_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown label shape"):
        normalizer_for({"lines": []})


def test_input_kinds() -> None:
    kinds = {folder: golden(folder).input_kind for folder in ("26-993", "NEVIS-1", "6199-2-50", "BOM-HW-1")}
    assert kinds == {
        "26-993": "factory_drawing",
        "NEVIS-1": "factory_drawing",
        "6199-2-50": "designer_plan",
        "BOM-HW-1": "bom_only",
    }


def test_single_line_is_mapped_and_missing_routes_are_filled() -> None:
    nevis = golden("NEVIS-1")
    assert [p.kind for p in nevis.pages][4:6] == ["single_line_diagram", "single_line_diagram"]
    nursery = golden("NURSERY-1")
    assert [(p.kind, p.route) for p in nursery.pages] == [
        ("technical_data", "context"),
        ("factory_template", "skip"),
        ("factory_template", "skip"),
        ("panel_front_view", "context"),
        *[("single_line_diagram", "process")] * 5,
    ]
    assert golden("BOM-HW-1").pages == ()


def test_unknown_kind_without_route_stays_unrouted() -> None:
    (page,) = pages([{"no": 1, "kind": "legend"}])
    assert (page.kind, page.route) == ("legend", None)


def test_nevis_resolved_attributes_win() -> None:
    (fnv,) = [c for c in golden("NEVIS-1").panels[0].components if c.designators == ("FNV",)]
    assert (fnv.poles, fnv.current_a) == (3, 6.0)  # the drawing's S204M says 4; the real quote confirms 3


def test_designator_ranges_are_expanded() -> None:
    assert designators(["F1–F3", "C1-C2", "Q0", "TC-G1"]) == ("F1", "F2", "F3", "C1", "C2", "Q0", "TC-G1")
    (f1_17,) = [c for c in golden("NURSERY-1").panels[0].components if "F1" in c.designators]
    assert len(f1_17.designators) == f1_17.qty == 17


@pytest.mark.parametrize(
    ("text", "attrs"),
    [
        ('מא"ז ABB S203M 3P ‏20A', {"poles": 3, "current_a": 20}),
        ('מא"ז ABB SN201M 1P+N ‏10A', {"poles": 1, "neutral": True, "current_a": 10}),
        ("מפסק בתיבה יצוקה ABB XT1C 4P ‏160A משולב פחת", {"poles": 4, "current_a": 160}),
        ("מגען 3P, ‏16A לפחות", {"poles": 3}),  # a minimum is not a rating
        ("ממסר עזר", {}),
    ],
)
def test_attributes_from_product_text(text: str, attrs: dict[str, object]) -> None:
    assert attributes_from_text(text) == attrs


def test_audit_keeps_only_confirmed_differences() -> None:
    a = golden("26-993").audit
    assert a is not None and a.matched == 15
    assert [(d.type, d.designators, d.value_at_risk) for d in a.differences] == [
        ("quantity_mismatch", ("QG1", "QG2"), Decimal("1250")),
        ("missing_in_quote", ("TC-G1", "TC-G2"), None),
        ("missing_in_quote", ("MS1", "MS2", "MS3"), None),
    ]  # the test terminals are not a difference
    nevis = golden("NEVIS-1").audit
    assert nevis is not None and nevis.matched == 13
    assert sum(len(d.designators) for d in nevis.differences if d.type == "missing_in_quote") == 12
    assert [d.designators for d in nevis.differences if d.type == "quantity_mismatch"] == [("FP1",)]
    nursery = golden("NURSERY-1").audit
    assert nursery is not None and [d.designators for d in nursery.differences] == [("FNV",), ("RNV",)]
    assert golden("6199-2-50").audit is None


def test_quote_totals_are_before_vat() -> None:
    assert golden("26-993").quote_total == Decimal("14022.0")
    assert golden("NEVIS-1").quote_total == Decimal("11603.0")
    assert golden("NURSERY-1").quote_total == Decimal("14109.0")
    assert golden("BOM-HW-1").quote_total is None
