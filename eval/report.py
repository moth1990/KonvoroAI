"""The report: per-drawing and per-stage tables, plus totals by input kind (S06 acceptance), as JSON and markdown.

Everything but `meta` is the metrics part. It holds no IDs, timestamps or timings, so two replay runs give
byte-identical metrics, and the committed baseline is the same shape.
"""

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from .canonical import CanonInjected, GoldenDrawing, Prediction
from .metrics import NOT_LABELLED, SECTIONS, Scores, panel_scores, score_drawing, total
from .metrics import audit as audit_metric

Report = dict[str, Any]

TITLES = {
    "s1": "Stage 1: intake and page classification (01 §10)",
    "s2": "Stage 2: extraction, designators found in the text (02 §10, S10)",
    "s3": "Stage 3: symbols, by designators and family counts (03 §10, S12)",
    "s3_family": "Stage 3: recall by family (03 §10)",
    "s4": "Stage 4: association and merge (04 §10)",
    "s5": "Stage 5: catalog matching, end to end (05 §10, S20)",
    "s5_labelled": "Stage 5: catalog matching on the labelled attributes (05 §10)",
    "s6": "Stage 6: validation, end to end (06 §10, S21)",
    "s6_labelled": "Stage 6: validation rules on the labelled quote, with injected errors (06 §10.1–10.2)",
    "audit": "Quote audit (11 §10)",
    "pricing": "Pricing backtest against the real quote (07 §10.2)",
}


def _dump(sections: dict[str, Scores]) -> dict[str, Any]:
    return {name: {metric: s.model_dump() for metric, s in scores.items()} for name, scores in sections.items()}


def _totals(many: list[dict[str, Scores]]) -> dict[str, Scores]:
    return {section: total([m[section] for m in many]) for section in SECTIONS}


def _injected(i: CanonInjected) -> str:
    outcome = "caught" if i.caught else "missed" if i.applicable else "n/a"
    return f"{i.kind}: {i.target}: {outcome} {','.join(i.rule_ids)}".strip()


def _predicted_at_risk(pred: Prediction) -> str | None:
    """The audit's value at risk on its shown differences (11 §5.5), beside the factory-confirmed one."""
    if pred.audit is None:
        return None
    shown = [d.value_at_risk for d in pred.audit if d.value_at_risk and (d.confidence or 0) >= audit_metric.SHOWN_FROM]
    return str(sum(shown, Decimal(0)))


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
            "backtest": pred.backtest,
            "confirmed_value_at_risk": str(sum(at_risk, Decimal(0))) if label.audit else None,
            "predicted_value_at_risk": _predicted_at_risk(pred),
            "extraction": pred.extraction,
            "detection": pred.detection,
            "merge": pred.merge,
            "matching": pred.matching,
            "validation": pred.validation,
            "findings": [
                f"{f.severity} {f.rule_id} {' '.join(f.designators[:6])}".strip() for f in pred.findings or ()
            ],
            "labelled_findings": [f"{f.severity} {f.rule_id}" for f in pred.labelled_findings or ()],
            "injected": [_injected(i) for i in pred.injected or ()],
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
    # the chat's per-request rows (answers included) are in the run's report, not the baseline
    kept = {k: v for k, v in report.items() if k not in ("meta", "chat_cases")}
    return json.dumps(kept, sort_keys=True, ensure_ascii=False, indent=2)


def fmt(score: dict[str, Any] | None) -> str:
    if score is None or score["value"] is None:
        return "n/a"
    if score["kind"] == "count":
        return f"{int(score['num'])} of {score['den']}"
    if score["kind"] == "mean":
        return f"{score['value']:.1%}"
    if score["kind"] == "average":
        return f"{score['value']:.1f} ({int(score['num'])} in {score['den']})"
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
    out += ["", "Not labelled yet: " + "; ".join(f"{k}: {v}" for k, v in report["not_labelled"].items()), ""]
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
                "| Drawing | Real quote, before VAT | Ours (own prices) | Lines priced | Derived: quote / ours "
                "| Leave one out | Lines priced | Confirmed value at risk |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            out += [
                f"| {d} | {v['quote_total']} | {v['predicted_total']} | {b.get('own_coverage')} "
                f"| {b.get('quote_derived')} / {b.get('own_derived')} | {b.get('loo_total')} | {b.get('loo_coverage')} "
                f"| {v['confirmed_value_at_risk']} |"
                for d, v in report["drawings"].items()
                if v["quote_total"] is not None
                for b in [v.get("backtest") or {}]
            ]
            out.append("")
    out += ["## Totals by input kind", ""]
    by_kind = report["totals"]["by_input_kind"]
    for section in SECTIONS:
        rows = [(kind, sections[section]) for kind, sections in by_kind.items() if sections[section]]
        if rows:
            out += [f"**{section}**", "", *_table(rows, "Input kind"), ""]
    for stage, field in (("3", "detection"), ("4", "merge")):
        counted = [(d, v[field]) for d, v in report["drawings"].items() if v.get(field)]
        if counted:
            keys = list(counted[0][1])
            out += [f"## Stage {stage} counts", "", "| Drawing | " + " | ".join(keys) + " |"]
            out += ["| --- " * (len(keys) + 1) + "|"]
            out += [f"| {d} | " + " | ".join(str(c.get(k, "")) for k in keys) + " |" for d, c in counted]
            out.append("")
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
