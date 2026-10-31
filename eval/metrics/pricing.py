"""The pricing backtest (07 §10.2): our total before VAT against the real quote's, within ±5%.

The real quotes left out items the factory confirmed (11), so a gap is not always ours: the report shows the
confirmed value at risk next to it (S06 decision).
"""

from decimal import Decimal

from .score import Score, Scores

TOLERANCE = Decimal("0.05")


def score(actual: Decimal | None, ours: Decimal | None) -> Scores:
    if actual is None or actual == 0:
        return {}
    if ours is None:
        return {"backtest_within_5pct": Score.na(), "backtest_deviation": Score.na("mean")}
    deviation = abs(ours - actual) / actual
    return {
        "backtest_within_5pct": Score.of(deviation <= TOLERANCE),
        "backtest_deviation": Score(num=float(round(deviation, 6)), den=1, kind="mean"),
    }
