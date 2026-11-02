"""Checks on a cost typed by hand (10 §8). A typo (1920 for 19.20) or a sale price typed as a cost would price every
later quote, so the entry is checked when it is made. Every check only warns: the user can save anyway.

- Against the manufacturer's list price, when the catalog has one: above it, or below 30% of it.
- Against similar products of the same factory (same family, brand and current, chosen by the caller): 3 times
  their median or more, or a third of it or less.
- Against the product's previous cost: a change of more than 50%.

Only the factory's own prices and the public list price are used, never another factory's (10 §8, §11). Amounts
are in one currency, the caller's.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Literal

LIST_LOW = Decimal("0.3")
SIMILAR_FACTOR = Decimal("3")
JUMP = Decimal("0.5")
RATIO = Decimal("0.01")

Code = Literal["far_from_list", "far_from_similar", "jump_from_previous"]


@dataclass(frozen=True)
class Warning:
    code: Code
    reference: Decimal  # the price it was compared with
    reference_date: date | None = None


@dataclass(frozen=True)
class Sanity:
    list_price: Decimal | None
    ratio_to_list: Decimal | None
    warnings: list[Warning] = field(default_factory=list)

    def as_json(self) -> dict[str, object]:
        """`products.sanity` (10 §9.2). The ratio is a string like every number here (non-negotiable 5)."""
        return {
            "list_price": str(self.list_price) if self.list_price is not None else None,
            "ratio_to_list": str(self.ratio_to_list) if self.ratio_to_list is not None else None,
            "warning_shown": bool(self.warnings),
            "warnings": [
                {
                    "code": w.code,
                    "reference": str(w.reference),
                    "reference_date": w.reference_date.isoformat() if w.reference_date else None,
                }
                for w in self.warnings
            ],
        }


def check_cost(
    cost: Decimal,
    list_price: Decimal | None = None,
    similar_costs: Sequence[Decimal] = (),
    previous: tuple[Decimal, date] | None = None,
) -> Sanity:
    warnings: list[Warning] = []
    ratio = None
    if list_price is not None and list_price > 0:
        ratio = (cost / list_price).quantize(RATIO, ROUND_HALF_UP)
        if cost > list_price or cost < list_price * LIST_LOW:
            warnings.append(Warning("far_from_list", list_price))
    if similar_costs:
        mid = Decimal(median(similar_costs))
        if mid > 0 and (cost >= mid * SIMILAR_FACTOR or cost * SIMILAR_FACTOR <= mid):
            warnings.append(Warning("far_from_similar", mid))
    if previous is not None:
        old, when = previous
        if old > 0 and abs(cost - old) / old > JUMP:
            warnings.append(Warning("jump_from_previous", old, when))
    return Sanity(list_price, ratio, warnings)
