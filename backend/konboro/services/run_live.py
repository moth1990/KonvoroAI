"""The live run step's data (01 §4.6 "ריצה", 13 §4.11 `live_run`; S28c): what the progress endpoint adds when the
flag is on. It reads three things the run already writes: `stage_runs` (each stage's start and end), `llm_calls`
(the cost) and `pipeline_events` (the live sentence, the counters, the page view's boxes).

No model is involved: the sentences come from templates in `pipeline/events.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db.models import PipelineEvent, StageRun
from konboro.pipeline.stages.s1_intake import thumbnail_key

from . import run_cost, run_estimate
from .drawings import Progress, stage_numbers
from .storage import Storage

LOG_SIZE = 6  # 01 §4.6: the log shows the last six events
# A gap this long between two stages is a pause (the user confirming pages, a rerun after a change): the clock
# starts again after it.
PAUSE = timedelta(minutes=2)
FINISHED = ("ready", "failed", "cancelled")


@dataclass(frozen=True)
class LiveStage:
    stage: int
    seconds: int | None
    cost_usd: Decimal | None
    calls: int
    models: dict[str, int]


@dataclass(frozen=True)
class LiveMessage:
    stage: int
    text: str
    at_s: int


@dataclass(frozen=True)
class LiveView:
    page_id: str
    page_no: int | None
    image_url: str | None
    size: list[float] | None
    boxes: list[list[float]]


@dataclass(frozen=True)
class Live:
    started_at: datetime | None
    elapsed_s: int
    seconds_left: int | None
    seconds_expected: int
    fraction: float
    cost_usd: Decimal
    cost_estimate_usd: Decimal
    cost_per_page_usd: Decimal | None
    stages: list[LiveStage]
    messages: list[LiveMessage]
    counters: dict[str, int] = field(default_factory=dict)
    view: LiveView | None = None


def _aware(t: datetime | None) -> datetime | None:
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def pass_start(runs: list[StageRun]) -> datetime | None:
    """When this pass of the run began: the first stage's start, or the start after the last pause."""
    started = sorted((r for r in runs if r.started_at is not None), key=lambda r: r.started_at)  # type: ignore[arg-type,return-value]
    begin: datetime | None = None
    previous_end: datetime | None = None
    for r in started:
        start = _aware(r.started_at)
        if begin is None or (previous_end is not None and start is not None and start - previous_end > PAUSE):
            begin = start
        previous_end = _aware(r.finished_at) or previous_end
    return begin


def live(
    s: Session,
    storage: Storage,
    p: Progress,
    *,
    now: datetime | None = None,
    shown_left: int | None = None,
) -> Live:
    d = p.drawing
    now = now or datetime.now(UTC)
    stages = stage_numbers(p)
    runs = {r.stage: r for r in p.runs}
    begin = pass_start(list(runs.values()))

    def in_pass(r: StageRun) -> bool:
        start = _aware(r.started_at)
        return start is not None and begin is not None and start >= begin

    if p.pages:
        units = run_estimate.units_after([page.route for page, _ in p.pages])
    else:
        units = run_estimate.units_before([], sum(f.page_count or 0 for f in p.files))
    rates = run_estimate.rates(s, d.tenant_id)
    times = [
        run_estimate.StageTime(
            n,
            runs[n].status if n in runs else "queued",
            _aware(runs[n].started_at) if n in runs and in_pass(runs[n]) else None,
            _aware(runs[n].finished_at) if n in runs and in_pass(runs[n]) else None,
        )
        for n in stages
    ]
    finished = d.status in FINISHED
    if finished:
        end = max((t.finished_at for t in times if t.finished_at), default=now)
        elapsed = int((end - begin).total_seconds()) if begin else 0
        expected = run_estimate.estimate(stages, units, rates)
        left: int | None = None
        seconds_expected, fraction = round(expected.seconds), 1.0
    else:
        timing = run_estimate.time_left(times, units, rates, now, begin, shown_left)
        elapsed, left, seconds_expected = timing.elapsed, timing.seconds_left, timing.seconds_expected
        fraction = min(timing.fraction, 0.99)

    cost = run_cost.drawing_cost(s, d.id)
    estimate = Decimal(0)
    out_stages = []
    for t in times:
        spent = cost.stages.get(t.stage)
        if t.status == "done" or (finished and spent is not None):
            estimate += spent.usd if spent else Decimal(0)
        elif t.status not in ("skipped", "failed"):
            estimate += rates[t.stage].usd * Decimal(str(run_estimate.stage_units(t.stage, units)))
        seconds = None
        if t.started_at is not None and (t.finished_at is not None or t.status == "running"):
            seconds = int(((t.finished_at or now) - t.started_at).total_seconds())
        out_stages.append(
            LiveStage(
                t.stage,
                seconds,
                spent.usd if spent else (Decimal(0) if t.status == "done" else None),
                spent.calls if spent else 0,
                dict(spent.models) if spent else {},
            )
        )
    estimate = max(estimate, cost.usd)

    events = _events(s, d.id, begin)
    pages = {page.id: page for page, _ in p.pages}
    page_count = len(p.pages) or sum(f.page_count or 0 for f in p.files)
    return Live(
        started_at=begin,
        elapsed_s=max(elapsed, 0),
        seconds_left=left,
        seconds_expected=seconds_expected,
        fraction=fraction,
        cost_usd=cost.usd,
        cost_estimate_usd=estimate,
        cost_per_page_usd=(cost.usd / page_count) if page_count else None,
        stages=out_stages,
        messages=[
            LiveMessage(e.stage, e.payload.get("text", ""), _seconds(e.created_at, begin))
            for e in events
            if e.kind == "message"
        ][-LOG_SIZE:],
        counters=_counters(events),
        view=None if finished else _view(storage, d.tenant_id, d.id, events, pages),
    )


def _seconds(at: datetime, begin: datetime | None) -> int:
    return max(int((_aware(at) - begin).total_seconds()), 0) if begin else 0  # type: ignore[operator]


def _events(s: Session, drawing_id: str, begin: datetime | None) -> list[PipelineEvent]:
    query = select(PipelineEvent).where(PipelineEvent.drawing_id == drawing_id)
    if begin is not None:
        query = query.where(PipelineEvent.created_at >= begin - timedelta(seconds=1))
    return list(s.scalars(query.order_by(PipelineEvent.created_at, PipelineEvent.id)))


def _counters(events: list[PipelineEvent]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for e in events:
        if e.kind == "counters":
            merged.update({k: int(v) for k, v in e.payload.items()})
    return merged


def _view(
    storage: Storage, tenant_id: str, drawing_id: str, events: list[PipelineEvent], pages: dict[str, Any]
) -> LiveView | None:
    """The page the run is on: the last one a sentence named; its boxes if stage 3 reported them."""
    page_id = next((e.payload.get("page_id") for e in reversed(events) if e.payload.get("page_id")), None)
    if page_id is None:
        return None
    boxes = next((e.payload for e in reversed(events) if e.kind == "boxes" and e.payload.get("page_id") == page_id), {})
    page = pages.get(page_id)
    size = boxes.get("size") or ([page.width_pt, page.height_pt] if page and page.width_pt and page.height_pt else None)
    page_no = boxes.get("page_no") or (page.page_no if page else None)
    return LiveView(
        page_id=page_id,
        page_no=page_no,
        image_url=storage.presigned_get(tenant_id, thumbnail_key(tenant_id, drawing_id, page_id)),
        size=size,
        boxes=boxes.get("boxes", []),
    )
