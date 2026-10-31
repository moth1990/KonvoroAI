"""`make eval` in replay mode (S06): it runs on all 5 golden drawings, writes both report files, matches the
committed baseline, and two runs give byte-identical metrics."""

import json
from pathlib import Path

import pytest

from eval import compare, report, run


@pytest.fixture(scope="module")
def first() -> report.Report:
    return run.evaluate("replay")


def test_replay_scores_every_golden_drawing(first: report.Report) -> None:
    assert sorted(first["drawings"]) == ["26-993", "6199-2-50", "BOM-HW-1", "NEVIS-1", "NURSERY-1"]
    assert set(first["totals"]["by_input_kind"]) == {"bom_only", "designer_plan", "factory_drawing"}
    nursery = first["drawings"]["NURSERY-1"]["scores"]
    assert nursery["s1"]["missed_process_pages"]["value"] == 0  # the stub routes every page to process
    assert nursery["pricing"]["backtest_within_5pct"]["value"] == 0.0  # the stub prices nothing


def test_replay_is_deterministic(first: report.Report) -> None:
    assert report.metrics_json(run.evaluate("replay")) == report.metrics_json(first)


def test_the_committed_baseline_is_current(first: report.Report) -> None:
    result = compare.compare(first, json.loads(compare.BASELINE.read_text(encoding="utf-8")))
    assert result.ok, compare.markdown(result)
    assert not result.improvements, "update the baseline: make eval-baseline"


def test_main_writes_both_report_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("EVAL_MODE", "replay")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert run.main(["--out", str(tmp_path / "reports")]) == 0
    (json_file,) = (tmp_path / "reports").glob("*.json")
    md_file = json_file.with_suffix(".md")
    assert json.loads(json_file.read_text())["meta"]["mode"] == "replay"
    assert "## Against the baseline" in md_file.read_text(encoding="utf-8")
    assert summary.read_text(encoding="utf-8") == md_file.read_text(encoding="utf-8")


def test_record_needs_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVAL_RECORD", "1")
    with pytest.raises(ValueError, match="EVAL_MODE=live"):
        run.main(["--out", str(tmp_path), "--no-compare"])
