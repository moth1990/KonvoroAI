"""The quote audit end to end (11, S15): `POST /audits` with a drawing and its quote, stages 1–4 and then the audit
step (stages 5–7 skipped), the rows, the API's reading of them, the user's decisions, the corrected quote, the
quota, the flag, and another tenant. The stand-in model (`fake_llm`) answers every model call; a spreadsheet quote
needs none.
"""

import io
import zipfile
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.contracts.audit import AuditResult
from konboro.db import models as m
from konboro.db.models.pipeline import AUDIT_STAGE
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.worker import Worker
from konboro.services import flags
from konboro.services.storage import Storage
from konboro_llm.stages.table_transcription import STAGE as TABLE

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_api_drawings import progress
from .test_api_upload import quota_row
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import photo

pytestmark = pytest.mark.integration

FLAG = "quote_audit"

# The drawing: a BOM, so stage 4 runs in code. The quote: one contactor short, the shunt trips left out, and a time
# switch the drawing doesn't have.
DRAWING = 'פריט;כמות\r\n"מא""ז 3X16";3\r\nמגען 3X25;2\r\nסליל הפסקה;2\r\n'
QUOTE = (  # as Excel exports it: every row padded to the table's width
    "הצעת מחיר מס' 10271;;;\r\n"
    ";;;\r\n"
    'תיאור;כמות;מחיר יחידה;סה"כ\r\n'
    '"מא""ז 3X16A";3;185;555\r\n'
    "מגען 3X25A;1;180;180\r\n"
    "שעון שבת;1;250;250\r\n"
    '"סה""כ";;;985\r\n'
)


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the flags, the symbol library and the attribute schemas
    return migrated_db


def dec(*values: str | None) -> tuple[Decimal | None, ...]:
    """Stored amounts come back at their column's scale ("185.0000"): compare them as numbers."""
    return tuple(Decimal(v) if v is not None else None for v in values)


def tenant_with_audits(engine: Engine, **kw: int) -> ApiTenant:
    tenant = add_tenant(engine, **kw)
    for key in (FLAG, "review_screen"):
        set_tenant_flag(engine, tenant.tenant_id, key, True)
    flags.cache.clear()
    return tenant


def post_audit(api: Api, tenant: ApiTenant, quote: tuple[str, bytes], drawing: tuple[str, bytes] | None = None):  # type: ignore[no-untyped-def]
    name, data = drawing or ("bom.csv", DRAWING.encode("utf-8-sig"))
    return api.client.post(
        "/audits",
        headers=api.as_(tenant),
        files=[("files", (name, data, "text/csv")), ("quote", (quote[0], quote[1], "application/octet-stream"))],
        data={"project": "לוח בדיקה"},
    )


def audited(api: Api, tenant: ApiTenant, pipeline: Pipeline, quote: tuple[str, bytes]) -> dict:  # type: ignore[type-arg]  # noqa: F811
    response = post_audit(api, tenant, quote)
    assert response.status_code == 201, response.text
    Worker(pipeline).run_until_idle()
    got = api.client.get(f"/audits/{response.json()['audit_id']}", headers=api.as_(tenant))
    assert got.status_code == 200, got.text
    return got.json()  # type: ignore[no-any-return]


def test_a_spreadsheet_quote_is_audited_with_no_model_call(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant, other = tenant_with_audits(engine), tenant_with_audits(engine)
    response = post_audit(api, tenant, ("quote.csv", QUOTE.encode("utf-8-sig")))
    assert response.status_code == 201, response.text
    upload = response.json()
    assert upload["counted_as"] == "audit" and upload["quote_file"]["detected_format"] == "csv"
    Worker(pipeline).run_until_idle()

    body = api.client.get(f"/audits/{upload['audit_id']}", headers=api.as_(tenant)).json()
    assert (body["status"], body["drawing_status"], body["quote_ref"]) == (
        "ready",
        "ready",
        {"number": "10271", "date": None, "total_before_vat": "985"},
    )
    assert body["quote_file_name"] == "quote.csv" and body["drawing_name"] == "לוח בדיקה"
    by_type = {d["type"]: d for d in body["differences"]}
    assert set(by_type) == {"qty_short", "missing_in_quote", "extra_in_quote"}
    short = by_type["qty_short"]
    assert dec(short["drawing_qty"], short["quote_qty"], short["amount"]) == dec("2", "1", "180")
    assert short["quote_line_index"] == 2
    assert by_type["missing_in_quote"]["family"] == "shunt_trip" and by_type["missing_in_quote"]["amount"] is None
    assert by_type["extra_in_quote"]["shown"] is False  # 11 §5.4: below 0.6, apart
    s = body["summary"]
    assert (s["quote_lines"], s["lines_matched"], s["missing_items"], s["value_at_risk"], s["to_check"]) == (
        3,
        1,
        3,
        "180.00",
        1,
    )
    assert [ln["status"] for ln in body["lines"]] == ["matched", "quantity_differs", "not_in_drawing"]
    assert dec(body["lines"][0]["unit_price"]) == dec("185")
    # the drawing side for the screen (S16): a BOM drawing has its sheet as a page, no viewer and nothing to box
    assert [(p["page_kind"], p["has_viewer"]) for p in body["pages"]] == [("bom_table", False)]
    assert all(d["boxes"] == [] for d in body["differences"])

    # the pipeline: stages 5–7 skipped, the audit step done, its contract in S3
    with tenant_session(tenant.tenant_id, engine) as ses:
        runs = dict(
            ses.execute(
                select(m.StageRun.stage, m.StageRun.status).where(m.StageRun.drawing_id == upload["drawing_id"])
            ).all()
        )
        assert runs == {1: "done", 2: "done", 3: "done", 4: "done", 5: "skipped", 6: "skipped", 7: "skipped", 8: "done"}
        key = ses.scalar(
            select(m.StageRun.output_key).where(
                m.StageRun.drawing_id == upload["drawing_id"], m.StageRun.stage == AUDIT_STAGE
            )
        )
        assert ses.scalar(select(func.count()).select_from(m.LlmCall)) == 0  # known headers: no model at all
        assert ses.scalar(select(func.count()).select_from(m.Quote)) == 0  # stage 7 never ran
    assert key is not None
    result = AuditResult.model_validate_json(storage.get(tenant.tenant_id, key))
    assert result.audit_id == upload["audit_id"] and result.summary.value_at_risk == Decimal("180.00")
    run = progress(api, tenant, upload["drawing_id"]).json()
    assert run["counted_as"] == "audit" and run["audit_id"] == upload["audit_id"] and run["quote_id"] is None
    # the run step's rows: stages 1–4 and the audit step, never the skipped 5–7 (S16)
    assert [(st["stage"], st["status"]) for st in run["stages"]] == [(n, "done") for n in (1, 2, 3, 4, 8)]
    assert run["stages"][-1]["name"] == "בדיקת ההצעה"
    assert run["stages"][-1]["summary"] == "3 שורות בהצעה · 2 הבדלים"
    assert quota_row(engine, tenant)[0] == 1  # counted, on the quote counter: the plan has no audit limit

    # another tenant sees nothing (RLS, and 404 from the API)
    assert api.client.get(f"/audits/{upload['audit_id']}", headers=api.as_(other)).status_code == 404
    with tenant_session(other.tenant_id, engine) as ses:
        assert ses.scalar(select(func.count()).select_from(m.AuditQuoteLine)) == 0
        assert ses.scalar(select(func.count()).select_from(m.AuditDifference)) == 0


def test_decisions_and_the_corrected_quote(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant, other = tenant_with_audits(engine), tenant_with_audits(engine)
    body = audited(api, tenant, pipeline, ("quote.csv", QUOTE.encode("utf-8-sig")))
    audit_id = body["audit_id"]
    diffs = {d["type"]: d["diff_id"] for d in body["differences"]}
    url = f"/audits/{audit_id}/differences"
    h = api.as_(tenant)

    assert api.client.patch(f"{url}/{diffs['qty_short']}", headers=h, json={"status": "confirmed"}).status_code == 200
    assert (
        api.client.patch(f"{url}/{diffs['missing_in_quote']}", headers=h, json={"status": "confirmed"}).json()["status"]
        == "confirmed"
    )
    no_reason = api.client.patch(f"{url}/{diffs['extra_in_quote']}", headers=h, json={"status": "rejected"})
    assert no_reason.status_code == 422
    rejected = api.client.patch(
        f"{url}/{diffs['extra_in_quote']}",
        headers=h,
        json={"status": "rejected", "reject_reason": "customer_supplies", "note": "  "},
    ).json()
    assert (rejected["status"], rejected["reject_reason"], rejected["reject_note"]) == (
        "rejected",
        "customer_supplies",
        None,
    )
    assert (
        api.client.patch(f"{url}/{diffs['qty_short']}", headers=api.as_(other), json={"status": "open"}).status_code
        == 404
    )
    with tenant_session(tenant.tenant_id, engine) as s:
        d = s.get_one(m.AuditDifference, diffs["qty_short"])
        assert d.decided_by == tenant.user_id and d.decided_at is not None

    made = api.client.post(f"/audits/{audit_id}/corrected-quote", headers=h)
    assert made.status_code == 200, made.text
    quote_id, created = made.json()["quote_id"], made.json()["created"]
    assert created is True
    again = api.client.post(f"/audits/{audit_id}/corrected-quote", headers=h).json()
    assert again == {"quote_id": quote_id, "created": False}
    assert api.client.post(f"/audits/{audit_id}/corrected-quote", headers=api.as_(other)).status_code == 404

    quote = api.client.get(f"/quotes/{quote_id}", headers=h)
    assert quote.status_code == 200, quote.text
    lines = [ln for p in quote.json()["panels"] for ln in p["lines"]]
    got = [(ln["description"], *dec(ln["qty"], ln["unit_price"])) for ln in lines]
    assert got == [
        ('מא"ז 3X16A', *dec("3", "185")),
        ("מגען 3X25A", *dec("1", "180")),
        ("שעון שבת", *dec("1", "250")),  # rejected: the line stays as the factory wrote it
        ("סליל הפסקה", *dec("2", None)),  # the confirmed missing item, no price in the quote
        ("מגען 3X25A", *dec("1", "180")),  # the confirmed short unit, at its line's price
    ]
    assert {ln["line_type"] for ln in lines} == {"manual"}
    assert api.client.get(f"/audits/{audit_id}", headers=h).json()["corrected_quote_id"] == quote_id


def test_a_photographed_quote_is_transcribed_with_its_prices(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """The stand-in reads quote 10999 (fake_llm.quote_table): its third line's total is wrong on purpose."""
    engine = seeded["app"]
    tenant = tenant_with_audits(engine)
    body = audited(api, tenant, pipeline, ("quote.jpg", photo()))
    assert body["quote_ref"] == {"number": fake_llm.QUOTE_NUMBER, "date": "2026-11-02", "total_before_vat": "524"}
    assert [(ln["description"], *dec(ln["qty"], ln["unit_price"], ln["total"])) for ln in body["lines"]] == [
        (t, *dec(q, p, s)) for t, q, p, s in fake_llm.QUOTE_ROWS
    ]
    assert all(ln["page_no"] == 1 for ln in body["lines"])
    arithmetic = [d for d in body["differences"] if d["type"] == "arithmetic"]
    assert [(d["quote_line_index"], *dec(d["amount"])) for d in arithmetic] == [(3, Decimal(10))]  # 1 × 250 ≠ 260
    with tenant_session(tenant.tenant_id, engine) as s:
        calls = s.scalars(select(m.LlmCall.stage)).all()
        line = s.scalars(select(m.AuditQuoteLine).where(m.AuditQuoteLine.line_index == 1)).one()
        assert line.bbox is not None and line.rows == [1]
    assert calls == [TABLE]  # the quote's page, once; the drawing is a spreadsheet


def test_an_audit_counts_on_its_own_counter_when_the_plan_has_one(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = tenant_with_audits(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        s.get_one(m.TenantPlanOverride, tenant.tenant_id).monthly_audit_limit = 3
    audited(api, tenant, pipeline, ("quote.csv", QUOTE.encode("utf-8-sig")))
    with tenant_session(tenant.tenant_id, engine) as s:
        used = dict(s.execute(select(m.QuotaUsage.counter, m.QuotaUsage.used)).all())
    assert used.get("audit") == 1 and used.get("quote", 0) == 0


def test_a_zip_quote_is_refused_and_nothing_is_kept(
    api: Api,
    seeded: dict[str, Engine],
) -> None:
    engine = seeded["app"]
    tenant = tenant_with_audits(engine)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("q.csv", QUOTE)
    response = post_audit(api, tenant, ("quote.zip", buf.getvalue()))
    assert response.status_code == 422
    assert any(d.get("error") == "quote_not_one_file" for d in response.json()["error"]["details"])
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.Drawing)) == 0
        assert s.scalar(select(func.count()).select_from(m.Audit)) == 0
    assert quota_row(engine, tenant) == (0, 0, 0)


def test_the_flag_off_hides_every_audit_route(api: Api, seeded: dict[str, Engine]) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, FLAG, False)
    flags.cache.clear()
    h = api.as_(tenant)
    fake_audit, fake_diff = "aud_" + "0" * 26, "dif_" + "0" * 26
    assert post_audit(api, tenant, ("quote.csv", QUOTE.encode())).status_code == 404
    assert api.client.get(f"/audits/{fake_audit}", headers=h).status_code == 404
    assert (
        api.client.patch(
            f"/audits/{fake_audit}/differences/{fake_diff}", headers=h, json={"status": "open"}
        ).status_code
        == 404
    )
    assert api.client.post(f"/audits/{fake_audit}/corrected-quote", headers=h).status_code == 404
