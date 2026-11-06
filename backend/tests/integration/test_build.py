"""The chat quote builder (13 §4.2, S27) on the local services, with the stand-in model, the sample catalog and the
demo price list: the prototype's message becomes three matched and priced lines, a second message merges, a
correction by message and its undo, the quota counted once at the first line (decision 2), the draft read and changed
like any quote, the flag, another factory, and that no price reaches the model."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import link_demo_catalog, seed_global, seed_price_list
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro_llm.providers import FakeProvider

from .api import Api, ApiTenant, add_tenant, set_tenant_flag

pytestmark = pytest.mark.integration

PROTOTYPE = 'מפסק ראשי 4X63, 12 מא"ז 1X16, פחת 4X40'


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    return migrated_db


@dataclass
class Builder:
    api: Api
    tenant: ApiTenant
    drawing_id: str | None = None

    @property
    def h(self) -> dict[str, str]:
        return self.api.as_(self.tenant)

    def say(self, text: str, status: int = 200) -> dict[str, Any]:
        path = f"/builds/{self.drawing_id}/messages" if self.drawing_id else "/builds"
        r = self.api.client.post(path, json={"text": text}, headers=self.h)
        assert r.status_code == status, r.text
        body = dict(r.json())
        if status == 200:
            self.drawing_id = body["drawing_id"]
        return body

    def get(self, status: int = 200) -> dict[str, Any]:
        r = self.api.client.get(f"/builds/{self.drawing_id}", headers=self.h)
        assert r.status_code == status, r.text
        return dict(r.json())

    def undo(self, status: int = 200) -> dict[str, Any]:
        r = self.api.client.post(f"/builds/{self.drawing_id}/undo", headers=self.h)
        assert r.status_code == status, r.text
        return dict(r.json())


def priced_tenant(engine: Engine, **kw: Any) -> ApiTenant:
    tenant = add_tenant(engine, **kw)
    with tenant_session(tenant.tenant_id, engine) as s:
        seed_price_list(s, tenant.tenant_id)
        link_demo_catalog(s, tenant.tenant_id)
        s.add(
            m.MarginRule(
                id=f"mr_{tenant.tenant_id[-12:]}",
                tenant_id=tenant.tenant_id,
                level="default",
                kind="markup",
                value=Decimal("0.25"),
            )
        )
    set_tenant_flag(engine, tenant.tenant_id, "chat_quote_builder", True)
    return tenant


@pytest.fixture
def builder(api: Api, seeded: dict[str, Engine]) -> Iterator[Builder]:
    api.app.state.llm_providers = fake_llm.fake_providers()
    yield Builder(api, priced_tenant(seeded["app"]))


def lines(body: dict[str, Any]) -> list[dict[str, Any]]:
    quote = body["quote"]
    return [ln for p in quote["panels"] for ln in p["lines"] if ln["line_type"] == "component"] if quote else []


def described(body: dict[str, Any]) -> list[tuple[str, int]]:
    return [(ln["description"], int(Decimal(ln["qty"]))) for ln in lines(body)]


def used(engine: Engine, tenant_id: str) -> int:
    with tenant_session(tenant_id, engine) as s:
        return int(s.scalar(select(func.coalesce(func.sum(m.QuotaUsage.used), 0))) or 0)


# --- the prototype's message ------------------------------------------------------------------------------------------


def test_the_prototypes_message_gives_three_priced_lines(builder: Builder) -> None:
    body = builder.say(PROTOTYPE)
    got = lines(body)
    assert len(got) == 3, described(body)
    main, mcbs, rcd = got
    assert int(Decimal(mcbs["qty"])) == 12
    assert "1P" in mcbs["description"] and "16A" in mcbs["description"]
    assert "4P" in main["description"] and "63A" in main["description"]  # its class by its current (05 §5.5.1)
    assert "40A" in rcd["description"] and "30mA" in rcd["description"]  # stage 5's default (05 §5.5)
    assert mcbs["sku"] and rcd["sku"], got
    # the sample catalog has no 4P 63A MCB: red, said so, as on any BOM
    assert main["sku"] is None and main["status"] == "red"
    assert any(ln["unit_price"] for ln in got)
    reply = body["messages"][-1]
    assert reply["role"] == "assistant" and reply["text"].startswith("הוספתי 3 שורות.")
    assert body["quote"]["input_kind"] == "bom_only" and body["can_undo"]


def test_a_second_message_merges_the_same_product(builder: Builder) -> None:
    builder.say(PROTOTYPE)
    body = builder.say('ועוד 4 מא"ז 1X16')
    assert [q for d, q in described(body) if "16A" in d and "1P" in d] == [16]
    assert len(lines(body)) == 3


def test_a_correction_and_a_removal_by_message_and_undo(builder: Builder) -> None:
    first = builder.say(PROTOTYPE)
    keys = {ln["description"]: ln["line_id"] for ln in lines(first)}
    body = builder.say("לא 12, 10. ותוריד את הפחת")
    got = described(body)
    assert len(got) == 2 and not any("פחת" in d for d, _ in got), got
    mcb = next(ln for ln in lines(body) if "1P" in ln["description"])
    assert int(Decimal(mcb["qty"])) == 10
    assert mcb["line_id"] == keys[mcb["description"]]  # the line kept its key, and so its id
    reply = body["messages"][-1]["text"]
    assert "עדכנתי" in reply and "הסרתי" in reply
    back = builder.undo()
    assert sorted(described(back)) == sorted(described(first))


def test_a_message_with_no_product_says_so_and_counts_nothing(api: Api, builder: Builder) -> None:
    before = used(api.engine, builder.tenant.tenant_id)
    body = builder.say("שלום, מה שלומך?")
    assert body["quote"] is None and body["quote_id"] is None
    assert body["messages"][-1]["text"].startswith("לא זיהיתי רכיבים")
    assert used(api.engine, builder.tenant.tenant_id) == before
    assert not body["can_undo"]


def test_the_quota_counts_once_at_the_first_line(api: Api, builder: Builder) -> None:
    before = used(api.engine, builder.tenant.tenant_id)
    builder.say(PROTOTYPE)
    builder.say("ועוד 2 מגען 3X25")
    assert used(api.engine, builder.tenant.tenant_id) == before + 1
    with tenant_session(builder.tenant.tenant_id, api.engine) as s:
        reasons = s.scalars(
            select(m.QuotaEvent.reason).where(
                m.QuotaEvent.drawing_id == builder.drawing_id, m.QuotaEvent.kind == "confirm"
            )
        ).all()
    assert reasons == ["chat_first_line"]


def test_a_factory_at_its_limit_cannot_start_a_build(api: Api, seeded: dict[str, Engine]) -> None:
    full = priced_tenant(seeded["app"], limit=3, used=3)
    b = Builder(api, full)
    body = b.say(PROTOTYPE, status=409)
    assert body["error"]["code"] == "quota_reached"


# --- the draft is a quote -------------------------------------------------------------------------------------------


def test_the_draft_opens_and_changes_like_any_quote(api: Api, builder: Builder) -> None:
    body = builder.say(PROTOTYPE)
    qid = body["quote_id"]
    r = api.client.get(f"/quotes/{qid}", headers=builder.h)
    assert r.status_code == 200 and r.json()["drawing_id"] == builder.drawing_id
    mcb = next(ln for ln in lines(body) if "1P" in ln["description"])
    r = api.client.post(f"/quotes/{qid}/lines/{mcb['line_id']}/qty", json={"qty": "8"}, headers=builder.h)
    assert r.status_code == 200, r.text
    after = builder.get()
    assert next(int(Decimal(ln["qty"])) for ln in lines(after) if ln["line_id"] == mcb["line_id"]) == 8
    # a later message keeps what the review did to the line, and its price
    again = builder.say("ועוד 2 מגען 3X25")
    kept = next(ln for ln in lines(again) if ln["line_id"] == mcb["line_id"])
    assert int(Decimal(kept["qty"])) == 8 and kept["unit_price"] == mcb["unit_price"]


def test_a_price_typed_on_an_unpriced_line(api: Api, builder: Builder) -> None:
    body = builder.say("2 מגען 3X25")
    qid = body["quote_id"]
    unpriced = [ln for ln in lines(body) if ln["unit_price"] is None]
    if not unpriced:
        pytest.skip("the demo price list prices the contactor")
    ln = unpriced[0]
    r = api.client.post(
        f"/quotes/{qid}/lines/{ln['line_id']}/price-entry", json={"unit_price": "120", "save": False}, headers=builder.h
    )
    assert r.status_code == 200, r.text
    got = next(x for x in lines(builder.get()) if x["line_id"] == ln["line_id"])
    assert Decimal(got["unit_price"]) == Decimal("120")


# --- the flag, other factories, the model ----------------------------------------------------------------------------


def test_the_flag_off_is_as_if_there_were_no_builder(api: Api, builder: Builder) -> None:
    builder.say(PROTOTYPE)
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "chat_quote_builder", False)
    from konboro.services import flags

    flags.cache.clear()
    builder.get(status=404)
    r = api.client.post("/builds", json={"text": PROTOTYPE}, headers=builder.h)
    assert r.status_code == 404
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "chat_quote_builder", True)
    flags.cache.clear()


def test_another_factorys_build_is_not_found(api: Api, builder: Builder, seeded: dict[str, Engine]) -> None:
    builder.say(PROTOTYPE)
    other = Builder(api, priced_tenant(seeded["app"]), builder.drawing_id)
    other.get(status=404)
    other.say("עוד 2", status=404)
    other.undo(status=404)


def test_no_price_reaches_the_model(api: Api, builder: Builder) -> None:
    """Non-negotiable 6: the model is shown descriptions and quantities, never a price, a cost or a customer; an
    amount the estimator typed is stripped before it goes (08 §5.4)."""
    sent: list[str] = []

    def answer(request: Any) -> dict[str, Any]:
        sent.append(f"{request.system}\n{request.user_text}")
        return fake_llm.answer(request)

    api.app.state.llm_providers = {"anthropic": FakeProvider(answer)}
    builder.say(PROTOTYPE)
    builder.say('לא 12, 10. ועוד מגען 3X25 ב-450 ש"ח')
    final = lines(builder.get())
    amounts = {Decimal(x) for ln in final for x in (ln["unit_price"], ln["line_total"], ln.get("unit_cost")) if x}
    assert amounts, "the draft is priced"
    for text in sent:
        assert "450" not in text and "₪" not in text
        for a in amounts:
            assert f"{a:.2f}" not in text, a
    assert any("לא 12, 10" in t for t in sent)


def test_the_overlay_and_the_export_read_a_draft_with_no_pages(api: Api, builder: Builder) -> None:
    body = builder.say(PROTOTYPE)
    qid = body["quote_id"]
    for flag in ("unresolved_overlay", "export_doc"):
        set_tenant_flag(api.engine, builder.tenant.tenant_id, flag, True)
    from konboro.services import flags

    flags.cache.clear()
    r = api.client.get(f"/quotes/{qid}/unresolved", headers=builder.h)
    assert r.status_code == 200, r.text
    assert all(s.get("bbox") for s in r.json()["spots"])  # no box without a place on a page
    r = api.client.get(f"/quotes/{qid}/versions/1/export.xlsx", headers=builder.h)
    assert r.status_code == 200, r.text


# --- voice (decision 1) ----------------------------------------------------------------------------------------------

AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 2048  # a WebM header and nothing worth hearing: the stand-in hears its sentence


def record(builder: Builder, status: int = 200, body: bytes = AUDIO, kind: str = "audio/webm") -> dict[str, Any]:
    path = f"/builds/{builder.drawing_id}/voice" if builder.drawing_id else "/builds/voice"
    r = builder.api.client.post(
        path, files={"recording": ("rec.webm", body, kind)}, data={"seconds": "4.2"}, headers=builder.h
    )
    assert r.status_code == status, r.text
    out = dict(r.json())
    if status == 200:
        builder.drawing_id = out["drawing_id"]
    return out


def keys(api: Api, tenant_id: str) -> set[str]:
    s3 = api.app.state.storage.s3
    bucket = api.app.state.storage.bucket
    found = s3.list_objects_v2(Bucket=bucket, Prefix=f"tenants/{tenant_id}/")
    return {o["Key"] for o in found.get("Contents", [])}


def test_a_recording_waits_for_add_and_is_never_stored(api: Api, builder: Builder) -> None:
    for flag in ("voice_input",):
        set_tenant_flag(api.engine, builder.tenant.tenant_id, flag, True)
    from konboro.services import flags

    flags.cache.clear()
    body = record(builder)
    card = body["messages"][-1]
    assert card["status"] == "pending" and card["heard"].startswith("מפסק ראשי ארבע על שישים ושלוש")
    assert [(i["text"], i["quantity"]) for i in card["items"]] == [
        ("מפסק ראשי 4X63", 1),
        ('מא"ז 1X16', 12),
        ('מא"ז 3X25', 4),
        ("פחת 4X40", 1),
    ]
    assert body["quote"] is None, "nothing is added before הוסף"
    stored = keys(api, builder.tenant.tenant_id)
    assert all("/stages/" in k for k in stored), stored  # the recording is nowhere
    r = api.client.post(f"/builds/{builder.drawing_id}/messages/{card['message_id']}/apply", headers=builder.h)
    assert r.status_code == 200, r.text
    got = described(dict(r.json()))
    assert len(got) == 4 and sorted(q for _, q in got) == [1, 1, 4, 12], got
    with tenant_session(builder.tenant.tenant_id, api.engine) as s:
        contents = [
            x.content for x in s.scalars(select(m.BuildMessage).where(m.BuildMessage.drawing_id == builder.drawing_id))
        ]
    assert all("audio" not in json.dumps(c) for c in contents)


def test_a_recording_sent_back_to_the_input_adds_nothing(api: Api, builder: Builder) -> None:
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "voice_input", True)
    from konboro.services import flags

    flags.cache.clear()
    card = record(builder)["messages"][-1]
    r = api.client.post(f"/builds/{builder.drawing_id}/messages/{card['message_id']}/dismiss", headers=builder.h)
    assert r.status_code == 200 and r.json()["messages"][-1]["status"] == "dismissed"
    r = api.client.post(f"/builds/{builder.drawing_id}/messages/{card['message_id']}/apply", headers=builder.h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_pending"
    assert builder.get()["quote"] is None


def test_a_recording_that_is_not_audio_or_too_big(api: Api, builder: Builder) -> None:
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "voice_input", True)
    from konboro.services import flags

    flags.cache.clear()
    assert record(builder, 422, kind="text/plain")["error"]["code"] == "recording_invalid"
    assert record(builder, 422, body=b"")["error"]["code"] == "recording_invalid"
    assert record(builder, 422, body=b"\x00" * (2 * 1024 * 1024 + 10))["error"]["code"] == "recording_invalid"


def test_voice_needs_its_flag_and_the_builder(api: Api, builder: Builder) -> None:
    from konboro.services import flags

    set_tenant_flag(api.engine, builder.tenant.tenant_id, "voice_input", False)
    flags.cache.clear()
    record(builder, 404)
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "voice_input", True)
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "chat_quote_builder", False)
    flags.cache.clear()
    record(builder, 404)  # voice_input depends on chat_quote_builder (13 §2)
    set_tenant_flag(api.engine, builder.tenant.tenant_id, "chat_quote_builder", True)
    flags.cache.clear()
