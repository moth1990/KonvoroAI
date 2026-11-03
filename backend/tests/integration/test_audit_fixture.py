"""The 26-993 audit fixture (S16 decision 2) as the audit screen reads it: seeded under fresh ids into each tenant,
its pages in S3 with a viewer, its differences boxed on the drawing, and a corrected quote made from it."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.audit_993 import load, seed_audit_993, seed_audit_993_pages
from konboro.services import flags
from konboro.services.storage import Storage

from .api import Api, set_tenant_flag

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def audits(api: Api, migrated_db: dict[str, Engine], storage: Storage) -> Iterator[tuple[str, str]]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    made = []
    for t in (api.a, api.b):
        with tenant_session(t.tenant_id, api.engine) as s:
            made.append(seed_audit_993(s, t.tenant_id, t.user_id))
            assert seed_audit_993_pages(s, storage, t.tenant_id) == 5
        set_tenant_flag(api.engine, t.tenant_id, "quote_audit", True)
    flags.cache.clear()
    a, b = made
    assert a is not None and b is not None and a != b
    yield a, b


def test_a_second_seed_leaves_the_tenant_alone(api: Api, audits: tuple[str, str], storage: Storage) -> None:
    with tenant_session(api.a.tenant_id, api.engine) as s:
        assert seed_audit_993(s, api.a.tenant_id, api.a.user_id) is None
        assert seed_audit_993_pages(s, storage, api.a.tenant_id) == 0
        assert s.scalar(select(func.count()).select_from(m.Audit)) == 1


def test_the_screen_reads_the_fixture_as_the_pipeline_wrote_it(api: Api, audits: tuple[str, str]) -> None:
    a, _ = audits
    r = api.client.get(f"/audits/{a}", headers=api.as_(api.a))
    assert r.status_code == 200, r.text
    body = r.json()
    fixture = load()
    assert (body["status"], body["drawing_name"], body["quote_file_name"]) == (
        "ready",
        "MAIN ELECTRICAL BOARD",
        "Hatzaa_10271.pdf",
    )
    assert (body["drawing_file_name"], body["drawing_number"]) == ("MAIN_ELECTRICAL_BOARD.pdf", "26/993")
    lamps = next(ln for ln in body["lines"] if ln["description"].startswith("מנורה"))
    assert lamps["status"] == "matched" and {"L1", "LG1"} <= set(lamps["designators"])
    assert body["quote_ref"]["number"] == "10271" and Decimal(body["quote_ref"]["total_before_vat"]) == 14022
    assert body["summary"]["quote_lines"] == len(body["lines"]) == len(fixture["audit_quote_lines"])
    assert len(body["differences"]) == len(fixture["audit_differences"])
    assert [p["page_no"] for p in body["pages"]] == [1, 2, 3, 4, 5]
    assert all(p["has_viewer"] and p["thumbnail_url"] for p in body["pages"])

    # QG2, short in the quote at 1,250 ₪ (the factory confirmed it), boxed where both feeders are drawn
    (short,) = [d for d in body["differences"] if "QG2" in d["designators"]]
    assert (short["type"], short["shown"], Decimal(short["amount"])) == ("qty_short", True, 1250)
    pages = {p["page_id"]: p["page_no"] for p in body["pages"]}
    assert short["boxes"] and {pages[b["page_id"]] for b in short["boxes"]} == {3}


def test_each_tenant_has_its_own_copy(api: Api, audits: tuple[str, str]) -> None:
    a, b = audits
    assert api.client.get(f"/audits/{a}", headers=api.as_(api.b)).status_code == 404
    mine = api.client.get(f"/audits/{a}", headers=api.as_(api.a)).json()
    diff = mine["differences"][0]["diff_id"]
    r = api.client.patch(f"/audits/{a}/differences/{diff}", headers=api.as_(api.a), json={"status": "confirmed"})
    assert r.status_code == 200, r.text
    assert r.json()["boxes"] == mine["differences"][0]["boxes"]  # a decision answers with the boxes too
    theirs = api.client.get(f"/audits/{b}", headers=api.as_(api.b)).json()
    assert {d["status"] for d in theirs["differences"]} == {"open"}
    assert not {d["diff_id"] for d in theirs["differences"]} & {d["diff_id"] for d in mine["differences"]}


def test_the_fixture_makes_a_corrected_quote(api: Api, audits: tuple[str, str]) -> None:
    _, b = audits
    made = api.client.post(f"/audits/{b}/corrected-quote", headers=api.as_(api.b))
    assert made.status_code == 200, made.text
    quote = api.client.get(f"/quotes/{made.json()['quote_id']}", headers=api.as_(api.b))
    assert quote.status_code == 200, quote.text
    assert sum(len(p["lines"]) for p in quote.json()["panels"]) == 17  # nothing confirmed: the quote's own lines
