"""The worker loop (konboro.pipeline.worker): it sweeps for unsent stages on its own timer (BUG-006), and a failed
sweep never stops it."""

import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from konboro.pipeline import worker as worker_module
from konboro.pipeline.worker import Worker


@dataclass
class FakeSettings:
    requeue_check_seconds: int = 60


@dataclass
class FakePipeline:
    stop: threading.Event
    passes_before_stop: int
    sweep_fails: bool = False
    settings: FakeSettings = field(default_factory=FakeSettings)
    queue: Any = None
    sweeps: int = 0
    passes: int = 0

    def requeue_unsent(self) -> list[tuple[str, str, int]]:
        self.sweeps += 1
        if self.sweep_fails:
            raise RuntimeError("database restarting")
        return []

    def handle(self, received: Any) -> None:  # never called: the fake queue is empty
        raise AssertionError


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


def run(pipeline: FakePipeline, clock: Clock, step_s: float, monkeypatch: pytest.MonkeyPatch) -> None:
    def run_once(self: Worker) -> int:
        pipeline.passes += 1
        clock.now += step_s
        if pipeline.passes >= pipeline.passes_before_stop:
            pipeline.stop.set()
        return 1  # busy, so the loop never sleeps

    monkeypatch.setattr(worker_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(Worker, "run_once", run_once)
    Worker(pipeline).run_forever(pipeline.stop)  # type: ignore[arg-type]


def test_the_worker_sweeps_at_start_and_then_on_its_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = FakePipeline(threading.Event(), passes_before_stop=13)
    run(pipeline, Clock(), step_s=10, monkeypatch=monkeypatch)  # 130 s of passes
    assert pipeline.sweeps == 3  # at 0 s, 60 s and 120 s


def test_a_failing_sweep_does_not_stop_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = FakePipeline(threading.Event(), passes_before_stop=3, sweep_fails=True)
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())  # no real back-off
    run(pipeline, Clock(), step_s=100, monkeypatch=monkeypatch)
    assert pipeline.passes == 3 and pipeline.sweeps >= 1
