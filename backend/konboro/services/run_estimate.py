"""How long a run takes and what it costs, before it starts and while it runs (01 §4.6 "זמן שנותר", S28c).

A stage's time and cost grow with its pages, so the rates are per page unit:
- Stage 1 reads every page: one unit each.
- Stages 2–8 work on the decoded pages: a `process` page is one unit, a `context` page a quarter, a `skip` page none.
- Before stage 1 the routes are not known (01 §4.6, item 4): each page counts by its size, an A4 page (the factory
  drawings' size, NURSERY's) being one, between half (a photo) and four (a designer's plan of A2 or more), and the
  decoded share of a drawing is assumed (`WORK_SHARE`).

The rates are medians over the last 30 days: a factory's own once it has 20 runs, else every factory's
(`konboro_stage_medians`, migration 0027) once there are 20 in all, else the seed below.

The seed is the prototype's NURSERY run (prototype `STAGES`): 9 pages, 6 decoded and 1 for context. A live eval run
replaces it later (the roadmap's backlog, S28c decision 2).

Time left is the remaining stages' expected time, scaled by how the finished stages went against their expected
time (between half and double), rounded to 10 seconds, never more than 20% above the last value the screen showed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

A4_PT2 = 595.28 * 841.89
SIZE_MIN, SIZE_MAX = 0.5, 4.0
ROUTE_WEIGHT = {"process": 1.0, "context": 0.25, "skip": 0.0}
WINDOW = timedelta(days=30)
MIN_RUNS = 20
RATIO_MIN, RATIO_MAX = 0.5, 2.0
ROUND_S = 10
MAX_RISE = 1.2
CACHE_S = 300

SEED_PAGES = 9
SEED_WORK = 6 + 0.25  # NURSERY: 6 pages decoded, 1 for context, 2 skipped
WORK_SHARE = SEED_WORK / SEED_PAGES
# (seconds, dollars) for the whole seed run, per stage (prototype STAGES); stage 8, the audit step, is a guess.
SEED_RUN: dict[int, tuple[float, str]] = {
    1: (8, "0.01"),
    2: (38, "0.11"),
    3: (52, "0.21"),
    4: (24, "0.06"),
    5: (18, "0.03"),
    6: (9, "0.02"),
    7: (3, "0"),
    8: (12, "0.03"),
}


@dataclass(frozen=True)
class Rate:
    seconds: float  # per page unit
    usd: Decimal  # per page unit


def _seed() -> dict[int, Rate]:
    out = {}
    for stage, (seconds, usd) in SEED_RUN.items():
        units = SEED_PAGES if stage == 1 else SEED_WORK
        out[stage] = Rate(seconds / units, Decimal(usd) / Decimal(str(units)))
    return out


SEED = _seed()

# The same query as `konboro_stage_medians` (migration 0027), for one factory under its own RLS.
MEDIANS_SQL = """
  WITH units AS (
    SELECT tenant_id, drawing_id,
           count(*)::float8 AS every_page,
           (count(*) FILTER (WHERE route = 'process') + 0.25 * count(*) FILTER (WHERE route = 'context'))::float8
             AS work
      FROM pages
     GROUP BY tenant_id, drawing_id
  ), cost AS (
    SELECT tenant_id, drawing_id, pipeline_stage AS stage, sum(cost_usd)::float8 AS usd
      FROM llm_calls
     WHERE drawing_id IS NOT NULL AND pipeline_stage IS NOT NULL
     GROUP BY tenant_id, drawing_id, pipeline_stage
  ), runs AS (
    SELECT r.stage,
           CASE WHEN r.stage = 1 THEN u.every_page ELSE u.work END AS n,
           extract(epoch FROM r.finished_at - r.started_at)::float8 AS seconds,
           coalesce(c.usd, 0) AS usd
      FROM stage_runs r
      JOIN drawings d ON d.tenant_id = r.tenant_id AND d.id = r.drawing_id
      JOIN units u ON u.tenant_id = r.tenant_id AND u.drawing_id = r.drawing_id
      LEFT JOIN cost c ON c.tenant_id = r.tenant_id AND c.drawing_id = r.drawing_id AND c.stage = r.stage
     WHERE d.status = 'ready' AND r.status = 'done'
       AND r.started_at IS NOT NULL AND r.finished_at > now() - :window
  )
  SELECT stage::smallint, count(*)::bigint,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds / n),
         percentile_cont(0.5) WITHIN GROUP (ORDER BY usd / n)
    FROM runs
   WHERE n > 0
   GROUP BY stage
"""


Medians = dict[int, tuple[int, float, float]]  # stage → (runs, seconds per unit, dollars per unit)


def _rows(rows: object) -> Medians:
    return {int(r[0]): (int(r[1]), float(r[2]), float(r[3])) for r in rows}  # type: ignore[attr-defined]


def own_medians(s: Session) -> Medians:
    return _rows(s.execute(text(MEDIANS_SQL), {"window": WINDOW}).all())


def all_medians(s: Session) -> Medians:
    return _rows(s.execute(text("SELECT * FROM konboro_stage_medians(:window)"), {"window": WINDOW}).all())


def _runs(medians: Medians) -> int:
    return max((n for n, _, _ in medians.values()), default=0)


def choose(own: Medians, every: Medians) -> dict[int, Rate]:
    """The factory's own rates once it has enough runs, else every factory's, else the seed; stage by stage, a
    stage with no history keeps the seed's."""
    picked = own if _runs(own) >= MIN_RUNS else every if _runs(every) >= MIN_RUNS else {}
    rates = dict(SEED)
    for stage, (_, seconds, usd) in picked.items():
        rates[stage] = Rate(seconds, Decimal(str(round(usd, 6))))
    return rates


_cache: dict[str, tuple[float, dict[int, Rate]]] = {}


def rates(s: Session, tenant_id: str) -> dict[int, Rate]:
    """Cached for 5 minutes per factory: the screen asks every 2 seconds, and medians move slowly."""
    hit = _cache.get(tenant_id)
    if hit is not None and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    found = choose(own_medians(s), all_medians(s))
    _cache[tenant_id] = (time.monotonic(), found)
    return found


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------------------------------------- units


def size_units(sizes_pt: list[tuple[float, float]], pages: int) -> float:
    """Pages by size, before stage 1: a page with no size (an image, a sheet) counts as one."""
    counted = [min(max(w * h / A4_PT2, SIZE_MIN), SIZE_MAX) for w, h in sizes_pt]
    return sum(counted) + max(pages - len(counted), 0)


@dataclass(frozen=True)
class Units:
    every_page: float  # stage 1
    work: float  # stages 2–8


def units_before(sizes_pt: list[tuple[float, float]], pages: int) -> Units:
    n = size_units(sizes_pt, pages)
    return Units(n, n * WORK_SHARE)


def units_after(routes: list[str | None]) -> Units:
    """Once stage 1 routed the pages. A page with no route yet is decoded, as stage 1 assumes."""
    return Units(float(len(routes)), sum(ROUTE_WEIGHT[r or "process"] for r in routes))


def stage_units(stage: int, units: Units) -> float:
    return units.every_page if stage == 1 else units.work


# --------------------------------------------------------------------------------------------------------- before


@dataclass(frozen=True)
class Estimate:
    seconds: float
    usd: Decimal


def estimate(stages: list[int], units: Units, table: dict[int, Rate]) -> Estimate:
    seconds = sum(table[n].seconds * stage_units(n, units) for n in stages)
    usd = sum((table[n].usd * Decimal(str(stage_units(n, units))) for n in stages), Decimal(0))
    return Estimate(seconds, usd)


# ---------------------------------------------------------------------------------------------------------- during


@dataclass(frozen=True)
class StageTime:
    stage: int
    status: str  # queued, running, done, failed, skipped
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class Left:
    seconds_left: int  # rounded to 10 s
    seconds_expected: int  # the whole run, as now expected
    elapsed: int
    fraction: float  # elapsed of elapsed + left, for the meter


def time_left(
    times: list[StageTime],
    units: Units,
    table: dict[int, Rate],
    now: datetime,
    started_at: datetime | None,
    shown_left: int | None = None,
) -> Left:
    expected = {t.stage: table[t.stage].seconds * stage_units(t.stage, units) for t in times}
    done = [(t, t.started_at, t.finished_at) for t in times if t.status == "done"]
    spans = [(t, end - start) for t, start, end in done if start is not None and end is not None]
    actual = sum(span.total_seconds() for _, span in spans)
    planned = sum(expected[t.stage] for t, _ in spans)
    ratio = min(max(actual / planned, RATIO_MIN), RATIO_MAX) if planned > 0 else 1.0

    left = 0.0
    for t in times:
        if t.status in ("queued",):
            left += expected[t.stage] * ratio
        elif t.status == "running":
            ran = (now - t.started_at).total_seconds() if t.started_at else 0.0
            left += max(expected[t.stage] * ratio - ran, 0.0)
    rounded = int(round(left / ROUND_S) * ROUND_S)
    if shown_left and rounded > shown_left * MAX_RISE:  # 01 §4.6: never more than 20% up at once
        rounded = int(shown_left * MAX_RISE // ROUND_S * ROUND_S)
    elapsed = int((now - started_at).total_seconds()) if started_at else 0
    total = elapsed + rounded
    return Left(
        seconds_left=rounded,
        seconds_expected=round(sum(expected.values())),
        elapsed=elapsed,
        fraction=elapsed / total if total > 0 else 0.0,
    )
