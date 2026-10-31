"""Compare a report with the baseline (S06 decision: the committed `eval/baseline.json`).

    python -m eval.compare eval/reports/<ts>.json [--baseline eval/baseline.json] [--allow-regression]

A metric that got worse, or that had a value and now is n/a or gone, is a regression: exit 1, unless
`--allow-regression` (the PR then explains it, CLAUDE.md "Testing rules"). A PR that moves a metric on purpose
updates the baseline with `make eval-baseline`, so the change is reviewed.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import LOWER_IS_BETTER

BASELINE = Path(__file__).resolve().parent / "baseline.json"
EPSILON = 1e-9


def flatten(report: dict[str, Any]) -> dict[str, float | None]:
    """`drawings/<id>/scores/<section>/<metric>`, `.../panels/<panel>/<metric>`, `totals/...` → value."""
    out: dict[str, float | None] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict) and "value" in node and "den" in node:
            out[path] = node["value"]
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}/{k}" if path else k)

    for drawing, d in report.get("drawings", {}).items():
        walk(d["scores"], f"drawings/{drawing}/scores")
        walk(d["panels"], f"drawings/{drawing}/panels")
    walk(report.get("totals", {}), "totals")
    return out


@dataclass
class Change:
    path: str
    before: float | None
    after: float | None


@dataclass
class Comparison:
    regressions: list[Change] = field(default_factory=list)
    improvements: list[Change] = field(default_factory=list)
    new: list[Change] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.regressions


def compare(current: dict[str, Any], baseline: dict[str, Any]) -> Comparison:
    now, before = flatten(current), flatten(baseline)
    result = Comparison()
    for path in sorted(before.keys() | now.keys()):
        old, new = before.get(path), now.get(path)
        change = Change(path, old, new)
        if path not in before:
            result.new.append(change)
        elif old is None:
            if new is not None:
                result.new.append(change)  # was n/a, is measured now
        elif new is None:
            result.regressions.append(change)  # had a value; now n/a or gone
        else:
            delta = new - old if path.rsplit("/", 1)[-1] not in LOWER_IS_BETTER else old - new
            if delta < -EPSILON:
                result.regressions.append(change)
            elif delta > EPSILON:
                result.improvements.append(change)
    return result


def _v(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g}"


def markdown(result: Comparison) -> str:
    out = ["## Against the baseline", ""]
    if not (result.regressions or result.improvements or result.new):
        return "\n".join([*out, "No change.", ""])
    for title, changes in (
        ("Regressions", result.regressions),
        ("Improvements", result.improvements),
        ("New", result.new),
    ):
        if changes:
            out += [f"**{title}** ({len(changes)})", "", "| Metric | Baseline | Now |", "| --- | --- | --- |"]
            out += [f"| `{c.path}` | {_v(c.before)} | {_v(c.after)} |" for c in changes]
            out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--allow-regression", action="store_true")
    args = parser.parse_args(argv)
    result = compare(json.loads(args.report.read_text()), json.loads(args.baseline.read_text()))
    print(markdown(result))
    if result.ok:
        return 0
    print(f"{len(result.regressions)} metric(s) got worse than {args.baseline.name}.", file=sys.stderr)
    return 0 if args.allow_regression else 1


if __name__ == "__main__":
    sys.exit(main())
