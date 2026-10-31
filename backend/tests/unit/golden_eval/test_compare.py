"""Comparing a report with the baseline: drops fail, gains pass, lower-is-better metrics, n/a, new and gone."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from eval import compare, report
from eval.canonical import CanonComponent, CanonPage, CanonPanel, GoldenDrawing, Prediction


def score(value: float | None, den: int = 10, kind: str = "ratio") -> dict[str, Any]:
    num = 0 if value is None else value * (den if kind != "count" else 1)
    return {"num": num, "den": 0 if value is None else den, "kind": kind, "value": value}


def make(**s1: dict[str, Any]) -> dict[str, Any]:
    return {"drawings": {"D": {"scores": {"s1": s1}, "panels": {}}}, "totals": {}}


def test_flatten_paths() -> None:
    r = make(page_kind_accuracy=score(0.5))
    r["drawings"]["D"]["panels"] = {"לוח ראשי": {"component_recall": score(0.1)}}
    r["totals"] = {"all": {"s1": {"page_kind_accuracy": score(0.5)}}}
    assert compare.flatten(r) == {
        "drawings/D/scores/s1/page_kind_accuracy": 0.5,
        "drawings/D/panels/לוח ראשי/component_recall": 0.1,
        "totals/all/s1/page_kind_accuracy": 0.5,
    }


def test_no_change() -> None:
    r = make(page_kind_accuracy=score(0.5))
    result = compare.compare(r, r)
    assert result.ok and not (result.improvements or result.new)
    assert "No change." in compare.markdown(result)


def test_a_drop_is_a_regression_and_a_gain_is_not() -> None:
    before = make(page_kind_accuracy=score(0.5), route_accuracy=score(0.5))
    after = make(page_kind_accuracy=score(0.4), route_accuracy=score(0.6))
    result = compare.compare(after, before)
    assert [c.path.rsplit("/", 1)[-1] for c in result.regressions] == ["page_kind_accuracy"]
    assert [c.path.rsplit("/", 1)[-1] for c in result.improvements] == ["route_accuracy"]
    assert not result.ok
    assert "**Regressions** (1)" in compare.markdown(result)


def test_lower_is_better_metrics() -> None:
    before = make(missed_process_pages=score(0, kind="count"))
    after = make(missed_process_pages=score(1, kind="count"))
    assert not compare.compare(after, before).ok
    assert compare.compare(before, after).improvements


def test_na_new_and_gone() -> None:
    measured = make(page_kind_accuracy=score(0.5))
    na = make(page_kind_accuracy=score(None))
    gone = make()
    assert not compare.compare(na, measured).ok  # had a value, now n/a
    assert not compare.compare(gone, measured).ok  # gone
    assert compare.compare(measured, na).new  # was n/a, measured now: fine
    assert compare.compare(measured, gone).new
    assert compare.compare(na, na).ok


def test_main_exit_codes(tmp_path: Path) -> None:
    worse, base = tmp_path / "now.json", tmp_path / "base.json"
    base.write_text(json.dumps(make(page_kind_accuracy=score(0.5))))
    worse.write_text(json.dumps(make(page_kind_accuracy=score(0.2))))
    assert compare.main([str(worse), "--baseline", str(base)]) == 1
    assert compare.main([str(worse), "--baseline", str(base), "--allow-regression"]) == 0
    assert compare.main([str(base), "--baseline", str(base)]) == 0


def test_the_built_report_compares_with_itself_and_renders() -> None:
    label = GoldenDrawing(
        id="T",
        file="t.pdf",
        input_kind="factory_drawing",
        pages=(CanonPage(no=1, kind="single_line_diagram", route="process"),),
        panels=(CanonPanel(name="P", components=(CanonComponent(family="rcd", designators=("Q1",), qty=1),)),),
        quote_total=Decimal(100),
    )
    pred = Prediction(
        pages=(CanonPage(no=1, kind="other", route="process"),),
        input_kind="factory_drawing",
        panels=(CanonPanel(name="P", components=()),),
        quote_total=Decimal(0),
    )
    r = report.build([(label, pred)])
    assert compare.compare(r, json.loads(report.metrics_json(r))).ok
    assert set(r["totals"]["by_input_kind"]) == {"factory_drawing"}
    md = report.markdown(r)
    for heading in ("Stage 1", "Stage 4", "Pricing backtest", "Totals by input kind", "Stages 2 and 3 are n/a"):
        assert heading in md
    assert "0.0% (0/1)" in md and "| T | 100 | 0 | None |" in md


def test_formatting() -> None:
    assert report.fmt(None) == "n/a"
    assert report.fmt(score(None)) == "n/a"
    assert report.fmt(score(0.5)) == "50.0% (5/10)"
    assert report.fmt({"num": 2, "den": 5, "kind": "count", "value": 2}) == "2 of 5"
    assert report.fmt({"num": 0.3, "den": 2, "kind": "mean", "value": 0.15}) == "15.0%"
