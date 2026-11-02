"""The BOM-only path on the local services (01 §5.8, S14): a spreadsheet and a picture of a BOM go through all 7
stages to the tenant's `components` rows, counted in the quota; an unsure column mapping stops for the user when
`bom_column_mapping` is on, and goes on yellow when it is off; the mapping model never sees a number from the file.
The model is the stand-in (`devtools/fake_llm.py`): never a real one in tests."""

import io
import re
from typing import Any

import pytest
from openpyxl import Workbook
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.contracts.merge import MergeResult
from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.bom.table import BomTable
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.worker import Worker
from konboro.services import flags
from konboro.services.storage import Storage
from konboro_llm import LLMRequest
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.table_transcription import STAGE as TABLE

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_api_drawings import progress
from .test_api_upload import quota_row, upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import photo
from .test_stage4 import merged

pytestmark = pytest.mark.integration

FLAG = "bom_column_mapping"


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # flags, the symbol library and the attribute schemas
    return migrated_db


def workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "כתב כמויות"
    for row in (
        ["הצעת מחיר"],
        [],
        ["מס'", "תיאור", "כמות", "לוח", "מחיר יחידה"],
        [1, 'מא"ז 1X16', 12, "לוח ראשי", 18.5],
        [2, 'מא"ז 1X16', 6, None, 18.5],  # the panel cell merged: the row above's
        [3, "מגען 3X25", 2, "לוח משנה", 120],
        [4, "פחת 4X40", 1, None, 240],
        [None, 'סה"כ', 21, None, None],
    ):
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def send(api: Api, tenant: ApiTenant, name: str, data: bytes) -> str:
    response = upload(api, tenant, [(name, data)])
    assert response.status_code == 201, response.text
    return str(response.json()["drawing_id"])


def components(engine: Engine, tenant: ApiTenant, drawing_id: str) -> list[m.Component]:
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = list(s.scalars(select(m.Component).where(m.Component.drawing_id == drawing_id).order_by(m.Component.id)))
        s.expunge_all()
    return rows


def panels(engine: Engine, tenant: ApiTenant, drawing_id: str) -> dict[str, str]:
    with tenant_session(tenant.tenant_id, engine) as s:
        return {p.id: p.name for p in s.scalars(select(m.Panel).where(m.Panel.drawing_id == drawing_id))}


def test_a_workbook_goes_through_all_7_stages(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    drawing_id = send(api, tenant, "boq.xlsx", workbook())
    Worker(pipeline).run_until_idle()

    body = progress(api, tenant, drawing_id).json()
    assert body["status"] == "ready"
    assert body["summary"]["input_kind"] == "bom_only"
    assert sorted(body["summary"]["panels"]) == ["לוח משנה", "לוח ראשי"]
    assert [s["summary"] for s in body["stages"][:4]] == [
        "כתב כמויות · 4 שורות · 2 לוחות",
        "אין שרטוט, רק כתב כמויות",
        "אין שרטוט, רק כתב כמויות",
        "4 שורות ב-3 מוצרים",
    ]
    [page] = body["pages"]
    assert page["bom"]["mapping_sure"] and page["bom"]["rows"] == 4
    assert [(c["letter"], c["role"], c["by"]) for c in page["bom"]["columns"]] == [
        ("A", "row_number", "code"),
        ("B", "item", "code"),
        ("C", "quantity", "code"),
        ("D", "panel", "code"),
        ("E", "price", "code"),
    ]
    assert used_count(engine, tenant) == 1  # a BOM-only upload counts (01 §4.5)

    names = panels(engine, tenant, drawing_id)
    rows = components(engine, tenant, drawing_id)
    got = sorted((names[r.panel_id], r.family, r.quantity) for r in rows)
    assert got == [("לוח משנה", "contactor", 2), ("לוח משנה", "rcd", 1), ("לוח ראשי", "circuit_breaker", 18)]
    for r in rows:
        assert all(a["value"] is None or a["source"] == "bom" for a in r.attributes.values())
        assert all(i["role"] == "bom_row" and i["rows"] and i["bbox"] is None for i in r.instances)
    out = merged(engine, storage, tenant.tenant_id, drawing_id)
    assert out.stats.by_method == {"bom": 4} and all(i.det_id is None for i in out.instances)
    with tenant_session(tenant.tenant_id, engine) as s:  # nothing was asked of a model: the headers are known
        assert s.scalar(select(func.count()).select_from(m.LlmCall)) == 0
    with tenant_session(other.tenant_id, engine) as s:  # RLS
        assert s.scalar(select(func.count()).select_from(m.Component)) == 0
        assert s.scalar(select(func.count()).select_from(m.ContextArtifact)) == 0


def used_count(engine: Engine, tenant: ApiTenant) -> int:
    used, _, _ = quota_row(engine, tenant)
    return used


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1255"])
def test_a_csv_from_hebrew_excel(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    encoding: str,
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    body = 'פריט;כמות\r\n"מא""ז 3X32";5\r\nמגען 2X25;1\r\n'
    drawing_id = send(api, tenant, "bom.csv", body.encode(encoding))
    Worker(pipeline).run_until_idle()
    assert progress(api, tenant, drawing_id).json()["status"] == "ready"
    rows = components(engine, tenant, drawing_id)
    assert sorted((r.family, r.quantity, r.attributes["poles"]["value"]) for r in rows) == [
        ("circuit_breaker", 5, 3),
        ("contactor", 1, 2),
    ]
    assert list(panels(engine, tenant, drawing_id).values()) == ["לוח 1"]


def bom_photo() -> bytes:
    return photo()  # sharp strokes: a blank page would stop as blurry (01 §5.3)


def test_a_photographed_bom_is_transcribed(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    """The stand-in reads a short form for "לוח קומה 1" (fake_llm.bom_table): the heading names the panel and the
    project, the third item goes on to the next row, and the rows keep their boxes on the page."""
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = send(api, tenant, "bom-photo.jpg", bom_photo())
    Worker(pipeline).run_until_idle()

    body = progress(api, tenant, drawing_id).json()
    assert (body["status"], body["summary"]["input_kind"], body["summary"]["panels"]) == (
        "ready",
        "bom_only",
        [fake_llm.BOM_PANEL],
    )
    assert body["pages"][0]["bom"]["source"] == "image"
    # BUG-030: a name read from a picture's heading may be misread; the done step asks the user to check it.
    [notice] = body["notices"]
    assert notice["code"] == "bom_panel_name_from_picture" and fake_llm.BOM_PANEL in notice["message"]
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        assert drawing.title_block is not None and drawing.title_block["project_name"] == "פרויקט הדגמה"
        [artifact] = s.scalars(select(m.ContextArtifact).where(m.ContextArtifact.drawing_id == drawing_id)).all()
        table = BomTable.model_validate_json(artifact.content)
        assert (table.source, table.panel_name, table.cropped) == ("image", fake_llm.BOM_PANEL, False)
        assert s.scalar(select(func.count()).select_from(m.LlmCall).where(m.LlmCall.stage == TABLE)) == 1
    rows = components(engine, tenant, drawing_id)
    assert sorted((r.family, r.quantity) for r in rows) == [
        ("circuit_breaker", 1),
        ("circuit_breaker", 12),
        ("energy_meter", 1),
    ]
    meter = next(r for r in rows if r.family == "energy_meter")
    assert meter.explicit_texts[0] == "רב מודד SATEC כולל יציאת ממסר"
    assert meter.instances[0]["rows"] == [3, 4] and meter.instances[0]["bbox"] is not None
    out = merged(engine, storage, tenant.tenant_id, drawing_id)
    assert out.instances and all(i.bbox is not None for i in out.instances)


def test_a_bom_photo_at_the_edge_warns_it_may_go_on(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    def answer(request: LLMRequest[Any]) -> dict[str, Any]:
        out = fake_llm.answer(request)
        if request.stage == TABLE and "rows" in out:
            out["rows"][-1]["box"] = [100, 960, 900, 1000]
        return out

    pipeline.llm_providers = {"anthropic": FakeProvider(answer)}
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = send(api, tenant, "bom-photo.jpg", bom_photo())
    Worker(pipeline).run_until_idle()
    body = progress(api, tenant, drawing_id).json()
    assert body["status"] == "ready"
    assert [n["code"] for n in body["notices"]] == ["bom_panel_name_from_picture", "bom_possibly_cropped"]


UNKNOWN_HEADERS = 'אלפא,בטא,גמא\r\nמגען 3X25,2,120.50\r\nמא"ז 1X16,14,18\r\n'


def recording(requests: list[LLMRequest[Any]]) -> FakeProvider:
    def answer(request: LLMRequest[Any]) -> dict[str, Any]:
        requests.append(request)
        return fake_llm.answer(request)

    return FakeProvider(answer)


def test_an_unsure_mapping_waits_for_the_user(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, FLAG, True)
    flags.cache.clear()
    requests: list[LLMRequest[Any]] = []
    pipeline.llm_providers = {"anthropic": recording(requests)}
    drawing_id = send(api, tenant, "bom.csv", UNKNOWN_HEADERS.encode())
    Worker(pipeline).run_until_idle()

    [request] = [r for r in requests if r.stage == TABLE]  # non-negotiable 6: no number from the file
    assert not request.images
    for secret in ("120", "50", "14", "18", "25", "16"):
        assert secret not in request.user_text
    assert not re.search(r"\d", request.user_text.split("\n\n", 1)[1])

    body = progress(api, tenant, drawing_id).json()
    assert body["status"] == "awaiting_confirmation" and body["confirmation_reasons"] == ["bom_mapping"]
    page = body["pages"][0]
    assert not page["bom"]["mapping_sure"]
    assert [(c["role"], c["by"]) for c in page["bom"]["columns"]] == [
        ("item", "model"),
        ("quantity", "model"),
        ("other", "model"),
    ]
    assert page["bom"]["columns"][0]["samples"] == ["מגען 3X25", 'מא"ז 1X16']

    url = f"/drawings/{drawing_id}/pages/{page['page_id']}/bom-columns"
    response = api.client.put(url, headers=api.as_(tenant), json={"columns": [{"index": 1, "role": "other"}]})
    assert response.status_code == 200, response.text
    response = api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(tenant))
    assert (response.status_code, response.json()["error"]["code"]) == (409, "bom_mapping_incomplete")

    roles = [{"index": 1, "role": "quantity"}, {"index": 2, "role": "price"}]
    response = api.client.put(url, headers=api.as_(tenant), json={"columns": roles})
    assert response.status_code == 200, response.text
    assert [(c["role"], c["by"]) for c in response.json()["pages"][0]["bom"]["columns"]] == [
        ("item", "model"),
        ("quantity", "user"),
        ("price", "user"),
    ]
    assert api.client.post(f"/drawings/{drawing_id}/confirm", headers=api.as_(tenant)).status_code == 200
    Worker(pipeline).run_until_idle()
    assert progress(api, tenant, drawing_id).json()["status"] == "ready"
    rows = components(engine, tenant, drawing_id)
    assert sorted((r.family, r.quantity) for r in rows) == [("circuit_breaker", 14), ("contactor", 2)]
    assert all(r.confidence >= 0.85 for r in rows)  # the user settled the mapping
    with tenant_session(tenant.tenant_id, engine) as s:
        events = s.scalars(select(m.CorrectionEvent).where(m.CorrectionEvent.type == "bom_columns_mapped")).all()
        assert [e.after for e in events][-1] == {"A": "item", "B": "quantity", "C": "price"}


def test_with_the_flag_off_an_unsure_mapping_goes_on_yellow(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, FLAG, False)
    flags.cache.clear()
    drawing_id = send(api, tenant, "bom.csv", UNKNOWN_HEADERS.encode())
    Worker(pipeline).run_until_idle()
    body = progress(api, tenant, drawing_id).json()
    assert body["status"] == "ready"
    rows = components(engine, tenant, drawing_id)
    assert rows and all(r.confidence < 0.85 for r in rows)  # S14 decision 1
    page_id = body["pages"][0]["page_id"]
    response = api.client.put(
        f"/drawings/{drawing_id}/pages/{page_id}/bom-columns",
        headers=api.as_(tenant),
        json={"columns": [{"index": 0, "role": "item"}]},
    )
    assert response.status_code == 404  # the flag is off: the route doesn't exist (13 §3)


def test_another_tenant_cannot_map_the_columns(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    for t in (tenant, other):
        set_tenant_flag(engine, t.tenant_id, FLAG, True)
    flags.cache.clear()
    drawing_id = send(api, tenant, "bom.csv", UNKNOWN_HEADERS.encode())
    Worker(pipeline).run_until_idle()
    page_id = progress(api, tenant, drawing_id).json()["pages"][0]["page_id"]
    response = api.client.put(
        f"/drawings/{drawing_id}/pages/{page_id}/bom-columns",
        headers=api.as_(other),
        json={"columns": [{"index": 0, "role": "item"}]},
    )
    assert response.status_code == 404
    with tenant_session(tenant.tenant_id, engine) as s:
        artifact = s.scalar(select(m.ContextArtifact).where(m.ContextArtifact.drawing_id == drawing_id))
        assert artifact is not None and not BomTable.model_validate_json(artifact.content).mapping_sure


def test_the_stage_4_output_of_a_bom_validates(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = send(api, tenant, "boq.xlsx", workbook())
    Worker(pipeline).run_until_idle()
    out = merged(engine, storage, tenant.tenant_id, drawing_id)
    assert MergeResult.model_validate_json(out.model_dump_json()) == out
    assert {c.component_id for c in out.components} == {i.component_id for i in out.instances}
