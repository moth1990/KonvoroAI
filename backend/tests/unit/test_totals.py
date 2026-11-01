"""Line amounts and quote sums (07 §7.6). Pricing code: every branch is covered (07 §10.1)."""

from decimal import Decimal as D

import pytest

from konboro.domain.totals import (
    LineFigures,
    Sums,
    line_amounts,
    margin_ratio,
    merge,
    quote_sums,
    sum_lines,
)


@pytest.mark.parametrize(
    ("price", "cost", "expected"),
    [
        (D("750"), D("545"), D("0.2733")),
        (D("130"), D("96"), D("0.2615")),
        (None, D("10"), None),
        (D("10"), None, None),
        (D("0"), D("0"), None),  # a kit add-on included in its parent's price
        (D("-5"), D("1"), None),
    ],
)
def test_margin_is_a_share_of_the_price(price: D | None, cost: D | None, expected: D | None) -> None:
    assert margin_ratio(price, cost) == expected


def test_line_amounts_multiply_without_rounding() -> None:
    a = line_amounts(D("2.5"), D("182.78"), D("142.80"))  # 07 §6.1's line, sold by the metre
    assert a.line_total == D("456.950")
    assert a.line_cost == D("357.000")
    assert a.margin_pct == D("0.2187")


def test_a_line_with_no_price_or_no_cost_has_no_amount() -> None:
    no_price = line_amounts(D(4), None, D("10"))
    assert (no_price.line_total, no_price.line_cost, no_price.margin_pct) == (None, D("40"), None)
    no_cost = line_amounts(D(1), D("340"), None)
    assert (no_cost.line_total, no_cost.line_cost, no_cost.margin_pct) == (D("340"), None, None)


def test_sums_leave_out_unpriced_lines_and_count_uncosted_ones() -> None:
    s = sum_lines(
        [
            LineFigures("green", D("750"), D("545")),
            LineFigures("green", D("340"), None),  # priced, no cost: out of the margin, counted
            LineFigures("green", D("0"), None),  # included in its parent: not a missing cost
            LineFigures("red", None, None),
            LineFigures("yellow", None, D("12")),  # a cost alone doesn't make a price
        ]
    )
    assert s.price_total == D("1090")
    assert s.cost_total == D("545")
    assert s.costed_price_total == D("750")
    assert s.line_counts == {"green": 3, "yellow": 1, "red": 1}
    assert (s.unpriced_count, s.uncosted_count) == (2, 1)


def test_merge_adds_panels_and_an_empty_quote_is_zero() -> None:
    a = sum_lines([LineFigures("green", D("100"), D("60")), LineFigures("red", None, None)])
    b = sum_lines([LineFigures("yellow", D("50"), None)])
    m = merge([a, b])
    assert (m.price_total, m.cost_total, m.costed_price_total) == (D("150"), D("60"), D("100"))
    assert m.line_counts == {"green": 1, "yellow": 1, "red": 1}
    assert (m.unpriced_count, m.uncosted_count) == (1, 1)
    assert merge([]) == Sums()


def test_quote_sums_without_discount() -> None:
    q = quote_sums(sum_lines([LineFigures("green", D("4674"), D("3139.5"))]), None, D("0.18"))
    assert q.discount is None and q.discount_pct is None
    assert q.net_total == D("4674")
    assert q.margin_abs == D("1534.5")
    assert q.margin_pct == D("0.3283")
    assert (q.vat, q.gross_total) == (D("841.32"), D("5515.32"))


def test_a_zero_discount_is_no_discount() -> None:
    q = quote_sums(sum_lines([LineFigures("green", D("100"), D("50"))]), D("0"), D("0.18"))
    assert q.discount is None and q.discount_pct is None


def test_the_discount_comes_off_the_quote_and_its_margin() -> None:
    """07 §6.1's example: 11236.90 with 3% off is 10899.79 before VAT."""
    sums = sum_lines([LineFigures("green", D("11236.90"), D("8420.50"))])
    q = quote_sums(sums, D("0.03"), D("0.18"))
    assert q.discount == D("337.11")
    assert q.net_total == D("10899.79")
    assert q.margin_abs == D("2479.29")
    assert q.margin_pct == D("0.2275")
    assert q.vat == D("1961.96")


def test_no_margin_when_nothing_has_a_cost() -> None:
    q = quote_sums(sum_lines([LineFigures("green", D("340"), None)]), None, D("0.18"))
    assert q.margin_abs == D("0")
    assert q.margin_pct is None
