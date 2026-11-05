"""`compare` with another quote of the same factory (08 §6.5): lines are paired by the component's signature (05 §3),
because the two quotes' line ids differ.

Pairing, in code:
1. A line's key is its signature; a line with none (a kit part, a derived or manual line, a family with no schema)
   is keyed by its SKU, and a line with neither by its description.
2. Within one key, a line pairs first with a line of the same SKU, then with the next one in the quote's order.
3. What is left on one side is added or removed.

A pair is "changed" when its SKU, manufacturer, quantity or unit price differ; an unchanged pair is not listed. The
amounts stay amounts here: the tool turns them into references (08 §5.4).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol


class LineLike(Protocol):
    id: str
    position: int
    line_type: str
    signature: str | None
    sku: str | None
    manufacturer: str | None
    description: str
    qty: Decimal
    unit_price: Decimal | None
    line_total: Decimal | None


Change = Literal["added", "removed", "changed"]
FIELDS = ("sku", "manufacturer", "qty", "unit_price")


@dataclass(frozen=True)
class Pair:
    change: Change
    before: LineLike | None  # the other quote's line
    after: LineLike | None  # the open quote's line
    fields: tuple[str, ...]  # what differs, for a changed pair

    @property
    def difference(self) -> Decimal | None:
        """The open quote's line total minus the other's; a side with no price leaves it unknown."""
        b = self.before.line_total if self.before else Decimal(0)
        a = self.after.line_total if self.after else Decimal(0)
        if b is None or a is None:
            return None
        return a - b


def key_of(line: LineLike) -> tuple[str, str]:
    if line.signature:
        return ("signature", line.signature)
    if line.sku:
        return ("sku", line.sku.strip().upper())
    return ("description", " ".join(line.description.split()))


def _differs(b: LineLike, a: LineLike) -> tuple[str, ...]:
    return tuple(f for f in FIELDS if getattr(b, f) != getattr(a, f))  # Decimal("4") == Decimal("4.000")


def pair(before: Sequence[LineLike], after: Sequence[LineLike]) -> list[Pair]:
    """Every line of both quotes, paired; in the open quote's order, then the other quote's removed lines."""
    pool: dict[tuple[str, str], list[LineLike]] = defaultdict(list)
    for b in sorted(before, key=lambda x: x.position):
        pool[key_of(b)].append(b)
    out: list[Pair] = []
    for a in sorted(after, key=lambda x: x.position):
        group = pool.get(key_of(a), [])
        match = next((b for b in group if b.sku == a.sku), None) or (group[0] if group else None)
        if match is None:
            out.append(Pair("added", None, a, ()))
            continue
        group.remove(match)
        out.append(Pair("changed", match, a, _differs(match, a)))
    for group in pool.values():
        out += [Pair("removed", b, None, ()) for b in group]
    return out


def changed(pairs: list[Pair]) -> list[Pair]:
    """The pairs that differ: added, removed, and changed ones with a field that moved."""
    return [p for p in pairs if p.change != "changed" or p.fields]
