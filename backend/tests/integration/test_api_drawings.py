"""Progress, cancel and the "new version" picker over HTTP (01 §4.6), tenant-scoped."""

import io
import urllib.request

import pytest
from PIL import Image
from sqlalchemy import Engine

from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import FAILED_MESSAGE, Pipeline
from konboro.pipeline.stages.s1_intake import THUMB_PX
from konboro.pipeline.worker import Worker

from .api import Api, add_tenant
from .test_pipeline import pipeline, start  # noqa: F401  (fixture and helper)


def progress(api: Api, tenant, drawing_id: str):  # type: ignore[no-untyped-def]
    return api.client.get(f"/drawings/{drawing_id}/progress", headers=api.as_(tenant))


def test_progress_from_upload_to_ready(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"])
    drawing_id = start(api, tenant, project="גן ילדים")
    body = progress(api, tenant, drawing_id).json()
    assert (body["status"], body["progress"], body["counted"], body["counted_as"]) == (
        "uploaded",
        0,
        False,
        "new_drawing",
    )
    assert [(s["stage"], s["status"], s["summary"]) for s in body["stages"]][:2] == [
        (1, "queued", None),
        (2, "queued", None),
    ]
    assert body["stages"][0]["name"] == "קליטה וסיווג עמודים"
    assert (body["name"], body["files"]) == ("גן ילדים", [{"name": "NURSERY-1.pdf", "page_count": 9}])
    assert (body["quote_id"], body["summary"], body["pages"]) == (None, None, [])

    Worker(pipeline).run_until_idle()
    body = progress(api, tenant, drawing_id).json()
    assert (body["status"], body["progress"], body["current_stage"], body["counted"]) == ("ready", 1, 7, True)
    assert [s["status"] for s in body["stages"]] == ["done"] * 7
    assert body["stages"][0]["summary"] == "9 עמודים · 2 תבניות של המפעל · לוח אחד"
    assert body["quote_id"].startswith("quo_")
    assert body["summary"] == {
        "input_kind": "factory_drawing",
        "panels": ["לוח ראשי"],
        "page_count": 9,
        "pages_by_route": {"process": 5, "context": 2, "skip": 2},
        "products": 0,
        "priced": 0,
        "findings": 0,
    }
    assert [p["page_no"] for p in body["pages"]] == list(range(1, 10))
    assert [p["page_kind"] for p in body["pages"]][:4] == [
        "technical_data",
        "factory_template",
        "factory_template",
        "panel_front_view",
    ]
    assert (body["confirmation_reasons"], body["notices"]) == ([], [])
    for page in (body["pages"][0], body["pages"][4]):  # a context page and a process page, which stage 2 renders
        with urllib.request.urlopen(page["thumbnail_url"]) as response:  # noqa: S310 (local S3Mock)
            thumb = Image.open(io.BytesIO(response.read()))
        assert thumb.format == "PNG"
        assert max(thumb.size) <= THUMB_PX  # the thumbnail, never stage 2's full render (BUG-023)


def test_cancel_over_http(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"], used=3)
    drawing_id = start(api, tenant)
    response = api.client.post(f"/drawings/{drawing_id}/cancel", headers=api.as_(tenant))
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["counted"]) == ("cancelled", False)
    assert {s["status"] for s in response.json()["stages"]} == {"skipped"}
    again = api.client.post(f"/drawings/{drawing_id}/cancel", headers=api.as_(tenant))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "drawing_finished")
    assert api.client.get("/quota", headers=api.as_(tenant)).json()["counters"][0]["used"] == 3
    Worker(pipeline).run_until_idle()


def test_a_failed_run_says_so_in_hebrew(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"])

    def broken(ctx: StageContext):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    pipeline.stages[2] = broken
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()
    body = progress(api, tenant, drawing_id).json()
    assert (body["status"], body["error"], body["counted"]) == ("failed", FAILED_MESSAGE, False)
    assert [s["status"] for s in body["stages"]][:3] == ["done", "failed", "queued"]


def test_the_version_picker_lists_finished_drawings(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    tenant = add_tenant(migrated_db["app"])
    finished = start(api, tenant, project="לוח קומה 3")
    Worker(pipeline).run_until_idle()
    start(api, tenant)  # still running: not offered
    body = api.client.get("/drawings/revisable", headers=api.as_(tenant)).json()
    assert [(r["drawing_id"], r["name"], r["version"]) for r in body] == [(finished, "לוח קומה 3", 1)]
    Worker(pipeline).run_until_idle()


def test_another_tenant_sees_nothing(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    engine = migrated_db["app"]
    a, b = add_tenant(engine), add_tenant(engine)
    drawing_id = start(api, a)
    Worker(pipeline).run_until_idle()
    assert progress(api, b, drawing_id).status_code == 404
    assert api.client.post(f"/drawings/{drawing_id}/cancel", headers=api.as_(b)).status_code == 404
    assert api.client.get("/drawings/revisable", headers=api.as_(b)).json() == []
    assert progress(api, a, drawing_id).json()["status"] == "ready"


@pytest.mark.parametrize("path", ["/drawings/not-an-id/progress", "/drawings/drw_x/cancel"])
def test_a_malformed_id_is_a_validation_error(api: Api, path: str) -> None:
    call = api.client.post if path.endswith("cancel") else api.client.get
    assert call(path, headers=api.as_(api.a)).status_code == 422
