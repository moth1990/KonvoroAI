"""Every metric on small hand-made cases: perfect, missing, extra, wrong attribute, merged vs unmerged, n/a."""

from decimal import Decimal
from typing import Any

import pytest

from eval.canonical import (
    CanonAudit,
    CanonComponent,
    CanonDifference,
    CanonPage,
    CanonPanel,
    GoldenDrawing,
    Prediction,
)
from eval.metrics import audit, pricing, score_drawing, stage1, stage4
from eval.metrics.score import Score, total


def comp(family: str, qty: int = 1, *des: str, **attrs: Any) -> CanonComponent:
    return CanonComponent(family=family, designators=des, attributes=attrs, qty=qty)


def drawing(*panels: CanonPanel, pages: tuple[CanonPage, ...] = (), **extra: Any) -> GoldenDrawing:
    return GoldenDrawing(id="T", file="t.pdf", input_kind="factory_drawing", pages=pages, panels=panels, **extra)


def predicted(*panels: CanonPanel, pages: tuple[CanonPage, ...] = (), **extra: Any) -> Prediction:
    return Prediction(pages=pages, input_kind=extra.pop("input_kind", "factory_drawing"), panels=panels, **extra)


def values(scores: dict[str, Score]) -> dict[str, float | None]:
    return {k: s.value for k, s in scores.items()}


# --- Score ------------------------------------------------------------------------------------------------------


def test_score_values_and_totals() -> None:
    assert Score(num=3, den=4).value == 0.75
    assert Score(num=2, den=9, kind="count").value == 2
    assert Score(num=0.3, den=2, kind="mean").value == 0.15
    assert Score.na().value is None  # nothing to score is n/a, not 0%
    summed = total([{"a": Score(num=1, den=1)}, {"a": Score(num=0, den=3), "b": Score.of(True)}])
    assert values(summed) == {"a": 0.25, "b": 1.0}
    with pytest.raises(ValueError, match="cannot add"):
        _ = Score(num=1, den=1) + Score(num=1, den=1, kind="count")


# --- stage 1 ----------------------------------------------------------------------------------------------------

LABEL_PAGES = (
    CanonPage(no=1, kind="technical_data", route="context"),
    CanonPage(no=2, kind="factory_template", route="skip"),
    CanonPage(no=3, kind="single_line_diagram", route="process"),
    CanonPage(no=4, kind="control_diagram", route="process"),
    CanonPage(no=5, kind="legend", route=None),
)


def test_stage1_perfect() -> None:
    label = drawing(CanonPanel(name="P", components=()), pages=LABEL_PAGES)
    pred = predicted(CanonPanel(name="P", components=()), pages=LABEL_PAGES)
    assert values(stage1.score(label, pred)) == {
        "page_kind_accuracy": 1.0,
        "route_accuracy": 1.0,  # page 5 has no route label: not counted
        "missed_process_pages": 0,
        "input_kind_accuracy": 1.0,
        "panel_count_accuracy": 1.0,
        "confirmation_rate": None,  # the prediction didn't say
    }


def test_stage1_title_block_per_field_and_confirmation() -> None:
    """01 §10: title-block accuracy per field, on the fields the label states; spacing and separators don't count."""
    label = drawing(
        pages=LABEL_PAGES, title_block={"drawing_number": "26/952-5", "date": "2026-10-05", "panel_name": "KARWANI"}
    )
    pred = predicted(
        pages=LABEL_PAGES,
        title_block={"drawing_number": "26 / 952-5", "date": "2026-05-10", "panel_name": "karwani", "revision": "C"},
        needs_confirmation=True,
    )
    scores = values(stage1.score(label, pred))
    assert {k: v for k, v in scores.items() if k.startswith("title_block_")} == {
        "title_block_drawing_number": 1.0,
        "title_block_date": 0.0,  # day and month swapped is wrong
        "title_block_panel_name": 1.0,
    }
    assert scores["confirmation_rate"] == 1.0


def test_stage1_skipped_and_missing_process_pages() -> None:
    label = drawing(CanonPanel(name="P", components=()), pages=LABEL_PAGES)
    pages = (
        CanonPage(no=1, kind="other", route="process"),
        CanonPage(no=2, kind="factory_template", route="skip"),
        CanonPage(no=3, kind="single_line_diagram", route="skip"),
    )  # page 4 never came back
    pred = predicted(pages=pages, input_kind="designer_plan")
    scores = stage1.score(label, pred)
    assert values(scores) == {
        "page_kind_accuracy": 0.4,
        "route_accuracy": 0.25,
        "missed_process_pages": 2,
        "input_kind_accuracy": 0.0,
        "panel_count_accuracy": 0.0,
        "confirmation_rate": None,
    }
    assert scores["missed_process_pages"].den == 2


def test_stage1_without_page_labels_is_na() -> None:
    scores = stage1.score(drawing(), predicted(pages=(CanonPage(no=1, kind="bom_table", route="context"),)))
    assert scores["page_kind_accuracy"].value is None
    assert scores["missed_process_pages"].value is None


# --- stage 4 ----------------------------------------------------------------------------------------------------


def test_stage4_by_designators() -> None:
    label = drawing(
        CanonPanel(
            name="P",
            components=(
                comp("circuit_breaker", 1, "Q0", current_a=80, poles=4),
                comp("circuit_breaker", 3, "F1", "F2", "F3", current_a=16, poles=1),
                comp("contactor", 2, "C1", "C2"),
            ),
        )
    )
    pred = predicted(
        CanonPanel(
            name="other name, one panel each",
            components=(
                comp("circuit_breaker", 1, "Q0", current_a=63, poles=4),  # wrong current
                comp("circuit_breaker", 2, "F1", "F2", current_a=16, poles=1),  # one missed
                comp("relay", 1, "R1"),  # extra
            ),
        )
    )
    total_, per_panel = stage4.score(label, pred)
    assert values(total_) == {
        "component_precision": pytest.approx(2 / 3, abs=1e-6),
        "component_recall": pytest.approx(2 / 3, abs=1e-6),
        "current_a_accuracy": 0.5,
        "poles_accuracy": 1.0,
        "quantity_accuracy": 0.5,
        "unit_recall": 0.5,  # 1 + 2 of 6
    }
    assert set(per_panel) == {"P"}


def test_stage4_family_must_agree_for_designators() -> None:
    m = stage4.match_panel([comp("relay", 1, "K1")], [comp("contactor", 1, "K1")])
    assert m.pairs == [] and values(m.scores())["component_recall"] == 0.0


def test_stage4_merged_and_unmerged_score_the_same() -> None:
    label = [comp("circuit_breaker", 2, current_a=16, poles=1), comp("circuit_breaker", 3, current_a=16, poles=1)]
    merged = [comp("circuit_breaker", 5, current_a=16, poles=1)]
    a = values(stage4.match_panel(label, merged).scores())
    b = values(stage4.match_panel(label, list(reversed(label))).scores())
    assert a == b
    assert a["component_recall"] == a["component_precision"] == a["quantity_accuracy"] == 1.0


def test_stage4_by_key_wrong_current_is_missed_and_extra() -> None:
    label = [comp("circuit_breaker", 1, current_a=16, poles=3), comp("rcd", 1, current_a=40, poles=4)]
    pred = [comp("circuit_breaker", 1, current_a=20, poles=3), comp("rcd", 1, current_a=40, poles=4)]
    scores = values(stage4.match_panel(label, pred).scores())
    assert (scores["component_precision"], scores["component_recall"]) == (0.5, 0.5)
    assert scores["current_a_accuracy"] is None  # measured on designator pairs only


def test_stage4_label_with_designators_falls_back_to_key() -> None:
    m = stage4.match_panel([comp("enclosure", 1, "W1")], [comp("enclosure", 1)])
    assert values(m.scores())["component_recall"] == 1.0


def test_stage4_recall_denominator_does_not_depend_on_the_prediction() -> None:
    label = [comp("circuit_breaker", 1, f"F{n}", current_a=16, poles=1) for n in range(1, 5)]
    for pred in ([], label[:2], [comp("circuit_breaker", 4, current_a=16, poles=1)]):
        assert stage4.match_panel(label, pred).scores()["component_recall"].den == 4
    merged = values(stage4.match_panel(label, [comp("circuit_breaker", 4, current_a=16, poles=1)]).scores())
    assert merged["component_recall"] == 0.25  # one predicted row without tags stands for one of the four


def test_stage4_only_in_panel_is_scored() -> None:
    other = CanonComponent(family="socket_outlet", qty=6, supply_scope="by_others")
    scores = values(stage4.match_panel([other, comp("rcd", 1)], [comp("rcd", 1)]).scores())
    assert (scores["component_recall"], scores["unit_recall"]) == (1.0, 1.0)


def test_stage4_no_prediction() -> None:
    label = drawing(CanonPanel(name="A", components=(comp("rcd"),)), CanonPanel(name="B", components=(comp("fuse"),)))
    total_, per_panel = stage4.score(label, predicted())
    assert values(total_)["component_recall"] == 0.0
    assert values(total_)["component_precision"] is None
    assert set(per_panel) == {"A", "B"}


def test_panels_pair_by_name_then_in_order() -> None:
    a, b, c = (CanonPanel(name=n, components=()) for n in ("לוח ראשי", "לוח סככה", "לוח ביתן"))
    x = CanonPanel(name="  לוח   ראשי ", components=())
    y = CanonPanel(name="unnamed", components=())
    assert stage4.pair_panels((a, b, c), (y, x)) == [(a, x), (b, y), (c, None)]
    assert stage4.pair_panels((a,), (x, y)) == [(a, x), (None, y)]


# --- audit ------------------------------------------------------------------------------------------------------

CONFIRMED = CanonAudit(
    matched=10,
    differences=(
        CanonDifference(type="missing_in_quote", item="מגען", designators=("C1", "C2")),
        CanonDifference(type="quantity_mismatch", item='מא"ז', designators=("FP1",)),
    ),
)


def test_audit_scores() -> None:
    pred = (
        CanonDifference(type="missing_in_quote", item="x", designators=("C2",), confidence=0.9),
        CanonDifference(type="possible_double_count", item="x", designators=("FP1",), confidence=0.8),
        CanonDifference(type="missing_in_quote", item="x", designators=("R9",), confidence=0.7),  # wrong
        CanonDifference(type="missing_in_quote", item="x", designators=("C1",), confidence=0.5),  # not shown
    )
    assert values(audit.score(CONFIRMED, pred)) == {
        "difference_precision": pytest.approx(2 / 3, abs=1e-6),
        "difference_recall": 1.0,
        "type_agreement": 0.5,
    }


def test_audit_na_and_unlabelled() -> None:
    assert all(v is None for v in values(audit.score(CONFIRMED, None)).values())
    assert audit.score(None, ()) == {}
    assert values(audit.score(CONFIRMED, ()))["difference_recall"] == 0.0


# --- pricing ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ours", "within", "deviation"),
    [("10000", 1.0, 0.0), ("10500", 1.0, 0.05), ("9400", 0.0, 0.06), ("0", 0.0, 1.0)],
)
def test_backtest(ours: str, within: float, deviation: float) -> None:
    assert values(pricing.score(Decimal("10000"), Decimal(ours))) == {
        "backtest_within_5pct": within,
        "backtest_deviation": deviation,
    }


def test_backtest_na() -> None:
    assert pricing.score(None, Decimal(1)) == {}
    assert all(v is None for v in values(pricing.score(Decimal(1), None)).values())


def test_score_drawing_has_every_section() -> None:
    label = drawing(CanonPanel(name="P", components=(comp("rcd"),)), audit=CONFIRMED, quote_total=Decimal(100))
    scores = score_drawing(label, predicted(quote_total=Decimal(100)))
    assert set(scores) == {"s1", "s4", "audit", "pricing"}
    assert scores["pricing"]["backtest_within_5pct"].value == 1.0
