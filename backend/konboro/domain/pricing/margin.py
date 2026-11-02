"""Sale price from margin rules (07 §7.3).

The most specific rule in force wins: `customer_sku` > `customer` > `sku` > `family` > `brand` > `default`.
`target` is the product id for `customer_sku` and `sku`, the family or the brand for those levels, and empty for
`customer` and `default`; the customer levels also match `customer_id`.

A product with `sale_mode` = `fixed` is the `sku`-level rule with its `fixed_price` (S18 decision 6): one store, the
product row, and the customer levels still beat it. Stored `sku` rules apply only to a product priced by rule.

Several rules in force at one level: the latest `valid_from`, then the highest version, then the id.

Formulas: `markup` price = cost × (1 + value); `margin` price = cost / (1 − value), value < 1; `fixed` price =
fixed_price. The margin floors only report (07 §7.3): they never change a price.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from konboro.domain.totals import margin_ratio

from . import ONE, money

Level = Literal["customer_sku", "customer", "sku", "family", "brand", "default"]
LEVELS: tuple[Level, ...] = ("customer_sku", "customer", "sku", "family", "brand", "default")


@dataclass(frozen=True)
class Rule:
    id: str
    level: Level
    kind: Literal["markup", "margin"] = "markup"
    value: Decimal | None = None
    fixed_price: Decimal | None = None
    target: str | None = None
    customer_id: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    version: int = 1


@dataclass(frozen=True)
class Subject:
    """What a rule can be for: the product, and the quote's customer."""

    product_id: str
    family: str
    brand: str | None
    sale_mode: Literal["rule", "fixed"] = "rule"
    fixed_price: Decimal | None = None
    customer_id: str | None = None


@dataclass(frozen=True)
class Sale:
    unit_price_raw: Decimal | None  # before 07 §7.6's rounding
    rule: dict[str, str | None] | None  # 07 §6.2 `margin_rule`, for the trace
    issue: Literal["no_margin_rule"] | None = None


class InvalidRule(ValueError):
    pass


def check(rule: Rule) -> None:
    """The database checks the same (`value_or_fixed`, `margin_below_one`); this says why before a write."""
    if (rule.value is None) == (rule.fixed_price is None):
        raise InvalidRule("a rule has a percentage or a fixed price, not both")
    if rule.kind == "margin" and rule.value is not None and rule.value >= ONE:
        raise InvalidRule("a margin must be below 100%")


def in_force(rule: Rule, on_date: date) -> bool:
    return (rule.valid_from is None or rule.valid_from <= on_date) and (
        rule.valid_to is None or rule.valid_to >= on_date
    )


def same_customer(rule: Rule, subject: Subject) -> bool:
    return subject.customer_id is not None and rule.customer_id == subject.customer_id


def applies(rule: Rule, subject: Subject) -> bool:
    match rule.level:
        case "customer_sku":
            return same_customer(rule, subject) and rule.target == subject.product_id
        case "customer":
            return same_customer(rule, subject)
        case "sku":
            return subject.sale_mode == "rule" and rule.target == subject.product_id
        case "family":
            return rule.target == subject.family
        case "brand":
            return subject.brand is not None and rule.target == subject.brand
        case _:  # "default": every product (the database allows no other level)
            return True


def product_rule(subject: Subject) -> Rule | None:
    if subject.sale_mode == "fixed" and subject.fixed_price is not None:
        return Rule(id=subject.product_id, level="sku", fixed_price=subject.fixed_price, target=subject.product_id)
    return None


def pick(rules: Sequence[Rule], subject: Subject, on_date: date) -> Rule | None:
    live = [r for r in rules if in_force(r, on_date) and applies(r, subject)]
    fixed = product_rule(subject)
    if fixed is not None:
        live.append(fixed)
    if not live:
        return None
    rank = {level: i for i, level in enumerate(LEVELS)}
    return min(live, key=lambda r: (rank[r.level], -(r.valid_from or date.min).toordinal(), -r.version, r.id))


def price(cost: Decimal | None, rule: Rule) -> Decimal | None:
    check(rule)
    if rule.fixed_price is not None:
        return rule.fixed_price
    if cost is None:
        return None
    value = cast(Decimal, rule.value)  # check(): a rule without a fixed price has a percentage
    if rule.kind == "margin":
        return money(cost / (ONE - value))
    return money(cost * (ONE + value))


def sale_price(cost: Decimal | None, rules: Sequence[Rule], subject: Subject, on_date: date) -> Sale:
    rule = pick(rules, subject, on_date)
    if rule is None:
        return Sale(None, None, "no_margin_rule")
    trace: dict[str, str | None] = {
        "rule_id": rule.id,
        "level": rule.level,
        "kind": "fixed" if rule.fixed_price is not None else rule.kind,
        "value": str(rule.value) if rule.value is not None else None,
        "fixed_price": str(rule.fixed_price) if rule.fixed_price is not None else None,
    }
    return Sale(price(cost, rule), trace)


@dataclass(frozen=True)
class FloorFinding:
    code: Literal["below_margin_floor", "quote_below_margin_floor"]
    margin_pct: Decimal
    floor: Decimal


def line_floor(unit_price: Decimal | None, unit_cost: Decimal | None, floor: Decimal | None) -> FloorFinding | None:
    """07 §7.3: a line's margin below `min_line_margin` is a finding and a tag, never a new price."""
    margin = margin_ratio(unit_price, unit_cost)
    if floor is None or margin is None or margin >= floor:
        return None
    return FloorFinding("below_margin_floor", margin, floor)


def quote_floor(margin_pct: Decimal | None, floor: Decimal | None) -> FloorFinding | None:
    """The quote's margin (`totals.quote_sums`) below `min_quote_margin`: a finding in the quote's header."""
    if floor is None or margin_pct is None or margin_pct >= floor:
        return None
    return FloorFinding("quote_below_margin_floor", margin_pct, floor)
