"""The pricing backtest (07 §10.2): our total before VAT against the real quote's, within ±5%, and our derived items
and labor against the quote's, within ±10% (`eval/backtest.py`, priced from the drawing's own quote, S22 decision 1).

The real quotes left out items the factory confirmed (11), so a gap is not always ours: the report shows the
confirmed value at risk next to it (S06 decision). The leave-one-out numbers are reported, not scored.
"""

from decimal import Decimal

from .score import Score, Scores

TOLERANCE = Decimal("0.05")
DERIVED_TOLERANCE = Decimal("0.10")


def score(actual: Decimal | None, ours: Decimal | None, backtest: dict[str, str | None] | None = None) -> Scores:
    if actual is None or actual == 0:
        return {}
    if ours is None:
        return {"backtest_within_5pct": Score.na(), "backtest_deviation": Score.na("mean")}
    deviation = abs(ours - actual) / actual
    out = {
        "backtest_within_5pct": Score.of(deviation <= TOLERANCE),
        "backtest_deviation": Score(num=float(round(deviation, 6)), den=1, kind="mean"),
    }
    theirs, mine = (backtest or {}).get("quote_derived"), (backtest or {}).get("own_derived")
    if theirs is not None and mine is not None and Decimal(theirs) > 0:
        gap = abs(Decimal(mine) - Decimal(theirs)) / Decimal(theirs)
        out["backtest_derived_within_10pct"] = Score.of(gap <= DERIVED_TOLERANCE)
        out["backtest_derived_deviation"] = Score(num=float(round(gap, 6)), den=1, kind="mean")
    return out
