"""Stage 3 on the local services (03): through the queue, every `process` page gets detections with crops under its
own tenant's S3 prefix, the model calls go through `konboro_llm` and are logged per tenant, a tenant's and a
designer's abbreviations reach only that tenant's drawings, and the run step shows the stage's line. The model is the
stand-in (`devtools/fake_llm.py`): never a real one in tests."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.contracts.detection import DetectionResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.detection import library
from konboro.pipeline.worker import Worker
from konboro.services.storage import Storage, TenantKeyError
from konboro_llm.stages.symbol_detection import STAGE as DETECT

from .api import Api, add_tenant, set_tenant_flag
from .test_api_drawings import progress
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY, send

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the symbol library's global rows (S12)
    return migrated_db


def detections(engine: Engine, storage: Storage, tenant_id: str, drawing_id: str) -> DetectionResult:
    with tenant_session(tenant_id, engine) as s:
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 3))
    assert key is not None
    return DetectionResult.model_validate_json(storage.get(tenant_id, key))


def test_stage_3_writes_detections_and_crops_under_the_tenant(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()

    out = detections(engine, storage, tenant.tenant_id, drawing_id)
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = {p.id: p for p in s.scalars(select(m.Page).where(m.Page.drawing_id == drawing_id))}
        calls = s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == DETECT).limit(1))
        version = library.load(s, None).version
        s.expunge_all()
    process = [p for p in rows.values() if p.route == "process"]
    assert len(out.pages) == len(process) > 0
    prefix = f"tenants/{tenant.tenant_id}/drawings/{drawing_id}/"
    for page in out.pages:
        assert page.detections, page.page_id  # the stand-in finds one breaker per tile
        assert page.library_version == version and page.detector_model == "symbol_detection"
        assert rows[page.page_id].symbol_count == len(page.detections)
        for d in page.detections:
            assert d.crop_uri is not None and d.crop_uri.startswith(prefix)
            assert storage.get(tenant.tenant_id, d.crop_uri)
            assert d.owner_tile_id in d.seen_in_tile_ids
        with pytest.raises(TenantKeyError):
            storage.get(other.tenant_id, page.detections[0].crop_uri or "")
    assert calls is not None  # detection went through konboro_llm and was logged for this tenant
    with tenant_session(other.tenant_id, engine) as s:
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == DETECT)) is None


def test_a_tenants_and_a_designers_abbreviations_reach_only_that_tenant(seeded: dict[str, Engine]) -> None:
    engine = seeded["app"]
    mine, theirs = add_tenant(engine), add_tenant(engine)
    with tenant_session(mine.tenant_id, engine) as s:
        s.add(m.TenantAbbreviation(id=new_id("tab"), tenant_id=mine.tenant_id, text="ZZ", symbol_class="timer"))
        s.add(
            m.TenantAbbreviation(
                id=new_id("tab"),
                tenant_id=mine.tenant_id,
                scope="designer",
                designer="רמאור",
                text="TC",
                symbol_class="contactor",
            )
        )
    with tenant_session(mine.tenant_id, engine) as s:
        assert library.load(s, None).classify_text("ZZ3").symbol_class == "timer"  # type: ignore[union-attr]
        assert library.load(s, None).classify_text("TC").symbol_class == "shunt_trip"  # type: ignore[union-attr]
        assert library.load(s, "רמאור").classify_text("TC").symbol_class == "contactor"  # type: ignore[union-attr]
    with tenant_session(theirs.tenant_id, engine) as s:
        assert library.load(s, None).classify_text("ZZ3") is None
        assert library.load(s, "רמאור").classify_text("TC").symbol_class == "shunt_trip"  # type: ignore[union-attr]


def test_the_run_step_shows_the_stage_3_line(api: Api, seeded: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(seeded["app"])
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    stage_3 = progress(api, tenant, drawing_id).json()["stages"][2]
    assert stage_3["status"] == "done"
    assert stage_3["summary"].endswith(" סימנים")  # the stand-in is always sure: nothing for the disambiguation call


def test_a_drawing_from_the_pipeline_opens_for_review(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """Stage 1 keeps each panel's boxes per page as a list (`panels.bboxes`); the quote API sends one box per page.
    The review fixture has no boxes, so only a drawing from the pipeline reaches that path (BUG-026)."""
    engine = seeded["app"]
    tenant = add_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, "review_screen", True)
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    quote_id = progress(api, tenant, drawing_id).json()["quote_id"]
    r = api.client.get(f"/quotes/{quote_id}", headers=api.as_(tenant))
    assert r.status_code == 200, r.text
    boxes = [pn["bbox"] for page in r.json()["pages"] for pn in page["panels"]]
    assert boxes and all(b is None or (len(b) == 4 and all(isinstance(v, float) for v in b)) for b in boxes)
