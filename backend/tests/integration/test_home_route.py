"""The chat home's routing (13 §4.3, S27) on the local services: each row of the table, by code first and the
`home_intent` stand-in for the rest; a question that names one quote opens it with the chat, several or none get a
question; a flag that is off; and that the model never sees a quote's name, a customer or an amount."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.services import flags
from konboro_llm.providers import FakeProvider

from .api import Api, ApiTenant, add_tenant, set_tenant_flag

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    return migrated_db


@dataclass
class Home:
    api: Api
    tenant: ApiTenant
    quotes: dict[str, str]

    def route(self, text: str, status: int = 200) -> dict[str, Any]:
        r = self.api.client.post("/home/route", json={"text": text}, headers=self.api.as_(self.tenant))
        assert r.status_code == status, r.text
        return dict(r.json())


def _quote(s: Any, tenant_id: str, name: str, project: str | None = None, customer: str | None = None) -> str:
    cus = None
    if customer:
        cus = m.Customer(id=new_id("cus"), tenant_id=tenant_id, name=customer)
        s.add(cus)
        s.flush()
    prj = None
    if project:
        prj = m.Project(id=new_id("prj"), tenant_id=tenant_id, name=project, customer_id=cus.id if cus else None)
        s.add(prj)
        s.flush()
    q = m.Quote(
        id=new_id("quo"),
        tenant_id=tenant_id,
        name=name,
        project_id=prj.id if prj else None,
        customer_id=cus.id if cus else None,
    )
    s.add(q)
    s.flush()
    s.add(m.QuoteVersion(id=new_id("qv"), tenant_id=tenant_id, quote_id=q.id, version=1))
    return q.id


@pytest.fixture
def home(api: Api, seeded: dict[str, Engine]) -> Iterator[Home]:
    tenant = add_tenant(seeded["app"])
    with tenant_session(tenant.tenant_id, api.engine) as s:
        quotes = {
            "nursery": _quote(s, tenant.tenant_id, "NURSERY-1_merged.pdf", "גן ילדים, לוח ראשי", 'קבלן לדוגמה בע"מ'),
            "kitchen1": _quote(s, tenant.tenant_id, "מטבח תעשייתי - לוח 1.pdf"),
            "kitchen2": _quote(s, tenant.tenant_id, "מטבח תעשייתי - לוח 2.pdf"),
        }
    for key in ("home_chat", "chat_quote_builder", "chat_layer", "quote_audit"):
        set_tenant_flag(api.engine, tenant.tenant_id, key, True)
    flags.cache.clear()
    api.app.state.llm_providers = fake_llm.fake_providers()
    yield Home(api, tenant, quotes)
    api.app.state.llm_providers = fake_llm.fake_providers()


def test_a_panel_description_goes_to_the_builder_with_its_text(home: Home) -> None:
    r = home.route('בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16')
    assert (r["kind"], r["to"], r["by"]) == ("go", "/build", "code")
    assert r["text"] == 'בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16'


def test_an_audit_request_goes_to_the_audit(home: Home) -> None:
    assert home.route("בדוק את הצעה 10271 מול השרטוט")["to"] == "/audit"


def test_the_price_list(home: Home) -> None:
    assert home.route("אילו מחירים חסרים במחירון?")["to"] == "/prices"


def test_a_drawing_goes_to_a_new_quote(home: Home) -> None:
    assert home.route("יש לי שרטוט חדש להעלות")["to"] == "/new"


def test_a_question_about_a_named_quote_opens_it_with_the_chat(home: Home) -> None:
    r = home.route("מה חסר בהצעה של NURSERY?")
    assert (r["kind"], r["to"], r["chat"]) == ("go", f"/review/{home.quotes['nursery']}", True)
    assert r["text"] == "מה חסר בהצעה של NURSERY?"
    # by its project's name, with a prefix ("בגן" → "גן" is too short; "ילדים" names it)
    assert home.route('כמה מא"זים יש בלוח של הילדים?')["to"] == f"/review/{home.quotes['nursery']}"


def test_a_question_that_names_two_quotes_asks_which(home: Home) -> None:
    r = home.route("מה חסר במטבח התעשייתי?")
    assert r["kind"] == "ask" and r["message"] == "על איזו הצעה?"
    assert {c["to"] for c in r["choices"]} == {
        f"/review/{home.quotes['kitchen1']}",
        f"/review/{home.quotes['kitchen2']}",
    }
    assert all(c["chat"] and c["text"] == "מה חסר במטבח התעשייתי?" for c in r["choices"])


def test_the_model_routes_what_code_cannot_and_unclear_asks(home: Home) -> None:
    r = home.route("רוצה לבנות משהו חדש")
    assert (r["kind"], r["to"], r["by"]) == ("go", "/build", "model")
    r = home.route("שלום")
    assert r["kind"] == "ask" and r["by"] == "model" and r["message"].startswith("לא בטוח")
    assert [c["to"] for c in r["choices"]][:3] == ["/build", "/new", "/audit"]


def test_a_question_about_no_quote_it_names_asks_which(home: Home) -> None:
    r = home.route("תשנה את ההצעה לשניידר")
    assert r["kind"] == "ask" and r["message"] == "על איזו הצעה?" and len(r["choices"]) == 3


def test_with_the_builder_off_a_description_is_a_toast(api: Api, home: Home) -> None:
    set_tenant_flag(api.engine, home.tenant.tenant_id, "chat_quote_builder", False)
    flags.cache.clear()
    r = home.route('12 מא"ז 1X16')
    assert (r["kind"], r["message"]) == ("toast", "כדי ליצור הצעה, צרפו שרטוט או כתב כמויות")


def test_the_route_is_off_with_home_chat_off(api: Api, home: Home) -> None:
    set_tenant_flag(api.engine, home.tenant.tenant_id, "home_chat", False)
    flags.cache.clear()
    home.route("שלום", status=404)


def test_the_model_sees_the_text_only(api: Api, home: Home) -> None:
    sent: list[str] = []

    def answer(request: Any) -> dict[str, Any]:
        sent.append(f"{request.system}\n{request.user_text}")
        return fake_llm.answer(request)

    api.app.state.llm_providers = {"anthropic": FakeProvider(answer)}
    home.route('משהו על הקבלן ב-1,200 ש"ח')
    assert sent, "code left it to the model"
    for text in sent:
        assert "NURSERY" not in text and "קבלן לדוגמה" not in text and "1,200" not in text


def test_a_quote_named_whole_by_common_words(api: Api, home: Home) -> None:
    with tenant_session(home.tenant.tenant_id, api.engine) as s:
        qid = _quote(s, home.tenant.tenant_id, "לוח חשמל קומה 3")
    r = home.route("מה חסר בהצעה של לוח חשמל קומה 3?")
    assert (r["kind"], r["to"], r["by"]) == ("go", f"/review/{qid}", "code")


def test_a_name_with_a_date_is_not_taken_for_a_price(api: Api, home: Home) -> None:
    with tenant_session(home.tenant.tenant_id, api.engine) as s:
        qid = _quote(s, home.tenant.tenant_id, "הצעה בצ'אט 06.11 09:12")
    assert home.route("מה חסר בהצעה של הצעה בצ'אט 06.11 09:12?")["to"] == f"/review/{qid}"


def test_a_name_whose_first_word_takes_a_prefix(api: Api, home: Home) -> None:
    with tenant_session(home.tenant.tenant_id, api.engine) as s:
        qid = _quote(s, home.tenant.tenant_id, "הצעה בצ'אט 06.11 09:37")
    assert home.route("מה חסר בהצעה בצ'אט 06.11 09:37?")["to"] == f"/review/{qid}"
