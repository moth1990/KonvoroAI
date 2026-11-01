"""Stage 2 on the local services (02): through the queue, every `process` page gets a render, tiles, a viewer
pyramid and a wire graph under its own tenant's S3 prefix; OCR goes through `konboro_llm` and is logged per tenant;
a PDF with a real text layer needs no OCR; and the run step shows the stage's line. The model is the stand-in
(`devtools/fake_llm.py`): never a real one in tests."""

import pytest
from sqlalchemy import Engine, select

from konboro.contracts.extraction import ExtractionResult
from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.worker import Worker
from konboro.services.storage import Storage, TenantKeyError
from konboro_llm.stages.ocr_transcription import STAGE as OCR

from ..unit.test_extraction import make_pdf
from .api import Api, add_tenant
from .test_api_drawings import progress
from .test_api_upload import upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY, send

pytestmark = pytest.mark.integration


def extraction(engine: Engine, storage: Storage, tenant_id: str, drawing_id: str) -> ExtractionResult:
    with tenant_session(tenant_id, engine) as s:
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 2))
    assert key is not None
    return ExtractionResult.model_validate_json(storage.get(tenant_id, key))


def test_stage_2_writes_renders_tiles_and_pyramids_under_the_tenant(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = migrated_db["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()

    out = extraction(engine, storage, tenant.tenant_id, drawing_id)
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = {p.id: p for p in s.scalars(select(m.Page).where(m.Page.drawing_id == drawing_id))}
        ocr_calls = s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == OCR).limit(1))
        s.expunge_all()
    process = [p for p in rows.values() if p.route == "process"]
    assert len(out.pages) == len(process) > 0
    prefix = f"tenants/{tenant.tenant_id}/drawings/{drawing_id}/"
    for page in out.pages:
        assert page.render is not None and page.render.dzi_uri is not None
        row = rows[page.page_id]
        assert row.render_key == page.render.image_uri
        assert row.tile_count == sum(1 for t in page.tiles if not t.is_blank)
        assert page.wire_graph is not None and page.wire_graph.status == "built"
        keys = [page.render.image_uri, page.render.dzi_uri, page.wire_graph.uri, *(t.image_uri for t in page.tiles)]
        for key in keys:
            assert key is not None and key.startswith(prefix)
            assert storage.get(tenant.tenant_id, key)  # it is there
        with pytest.raises(TenantKeyError):
            storage.get(other.tenant_id, page.render.image_uri)  # and only for its own tenant
        assert page.text_spans and all(s.source == "ocr" for s in page.text_spans)
    assert ocr_calls is not None  # OCR went through konboro_llm and was logged for this tenant
    with tenant_session(other.tenant_id, engine) as s:
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == OCR)) is None


def test_a_pdf_with_a_text_layer_needs_no_ocr(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    texts = [("Q1 C16 3P", 100.0, 700.0, 0.0), ("MAIN 400A", 100.0, 650.0, 0.0), ("F1 B10", 300.0, 600.0, 0.0)]
    lines = [(50.0 + 10 * i, 100.0, 50.0 + 10 * i, 500.0) for i in range(60)]
    # the stand-in classifies page 5 onwards as single-line diagrams (fake_llm.KINDS)
    data = make_pdf(texts=texts, lines=lines, pages=5)
    response = upload(api, tenant, [("text-layer.pdf", data)])
    assert response.status_code == 201, response.text
    drawing_id = str(response.json()["drawing_id"])
    Worker(pipeline).run_until_idle()

    out = extraction(engine, storage, tenant.tenant_id, drawing_id)
    (page,) = out.pages
    assert {s.text for s in page.text_spans} >= {"Q1", "MAIN", "400A", "F1"}
    assert all(s.source == "pdf_text" and s.confidence == 1.0 for s in page.text_spans)
    assert page.stats.ocr_span_count == 0
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == OCR)) is None
    stage_2 = progress(api, tenant, drawing_id).json()["stages"][1]
    assert stage_2["status"] == "done" and stage_2["summary"].startswith("טקסט מהקובץ · ")


def test_the_run_step_shows_the_stage_2_line(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"])
    drawing_id = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    stages = progress(api, tenant, drawing_id).json()["stages"]
    assert stages[1]["summary"].startswith("שכבת טקסט חסרה, OCR על 5 עמודים · ")
    assert stages[1]["summary"].endswith("אריחים")
