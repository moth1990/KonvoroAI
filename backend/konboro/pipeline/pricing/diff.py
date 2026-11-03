"""07 §7.7: what changed between two versions of a quote, line by line, by how much and why.

Lines are paired by `line_key` (stage 7's stable handle), else by SKU and description within the panel, so a line
the user added by hand pairs with itself. Amounts are decimal strings, as everywhere in the contract (07 §6.1).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class LineSnap:
    """What a version says about one line."""

    key: str
    panel_id: str | None
    description: str
    sku: str | None
    qty: Decimal
    unit_price: Decimal | None
    line_total: Decimal | None
    unit_cost: Decimal | None = None
    cost_ref: str | None = None  # the price-list row or brand discount the cost came from
    rule_ref: str | None = None  # the margin rule, a fixed price or an override


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _pair_key(ln: LineSnap) -> str:
    return ln.key or f"{ln.panel_id}|{ln.sku}|{ln.description}"


def why(before: LineSnap, after: LineSnap) -> list[str]:
    out = []
    if before.sku != after.sku:
        out.append("sku")
    if before.qty != after.qty:
        out.append("qty")
    if before.unit_cost != after.unit_cost or before.cost_ref != after.cost_ref:
        out.append("cost")
    if before.rule_ref != after.rule_ref:
        out.append("margin_rule")
    if before.unit_price != after.unit_price and not out:
        out.append("price")
    return out


def diff(
    before: Sequence[LineSnap], after: Sequence[LineSnap], from_version: int, net_before: Decimal, net_after: Decimal
) -> dict[str, Any]:
    old = {_pair_key(ln): ln for ln in before}
    new = {_pair_key(ln): ln for ln in after}
    lines: list[dict[str, Any]] = []
    for key, a in new.items():
        b = old.get(key)
        if b is None:
            lines.append({"key": key, "change": "added", "description": a.description, "after": _snap(a)})
            continue
        reasons = why(b, a)
        if reasons or b.line_total != a.line_total:
            delta = (a.line_total or Decimal(0)) - (b.line_total or Decimal(0))
            lines.append(
                {
                    "key": key,
                    "change": "changed",
                    "description": a.description,
                    "before": _snap(b),
                    "after": _snap(a),
                    "delta": str(delta),
                    "why": reasons or ["price"],
                }
            )
    for key, b in old.items():
        if key not in new:
            lines.append({"key": key, "change": "removed", "description": b.description, "before": _snap(b)})
    return {
        "from_version": from_version,
        "lines": lines,
        "net_before": str(net_before),
        "net_after": str(net_after),
        "delta": str(net_after - net_before),
    }


def _snap(ln: LineSnap) -> dict[str, Any]:
    return {
        "sku": ln.sku,
        "qty": str(ln.qty),
        "unit_price": _s(ln.unit_price),
        "line_total": _s(ln.line_total),
    }
