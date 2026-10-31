"""The coordinator (00 §4.3, 12 §3): code, not a model, decides what runs next.

One message = one stage of one drawing. For each:
1. Claim: lock the drawing, skip it if it was cancelled or finished, mark the stage `running`.
2. Run: the stage reads the previous contracts, writes its rows, and its own contract goes to S3. Before the
   commit the drawing is locked again, so a cancel that arrived meanwhile wins and the stage's rows roll back.
3. Hand off: stage 1 confirms the quota (01 §4.5; S05 decision) in the same transaction, stage 7 marks the
   drawing `ready`, any other stage queues the next one.

A stage that raises is retried after `stage_retry_seconds`. After the third receive the queue's redrive policy
moves the message to the DLQ; `handle_dead` marks the drawing `failed` and gives the quota back, released or
refunded (01 §4.5: a technical failure is not counted).

Messages are sent after the commit, so one can be lost: a failed send, or a process that dies first. Each stage run
records `sent_at`, and `requeue_unsent` sends again any stage that no worker claimed in time (BUG-006). A second
copy of a message whose stage is already running is dropped, so a stage never runs twice at once (BUG-007).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from konboro.db.ids import new_id
from konboro.db.models import Drawing, QuotaEvent, StageRun
from konboro.db.session import global_session, tenant_session
from konboro.services import quota
from konboro.services.llm import usage_recorder
from konboro.services.queue import MAX_RECEIVES, Queue, Received, StageMessage
from konboro.services.storage import Storage, drawing_key
from konboro.settings import Settings
from konboro_llm import LLMClient
from konboro_llm.base import LLMProvider

from .context import StageContext
from .stages import STAGES, Stage

log = logging.getLogger("konboro.pipeline")

FINISHED = ("ready", "failed", "cancelled")
FAILED_MESSAGE = "הפענוח נכשל בגלל תקלה אצלנו. ההעלאה לא נספרה במכסה. נסו להעלות שוב בעוד כמה דקות"

Outcome = Literal["done", "retry", "skipped"]


class CancelledError(Exception):
    """The drawing was cancelled while its stage ran."""


class DrawingFinishedError(Exception):
    """Cancel came too late: the drawing is already ready, failed or cancelled."""


def _now() -> datetime:
    return datetime.now(UTC)


def _lock(session: Session, drawing_id: str) -> Drawing | None:
    """FOR NO KEY UPDATE: only non-key columns change, and it doesn't wait on the key-share locks a running stage
    holds by inserting pages and panels that point at the drawing, so a cancel never blocks on a stage."""
    query = select(Drawing).where(Drawing.id == drawing_id).with_for_update(key_share=True)  # FOR NO KEY UPDATE
    return session.scalar(query)


def _quota_back(session: Session, drawing: Drawing, reason: str) -> str:
    """Release or refund the drawing's reservation, and record it on the drawing."""
    q = dict(drawing.quota or {})
    reservation = q.get("reservation_id")
    if not reservation:
        return "none"
    outcome = quota.give_back(session, drawing.tenant_id, reservation, reason, drawing_id=drawing.id)
    q["counted"] = False
    drawing.quota = q
    return outcome


def cancel(session: Session, tenant_id: str, drawing_id: str) -> str:
    """Stop the pipeline at the next stage boundary and give the quota back (01 §4.6, "בטל פענוח").
    The files stay. Returns how the quota was given back: released, refunded or none."""
    drawing = _lock(session, drawing_id)
    if drawing is None or drawing.tenant_id != tenant_id:
        raise LookupError(drawing_id)
    if drawing.status in FINISHED:
        raise DrawingFinishedError(drawing.status)
    drawing.status = "cancelled"
    outcome = _quota_back(session, drawing, "cancelled")
    session.execute(
        update(StageRun)
        .where(StageRun.drawing_id == drawing_id, StageRun.status.in_(("queued", "running")))
        .values(status="skipped", finished_at=_now())
    )
    return outcome


@dataclass
class Pipeline:
    settings: Settings
    engine: Engine
    storage: Storage
    queue: Queue
    stages: dict[int, Stage] = field(default_factory=lambda: dict(STAGES))
    llm_providers: dict[str, LLMProvider] = field(default_factory=dict)  # live in the worker, cassettes in eval

    def handle(self, received: Received) -> Outcome:
        msg = received.message
        if not self._claim(msg, redelivered=received.receive_count > 1):
            self.queue.delete(received)
            return "skipped"
        try:
            following = self._run(msg)
        except CancelledError:
            log.info("stage %s of %s stopped: cancelled", msg.stage, msg.drawing_id)
            self.queue.delete(received)
            return "skipped"
        except Exception as e:
            log.exception("stage %s of %s failed (attempt %s)", msg.stage, msg.drawing_id, received.receive_count)
            self._record_failure(msg, e, received.receive_count)
            last = received.receive_count >= MAX_RECEIVES
            self.queue.retry_later(received, 0 if last else self.settings.stage_retry_seconds)
            return "retry"
        self.queue.delete(received)
        if following:
            self.queue.send(following)
        return "done"

    def handle_dead(self, received: Received) -> None:
        """A message the stage queue gave up on: the drawing failed, and the upload doesn't count."""
        msg = received.message
        with tenant_session(msg.tenant_id, self.engine) as s:
            drawing = _lock(s, msg.drawing_id)
            if drawing is not None and drawing.status not in FINISHED:
                drawing.status = "failed"
                outcome = _quota_back(s, drawing, "stage_failed")
                issue = {"code": "pipeline_failed", "severity": "error", "stage": msg.stage, "message": FAILED_MESSAGE}
                drawing.issues = [*drawing.issues, issue]
                run = s.get(StageRun, (msg.tenant_id, msg.drawing_id, msg.stage))
                if run is not None:
                    run.status, run.finished_at = "failed", _now()
                log.error("drawing %s failed at stage %s; quota %s", msg.drawing_id, msg.stage, outcome)
        self.queue.delete(received)

    def run_inline(self, first: StageMessage) -> None:
        """Every stage in turn in this process, without the queue: the golden-set eval (S06). A stage that raises
        is not retried; the error goes to the caller."""
        msg: StageMessage | None = first
        while msg is not None:
            if not self._claim(msg):
                raise RuntimeError(f"stage {msg.stage} of {msg.drawing_id} could not be claimed")
            msg = self._run(msg)

    def requeue_unsent(self, older_than: timedelta | None = None) -> list[tuple[str, str, int]]:
        """Send again every stage whose message went out `older_than` ago and was never claimed (BUG-006). The
        lookup is the one cross-tenant read, IDs only (migration 0004); each row is checked again inside its
        tenant's session before anything is sent. Returns what it sent, as (tenant_id, drawing_id, stage)."""
        age = older_than if older_than is not None else timedelta(seconds=self.settings.requeue_after_seconds)
        with global_session(self.engine) as s:
            rows = s.execute(text("SELECT * FROM konboro_unsent_stages(:age)"), {"age": age}).all()
        sent = []
        for row in rows:
            with tenant_session(row.tenant_id, self.engine) as s:
                drawing = _lock(s, row.drawing_id)
                run = s.get(StageRun, (row.tenant_id, row.drawing_id, row.stage))
                if drawing is None or drawing.status in FINISHED or run is None:
                    continue
                if run.status != "queued" or run.attempts or run.sent_at is None or run.sent_at > _now() - age:
                    continue  # claimed or sent meanwhile
                run.sent_at = _now()
                trace_id = drawing.trace_id or new_id("trc")
                msg = StageMessage(
                    drawing_id=drawing.id, tenant_id=drawing.tenant_id, stage=run.stage, trace_id=trace_id
                )
            self.queue.send(msg)  # after the commit, like every send
            log.warning("stage %s of %s was never claimed; sent again", msg.stage, msg.drawing_id)
            sent.append((msg.tenant_id, msg.drawing_id, msg.stage))
        return sent

    def _claim(self, msg: StageMessage, redelivered: bool = False) -> bool:
        with tenant_session(msg.tenant_id, self.engine) as s:
            drawing = _lock(s, msg.drawing_id)
            if drawing is None or drawing.status in FINISHED:
                return False
            run = s.get_one(StageRun, (msg.tenant_id, msg.drawing_id, msg.stage))
            if run.status in ("done", "skipped"):
                return False  # a duplicate delivery
            if run.status == "running" and not redelivered:
                # A second copy of the message, while the first copy's stage runs. A worker that died mid-stage
                # is different: its own message comes back once the visibility timeout ends, received again.
                return False
            run.status, run.attempts, run.started_at = "running", run.attempts + 1, _now()
            drawing.status, drawing.current_stage = "processing", msg.stage
            return True

    def _run(self, msg: StageMessage) -> StageMessage | None:
        with tenant_session(msg.tenant_id, self.engine) as s:
            drawing = s.get_one(Drawing, msg.drawing_id)
            llm = LLMClient(self.llm_providers, on_call=usage_recorder(self.engine, msg.tenant_id, msg.drawing_id))
            output = self.stages[msg.stage](StageContext(s, self.storage, drawing, msg.stage, llm))
            key = drawing_key(msg.tenant_id, msg.drawing_id, "stages", f"s{msg.stage}.json")
            self.storage.put(msg.tenant_id, key, output.model_dump_json().encode(), "application/json")

            s.flush()
            locked = _lock(s, msg.drawing_id)
            s.refresh(drawing)
            if locked is None or drawing.status == "cancelled":
                raise CancelledError(msg.drawing_id)
            run = s.get_one(StageRun, (msg.tenant_id, msg.drawing_id, msg.stage))
            run.status, run.finished_at, run.output_key, run.error = "done", _now(), key, None
            drawing.progress = msg.stage / 7
            if msg.stage == 1:
                self._count(s, drawing)
            if msg.stage == 7:
                drawing.status = "ready"
                return None
            s.get_one(StageRun, (msg.tenant_id, msg.drawing_id, msg.stage + 1)).sent_at = _now()
            return StageMessage(
                drawing_id=msg.drawing_id, tenant_id=msg.tenant_id, stage=msg.stage + 1, trace_id=msg.trace_id
            )

    def _count(self, session: Session, drawing: Drawing) -> None:
        """Stage 1 succeeded: the upload counts now (01 §4.5 step 2)."""
        q: dict[str, Any] = dict(drawing.quota or {})
        if not q.get("reservation_id"):
            return  # a new version reserves nothing (S05 decision)
        quota.confirm(session, drawing.tenant_id, q["reservation_id"], drawing_id=drawing.id)
        q["counted"] = True
        q["quota_event_id"] = session.scalar(
            select(QuotaEvent.id).where(QuotaEvent.reservation_id == q["reservation_id"], QuotaEvent.kind == "confirm")
        )
        drawing.quota = q

    def _record_failure(self, msg: StageMessage, error: Exception, attempt: int) -> None:
        with tenant_session(msg.tenant_id, self.engine) as s:
            run = s.get(StageRun, (msg.tenant_id, msg.drawing_id, msg.stage))
            if run is not None:
                run.status = "queued"  # until the retry, or the DLQ marks it failed
                run.error = {"type": type(error).__name__, "message": str(error)[:500], "attempt": attempt}
