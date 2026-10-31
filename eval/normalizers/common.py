"""What every normalizer shares: page kinds and routes, designators, attributes, and the real quote."""

import re
from decimal import Decimal
from typing import Any

from konboro.contracts.intake import Route

from ..canonical import CanonAudit, CanonDifference, CanonPage, DifferenceType

# Known quirks in the label files (CLAUDE.md, "Known spec inconsistencies").
KIND_ALIASES = {"single_line": "single_line_diagram"}

# A page without a route gets the one the other golden files give its kind (S06 decision). 01 §7 has no row for
# technical_data or factory_template yet; that is fixed in S08, not here.
ROUTE_BY_KIND: dict[str, Route] = {
    "technical_data": "context",
    "panel_front_view": "context",
    "factory_template": "skip",
    "single_line_diagram": "process",
    "control_diagram": "process",
}


def pages(raw: list[dict[str, Any]]) -> tuple[CanonPage, ...]:
    out = []
    for page in raw:
        kind = KIND_ALIASES.get(page["kind"], page["kind"])
        out.append(CanonPage(no=page["no"], kind=kind, route=page.get("route") or ROUTE_BY_KIND.get(kind)))
    return tuple(out)


_RANGE = re.compile(r"^([A-Z]+)(\d+)\s*[–-]\s*\1?(\d+)$")  # "F1–F17", "C1-C5"


def designators(raw: list[str] | None) -> tuple[str, ...]:
    """Ranges expanded, so "F1–F17" overlaps with a predicted "F3"."""
    out: list[str] = []
    for d in raw or []:
        m = _RANGE.match(d.strip())
        if m and int(m[2]) < int(m[3]):
            out.extend(f"{m[1]}{n}" for n in range(int(m[2]), int(m[3]) + 1))
        else:
            out.append(d.strip())
    return tuple(out)


def attributes(raw: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (raw or {}).items() if v is not None}


_POLES = re.compile(r"\b(\d)P(\+N)?\b")
_CURRENT = re.compile(r"(?<![\dX×])(\d+(?:\.\d+)?)A\b")


def attributes_from_text(product: str) -> dict[str, Any]:
    """For a label that writes current and poles only in the product name ("מא\"ז ABB S203M 3P ‏20A"). A minimum
    ("‏16A לפחות") is not a rating, so it is left out."""
    out: dict[str, Any] = {}
    if m := _POLES.search(product):
        out["poles"] = int(m[1])
        if m[2]:
            out["neutral"] = True
    if "לפחות" not in product and (m := _CURRENT.search(product)):
        value = float(m[1])
        out["current_a"] = int(value) if value.is_integer() else value
    return out


def _money(value: float | int | str | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def quote_total(quote: dict[str, Any] | None) -> Decimal | None:
    """The real quote's total before VAT (07 §10.2): `subtotal` or `total_before_vat`."""
    if quote is None:
        return None
    return _money(quote.get("subtotal", quote.get("total_before_vat")))


DIFFERENCE_TYPES: dict[str, DifferenceType] = {"missing": "missing_in_quote", "quantity_mismatch": "quantity_mismatch"}


def audit(quote: dict[str, Any] | None) -> CanonAudit | None:
    """The differences the factory confirmed (11 §10). Two shapes: `comparison.differences[]` with a `type`, and
    NEVIS-1's `comparison_with_labels` with one list per kind."""
    if quote is None:
        return None
    diffs: list[CanonDifference] = []
    if "comparison" in quote:
        comparison = quote["comparison"]
        for d in comparison["differences"]:
            if d["type"] == "not_a_difference" or not d.get("confirmed_by_factory"):
                continue
            diffs.append(
                CanonDifference(
                    type=DIFFERENCE_TYPES[d["type"]],
                    item=d["item"],
                    designators=designators(d.get("designators")),
                    value_at_risk=_money(d.get("value_at_risk")),
                )
            )
        return CanonAudit(matched=comparison.get("matched_lines"), differences=tuple(diffs))
    comparison = quote["comparison_with_labels"]  # confirmed as a whole: NEVIS-1 labels, verified_with_factory
    lists: tuple[tuple[str, DifferenceType], ...] = (
        ("in_drawing_not_in_quote", "missing_in_quote"),
        ("quantity_differences", "quantity_mismatch"),
    )
    for key, kind in lists:
        for d in comparison.get(key, []):
            diffs.append(CanonDifference(type=kind, item=d["what"], designators=designators(d["designators"])))
    return CanonAudit(matched=comparison.get("lines_matching_drawing"), differences=tuple(diffs))
