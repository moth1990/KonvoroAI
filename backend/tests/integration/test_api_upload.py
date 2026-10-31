"""POST /drawings: the checks of 01 §4.3 in order, all-or-nothing, and no quota trace for a rejected upload."""

import io
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import Engine, func, select, text

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.services.queue import STAGE_QUEUES, Queue
from konboro.services.storage import Storage

from .api import Api, ApiTenant, add_tenant

NURSERY = Path(__file__).resolve().parents[3] / "golden" / "NURSERY-1" / "NURSERY-1.pdf"
DWG = b"AC1027" + b"\x00" * 64


def pdf(pages: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def upload(api: Api, tenant: ApiTenant, files: list[tuple[str, bytes]], **form: str):  # type: ignore[no-untyped-def]
    parts = [("files", (name, data, "application/octet-stream")) for name, data in files]
    return api.client.post("/drawings", headers=api.as_(tenant), files=parts, data=form)


def quota_row(engine: Engine, tenant: ApiTenant) -> tuple[int, int, int]:
    with tenant_session(tenant.tenant_id, engine) as s:
        used, reserved = s.execute(
            select(func.coalesce(func.sum(m.QuotaUsage.used), 0), func.coalesce(func.sum(m.QuotaUsage.reserved), 0))
        ).one()
        events = s.scalar(select(func.count()).select_from(m.QuotaEvent))
    return int(used), int(reserved), int(events or 0)


def drawing_count(engine: Engine, tenant: ApiTenant) -> int:
    with tenant_session(tenant.tenant_id, engine) as s:
        return int(s.scalar(select(func.count()).select_from(m.Drawing)) or 0)


def test_a_valid_upload_is_stored_reserved_and_queued(
    api: Api, migrated_db: dict[str, Engine], clean_queue: Queue, storage: Storage
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, used=12)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], customer="קבלן", project="גן ילדים")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["counted_as"] == "new_drawing"
    assert body["files"] == [
        {
            "name": "NURSERY-1.pdf",
            "size_bytes": NURSERY.stat().st_size,
            "detected_format": "pdf",
            "page_count": 9,
            "error": None,
            "message": None,
        }
    ]
    drawing_id = body["drawing_id"]

    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        (file,) = s.scalars(select(m.DrawingFile)).all()
        runs = s.scalars(select(m.StageRun.status).order_by(m.StageRun.stage)).all()
        project = s.get_one(m.Project, drawing.project_id)
        assert (project.name, s.get_one(m.Customer, project.customer_id).name) == ("גן ילדים", "קבלן")
        assert drawing.quota and drawing.quota["counted"] is False
        reservation = s.get_one(m.QuotaEvent, drawing.quota["reservation_id"])
        assert (reservation.kind, reservation.drawing_id) == ("reserve", drawing_id)
        key, file_id, trace_id = file.storage_key, file.id, drawing.trace_id
    assert key == f"tenants/{tenant.tenant_id}/drawings/{drawing_id}/files/{file_id}.pdf"
    assert storage.get(tenant.tenant_id, key) == NURSERY.read_bytes()
    assert runs == ["queued"] * 7
    assert quota_row(engine, tenant) == (12, 1, 1)  # reserved, not yet counted: that happens after stage 1

    (queued,) = clean_queue.receive(STAGE_QUEUES[1], wait_s=2)
    assert queued.message.model_dump() == {
        "drawing_id": drawing_id,
        "tenant_id": tenant.tenant_id,
        "stage": 1,
        "trace_id": trace_id,
    }
    clean_queue.delete(queued)


def test_a_cad_file_rejects_the_whole_upload_and_leaves_no_trace(
    api: Api, migrated_db: dict[str, Engine], clean_queue: Queue
) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes()), ("MAIN_BOARD.dwg", DWG)])
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "upload_rejected"
    assert [(d["name"], d["error"]) for d in error["details"]] == [
        ("NURSERY-1.pdf", None),
        ("MAIN_BOARD.dwg", "cad_not_supported"),
    ]
    assert "Plot ל-PDF" in error["details"][1]["message"]
    assert drawing_count(engine, tenant) == 0
    assert quota_row(engine, tenant) == (0, 0, 0)  # the reservation rolled back with the rest
    assert clean_queue.receive(STAGE_QUEUES[1], wait_s=1) == []


def test_too_large_and_too_many_pages(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        s.execute(text("UPDATE tenant_plan_overrides SET max_pages_per_file = 5"))
    big = b"a,b\n" + b"1" * (20 * 1024 * 1024)
    response = upload(api, tenant, [("scan_site.csv", big), ("project_full.pdf", pdf(6))])
    details = response.json()["error"]["details"]
    assert [(d["error"], d["message"]) for d in details] == [
        (
            "too_large",
            "הקובץ scan_site.csv גדול מ-20MB. אפשר לייצא אותו מחדש בלי תמונות ברזולוציה גבוהה, או לפצל אותו.",
        ),
        (
            "too_many_pages",
            "בקובץ project_full.pdf יש 6 עמודים, והמקסימום בחבילה שלכם הוא 5. "
            "אפשר להעלות רק את עמודי הלוחות, או לפצל את הקובץ.",
        ),
    ]
    assert drawing_count(engine, tenant) == 0


def test_the_quota_is_checked_first(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, limit=10, used=10)
    response = upload(api, tenant, [("MAIN_BOARD.dwg", DWG)])  # a bad file too, but the quota comes first
    assert (response.status_code, response.json()["error"]["code"]) == (403, "quota_reached")
    assert drawing_count(engine, tenant) == 0
    assert quota_row(engine, tenant) == (10, 0, 0)


def test_a_new_version_reserves_nothing(api: Api, migrated_db: dict[str, Engine], clean_queue: Queue) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine, limit=10, used=10)  # even with the quota full
    with tenant_session(tenant.tenant_id, engine) as s:
        s.add(m.Drawing(id=(previous := new_id("drw")), tenant_id=tenant.tenant_id, status="ready"))
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], revision_of=previous)
    assert response.status_code == 201, response.text
    assert response.json()["counted_as"] == "revision"
    assert quota_row(engine, tenant) == (10, 0, 0)
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, response.json()["drawing_id"])
        assert drawing.revision_of == previous
        assert drawing.quota == {"counted": False, "reason": "revision", "reservation_id": None, "quota_event_id": None}
    clean_queue.purge(STAGE_QUEUES[1])


def test_a_version_of_another_tenants_drawing_is_not_found(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    a, b = add_tenant(engine), add_tenant(engine)
    with tenant_session(a.tenant_id, engine) as s:
        s.add(m.Drawing(id=(theirs := new_id("drw")), tenant_id=a.tenant_id, status="ready"))
    response = upload(api, b, [("NURSERY-1.pdf", NURSERY.read_bytes())], revision_of=theirs)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")
    assert drawing_count(engine, b) == 0


def test_no_files_is_a_validation_error(api: Api) -> None:
    response = api.client.post("/drawings", headers=api.as_(api.a), data={"project": "x"})
    assert response.status_code == 422


def test_upload_needs_a_token(api: Api) -> None:
    assert api.client.post("/drawings", files=[("files", ("a.pdf", b"%PDF-", "application/pdf"))]).status_code == 401
