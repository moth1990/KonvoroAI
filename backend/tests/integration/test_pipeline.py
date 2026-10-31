"""The pipeline end to end on the local services (00 §4, 12 §3): upload → 7 stub stages through the queues →
a quote, with the quota counted at stage 1, given back on cancel or failure, and never for a new version."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select

from konboro.contracts import STAGE_OUTPUTS
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.pipeline import coordinator
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import STAGES
from konboro.pipeline.worker import Worker
from konboro.services.queue import STAGE_QUEUES, Queue
from konboro.services.storage import Storage

from .api import Api, ApiTenant, add_tenant
from .aws import aws_settings
from .test_api_upload import upload

NURSERY = Path(__file__).resolve().parents[3] / "golden" / "NURSERY-1" / "NURSERY-1.pdf"


@pytest.fixture
def pipeline(migrated_db: dict[str, Engine], clean_queue: Queue, storage: Storage) -> Pipeline:
    return Pipeline(aws_settings(), migrated_db["app"], storage, clean_queue)


def start(api: Api, tenant: ApiTenant, **form: str) -> str:
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], **form)
    assert response.status_code == 201, response.text
    return str(response.json()["drawing_id"])


def quota_state(engine: Engine, tenant: ApiTenant) -> tuple[int, int, list[str]]:
    with tenant_session(tenant.tenant_id, engine) as s:
        used = s.scalar(select(func.coalesce(func.sum(m.QuotaUsage.used), 0)))
        reserved = s.scalar(select(func.coalesce(func.sum(m.QuotaUsage.reserved), 0)))
        kinds = s.scalars(select(m.QuotaEvent.kind).order_by(m.QuotaEvent.created_at, m.QuotaEvent.id)).all()
    return int(used or 0), int(reserved or 0), list(kinds)


def stage_one_only(pipeline: Pipeline) -> None:
    (received,) = pipeline.queue.receive(STAGE_QUEUES[1], wait_s=2)
    assert pipeline.handle(received) == "done"


def test_a_drawing_runs_through_all_seven_stages(
    api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline, storage: Storage
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=12)
    drawing_id = start(api, tenant, project="גן ילדים, לוח ראשי")
    assert Worker(pipeline).run_until_idle() == 7

    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        runs = s.scalars(select(m.StageRun).order_by(m.StageRun.stage)).all()
        pages = s.scalars(select(m.Page).order_by(m.Page.page_no)).all()
        (panel,) = s.scalars(select(m.Panel)).all()
        (quote,) = s.scalars(select(m.Quote)).all()
        (version,) = s.scalars(select(m.QuoteVersion)).all()
        assert (drawing.status, drawing.progress, drawing.current_stage) == ("ready", 1.0, 7)
        assert drawing.input_kind == "designer_plan"
        assert drawing.quota is not None and drawing.quota["counted"] is True and drawing.quota["quota_event_id"]
        assert [(r.stage, r.status, r.attempts) for r in runs] == [(n, "done", 1) for n in range(1, 8)]
        assert [p.page_no for p in pages] == list(range(1, 10))
        assert {p.route for p in pages} == {"process"} and all(p.render_key for p in pages)
        assert (pages[0].width_pt, pages[0].height_pt) == (842.0, 595.0)  # from the PDF, in points
        assert (panel.name, len(panel.page_ids)) == ("גן ילדים, לוח ראשי", 9)
        assert (quote.drawing_id, quote.name, version.version, version.status) == (
            drawing_id,
            "גן ילדים, לוח ראשי",
            1,
            "draft",
        )
        outputs = {r.stage: r.output_key for r in runs}
        thumb = pages[0].render_key
    for stage, key in outputs.items():
        assert key is not None
        STAGE_OUTPUTS[stage].model_validate_json(storage.get(tenant.tenant_id, key))  # every output is its contract
    assert storage.get(tenant.tenant_id, str(thumb)).startswith(b"\x89PNG")
    assert quota_state(engine, tenant) == (13, 0, ["reserve", "confirm"])  # counted once, at stage 1


def test_the_quota_counts_when_stage_1_succeeds(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    start(api, tenant)
    assert quota_state(engine, tenant) == (0, 1, ["reserve"])
    stage_one_only(pipeline)
    assert quota_state(engine, tenant) == (1, 0, ["reserve", "confirm"])
    Worker(pipeline).run_until_idle()


def test_cancel_before_stage_1_releases(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)
    with tenant_session(tenant.tenant_id, engine) as s:
        assert coordinator.cancel(s, tenant.tenant_id, drawing_id) == "released"
    assert Worker(pipeline).run_until_idle() == 1  # the stage-1 message, skipped
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.get_one(m.Drawing, drawing_id).status == "cancelled"
        assert s.scalar(select(func.count()).select_from(m.Page)) == 0
        assert set(s.scalars(select(m.StageRun.status)).all()) == {"skipped"}
        assert s.scalar(select(func.count()).select_from(m.DrawingFile)) == 1  # the files stay
    assert quota_state(engine, tenant) == (0, 0, ["reserve", "release"])


def test_cancel_after_stage_1_refunds(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=4)
    drawing_id = start(api, tenant)
    stage_one_only(pipeline)
    with tenant_session(tenant.tenant_id, engine) as s:
        assert coordinator.cancel(s, tenant.tenant_id, drawing_id) == "refunded"
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        assert drawing.status == "cancelled"
        assert drawing.quota is not None and drawing.quota["counted"] is False
        assert s.scalar(select(func.count()).select_from(m.Quote)) == 0
    assert quota_state(engine, tenant) == (4, 0, ["reserve", "confirm", "refund"])


def test_cancel_of_a_finished_drawing_is_refused(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s, pytest.raises(coordinator.DrawingFinishedError):
        coordinator.cancel(s, tenant.tenant_id, drawing_id)


def test_a_cancel_during_a_stage_rolls_that_stage_back(
    api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)

    def cancelled_mid_stage(ctx: StageContext):  # type: ignore[no-untyped-def]
        out = STAGES[1](ctx)  # the pages are written, not yet committed
        with tenant_session(tenant.tenant_id, engine) as other:  # the user's cancel, in its own transaction
            assert coordinator.cancel(other, tenant.tenant_id, drawing_id) == "released"
        return out

    pipeline.stages[1] = cancelled_mid_stage
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.get_one(m.Drawing, drawing_id).status == "cancelled"
        assert s.scalar(select(func.count()).select_from(m.Page)) == 0  # rolled back with the stage
    assert quota_state(engine, tenant) == (0, 0, ["reserve", "release"])  # never confirmed


def test_a_crashing_stage_ends_in_the_dlq_failed_and_refunded(
    api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=2)

    def broken(ctx: StageContext):  # type: ignore[no-untyped-def]
        raise RuntimeError("symbol detector unavailable")

    pipeline.stages[3] = broken
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()

    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        run = s.get_one(m.StageRun, (tenant.tenant_id, drawing_id, 3))
        assert drawing.status == "failed"
        assert [i["code"] for i in drawing.issues] == ["pipeline_failed"]
        assert (run.status, run.attempts) == ("failed", 3)
        assert run.error == {"type": "RuntimeError", "message": "symbol detector unavailable", "attempt": 3}
        assert s.get_one(m.StageRun, (tenant.tenant_id, drawing_id, 4)).status == "queued"  # never reached
    assert quota_state(engine, tenant) == (2, 0, ["reserve", "confirm", "refund"])


def test_a_new_version_never_counts(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, limit=10, used=10)
    with tenant_session(tenant.tenant_id, engine) as s:
        s.add(m.Drawing(id=(first := new_id("drw")), tenant_id=tenant.tenant_id, status="ready"))
    drawing_id = start(api, tenant, revision_of=first)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        assert drawing.status == "ready"
        assert drawing.quota is not None and drawing.quota["counted"] is False
    assert quota_state(engine, tenant) == (10, 0, [])
