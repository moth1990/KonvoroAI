"""Pricing rules as pure functions (07 §7.2–7.3, 10 §8). `Decimal` only, never float (non-negotiable 5), and no
database: the service maps rows to these dataclasses. 100% branch coverage is enforced (07 §10.1).

- `fx`: the rate a quote date uses (S18 decision 4).
- `cost`: which cost enters a quote, and its `price_status` (07 §7.2, §7.2.2).
- `margin`: the margin rule that applies, its formula, and the margin floors (07 §7.3).
- `sanity`: the checks on a cost typed by hand (10 §8).
"""

from decimal import ROUND_HALF_UP, Decimal

# Money is numeric(14,4) in the database: a computed cost or price keeps 4 places. Rounding to the agora is 07 §7.6's.
MONEY = Decimal("0.0001")
ZERO = Decimal("0")
ONE = Decimal("1")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, ROUND_HALF_UP)
