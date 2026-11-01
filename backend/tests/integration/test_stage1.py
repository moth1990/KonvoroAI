"""Stage 1 on the local services (01): reuse by hash stays inside a tenant (01 §11), factory templates are matched
without a model only for their producer (01 §5.7), a blurry photo stops the drawing at once without counting
(01 §5.3, §4.5), the pipeline waits for confirmation when it must (01 §5.6), and a long stage is never delivered
twice (BUG-009). The model is the stand-in (`devtools/fake_llm.py`): never a real one in tests."""

import io
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import Engine, func, select, text

from konboro.db import models as m
from konboro.db.session import global_session, tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.intake.pages import read_pages
from konboro.pipeline.worker import Worker
from konboro.services.queue import STAGE_QUEUES
from konboro_llm import LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.page_classification import STAGE as CLASSIFY
from konboro_llm.stages.page_classification import TitleBlockAnswer

from .api import Api, ApiTenant, add_tenant
from .test_api_upload import upload
from .test_pipeline import pipeline, quota_state, start  # noqa: F401  (fixture and helpers)

GOLDEN = Path(__file__).resolve().parents[3] / "golden"
NEVIS = GOLDEN / "NEVIS-1" / "NEVIS-1.pdf"
NURSERY = GOLDEN / "NURSERY-1" / "NURSERY-1.pdf"


def pages_of(engine: Engine, tenant: ApiTenant, drawing_id: str) -> list[m.Page]:
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = s.scalars(select(m.Page).where(m.Page.drawing_id == drawing_id).order_by(m.Page.page_no)).all()
        s.expunge_all()
        return list(rows)


def send(api: Api, tenant: ApiTenant, path: Path, name: str | None = None) -> str:
    response = upload(api, tenant, [(name or path.name, path.read_bytes())])
    assert response.status_code == 201, response.text
    return str(response.json()["drawing_id"])


def classify_calls(provider: FakeProvider) -> int:
    return sum(1 for stage, _, _ in provider.calls if stage == CLASSIFY)


def with_designer(designer: str) -> FakeProvider:
    def answer(request: LLMRequest[Any]) -> dict[str, Any]:
        out = fake_llm.answer(request)
        if "designer" in out:
            out = {**out, "designer": designer}
        if isinstance(out.get("title_block"), dict):
            out = {**out, "title_block": {**out["title_block"], "designer": designer}}
        return out

    return FakeProvider(answer)


# --- reuse by hash (01 §5.1, §11) -------------------------------------------------------------------------------


def test_reuse_by_hash_never_crosses_tenants(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    engine = migrated_db["app"]
    a, b = add_tenant(engine), add_tenant(engine)
    first = send(api, a, NURSERY)
    Worker(pipeline).run_until_idle()
    other = send(api, b, NURSERY)  # the same file, in another factory
    Worker(pipeline).run_until_idle()
    again = send(api, a, NURSERY)  # the same file, in the same factory
    Worker(pipeline).run_until_idle()

    first_pages = {p.sha256: p.id for p in pages_of(engine, a, first)}
    assert {p.classified_by for p in pages_of(engine, b, other)} <= {"model", "template"}
    assert all(p.reused_from is None for p in pages_of(engine, b, other))
    reused = pages_of(engine, a, again)
    assert {p.classified_by for p in reused} == {"reused"}
    assert [p.reused_from for p in reused] == [first_pages[p.sha256] for p in reused]
    with tenant_session(a.tenant_id, engine) as s:
        kinds = [s.get_one(m.Drawing, d).input_kind for d in (first, again)]
    assert kinds == ["factory_drawing", "factory_drawing"]  # the page's tag reading is reused too (BUG-015)
    assert {p.component_labels for p in reused if p.route == "process"} == {"tags_and_models"}
    assert quota_state(engine, b)[0] == 1  # counted in b: nothing of a's was reused there


# --- the title block (01 §5.4, S08 decision) ----------------------------------------------------------------------


def test_a_title_block_nobody_boxed_is_read_from_the_whole_page(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """BUG-014: on a large sheet the classifier may box no title block and read none from its overview. The first
    process page is then read whole at the detail size, once. (6199-2-50 is one single-line sheet.)"""
    engine = migrated_db["app"]
    tenant = add_tenant(engine)

    def unboxed(request: LLMRequest[Any]) -> dict[str, Any]:
        out = fake_llm.answer(request)
        if request.stage == CLASSIFY:
            regions = [r for r in out["regions"] if r["region_kind"] != "title_block"]
            out = {**out, "page_kind": "single_line_diagram", "title_block": None, "regions": regions}
        return out

    provider = FakeProvider(unboxed)
    pipeline.llm_providers = {"anthropic": provider}
    drawing_id = send(api, tenant, GOLDEN / "6199-2-50" / "6199-2-50.pdf")
    Worker(pipeline).run_until_idle()
    reads = [r for r in provider.requests if r.output_schema is TitleBlockAnswer]
    assert len(reads) == 1
    with tenant_session(tenant.tenant_id, engine) as s:
        block = s.get_one(m.Drawing, drawing_id).title_block
    assert block is not None and block["drawing_number"] == fake_llm.TITLE_BLOCK["drawing_number"]


# --- factory templates (01 §5.7) ---------------------------------------------------------------------------------


def test_a_template_page_is_classified_without_the_model(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """NEVIS-1 pages 2–3 become templates; NURSERY-1 page 3 is the same page and matches; its page 2 is the same
    tables in another layout, so it goes to the model (the safe side)."""
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    provider = FakeProvider(fake_llm.answer)
    pipeline.llm_providers = {"anthropic": provider}
    send(api, tenant, NEVIS)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.PageTemplate)) == 2
    before = classify_calls(provider)

    nursery = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    pages = pages_of(engine, tenant, nursery)
    assert [(p.page_no, p.classified_by) for p in pages if p.classified_by == "template"] == [(3, "template")]
    assert (pages[2].page_kind, pages[2].route, pages[2].model) == ("factory_template", "skip", None)
    assert classify_calls(provider) - before == 8  # nine pages, one of them a template


def test_a_template_counts_only_for_its_producer(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    pipeline.llm_providers = {"anthropic": with_designer("מפעל אחד")}
    send(api, tenant, NEVIS)
    Worker(pipeline).run_until_idle()
    provider = with_designer("מפעל אחר")
    pipeline.llm_providers = {"anthropic": provider}
    nursery = send(api, tenant, NURSERY)
    Worker(pipeline).run_until_idle()
    pages = pages_of(engine, tenant, nursery)
    assert "template" not in {p.classified_by for p in pages}
    asked = [r.user_text.split(",")[0] for r in provider.requests if r.stage == CLASSIFY]
    # Page 3 matched a template at first; once the title block named another producer, it went to the model.
    assert asked[-1] == "Page 3 of 9" and sorted(asked) == sorted(f"Page {n} of 9" for n in range(1, 10))


def test_templates_stay_in_their_tenant(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    engine = migrated_db["app"]
    a, b = add_tenant(engine), add_tenant(engine)
    send(api, a, NEVIS)
    Worker(pipeline).run_until_idle()
    nursery = send(api, b, NURSERY)
    Worker(pipeline).run_until_idle()
    assert "template" not in {p.classified_by for p in pages_of(engine, b, nursery)}


# --- quality: fail fast (01 §5.3) --------------------------------------------------------------------------------


def photo(blur: float = 0) -> bytes:
    """A phone photo of a handwritten list: dark strokes on paper, 1,400 px tall."""
    img = Image.new("RGB", (900, 1400), "white")
    draw = ImageDraw.Draw(img)
    for row in range(40, 1360, 34):
        for col in range(60, 840, 46):
            draw.line([(col, row), (col + 30, row + 18)], fill="black", width=3)
            draw.line([(col + 30, row), (col, row + 18)], fill="black", width=2)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def test_a_blurry_photo_stops_at_once_and_does_not_count(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=2)
    provider = FakeProvider(fake_llm.answer)
    pipeline.llm_providers = {"anthropic": provider}
    response = upload(api, tenant, [("bom.jpg", photo(blur=4))])
    drawing_id = response.json()["drawing_id"]
    assert Worker(pipeline).run_until_idle() == 1  # stage 1 only
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        assert drawing.status == "failed"
        (issue,) = [i for i in drawing.issues if i["severity"] == "error"]
        assert issue["code"] == "blurry" and "לא קריא" in issue["message"]
        assert {r.status for r in s.scalars(select(m.StageRun).where(m.StageRun.stage >= 2))} == {"skipped"}
    assert provider.calls == []  # no model saw it
    assert quota_state(engine, tenant) == (2, 0, ["reserve", "release"])


def test_a_sharp_photo_goes_on(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    response = upload(api, tenant, [("bom.jpg", photo())])
    drawing_id = response.json()["drawing_id"]
    Worker(pipeline).run_until_idle()
    (page,) = pages_of(engine, tenant, drawing_id)
    assert (page.quality, page.geometry_source, page.text_source) == ("ok", "raster", "ocr")
    assert (page.width_pt, page.height_pt) == (900.0, 1400.0)  # no DPI in the file: one pixel is one point


# --- confirmation (01 §5.6) ---------------------------------------------------------------------------------------


def test_the_pipeline_waits_for_confirmation(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=1)
    drawing_id = send(api, tenant, NURSERY, name="unsure-NURSERY.pdf")
    assert Worker(pipeline).run_until_idle() == 1
    with global_session(engine) as s:  # the sweep's own lookup, read only: other tests' drawings stay untouched
        unsent = s.execute(text("SELECT drawing_id FROM konboro_unsent_stages(interval '0')")).scalars().all()
    assert drawing_id not in unsent  # stage 2 was never sent, so the sweep has nothing to send again
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        assert (drawing.status, drawing.needs_confirmation) == ("awaiting_confirmation", True)
        assert s.get_one(m.StageRun, (tenant.tenant_id, drawing_id, 2)).sent_at is None
    assert quota_state(engine, tenant) == (2, 0, ["reserve", "confirm"])  # counted: stage 1 succeeded (01 §4.5)


# --- the heartbeat (BUG-009) --------------------------------------------------------------------------------------


def test_a_long_stage_is_not_delivered_twice(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    """The message's visibility is cut to 1 s; the stage runs 4 s. Without the heartbeat the queue would hand the
    message out again mid-stage."""
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    pipeline.settings = pipeline.settings.model_copy(
        update={"stage_heartbeat_seconds": 0.3, "stage_visibility_seconds": 1}
    )
    original = pipeline.stages[1]
    seen_again: list[int] = []

    def slow(ctx: StageContext) -> Any:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            seen_again.append(len(pipeline.queue.receive(STAGE_QUEUES[1])))
            time.sleep(0.5)
        return original(ctx)

    pipeline.stages[1] = slow
    start(api, tenant)
    (received,) = pipeline.queue.receive(STAGE_QUEUES[1], wait_s=2)
    pipeline.queue.extend(received, 1)
    done = threading.Event()
    outcome: list[str] = []

    def handle() -> None:
        outcome.append(pipeline.handle(received))
        done.set()

    threading.Thread(target=handle, daemon=True).start()
    assert done.wait(60)
    assert outcome == ["done"]
    assert sum(seen_again) == 0
    Worker(pipeline).run_until_idle()


def test_without_the_heartbeat_the_message_comes_back(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """The control for the test above: the same short visibility, no heartbeat, and the message is seen again."""
    tenant = add_tenant(migrated_db["app"])
    start(api, tenant)
    (received,) = pipeline.queue.receive(STAGE_QUEUES[1], wait_s=2)
    pipeline.queue.extend(received, 1)
    time.sleep(1.5)
    again = pipeline.queue.receive(STAGE_QUEUES[1], wait_s=1)
    assert len(again) == 1
    pipeline.queue.delete(again[0])


# --- what the model sees (01 §11, CLAUDE.md non-negotiable 6) ----------------------------------------------------


def test_the_model_never_sees_the_customer_or_the_project(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """Only page images and the page's own text reach the model: not the customer or project the user typed."""
    tenant = add_tenant(migrated_db["app"])
    provider = FakeProvider(fake_llm.answer)
    pipeline.llm_providers = {"anthropic": provider}
    response = upload(
        api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], customer="לקוח סודי", project="פרויקט סודי"
    )
    assert response.status_code == 201
    Worker(pipeline).run_until_idle()
    assert provider.requests
    hashes = {p.sha256 for p in read_pages("fil", "pdf", NURSERY.read_bytes())}
    for request in provider.requests:
        sent = f"{request.system}\n{request.user_text}\n{[i.key for i in request.images]}"
        assert "סודי" not in sent
        assert request.tenant_id == tenant.tenant_id  # for cost logging; never sent (konboro_llm.types)
        # images of the pages only, and stage 3's reference sheets: our own drawings, keyed by the library version
        assert all(i.key and (i.key.split(":")[0] in hashes or i.key.startswith("lib-")) for i in request.images)


# --- every golden file through the queue -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("folder", "pages", "rotation"),
    [("26-993", 5, 90), ("6199-2-50", 1, 0), ("NEVIS-1", 9, 270), ("NURSERY-1", 9, 270), ("BOM-HW-1", 1, 0)],
)
def test_every_golden_file_goes_through_stage_1(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    folder: str,
    pages: int,
    rotation: int,
) -> None:
    """The code facts match the labels' `file_facts` (rotation, vector geometry, OCR text); the kinds come from the
    stand-in model, so they are checked by the eval, not here."""
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    path = next((GOLDEN / folder).glob(f"{folder}.*"))
    drawing_id = send(api, tenant, path)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.get_one(m.Drawing, drawing_id).status in ("ready", "awaiting_confirmation")
    rows = pages_of(engine, tenant, drawing_id)
    assert len(rows) == pages and {p.rotation_applied for p in rows} == {rotation}
    expected = ("raster", "ocr") if path.suffix == ".jpg" else ("vector", "ocr")
    assert {(p.geometry_source, p.text_source) for p in rows} == {expected}
    assert all(p.render_key and p.sha256 and p.quality == "ok" for p in rows)
