"""06 §6.3: the designer's BOM against the quote, in code. One of the strongest checks: the BOM is a source the
pipeline did not make.

1. Each BOM row is read as stage 4 reads a row (`association.bom`, 04 §5.1) and signed: its family and the values that
   tell products apart (`KEYS`), as written.
2. The quote's components are signed the same way, from their final values, per panel (a table that names its panel)
   or for the whole drawing (one that names none).
3. Signatures pair exactly, then a row that left a value out pairs with the quote's rows that have it ("מא"ז 16A" with
   the 3P C16 ones). What is left is missing from the quote, or extra in it; a pair with other quantities differs.

On a BOM-only drawing the BOM is what the quote is made of, and there is nothing to compare (`bom_is_the_source`).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.merge import Component
from konboro.contracts.validation import BomCrosscheck, QtyDiff
from konboro.pipeline.matching import catalog, text

from .checks import Hit, count_text, sku_like
from .model import Device

KEYS = ("current_a", "poles", "residual_ma")
RULES = ("BOM_MISSING_IN_QUOTE", "BOM_EXTRA_IN_QUOTE", "BOM_QTY_DIFF", "BOM_SKU_DIFF")


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else v


def sign(family: str, values: dict[str, Any]) -> str:
    parts = [family] + [
        f"{k}={text.number(values[k]) if isinstance(values[k], int | float) else values[k]}"
        for k in KEYS
        if values.get(k) is not None
    ]
    return "|".join(parts)


def _fits(bom_values: dict[str, Any], quote_values: dict[str, Any]) -> bool:
    return all(_num(quote_values.get(k)) == _num(v) for k, v in bom_values.items() if v is not None)


@dataclass
class Side:
    signature: str
    family: str
    values: dict[str, Any]
    qty: int
    devices: list[Device] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def _what(family: str, values: dict[str, Any]) -> str:
    return text.describe(family, None, "", None, values).replace("  ", " ").strip()


def _bom_sides(rows: list[Component]) -> list[Side]:
    by: dict[str, Side] = {}
    for c in rows:
        if c.family == "unknown":
            continue
        values = {k: c.attributes[k].value for k in KEYS if k in c.attributes and c.attributes[k].value is not None}
        sig = sign(c.family, values)
        side = by.setdefault(sig, Side(sig, c.family, values, 0))
        side.qty += c.quantity
        side.texts += c.explicit_texts
    return list(by.values())


def _quote_sides(devices: list[Device]) -> list[Side]:
    by: dict[str, Side] = {}
    for d in devices:
        values = {k: d.values[k] for k in KEYS if d.values.get(k) is not None}
        sig = sign(d.family, values)
        side = by.setdefault(sig, Side(sig, d.family, values, 0))
        side.qty += d.component.quantity
        side.devices.append(d)
    return list(by.values())


@dataclass
class Outcome:
    hits: dict[str, list[Hit]]
    summary: BomCrosscheck


def compare(rows: list[Component], devices: list[Device]) -> Outcome:
    bom = _bom_sides(rows)
    families = {b.family for b in bom}
    quote = [q for q in _quote_sides([d for d in devices if d.billable and d.in_panel]) if q.family in families]
    paired: dict[str, list[Side]] = defaultdict(list)
    left = {q.signature: q for q in quote}
    for b in bom:  # exact first
        if b.signature in left:
            paired[b.signature].append(left.pop(b.signature))
    for b in bom:  # then a row that left a value out
        if paired[b.signature]:
            continue
        fits = [q for q in left.values() if q.family == b.family and _fits(b.values, q.values)]
        for q in fits:
            paired[b.signature].append(left.pop(q.signature))
    hits: dict[str, list[Hit]] = {r: [] for r in RULES}
    missing, diffs = [], []
    matched = 0
    for b in bom:
        qs = paired[b.signature]
        what = _what(b.family, b.values)
        if not qs:
            missing.append(b.signature)
            hits["BOM_MISSING_IN_QUOTE"].append(Hit(values={"signature": b.signature, "bom_qty": b.qty, "what": what}))
            continue
        matched += 1
        quote_qty = sum(q.qty for q in qs)
        ids = [d.id for q in qs for d in q.devices]
        if quote_qty != b.qty:
            diffs.append(QtyDiff(signature=b.signature, bom_qty=b.qty, quote_qty=quote_qty))
            v = {"signature": b.signature, "bom_qty": b.qty, "quote_qty": quote_qty, "what": what}
            hits["BOM_QTY_DIFF"].append(Hit(ids, values=v))
        written = [t for t in b.texts if sku_like(t)]
        chosen = {catalog.norm_sku(d.match.chosen_sku) for q in qs for d in q.devices if d.match and d.match.chosen_sku}
        for t in written:
            n = catalog.norm_sku(t)
            if chosen and not any(n in c or c in n for c in chosen):
                skus = ", ".join(
                    sorted({d.match.chosen_sku for q in qs for d in q.devices if d.match and d.match.chosen_sku})
                )
                hits["BOM_SKU_DIFF"].append(Hit(ids, values={"bom_sku": t, "sku": skus, "what": what}))
                break
    extra = list(left.values())
    for q in extra:
        what = count_text(q.devices)
        v = {"signature": q.signature, "quote_qty": q.qty, "what": _what(q.family, q.values), "designators": what}
        hits["BOM_EXTRA_IN_QUOTE"].append(Hit([d.id for d in q.devices], values=v))
    summary = BomCrosscheck(
        available=True,
        matched_signatures=matched,
        missing_in_quote=missing,
        extra_in_quote=[q.signature for q in extra],
        qty_diffs=diffs,
    )
    return Outcome(hits, summary)
