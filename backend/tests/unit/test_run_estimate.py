"""The run's expected time and cost, and the time left (01 §4.6 "זמן שנותר", S28c)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from konboro.services import run_estimate as est
from konboro.services.run_estimate import Rate, StageTime, Units

A3 = (841.89, 1190.55)
A4 = (595.28, 841.89)
NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
QUOTE = list(range(1, 8))


def test_the_seed_gives_the_prototypes_nursery_run_for_nine_a3_pages() -> None:
    """The prototype's start bar for NURSERY's nine A4 pages: "9 עמודים · כ-3 דקות · כ-$0.44"."""
    found = est.estimate(QUOTE, est.units_before([A4] * 9, 9), est.SEED)
    assert round(found.seconds) == 152
    assert found.usd.quantize(Decimal("0.01")) == Decimal("0.44")


def test_a_page_counts_by_its_size_between_half_and_four() -> None:
    assert est.size_units([A4], 1) == 1
    assert est.size_units([A3], 1) == pytest.approx(2, abs=1e-3)  # an A3 is two A4s
    assert est.size_units([(A4[0] / 2, A4[1] / 2)], 1) == 0.5  # an A6 counts as half, the floor
    assert est.size_units([(4394, 2069)], 1) == 4  # 25.26.100, a designer's plan: capped at four
    assert est.size_units([], 3) == 3  # an image or a sheet: one each


def test_after_stage_1_pages_count_by_their_route() -> None:
    units = est.units_after(["process", "process", "context", "skip", None])
    assert units == Units(5, 3.25)  # stage 1 read all five; a page with no route yet is decoded
    assert est.stage_units(1, units) == 5
    assert est.stage_units(3, units) == 3.25


def test_the_medians_are_the_factorys_own_after_20_runs_else_everyones_else_the_seed() -> None:
    own = {3: (25, 9.0, 0.05)}
    every = {3: (40, 7.0, 0.04), 2: (40, 5.0, 0.02)}
    assert est.choose(own, every)[3] == Rate(9.0, Decimal("0.05"))
    assert est.choose(own, every)[2] == est.SEED[2]  # the factory's own has no stage 2: the seed's
    few = {3: (5, 9.0, 0.05)}
    assert est.choose(few, every)[3] == Rate(7.0, Decimal("0.04"))
    assert est.choose(few, {3: (19, 7.0, 0.04)}) == est.SEED


def times(*rows: tuple[int, str, int | None, int | None]) -> list[StageTime]:
    """(stage, status, started seconds ago, finished seconds ago)."""

    def at(ago: int | None) -> datetime | None:
        return NOW - timedelta(seconds=ago) if ago is not None else None

    return [StageTime(n, status, at(start), at(end)) for n, status, start, end in rows]


FLAT = {n: Rate(10.0, Decimal("0.01")) for n in range(1, 9)}  # 10 s a unit, every stage
ONE = Units(1, 1)


def test_time_left_is_the_stages_left_rounded_to_ten_seconds() -> None:
    left = est.time_left(times((1, "running", 4, None), (2, "queued", None, None)), ONE, FLAT, NOW, NOW - timedelta(4))
    assert left.seconds_left == 20  # 6 s left of stage 1, 10 s of stage 2: 16, rounded
    assert left.seconds_expected == 20


def test_slow_stages_make_the_rest_slower_up_to_double() -> None:
    four = Units(1, 4)  # stage 2 expects 40 s
    slow = times((1, "done", 60, 30), (2, "queued", None, None))  # 30 s where 10 were expected
    assert est.time_left(slow, four, FLAT, NOW, NOW - timedelta(seconds=60)).seconds_left == 80  # the cap: double
    fast = times((1, "done", 60, 58), (2, "queued", None, None))  # 2 s where 10 were expected
    assert est.time_left(fast, four, FLAT, NOW, NOW - timedelta(seconds=60)).seconds_left == 20  # the floor: half


def test_time_left_never_rises_more_than_a_fifth_at_once() -> None:
    rows = times(*[(n, "queued", None, None) for n in QUOTE])
    left = est.time_left(rows, ONE, FLAT, NOW, None, shown_left=40)
    assert left.seconds_left == 40  # 70 s expected, but the screen showed 40: at most 48, rounded down
    assert est.time_left(rows, ONE, FLAT, NOW, None, shown_left=0).seconds_left == 70  # nothing shown yet


def test_the_meter_is_elapsed_of_elapsed_and_left() -> None:
    rows = times((1, "done", 20, 10), (2, "running", 10, None), (3, "queued", None, None))
    left = est.time_left(rows, ONE, FLAT, NOW, NOW - timedelta(seconds=20))
    assert left.elapsed == 20
    assert left.seconds_left == 10
    assert round(left.fraction, 2) == 0.67
