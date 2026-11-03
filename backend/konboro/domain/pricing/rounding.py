"""Rounding (07 §7.6; S22 decision 2).

Only the unit price is rounded, by the factory's setting: to the agora (the default), or to a whole shekel, 5 or
10 shekels. VAT is rounded to the agora (`totals.quote_sums`). Subtotals are never rounded: a line's total is the
rounded unit price × qty, and the sums add those up.

Half up, as in every other rounding here. A price of 0.00 stays 0.00, so a kit add-on included in its parent's
price is never rounded up to a shekel.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Rounding = Literal["agora", "shekel", "five", "ten"]
MODES: tuple[Rounding, ...] = ("agora", "shekel", "five", "ten")
STEPS: dict[Rounding, Decimal] = {
    "agora": Decimal("0.01"),
    "shekel": Decimal("1"),
    "five": Decimal("5"),
    "ten": Decimal("10"),
}
AGORA = Decimal("0.01")


class UnknownRounding(ValueError):
    pass


def mode(value: str | None) -> Rounding:
    """The factory's setting, checked: an unknown value is a bug in the settings, not a reason to guess."""
    if value is None:
        return "agora"
    if value not in STEPS:
        raise UnknownRounding(value)
    return value  # checked just above


def round_price(raw: Decimal, rounding: Rounding) -> Decimal:
    step = STEPS[rounding]
    # to a multiple of the step, half up; kept to the agora so every stored price has the same scale
    return ((raw / step).quantize(Decimal("1"), ROUND_HALF_UP) * step).quantize(AGORA)
