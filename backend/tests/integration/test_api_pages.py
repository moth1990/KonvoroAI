"""Confirming the pages and changing a page's kind over HTTP (01 §5.6), checked against the actor and the tenant.

A change is a `page_reclassified` correction event; it rewrites stage 1's output so later stages read it; a changed
route on a finished drawing runs stages 2–7 again without counting (S08 decision); a page marked as a factory
template becomes one (01 §5.7)."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select

from konboro.contracts.intake import IntakeResult
from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.worker import Worker
from konboro.services.storage import Storage

from .api import Api, ApiTenant, add_tenant
from .test_api_upload import upload
from .test_pipeline import pipeline, quota_state  # noqa: F401  (fixture and helper)

NURSERY = Path(__file__).resolve().parents[3] / "golden" / "NURSERY-1" / "NURSERY-1.pdf"


def start(api: Api, tenant: ApiTenant, name: str = "NURSERY-1.pdf") -> str:
    response = upload(api, tenant, [(name, NURSERY.read_bytes())])
    assert response.status_code == 201, response.text
    return str(response.json()["drawing_id"])


def progress(api: Api, tenant: ApiTenant, drawing_id: str) -> dict[str, Any]:
    response = api.client.get(f"/drawings/{drawing_id}/progress", headers=api.as_(tenant))
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def change(api: Api, tenant: ApiTenant, drawing_id: str, page_id: str, kind: str):  # type: ignore[no-untyped-def]
    return api.client.patch(
        f"/drawings/{drawing_id}/pages/{page_id}", headers=api.as_(tenant), json={"page_kind": kind}
    )


def intake(engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str) -> IntakeResult:
    with tenant_session(tenant.tenant_id, engine) as s:
        key = s.get_one(m.StageRun, (tenant.tenant_id, drawing_id, 1)).output_key
    assert key is not None
    return IntakeResult.model_validate_json(storage.get(tenant.tenant_id, key))


def test_confirm_then_decoding_goes_on(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"])
    drawing_id = start(api, tenant, "unsure.pdf")
    assert Worker(pipeline).run_until_idle() == 1
    body = progress(api, tenant, drawing_id)
    assert (body["status"], body["confirmation_reasons"]) == ("awaiting_confirmation", ["low_confidence"])
    assert [p["unsure"] for p in body["pages"]] == [True] + [False] * 8
    assert body["pages"][0]["page_kind_confidence"] == 0.6 and body["summary"] is None

    response = api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(tenant))
    assert response.status_code == 200 and response.json()["status"] == "processing"
    assert Worker(pipeline).run_until_idle() == 6
    assert progress(api, tenant, drawing_id)["status"] == "ready"
    again = api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(tenant))
    assert (again.status_code, again.json()["error"]["code"]) == (409, "not_awaiting_confirmation")


def test_a_correction_while_waiting(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant, "unsure.pdf")
    Worker(pipeline).run_until_idle()
    first = progress(api, tenant, drawing_id)["pages"][0]

    response = change(api, tenant, drawing_id, first["page_id"], "single_line_diagram")
    assert response.status_code == 200, response.text
    page = response.json()["pages"][0]
    assert (page["page_kind"], page["route"], page["classified_by"], page["unsure"]) == (
        "single_line_diagram",
        "process",
        "user",
        False,
    )
    assert response.json()["confirmation_reasons"] == []  # nothing left to doubt; the user still confirms
    assert Worker(pipeline).run_until_idle() == 0  # nothing re-runs while waiting

    with tenant_session(tenant.tenant_id, engine) as s:
        (event,) = s.scalars(select(m.CorrectionEvent)).all()
        assert (event.type, event.source, event.page_id, event.user_id) == (
            "page_reclassified",
            "new_quote",
            first["page_id"],
            tenant.user_id,
        )
        assert event.before == {"page_kind": "technical_data", "route": "context", "confidence": 0.6}
        assert event.after == {"page_kind": "single_line_diagram", "route": "process", "confidence": 1.0}
    out = intake(engine, storage, tenant, drawing_id)
    assert (out.pages[0].page_kind, out.pages[0].route, out.pages[0].classified_by) == (
        "single_line_diagram",
        "process",
        "user",
    )
    (panel,) = out.panels
    assert first["page_id"] in panel.page_ids  # the page joined the drawing's panel

    api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(tenant))
    assert Worker(pipeline).run_until_idle() == 6


def test_a_new_route_on_a_finished_drawing_runs_stages_2_to_7_again(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=5)
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()
    skipped = next(p for p in progress(api, tenant, drawing_id)["pages"] if p["route"] == "skip")

    response = change(api, tenant, drawing_id, skipped["page_id"], "control_diagram")
    assert response.status_code == 200 and response.json()["status"] == "processing"
    assert Worker(pipeline).run_until_idle() == 6
    body = progress(api, tenant, drawing_id)
    assert body["status"] == "ready"
    assert body["summary"]["pages_by_route"] == {"process": 6, "context": 2, "skip": 1}
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.Quote)) == 1  # the same quote
        runs = s.scalars(select(m.StageRun).order_by(m.StageRun.stage)).all()
        assert [(r.stage, r.status, r.attempts) for r in runs] == [(1, "done", 1)] + [
            (n, "done", 1) for n in range(2, 8)
        ]
    assert quota_state(engine, tenant)[:2] == (6, 0)  # counted once


def test_the_same_route_runs_nothing_again(api: Api, migrated_db: dict[str, Engine], pipeline: Pipeline) -> None:  # noqa: F811
    tenant = add_tenant(migrated_db["app"])
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()
    diagram = progress(api, tenant, drawing_id)["pages"][5]
    response = change(api, tenant, drawing_id, diagram["page_id"], "control_diagram")
    assert response.status_code == 200 and response.json()["status"] == "ready"
    assert Worker(pipeline).run_until_idle() == 0


def test_a_page_marked_as_a_template_becomes_one(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        before = s.scalar(select(func.count()).select_from(m.PageTemplate))
    front = progress(api, tenant, drawing_id)["pages"][3]
    assert change(api, tenant, drawing_id, front["page_id"], "factory_template").status_code == 200
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = s.scalars(select(m.PageTemplate).order_by(m.PageTemplate.created_at)).all()
        assert len(rows) == (before or 0) + 1
        assert (rows[-1].source_page_id, rows[-1].producer) == (front["page_id"], "מפעל הדגמה")
    Worker(pipeline).run_until_idle()


def test_changes_are_checked_against_the_tenant_and_the_state(
    api: Api,
    migrated_db: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = migrated_db["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    drawing_id = start(api, tenant, "unsure.pdf")
    elsewhere = start(api, tenant)
    busy = change(api, tenant, elsewhere, "pg_" + "0" * 26, "legend")
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "drawing_busy")  # stage 1 hasn't run
    Worker(pipeline).run_until_idle()
    page = progress(api, tenant, drawing_id)["pages"][0]
    foreign_page = progress(api, tenant, elsewhere)["pages"][0]

    assert change(api, other, drawing_id, page["page_id"], "legend").status_code == 404  # another tenant
    assert api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(other)).status_code == 404
    assert change(api, tenant, drawing_id, foreign_page["page_id"], "legend").status_code == 404  # not its page
    bad = change(api, tenant, drawing_id, page["page_id"], "a_poster")
    assert bad.status_code == 422  # only the closed list (01 §5.4)
    unauthenticated = api.client.patch(f"/drawings/{drawing_id}/pages/{page['page_id']}", json={"page_kind": "legend"})
    assert unauthenticated.status_code == 401
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.CorrectionEvent)) == 0
