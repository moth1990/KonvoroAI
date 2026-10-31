"""Stages reach the model through `ctx.llm` (S06): every answered call is an `llm_calls` row for the drawing's
tenant, written in its own transaction so a stage that fails afterwards still leaves its cost (00 §7.2). And a
replayed cassette goes through the pipeline like a live answer."""

from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, select

from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import STAGES
from konboro.services import drawings
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage
from konboro_llm import LLMRequest
from konboro_llm.providers import CassetteProvider, FakeProvider

from .api import ApiTenant, add_tenant
from .aws import aws_settings

NURSERY = Path(__file__).resolve().parents[3] / "golden" / "NURSERY-1" / "NURSERY-1.pdf"


class Kind(BaseModel):
    page_kind: str


def ask(ctx: StageContext) -> Kind:
    request = LLMRequest(
        stage="page_classification",
        system="Classify the page.",
        user_text="page 1",
        output_schema=Kind,
        tenant_id=ctx.tenant_id,
    )
    return ctx.llm.run(request).data


@pytest.fixture
def pipeline(migrated_db: dict[str, Engine], storage: Storage) -> Pipeline:
    settings = aws_settings()
    return Pipeline(settings, migrated_db["app"], storage, Queue(settings))


def upload(pipeline: Pipeline, tenant: ApiTenant) -> StageMessage:
    with tenant_session(tenant.tenant_id, pipeline.engine) as s:
        new = drawings.create_upload(
            s,
            pipeline.storage,
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            files=[("NURSERY-1.pdf", NURSERY.read_bytes())],
        )
        return StageMessage(
            drawing_id=new.drawing.id, tenant_id=tenant.tenant_id, stage=1, trace_id=str(new.drawing.trace_id)
        )


def calls(engine: Engine, tenant: ApiTenant) -> list[tuple[str, str, str | None, int]]:
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = s.scalars(select(m.LlmCall)).all()
        return [(r.stage, r.provider, r.drawing_id, r.attempts) for r in rows]


def test_a_call_from_a_stage_is_logged(migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    tenant, other = add_tenant(migrated_db["app"]), add_tenant(migrated_db["app"])
    fake = FakeProvider([{"page_kind": "single_line_diagram"}])
    pipeline.llm_providers = {"anthropic": fake}

    def stage_1(ctx: StageContext) -> BaseModel:
        assert ask(ctx).page_kind == "single_line_diagram"
        return STAGES[1](ctx)

    pipeline.stages[1] = stage_1
    msg = upload(pipeline, tenant)
    pipeline.run_inline(msg)

    assert len(fake.calls) == 1
    assert calls(migrated_db["app"], tenant) == [("page_classification", "fake", msg.drawing_id, 1)]
    assert calls(migrated_db["app"], other) == []  # RLS: the row is the tenant's own


def test_the_cost_stays_when_the_stage_fails_after_the_call(migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:
    tenant = add_tenant(migrated_db["app"])
    pipeline.llm_providers = {"anthropic": FakeProvider([{"page_kind": "legend"}])}

    def stage_1(ctx: StageContext) -> BaseModel:
        ask(ctx)
        raise RuntimeError("after the model answered")

    pipeline.stages[1] = stage_1
    with pytest.raises(RuntimeError, match="after the model answered"):
        pipeline.run_inline(upload(pipeline, tenant))
    assert [c[0] for c in calls(migrated_db["app"], tenant)] == ["page_classification"]


def test_a_cassette_replays_through_the_pipeline(
    migrated_db: dict[str, Engine], pipeline: Pipeline, tmp_path: Path
) -> None:
    tenant = add_tenant(migrated_db["app"])
    recorder = CassetteProvider(tmp_path, "record", wrapped=FakeProvider([{"page_kind": "control_diagram"}]))
    seen: list[str] = []

    def stage_1(ctx: StageContext) -> BaseModel:
        seen.append(ask(ctx).page_kind)
        return STAGES[1](ctx)

    pipeline.stages[1] = stage_1
    pipeline.llm_providers = {"anthropic": recorder}
    pipeline.run_inline(upload(pipeline, tenant))
    pipeline.llm_providers = {"anthropic": CassetteProvider(tmp_path, "replay")}
    pipeline.run_inline(upload(pipeline, tenant))

    assert seen == ["control_diagram", "control_diagram"]
    assert [c[1] for c in calls(migrated_db["app"], tenant)] == ["fake", "cassette"]
