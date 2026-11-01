"""Line amounts and quote sums (07 §7.6, steps 4–10). Pure Decimal, never float (non-negotiable 5).

Stage 7 decides prices (S22). This module only multiplies and adds them up, so the write path, the read API and
stage 7 all get the same sums:
- `line_total` = unit price × qty and `line_cost` = unit cost × qty. Subtotals are not rounded (07 §7.6).
- A line with no price is left out of every sum and counted in `unpriced_count`.
- Margin counts only the lines that have both a price and a cost, after the quote discount. The priced lines with
  no cost are counted, so the screen can say how many are left out (09 §6.3).
- The discount and VAT are rounded to the agora.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

AGORA = Decimal("0.01")
RATE = Decimal("0.0001")
ZERO = Decimal("0")
STATUSES = ("green", "yellow", "red")


def margin_ratio(price: Decimal | None, cost: Decimal | None) -> Decimal | None:
    """Margin as a share of the price (07 §6.2: always shown as margin, even when the rule is a markup)."""
    if price is None or cost is None or price <= ZERO:
        return None
    return ((price - cost) / price).quantize(RATE, ROUND_HALF_UP)


@dataclass(frozen=True)
class LineAmounts:
    line_total: Decimal | None
    line_cost: Decimal | None
    margin_pct: Decimal | None


def line_amounts(qty: Decimal, unit_price: Decimal | None, unit_cost: Decimal | None) -> LineAmounts:
    total = unit_price * qty if unit_price is not None else None
    cost = unit_cost * qty if unit_cost is not None else None
    return LineAmounts(total, cost, margin_ratio(unit_price, unit_cost))


@dataclass(frozen=True)
class LineFigures:
    """What the sums need from one live (not deleted) line."""

    status: str
    line_total: Decimal | None
    line_cost: Decimal | None


@dataclass(frozen=True)
class Sums:
    cost_total: Decimal = ZERO  # cost of the priced lines that have one
    price_total: Decimal = ZERO
    costed_price_total: Decimal = ZERO  # price of the lines that count toward margin
    line_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATUSES, 0))
    unpriced_count: int = 0
    uncosted_count: int = 0  # priced lines, with a non-zero total, that have no cost


def sum_lines(lines: Iterable[LineFigures]) -> Sums:
    cost = price = costed = ZERO
    counts = dict.fromkeys(STATUSES, 0)
    unpriced = uncosted = 0
    for line in lines:
        counts[line.status] += 1
        if line.line_total is None:
            unpriced += 1
            continue
        price += line.line_total
        if line.line_cost is None:
            # A kit add-on included in its parent's price (0.00) has no cost of its own to miss.
            uncosted += line.line_total != ZERO
            continue
        cost += line.line_cost
        costed += line.line_total
    return Sums(cost, price, costed, counts, unpriced, uncosted)


def merge(parts: Iterable[Sums]) -> Sums:
    """The quote's sums from its panels' sums."""
    ps = list(parts)
    return Sums(
        sum((p.cost_total for p in ps), ZERO),
        sum((p.price_total for p in ps), ZERO),
        sum((p.costed_price_total for p in ps), ZERO),
        {k: sum(p.line_counts[k] for p in ps) for k in STATUSES},
        sum(p.unpriced_count for p in ps),
        sum(p.uncosted_count for p in ps),
    )


@dataclass(frozen=True)
class QuoteSums:
    sums: Sums
    discount_pct: Decimal | None
    discount: Decimal | None
    net_total: Decimal
    margin_abs: Decimal
    margin_pct: Decimal | None
    vat_rate: Decimal
    vat: Decimal
    gross_total: Decimal


def quote_sums(sums: Sums, discount_pct: Decimal | None, vat_rate: Decimal) -> QuoteSums:
    """07 §7.6 steps 6–10. The discount comes off the quote, not off line prices."""
    discount = (sums.price_total * discount_pct).quantize(AGORA, ROUND_HALF_UP) if discount_pct else None
    off = discount or ZERO
    net = sums.price_total - off
    margin_base = sums.costed_price_total - off
    margin_abs = margin_base - sums.cost_total
    margin_pct = (margin_abs / margin_base).quantize(RATE, ROUND_HALF_UP) if margin_base > ZERO else None
    vat = (net * vat_rate).quantize(AGORA, ROUND_HALF_UP)
    return QuoteSums(sums, discount_pct or None, discount, net, margin_abs, margin_pct, vat_rate, vat, net + vat)
