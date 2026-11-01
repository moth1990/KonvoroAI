"""Stage 4 on the local services (04): through the queue, the drawing's components are written to its tenant's
`components` rows (and replaced when the stage runs again), the tile agent's calls go through `konboro_llm` and are
logged per tenant, the agent never sees the customer, the title block or a price, and the run step shows the stage's
line. The model is the stand-in (`devtools/fake_llm.py`): never a real one in tests."""

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.contracts.merge import MergeResult
from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import s4_association
from konboro.pipeline.worker import Worker
from konboro.services.storage import Storage
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.text_association import STAGE as ASSOCIATE

from .api import Api, add_tenant
from .test_api_drawings import progress
from .test_api_upload import upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY, send

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the symbol library and the attribute schemas (S12, S13)
    return migrated_db


def merged(engine: Engine, storage: Storage, tenant_id: str, drawing_id: str) -> MergeResult:
    with tenant_session(tenant_id, engine) as s:
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 4))
    assert key is not None
    return MergeResult.model_validate_json(storage.get(tenant_id, key))


def test_stage_4_writes_the_components_under_the_tenant(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()

    out = merged(engine, storage, tenant.tenant_id, drawing_id)
    assert out.components and out.instances
    # the stand-in tags every breaker "Q1": one device per panel, however many pages draw it (04 §5.8)
    assert all(c.designators == ["Q1"] and c.quantity == 1 for c in out.components)
    assert {i.component_id for i in out.instances} == {c.component_id for c in out.components}
    assert out.stats.tiles_with_agent > 0  # nothing written beside them: the agent is asked
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = s.scalars(select(m.Component).where(m.Component.drawing_id == drawing_id)).all()
        assert sorted(r.id for r in rows) == sorted(c.component_id for c in out.components)
        assert all(r.supply_scope == "in_panel" and r.designators == ["Q1"] for r in rows)
        assert all(len(r.instances) >= 1 and r.instances[0]["page_id"].startswith("pg_") for r in rows)
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == ASSOCIATE).limit(1)) is not None
        assert (
            s.scalar(select(m.StageRun.status).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 7))
            == "done"
        )
    with tenant_session(other.tenant_id, engine) as s:  # RLS
        assert s.scalar(select(func.count()).select_from(m.Component)) == 0
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == ASSOCIATE)) is None


def test_a_rerun_replaces_the_components(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    first = merged(engine, storage, tenant.tenant_id, drawing_id)
    with tenant_session(tenant.tenant_id, engine) as s:  # stage 4 again, as when a page moves to another route (S08)
        drawing = s.get_one(m.Drawing, drawing_id)
        again = s4_association.run(StageContext(s, storage, drawing, 4, LLMClient(fake_llm.fake_providers())))
    assert [c.component_id for c in again.components] == [c.component_id for c in first.components]  # ids by place
    with tenant_session(tenant.tenant_id, engine) as s:
        count = s.scalar(select(func.count()).select_from(m.Component).where(m.Component.drawing_id == drawing_id))
    assert count == len(first.components)


def test_the_tile_agent_never_sees_the_customer_the_title_block_or_a_price(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """04 §5.4, §12 and CLAUDE.md non-negotiable 6: one tile, its spans and the legend; nothing else."""
    tenant = add_tenant(seeded["app"])
    provider = FakeProvider(fake_llm.answer)
    pipeline.llm_providers = {"anthropic": provider}
    response = upload(
        api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], customer="לקוח סודי", project="פרויקט סודי"
    )
    assert response.status_code == 201
    Worker(pipeline).run_until_idle()
    asked = [r for r in provider.requests if r.stage == ASSOCIATE]
    assert asked
    title_block = [v for v in fake_llm.TITLE_BLOCK.values() if v]
    for request in asked:
        sent = f"{request.system}\n{request.user_text}\n{[i.key for i in request.images]}"
        assert "סודי" not in sent
        assert not any(v in sent for v in title_block)
        assert "₪" not in sent and "מחיר" not in sent and "$T" not in sent  # no amount, not even a reference
        assert len(request.images) == 1 and ":assoc:" in (request.images[0].key or "")  # one tile, keyed by its page


def test_the_run_step_shows_the_stage_4_line(api: Api, seeded: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(seeded["app"])
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    stage_4 = progress(api, tenant, drawing_id).json()["stages"][3]
    assert stage_4["status"] == "done"
    assert stage_4["summary"].startswith("איחוד לפי תגים: ")  # the stand-in's breakers are tagged
