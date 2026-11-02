"""Currency conversion (07 §7.2 "מטבע"; S18 decision 4).

`fx_rates` holds how many units of the quote currency (ILS) one unit of a foreign currency costs, by date. A quote
uses the latest rate on or before its date, at most `MAX_AGE_DAYS` old (weekends and holidays have none). With no
such rate the line has no price (`fx_rate_missing`, 07 §8). A v1.0 quote is in ILS (07 §13.5).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from . import money

MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class FxRate:
    currency: str
    rate_date: date
    rate: Decimal


@dataclass(frozen=True)
class Converted:
    amount: Decimal
    original_currency: str | None = None  # null when no conversion was needed
    original_amount: Decimal | None = None
    fx_rate: Decimal | None = None
    fx_date: date | None = None


class FxRateMissing(Exception):
    def __init__(self, currency: str, on_date: date) -> None:
        super().__init__(f"no {currency} rate within {MAX_AGE_DAYS} days before {on_date}")
        self.currency = currency
        self.on_date = on_date


def rate_for(rates: Iterable[FxRate], currency: str, on_date: date) -> FxRate:
    usable = [
        r
        for r in rates
        if r.currency == currency and r.rate_date <= on_date and (on_date - r.rate_date).days <= MAX_AGE_DAYS
    ]
    if not usable:
        raise FxRateMissing(currency, on_date)
    return max(usable, key=lambda r: r.rate_date)


def convert(amount: Decimal, currency: str, to_currency: str, rates: Iterable[FxRate], on_date: date) -> Converted:
    if currency == to_currency:
        return Converted(amount)
    rate = rate_for(rates, currency, on_date)
    return Converted(money(amount * rate.rate), currency, amount, rate.rate, rate.rate_date)
