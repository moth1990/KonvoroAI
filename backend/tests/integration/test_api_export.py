"""The quote's documents (13 §4.1, `export_doc`; S26) on the NURSERY-1 fixture: the versions, the customer document's
preview, the PDF printed by Chromium, the internal Excel, and the factory's template on the settings screen."""

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import pypdfium2 as pdfium
import pytest
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery
from konboro.domain import permissions
from konboro.services.export import shekels
from konboro.services.storage import Storage

from .api import Api, ApiTenant, add_tenant, set_tenant_flag

FLAG = "export_doc"


@dataclass
class Fixture:
    api: Api
    tenant: ApiTenant
    quote_id: str

    def get(self, path: str, status: int = 200, tenant: ApiTenant | None = None) -> Any:
        r = self.api.client.get(path, headers=self.api.as_(tenant or self.tenant))
        assert r.status_code == status, r.text
        return r

    def send(self, method: str, path: str, status: int = 200, **kw: Any) -> Any:
        r = self.api.client.request(method, path, headers=self.api.as_(self.tenant), **kw)
        assert r.status_code == status, r.text
        return r.json()

    @property
    def base(self) -> str:
        return f"/quotes/{self.quote_id}"


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    return migrated_db


@pytest.fixture
def fixture(api: Api, seeded: dict[str, Engine]) -> Iterator[Fixture]:
    tenant = add_tenant(seeded["app"])
    with tenant_session(tenant.tenant_id, api.engine) as s:
        qid = seed_nursery(s, tenant.tenant_id)
    assert qid is not None
    set_tenant_flag(api.engine, tenant.tenant_id, FLAG, True)
    yield Fixture(api, tenant, qid)


def pdf_text(body: bytes) -> str:
    doc = pdfium.PdfDocument(body)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (160, 48), (32, 96, 160)).save(out, "PNG")
    return out.getvalue()


def test_the_versions_and_the_customer_documents_preview(fixture: Fixture) -> None:
    assert fixture.get(f"{fixture.base}/versions").json() == [
        {"version": 1, "status": "draft", "quote_date": "2026-10-13", "sent_at": None, "current": True}
    ]
    quote = fixture.get(fixture.base).json()
    doc = fixture.get(f"{fixture.base}/versions/1/document").json()
    assert (doc["name"], doc["drawing_number"], doc["version"], doc["draft"], doc["show_sku"]) == (
        "NURSERY",
        "26/952",
        1,
        True,
        False,
    )
    (section,) = doc["sections"]
    lines = quote["panels"][0]["lines"]
    # every live line but Q0's kit part, which is included in its parent's price ("כלול")
    assert [r["description"] for r in section["rows"]] == [ln["description"] for ln in lines if not ln["included"]]
    assert all(r["sku"] is None for r in section["rows"])  # the factory shows no SKUs until it says so
    assert doc["unpriced_count"] == 5 and sum(r["line_total"] is None for r in section["rows"]) == 5
    totals = quote["totals"]
    assert doc["totals"]["net_total"] == totals["net_total"] and doc["totals"]["gross_total"] == totals["gross_total"]
    assert doc["totals"]["vat"] == totals["vat"] and doc["totals"]["discount"] is None
    assert not {"unit_cost", "line_cost", "margin_pct", "cost_source", "status"} & set(section["rows"][0])


def test_the_pdf_has_the_prices_and_totals_and_none_of_the_costs(fixture: Fixture) -> None:
    r = fixture.get(f"{fixture.base}/versions/1/export.pdf")
    assert r.headers["content-type"] == "application/pdf"
    disposition = r.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="quote-v1.pdf"')
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == "הצעת מחיר NURSERY גרסה 1.pdf"
    assert r.content.startswith(b"%PDF")
    text = pdf_text(r.content)

    quote = fixture.get(fixture.base).json()
    lines = [ln for ln in quote["panels"][0]["lines"] if not ln["included"]]
    priced = [ln for ln in lines if ln["line_total"]]
    for ln in priced:
        assert shekels(Decimal(ln["line_total"])) in text, ln["description"]
        assert shekels(Decimal(ln["unit_price"])) in text, ln["description"]
    for key in ("net_total", "vat", "gross_total"):
        assert shekels(Decimal(quote["totals"][key])) in text, key
    assert "טיוטה" in text  # a draft (S26 decision 3)

    # 07 §12: no supplier, and no cost that is not also some price on the page
    prices = {shekels(Decimal(ln[k])) for ln in priced for k in ("unit_price", "line_total")}
    costs = {shekels(Decimal(ln["unit_cost"])) for ln in lines if ln["unit_cost"]} - prices
    assert costs, "the fixture has costs to look for"
    amounts = set(re.findall(r"-?₪[\d,]+(?:\.\d+)?", text))  # whole amounts: "₪18" is not in "₪180"
    assert not costs & amounts
    assert "מפיץ" not in text and "ספק" not in text and "עלות" not in text


def test_the_excel_has_every_line_with_its_costs_and_the_apis_money(fixture: Fixture) -> None:
    r = fixture.get(f"{fixture.base}/versions/1/export.xlsx")
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    assert unquote(r.headers["content-disposition"].split("filename*=UTF-8''", 1)[1]) == (
        "הצעה פנימית NURSERY גרסה 1.xlsx"
    )
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["שורות", "ממצאים", "סיכום"]
    sheet = wb["שורות"]
    assert sheet.sheet_view.rightToLeft
    header = [c.value for c in sheet[1]]
    col = {name: header.index(name) for name in header}
    rows = [[c.value for c in row] for row in sheet.iter_rows(min_row=2)]

    quote = fixture.get(fixture.base).json()
    lines = quote["panels"][0]["lines"]
    assert [row[col["תיאור"]] for row in rows] == [ln["description"] for ln in lines]  # every live line, kit too
    for row, ln in zip(rows, lines, strict=True):
        for name, key in (("מחיר ליחידה", "unit_price"), ('סה"כ', "line_total"), ("עלות ליחידה", "unit_cost")):
            value = row[col[name]]
            assert (None if value is None else Decimal(str(value))) == (
                None if ln[key] is None else Decimal(ln[key])
            ), (ln["description"], name)
        assert row[col["צבע"]] == {"green": "ירוק", "yellow": "צהוב", "red": "אדום"}[ln["status"]]
    f1 = next(row for row in rows if row[col["תגים"]] == "F1–F17")
    assert (f1[col["מקור העלות"]], f1[col["ספק"]]) == ("מחירון ספק", "ספק א׳ · מפיץ ABB")
    assert f1[col["מקור המחיר"]] == "הצעה 10288"
    assert sheet.cell(row=2, column=col["עלות ליחידה"] + 1).number_format == '"₪"#,##0.00'

    findings = [[c.value for c in row] for row in wb["ממצאים"].iter_rows(min_row=2)]
    assert [f[1] for f in findings] == [f["title"] for f in quote["findings"]]
    totals = {row[0].value: row[1].value for row in wb["סיכום"].iter_rows() if row[0].value}
    assert Decimal(str(totals['סה"כ לפני מע"מ'])) == Decimal(quote["totals"]["net_total"])
    assert Decimal(str(totals["לתשלום"])) == Decimal(quote["totals"]["gross_total"])
    assert totals["סטטוס"] == "טיוטה" and totals["שורות בלי מחיר"] == 5


def test_an_earlier_version_exports_its_own_lines(fixture: Fixture) -> None:
    fixture.send("POST", f"{fixture.base}/send")
    fixture.send("POST", f"{fixture.base}/versions")  # version 2, a copy of version 1 as a draft
    lines = fixture.get(fixture.base).json()["panels"][0]["lines"]
    rnv = next(ln for ln in lines if ln["designators"] == ["RNV"])
    fixture.send("DELETE", f"{fixture.base}/lines/{rnv['line_id']}")

    versions = fixture.get(f"{fixture.base}/versions").json()
    assert [(v["version"], v["status"], v["current"]) for v in versions] == [(2, "draft", True), (1, "sent", False)]
    assert versions[1]["sent_at"] is not None
    one = fixture.get(f"{fixture.base}/versions/1/document").json()
    two = fixture.get(f"{fixture.base}/versions/2/document").json()
    names = lambda d: [r["description"] for s in d["sections"] for r in s["rows"]]  # noqa: E731
    assert "ממסר עזר" in names(one) and "ממסר עזר" not in names(two)
    assert (one["draft"], two["draft"]) == (False, True)

    sent = pdf_text(fixture.get(f"{fixture.base}/versions/1/export.pdf").content)
    assert "טיוטה" not in sent and "ממסר עזר" in sent
    assert "טיוטה" in pdf_text(fixture.get(f"{fixture.base}/versions/2/export.pdf").content)


def test_the_factorys_template_on_the_document(fixture: Fixture, storage: Storage) -> None:
    out = fixture.get("/settings/document").json()
    tenant_name = out["company"]["name"]
    assert out == {
        "company": {"name": tenant_name, "company_id": None, "address": None, "phone": None},
        "terms": None,
        "show_sku": False,
        "logo_url": None,
    }
    body = {
        "company": {"name": 'לוחות בדיקה בע"מ', "company_id": "510000001", "address": "  ", "phone": "03-5550000"},
        "terms": "תנאי תשלום: שוטף + 30",
        "show_sku": True,
    }
    saved = fixture.send("PUT", "/settings/document", json=body)
    assert saved["company"] == {**body["company"], "address": None}  # blank is not set
    assert (saved["terms"], saved["show_sku"]) == ("תנאי תשלום: שוטף + 30", True)

    logo = fixture.send("PUT", "/settings/document/logo", files={"file": ("logo.png", png(), "image/png")})
    assert logo["logo_url"] and "branding/logo.png" in logo["logo_url"]
    with tenant_session(fixture.tenant.tenant_id, fixture.api.engine) as s:
        key = s.get_one(m.TenantSettings, fixture.tenant.tenant_id).document["logo"]["key"]
    assert key == f"tenants/{fixture.tenant.tenant_id}/branding/logo.png" and storage.exists(
        fixture.tenant.tenant_id, key
    )
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = fixture.send("PUT", "/settings/document/logo", status=422, files={"file": ("logo.png", svg, "image/png")})
    assert r["error"]["code"] == "logo_type"

    doc = fixture.get(f"{fixture.base}/versions/1/document").json()
    assert doc["company"] == 'לוחות בדיקה בע"מ' and doc["show_sku"]
    assert any(r["sku"] == "SN201M-C10" for r in doc["sections"][0]["rows"])
    text = pdf_text(fixture.get(f"{fixture.base}/versions/1/export.pdf").content)
    assert "510000001" in text and "SN201M-C10" in text and "30 +" in text.replace("+ 30", "30 +")

    # another factory sees its own template only
    other = fixture.api.b
    set_tenant_flag(fixture.api.engine, other.tenant_id, FLAG, True)
    theirs = fixture.get("/settings/document", tenant=other).json()
    assert theirs["company"]["name"] != 'לוחות בדיקה בע"מ' and theirs["logo_url"] is None

    gone = fixture.send("DELETE", "/settings/document/logo")
    assert gone["logo_url"] is None and not storage.exists(fixture.tenant.tenant_id, key)


def test_the_routes_are_not_there_with_the_flag_off(fixture: Fixture) -> None:
    set_tenant_flag(fixture.api.engine, fixture.tenant.tenant_id, FLAG, False)
    for path in (
        f"{fixture.base}/versions",
        f"{fixture.base}/versions/1/document",
        f"{fixture.base}/versions/1/export.pdf",
        f"{fixture.base}/versions/1/export.xlsx",
        "/settings/document",
    ):
        assert fixture.get(path, status=404).json()["error"]["code"] == "not_found", path


def test_another_tenants_quote_or_a_missing_version_is_not_found(fixture: Fixture) -> None:
    other = fixture.api.b
    set_tenant_flag(fixture.api.engine, other.tenant_id, FLAG, True)
    for path in ("versions", "versions/1/document", "versions/1/export.pdf", "versions/1/export.xlsx"):
        fixture.get(f"{fixture.base}/{path}", status=404, tenant=other)
    fixture.get(f"{fixture.base}/versions/9/document", status=404)
    fixture.get(f"{fixture.base}/versions/9/export.pdf", status=404)


def test_the_excel_needs_cost_permission_and_the_pdf_does_not(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """07 §12, 09 §12: the Excel has costs, margins and suppliers; the customer PDF has none of them."""
    monkeypatch.setitem(
        permissions.ROLE_PERMISSIONS, "owner", frozenset(permissions.Permission) - {permissions.Permission.COSTS_READ}
    )
    fixture.get(f"{fixture.base}/versions/1/export.xlsx", status=403)
    fixture.get(f"{fixture.base}/versions/1/document")
    assert fixture.get(f"{fixture.base}/versions/1/export.pdf").content.startswith(b"%PDF")
