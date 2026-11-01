"""The pipeline worker: `python -m konboro.pipeline.worker` (make dev runs it next to the API).

One loop polls every stage queue and the DLQ. In AWS each stage gets its own workers (12 §3); locally one process
does all seven.
"""

import logging
import signal
import threading
import time

from sqlalchemy import Engine

from konboro.db.session import app_engine
from konboro.services.llm import live_providers
from konboro.services.queue import DLQ, STAGE_QUEUES, Queue
from konboro.services.storage import Storage
from konboro.settings import Settings, get_settings
from konboro_llm.base import LLMProvider

from .coordinator import Pipeline
from .stages import Stage

log = logging.getLogger("konboro.worker")

IDLE_SLEEP_S = 0.25


class Worker:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.queue = pipeline.queue

    def run_once(self) -> int:
        """One pass over every queue. Returns how many messages it handled."""
        handled = 0
        for stage in sorted(STAGE_QUEUES):
            for received in self.queue.receive(STAGE_QUEUES[stage], max_messages=5):
                self.pipeline.handle(received)
                handled += 1
        for received in self.queue.receive(DLQ, max_messages=5):
            self.pipeline.handle_dead(received)
            handled += 1
        return handled

    def run_until_idle(self, max_passes: int = 200) -> int:
        """Tests: keep going until a pass finds nothing."""
        total = 0
        for _ in range(max_passes):
            handled = self.run_once()
            total += handled
            if handled == 0:
                return total
        raise RuntimeError("the pipeline did not settle")

    def run_forever(self, stop: threading.Event) -> None:
        log.info("worker started")
        next_sweep = time.monotonic()
        while not stop.is_set():
            try:
                if time.monotonic() >= next_sweep:
                    next_sweep = time.monotonic() + self.pipeline.settings.requeue_check_seconds
                    self.pipeline.requeue_unsent()
                if self.run_once() == 0:
                    stop.wait(IDLE_SLEEP_S)
            except Exception:  # a queue or DB hiccup must not kill the worker
                log.exception("worker pass failed")
                stop.wait(2)
        log.info("worker stopped")


def providers_for(settings: Settings) -> dict[str, LLMProvider]:
    """Real Claude when there is a key. A local worker without one (`make dev`) falls back to the stand-in model,
    loudly: its page kinds are made up. Anywhere else, no key means stage 1 fails, as it should."""
    live = live_providers()
    if live or settings.env != "local":
        return live
    from konboro.devtools.fake_llm import fake_providers

    log.warning("no ANTHROPIC_API_KEY: stage 1 uses the stand-in model, and its page kinds are made up")
    return fake_providers()


def build(
    settings: Settings,
    engine: Engine | None = None,
    stages: dict[int, Stage] | None = None,
    llm_providers: dict[str, LLMProvider] | None = None,
) -> Worker:
    providers = llm_providers if llm_providers is not None else providers_for(settings)
    pipeline = Pipeline(settings, engine or app_engine(), Storage(settings), Queue(settings), llm_providers=providers)
    if stages is not None:
        pipeline.stages = stages
    return Worker(pipeline)


def start_in_thread(
    settings: Settings,
    engine: Engine | None = None,
    stages: dict[int, Stage] | None = None,
    llm_providers: dict[str, LLMProvider] | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """For the E2E API, which runs a worker beside itself."""
    stop = threading.Event()
    worker = build(settings, engine, stages, llm_providers)
    thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True, name="worker")
    thread.start()
    return thread, stop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            worker = build(get_settings())
            break
        except Exception:  # services still starting: try again
            log.exception("worker could not start; retrying")
            time.sleep(2)
    else:
        return
    worker.run_forever(stop)


if __name__ == "__main__":
    main()
