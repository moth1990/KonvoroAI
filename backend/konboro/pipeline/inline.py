"""A drawing's stages run in this process, in the request, for a chat build (13 §4.2, S27 design 2).

A chat build has no files and nothing slow: each message adds rows, and stages 4–7 run on them at once so the
estimator sees the lines in one round trip, as a review action reruns stages 6 and 7 (S23). The stages are the
pipeline's own `run(ctx)`, and each writes its contract where the coordinator does (`stages/sN.json`), with its
`stage_runs` row, so the review screen and every action read a chat build like any drawing. The queue and the
coordinator are not involved: there is no message to lose and no worker to wait for.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.services.storage import Storage, drawing_key
from konboro_llm import LLMClient

from .context import StageContext
from .stages import STAGES


class Remembered:
    """The storage for one message: what it writes goes to S3 and is kept here too, so the next stage reads its input
    from memory instead of from S3 (each round trip is ~0.25 s on the local S3Mock, and one message makes about 20).
    Anything else goes to the real storage, which still checks every key's tenant."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._kept: dict[tuple[str, str], bytes] = {}

    def put(self, tenant_id: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self._storage.put(tenant_id, key, body, content_type)
        self._kept[tenant_id, key] = body

    def get(self, tenant_id: str, key: str) -> bytes:
        found = self._kept.get((tenant_id, key))
        if found is None:
            found = self._storage.get(tenant_id, key)
            self._kept[tenant_id, key] = found
        return found

    def delete(self, tenant_id: str, key: str) -> None:
        self._kept.pop((tenant_id, key), None)
        self._storage.delete(tenant_id, key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._storage, name)


def write_output(session: Session, storage: Storage, drawing: m.Drawing, stage: int, output: BaseModel) -> str:
    key = drawing_key(drawing.tenant_id, drawing.id, "stages", f"s{stage}.json")
    storage.put(drawing.tenant_id, key, output.model_dump_json().encode(), "application/json")
    run = session.get(m.StageRun, (drawing.tenant_id, drawing.id, stage))
    now = datetime.now(UTC)
    if run is None:
        run = m.StageRun(tenant_id=drawing.tenant_id, drawing_id=drawing.id, stage=stage, attempts=0)
        session.add(run)
    run.status, run.output_key, run.error = "done", key, None
    run.started_at, run.finished_at, run.attempts = now, now, (run.attempts or 0) + 1
    session.flush()
    return key


def run_stages(
    session: Session, storage: Storage, drawing: m.Drawing, llm: LLMClient, stages: tuple[int, ...]
) -> dict[int, BaseModel]:
    out: dict[int, BaseModel] = {}
    for n in stages:
        output = STAGES[n](StageContext(session, storage, drawing, n, llm))
        write_output(session, storage, drawing, n, output)
        out[n] = output
    return out
