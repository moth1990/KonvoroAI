"""07 §7.5: a line's final colour, the one place it is decided (00 §6.3). The worst of:

| Source | Green | Yellow | Red |
| --- | --- | --- | --- |
| the line's confidence (stages 3–5) | ≥ 0.85 | 0.5–0.85 | < 0.5 |
| the match (stage 5) | `matched` | `ambiguous` | `unmatched`, `conflict` |
| the validator (stage 6) | no finding, `info` | `warning` | `error` |
| the price (7.2) | `ok` | `stale`, `discount_based` | `missing` |
| the line type | | | `missing` |

A derived line is coloured by its price and its catalog query only; a manual line is green unless it has no price;
a required service ("חישוב חום") is yellow with no price, for the factory to decide. A kit part priced in its parent
("included") is green. Every reason is kept in `status_reasons`, not only the worst (09 §9).

A line the estimator approved (09 §7.2, §9) is green with "אושר", whatever its confidence, match or finding said: those
reasons are kept, turned green, with the colour they had in `was`. Its price still counts: approving does not price a
line that has none.
"""

from typing import Any

from .edits import APPROVED
from .lines import Draft

RANK = {"green": 0, "yellow": 1, "red": 2}
PRICE_STATUS = {"ok": "green", "stale": "yellow", "discount_based": "yellow", "missing": "red"}


def worst(statuses: list[str]) -> str:
    return max(statuses, key=RANK.__getitem__, default="green")


def price_reason(line: Draft) -> dict[str, Any]:
    """The price's reason keeps its pricing issues (07 §8) and the margin floor it fell under, so a line priced
    again from its stored row (`load.priced_as_stored`) reports what stage 7 found."""
    if line.included:
        return {"source": "price", "value": "included", "status": "green"}
    if line.derived and line.derived.get("service"):
        return {"source": "price", "value": "service", "status": "yellow"}
    out: dict[str, Any] = {
        "source": "price",
        "value": line.priced.price_status,
        "status": PRICE_STATUS[line.priced.price_status],
    }
    if line.priced.issues:
        out["issues"] = list(line.priced.issues)
    if line.priced.floor is not None:
        out["floor"] = str(line.priced.floor)
    return out


def finalize(line: Draft) -> None:
    if line.line_type in ("derived", "labor"):
        reasons = [r for r in line.reasons if r["source"] == "match" and r["status"] == "green"]
        if line.query_failed:
            reasons.append({"source": "match", "value": "unmatched", "status": "red"})
    elif line.line_type == "manual":
        reasons = [{"source": "user", "value": "manual", "status": "green"}]
    else:
        reasons = list(line.reasons)
    if line.approved and line.line_type != "manual":
        reasons = [APPROVED] + [
            r if r["status"] == "green" else {**r, "status": "green", "was": r["status"]} for r in reasons
        ]
    if not line.query_failed:
        reasons.append(price_reason(line))
    line.status_reasons = reasons
    line.status = worst([r["status"] for r in reasons])
