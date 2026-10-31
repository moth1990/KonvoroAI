"""The report: per-drawing and per-stage tables, plus totals by input kind (S06 acceptance), as JSON and markdown.

Everything but `meta` is the metrics part. It holds no IDs, timestamps or timings, so two replay runs give
byte-identical metrics, and the committed baseline is the same shape.
"""

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from .canonical import GoldenDrawing, Prediction
from .metrics import NOT_LABELLED, SECTIONS, Scores, panel_scores, score_drawing, total

Report = dict[str, Any]

TITLES = {
    "s1": "Stage 1: intake and page classification (01 §10)",
    "s4": "Stage 4: association and merge (04 §10)",
    "audit": "Quote audit (11 §10)",
    "pricing": "Pricing backtest against the real quote (07 §10.2)",
}


def _dump(sections: dict[str, Scores]) -> dict[str, Any]:
    return {name: {metric: s.model_dump() for metric, s in scores.items()} for name, scores in sections.items()}


def _totals(many: list[dict[str, Scores]]) -> dict[str, Scores]:
    return {section: total([m[section] for m in many]) for section in SECTIONS}


def build(results: list[tuple[GoldenDrawing, Prediction]]) -> Report:
    drawings: dict[str, Any] = {}
    every: list[dict[str, Scores]] = []
    by_kind: dict[str, list[dict[str, Scores]]] = defaultdict(list)
    for label, pred in results:
        scores = score_drawing(label, pred)
        every.append(scores)
        by_kind[label.input_kind].append(scores)
        at_risk = [d.value_at_risk for d in label.audit.differences if d.value_at_risk] if label.audit else []
        drawings[label.id] = {
            "input_kind": label.input_kind,
            "labelled": {"products": label.products, "units": label.units},
            "predicted": {
                "products": sum(len(p.components) for p in pred.panels),
                "units": sum(c.qty for p in pred.panels for c in p.components),
            },
            "quote_total": str(label.quote_total) if label.quote_total is not None else None,
            "predicted_total": str(pred.quote_total) if pred.quote_total is not None else None,
            "confirmed_value_at_risk": str(sum(at_risk, Decimal(0))) if label.audit else None,
            "scores": _dump(scores),
            "panels": _dump(panel_scores(label, pred)),
        }
    return {
        "drawings": drawings,
        "totals": {
            "all": _dump(_totals(every)),
            "by_input_kind": {kind: _dump(_totals(many)) for kind, many in sorted(by_kind.items())},
        },
        "not_labelled": NOT_LABELLED,
    }


def metrics_json(report: Report) -> str:
    return json.dumps({k: v for k, v in report.items() if k != "meta"}, sort_keys=True, ensure_ascii=False, indent=2)


def fmt(score: dict[str, Any] | None) -> str:
    if score is None or score["value"] is None:
        return "n/a"
    if score["kind"] == "count":
        return f"{int(score['num'])} of {score['den']}"
    if score["kind"] == "mean":
        return f"{score['value']:.1%}"
    return f"{score['value']:.1%} ({int(score['num'])}/{score['den']})"


def _table(rows: list[tuple[str, dict[str, Any]]], first: str) -> list[str]:
    metrics: list[str] = []
    for _, scores in rows:
        metrics.extend(m for m in scores if m not in metrics)
    if not metrics:
        return []
    lines = [f"| {first} | " + " | ".join(metrics) + " |", "| --- " * (len(metrics) + 1) + "|"]
    lines += [f"| {name} | " + " | ".join(fmt(scores.get(m)) for m in metrics) + " |" for name, scores in rows]
    return lines


def markdown(report: Report) -> str:
    meta = report.get("meta", {})
    out = [f"# Golden eval: {meta.get('created_at', '')}", ""]
    out.append(
        f"Mode `{meta.get('mode', '?')}`, commit `{meta.get('commit', '?')}`, {len(report['drawings'])} drawings."
    )
    out += ["", "Stages 2 and 3 are n/a: " + "; ".join(f"{k}: {v}" for k, v in report["not_labelled"].items()), ""]
    for section in SECTIONS:
        rows = [(d, v["scores"][section]) for d, v in report["drawings"].items() if v["scores"][section]]
        table = _table([*rows, ("**all**", report["totals"]["all"][section])], "Drawing")
        if table:
            out += [f"## {TITLES[section]}", "", *table, ""]
        if section == "s4":
            panels = [(f"{d} / {p}", s) for d, v in report["drawings"].items() for p, s in v["panels"].items()]
            out += ["Per panel:", "", *_table(panels, "Panel"), ""]
        if section == "pricing":
            out += [
                "| Drawing | Real quote, before VAT | Ours | Confirmed value at risk |",
                "| --- | --- | --- | --- |",
            ]
            out += [
                f"| {d} | {v['quote_total']} | {v['predicted_total']} | {v['confirmed_value_at_risk']} |"
                for d, v in report["drawings"].items()
                if v["quote_total"] is not None
            ]
            out.append("")
    out += ["## Totals by input kind", ""]
    by_kind = report["totals"]["by_input_kind"]
    for section in SECTIONS:
        rows = [(kind, sections[section]) for kind, sections in by_kind.items() if sections[section]]
        if rows:
            out += [f"**{section}**", "", *_table(rows, "Input kind"), ""]
    out += [
        "## Counts",
        "",
        "| Drawing | Labelled products / units | Predicted products / units |",
        "| --- | --- | --- |",
    ]
    for d, v in report["drawings"].items():
        lab, pred = v["labelled"], v["predicted"]
        out.append(f"| {d} | {lab['products']} / {lab['units']} | {pred['products']} / {pred['units']} |")
    return "\n".join(out) + "\n"
