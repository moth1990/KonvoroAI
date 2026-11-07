"""The chat layer II (S25b, 08 §6.4–6.5, §7.4) on the NURSERY-1 fixture: the lines' signatures, `list_quotes` and
`compare` with another quote, `explain_line` with the drawing crop, and a proposal remembered for a customer or the
factory, with undo."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_price_list
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.devtools.fixtures.nursery import EARLIER_NAME, seed_earlier_quote, seed_nursery, seed_nursery_pages
from konboro.services.storage import Storage

from .api import Api, add_tenant, set_tenant_flag
from .test_chat import Chat, seeded  # noqa: F401  # the module's fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def chat(api: Api, seeded: dict[str, Engine], storage: Storage) -> Iterator[Chat]:  # noqa: F811
    tenant = add_tenant(seeded["app"])
    with tenant_session(tenant.tenant_id, api.engine) as s:
        seed_price_list(s, tenant.tenant_id)
        s.add(
            m.MarginRule(
                id=new_id("mr"), tenant_id=tenant.tenant_id, level="default", kind="markup", value=Decimal("0.25")
            )
        )
        qid = seed_nursery(s, tenant.tenant_id)
        seed_nursery_pages(s, storage, tenant.tenant_id)
        assert seed_earlier_quote(s, tenant.tenant_id) is not None
    assert qid is not None
    set_tenant_flag(api.engine, tenant.tenant_id, "chat_layer", True)
    c = Chat(api, tenant, qid)
    c.model(fake_llm.answer)
    yield c
    api.app.state.llm_providers = fake_llm.fake_providers()


def lines_of(chat: Chat, name: str) -> list[m.QuoteLine]:
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        rows = s.scalars(
            select(m.QuoteLine)
            .join(m.QuoteVersion, m.QuoteVersion.id == m.QuoteLine.quote_version_id)
            .join(m.Quote, m.Quote.id == m.QuoteVersion.quote_id)
            .where(m.Quote.name == name, m.QuoteLine.deleted_at.is_(None))
            .order_by(m.QuoteLine.position)
        ).all()
        s.expunge_all()
        return list(rows)


def test_fixture_lines_are_signed_as_stage_5_signs_them(chat: Chat) -> None:
    rows = {r.line_key: r for r in lines_of(chat, "NURSERY")}
    # inferred and filled in as stage 5 does: the class from the rating, the breaking capacity from the default
    assert rows["fixture:f22"].signature == "circuit_breaker|mcb|current_a=16|poles=3|bc_ka>=10|neutral=false"
    assert str(rows["fixture:f31"].signature).startswith("circuit_breaker|mcb|current_a=16|poles=1|")
    assert rows["fixture:q0b"].signature is None  # a kit part pairs by its SKU
    signed = [r.signature for r in rows.values() if r.signature]
    assert len(signed) == len(set(signed))  # one line per signature on NURSERY


def test_the_earlier_quote_is_sent_with_its_differences(chat: Chat) -> None:
    now = {r.signature: r for r in lines_of(chat, "NURSERY") if r.signature}
    before = {r.signature: r for r in lines_of(chat, EARLIER_NAME) if r.signature}
    assert set(now) - set(before) == {next(s for s, r in now.items() if r.line_key == "fixture:fnv")}
    f22 = next(s for s, r in now.items() if r.line_key == "fixture:f22")
    assert (before[f22].qty, now[f22].qty) == (Decimal(4), Decimal(5))
    assert all(r.component_id is None for r in before.values())
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        status = s.scalar(
            select(m.QuoteVersion.status)
            .join(m.Quote, m.Quote.id == m.QuoteVersion.quote_id)
            .where(m.Quote.name == EARLIER_NAME)
        )
    assert status == "sent"


def calls(*names_args: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {"tool_calls": [{"name": n, "args": a} for n, a in names_args]}


def result_of(fake: Any, turn: int, n: int = 0) -> dict[str, Any]:
    """The `n`th tool result the model got before its `turn`th call."""
    return dict(fake.turns[turn].turns[-1].tool_results[n].content)


def test_list_quotes_names_the_other_quote_without_its_name(chat: Chat) -> None:
    fake = chat.model([calls(("list_quotes", {})), {"answer": {"text": "מצאתי את {{quote:QT1}} ואת {{quote:QT9}}"}}])
    turn = chat.say("תראה לי הצעות אחרות")
    listed = result_of(fake, 1)
    assert listed["total_count"] == 1
    q = listed["quotes"][0]
    assert q["quote"] == "QT1" and q["status"] == "sent" and q["version"] == 1
    assert q["same_drawing"] is False and q["line_count"] > 10
    assert EARLIER_NAME not in str(listed) and "NURSERY" not in str(listed)  # the name never reaches the model
    text = turn["assistant"]["blocks"][0]["content"]
    assert "{{quote:quo_" in text and "QT9" not in text  # a name the conversation never gave is removed
    assert list(turn["assistant"]["quotes"].values()) == [EARLIER_NAME]


def test_list_quotes_matches_the_estimators_words_in_code(chat: Chat) -> None:
    fake = chat.model(
        [
            calls(("list_quotes", {"text": "הצעה קודמת"})),
            calls(("list_quotes", {"text": "בית ספר"})),
            {"answer": {"text": "-"}},
        ]
    )
    chat.say("תשווה להצעה הקודמת")
    assert result_of(fake, 1)["total_count"] == 1
    assert result_of(fake, 2)["total_count"] == 0


def _other_quote(chat: Chat, name: str) -> str:
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        q = m.Quote(id=new_id("quo"), tenant_id=chat.tenant.tenant_id, name=name)
        s.add(q)
        s.flush()
        s.add(m.QuoteVersion(id=new_id("qv"), tenant_id=chat.tenant.tenant_id, quote_id=q.id, version=1))
        return q.id


@pytest.mark.parametrize("name", ["הצעה בצ'אט 06.11 09:37", "25.26.100.01"])
def test_a_quote_named_with_a_date_or_a_dotted_number_is_compared_by_its_name(chat: Chat, name: str) -> None:
    """BUG-099: the estimator's message reaches the model as typed, `list_quotes` matches the name in code, and the
    answer check reads no amount in the name or a date; a price beside it is still asked again, then removed."""
    qid = _other_quote(chat, name)
    fake = chat.model(
        [
            calls(("list_quotes", {"text": name})),
            calls(("compare", {"quote": "QT1"})),
            {"answer": {"text": f"מול {{{{quote:QT1}}}} ({name}, מ-06.11.2026): 3 שורות שונות, המחיר ליחידה 12.40"}},
            {"answer": {"text": f"מול {{{{quote:QT1}}}} ({name}): שוב 12.40"}},
        ]
    )
    turn = chat.say(f"תשווה להצעה {name}")
    assert name in (fake.turns[0].turns[-1].text or "")  # the message as typed
    listed = result_of(fake, 1)
    assert listed["total_count"] == 1 and listed["quotes"][0]["quote"] == "QT1"
    assert result_of(fake, 2)["other_quote"] == "QT1"
    assert len(fake.turns) == 4  # asked once again, for the price only
    assert "12.40" in (fake.turns[3].turns[-1].text or "") and name not in (fake.turns[3].turns[-1].text or "")
    text = turn["assistant"]["blocks"][0]["content"]
    assert name in text and "12.40" not in text
    assert "{{quote:" + qid + "}}" in text


def test_compare_with_another_quote_pairs_lines_by_signature(chat: Chat) -> None:
    fake = chat.model(
        [calls(("list_quotes", {})), calls(("compare", {"quote": "QT1"})), {"answer": {"text": "הנה ההבדלים"}}]
    )
    chat.say("מה השתנה מול ההצעה הקודמת?")
    out = result_of(fake, 2)
    assert out["other_quote"] == "QT1" and out["other_status"] == "sent"
    by_change: dict[str, list[dict[str, Any]]] = {}
    for x in out["lines"]:
        by_change.setdefault(x["change"], []).append(x)
    # FNV is new; F22–F25+F30 went from 4 to 5; Q01's price moved; nothing was removed
    assert [x["description"] for x in by_change["added"]] == ['מא"ז ABB S203M 3P \u200f6A']
    qty = next(x for x in by_change["changed"] if "qty" in x["changed"])
    assert (qty["qty_other"], qty["qty_this"]) == (4, 5)
    price = next(x for x in by_change["changed"] if "unit_price" in x["changed"])
    assert price["unit_price_other"] != price["unit_price_this"]
    assert price["unit_price_other"].startswith("$T")  # references, never amounts
    assert "QT1" in out["legend"]
    assert "removed" not in by_change
    assert len(out["lines"]) == 3  # the other lines pair unchanged, the four "device" lines by SKU among them
    assert out["difference"].startswith("$T")


def test_compare_with_an_unknown_or_foreign_quote(chat: Chat, api: Api) -> None:
    other = add_tenant(api.engine)
    with tenant_session(other.tenant_id, api.engine) as s:
        foreign = seed_nursery(s, other.tenant_id)
    fake = chat.model([calls(("compare", {"quote": "QT1"})), {"answer": {"text": "-"}}])
    chat.say("תשווה")
    assert result_of(fake, 1)["error"] == "unknown_quote"  # never listed
    # a foreign quote's id put into the conversation's names by hand: RLS and the tenant check both refuse it
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        conv = s.scalar(select(m.ChatConversation).where(m.ChatConversation.quote_id == chat.quote_id))
        assert conv is not None
        conv.state = {**conv.state, "names": {**conv.state.get("names", {}), "QT7": foreign}}
    fake = chat.model([calls(("compare", {"quote": "QT7"})), {"answer": {"text": "-"}}])
    chat.say("תשווה ל-QT7")
    assert result_of(fake, 1)["error"] == "unknown_quote"


def test_a_clicked_option_with_a_quote_reaches_the_model_by_its_name(chat: Chat) -> None:
    chat.model([calls(("list_quotes", {})), {"answer": {"text": "איזו?", "clarification_options": ["{{quote:QT1}}"]}}])
    turn = chat.say("תשווה להצעה אחרת")
    option = turn["assistant"]["blocks"][1]["options"][0]
    assert option.startswith("{{quote:quo_")
    fake = chat.model([{"answer": {"text": "-"}}])
    back = chat.say(option)
    assert fake.turns[0].turns[-1].text.endswith("{{quote:QT1}}")  # the id went back to its name
    assert back["user"]["quotes"] == {option[8:-2]: EARLIER_NAME}


# --- explain_line (08 §6.4) -------------------------------------------------------------------------------------


def line_id(chat: Chat, key: str) -> str:
    return next(r.id for r in lines_of(chat, "NURSERY") if r.line_key == key)


def test_explain_line_answers_from_the_trace_and_a_crop(chat: Chat) -> None:
    fake = chat.model(fake_llm.answer)
    f22 = line_id(chat, "fixture:f22")
    turn = chat.say("למה 3 קטבים?", selected_line_ids=[f22])
    sub = [r for r in fake.requests if r.stage == "line_explanation"]
    assert len(sub) == 1
    req = sub[0]
    assert len(req.images) == 1 and req.images[0].data[:4] == b"\x89PNG"
    assert str(req.images[0].key).startswith("line_explanation:") and ":p8:" in str(req.images[0].key)
    # no money and none of the conversation: only the question and the trace
    assert "$T" not in req.user_text and "$P" not in req.user_text and "185" not in req.user_text
    assert not any(k in req.user_text for k in ("price_trace", "unit_price", "line_total", "unit_cost"))
    assert "F22" in req.user_text and '"instance": "I1"' in req.user_text
    text = turn["assistant"]["blocks"][0]["content"]
    assert "נקרא מהשרטוט" in text
    instance = text.split("{{instance:", 1)[1].split("}}", 1)[0]
    placed = turn["assistant"]["instances"][instance]
    assert placed["line_id"] == f22 and len(placed["bbox"]) == 4
    focus = next(b for b in turn["assistant"]["blocks"] if b["type"] == "ui_action")
    assert focus["instance_ids"] == [instance] and focus["line_ids"] == [f22]
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        stages = list(s.scalars(select(m.LlmCall.stage)))
    assert stages.count("line_explanation") == 1


def test_explain_line_says_a_default_is_the_factorys(chat: Chat) -> None:
    """The enclosure's values come from the notes; a factory default is said as one (the stand-in reads the first)."""
    fake = chat.model(fake_llm.answer)
    enc = line_id(chat, "fixture:enc")
    chat.say("למה IP55?", selected_line_ids=[enc])
    req = next(r for r in fake.requests if r.stage == "line_explanation")
    assert '"source": "notes"' in req.user_text
    out = result_of(fake, 1)
    assert out["crop"] is True and out["trace_supported"] is True
    assert {"attribute": "ip", "value": "55", "source": "notes"} in out["filled_in"]


def test_explain_line_drops_what_it_was_not_given(chat: Chat) -> None:
    fake = chat.model(
        [
            calls(("query_lines", {"text": "S203M"})),
            calls(("explain_line", {"line": "L1", "question": "למה?"})),
            {
                "answer": "לא ברור מהעקבות.",
                "cites": {"line_ids": ["L1", "L99"], "instance_ids": ["I9"], "span_ids": ["S1", "S40"]},
                "focus": {"instance_ids": ["I9"]},
                "confidence": 0.4,
                "trace_supported": False,
            },
            {"answer": {"text": "אין לי מספיק מידע. כדאי לבדוק בשרטוט {{instance:I9}}"}},
        ]
    )
    turn = chat.say("למה השורה הזו?")
    out = result_of(fake, 2)
    assert out["focus"] == [] and out["shown_on_drawing"] is False
    assert "not explain" in out["note"]
    text = turn["assistant"]["blocks"][0]["content"]
    assert "instance" not in text  # I9 was never located: the answer check removes it
    assert not any(b["type"] == "ui_action" for b in turn["assistant"]["blocks"])


# --- remember (08 §7.4, 05 §11) -----------------------------------------------------------------------------------


def apply_as(chat: Chat, proposal_id: str, remember: str, status: int = 200) -> dict[str, Any]:
    r = chat.api.client.post(f"/chat/proposals/{proposal_id}/apply", json={"remember": remember}, headers=chat.h)
    assert r.status_code == status, r.text
    return dict(r.json())


def memory(chat: Chat) -> list[tuple[str | None, str, str | None, str, int]]:
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        rows = s.scalars(select(m.MatchMemory).order_by(m.MatchMemory.signature))
        return [(r.customer_id, r.signature, r.brand_context, r.sku, r.approved_count) for r in rows]


def brand_proposal(chat: Chat) -> dict[str, Any]:
    chat.model(fake_llm.answer)
    turn = chat.say('החלף את כל מא"זי ABB ל-Schneider')
    assert len(turn["proposals"]) == 1
    return dict(turn["proposals"][0])


def swapped(prop: dict[str, Any]) -> dict[str, str]:
    """line id -> the SKU the proposal gives it, for the lines that change SKU."""
    return {
        x["line_id"]: x["after"]["sku"]
        for x in prop["diff"]["lines_changed"]
        if x["after"]["sku"] and x["after"]["sku"] != x["before"]["sku"]
    }


def set_customer(chat: Chat) -> str:
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        c = m.Customer(id=new_id("cus"), tenant_id=chat.tenant.tenant_id, name="עיריית בדיקה")
        s.add(c)
        s.flush()
        q = s.get(m.Quote, chat.quote_id)
        assert q is not None
        q.customer_id = c.id
        return str(c.id)


def test_a_brand_swap_offers_the_factory_but_not_a_customer_it_lacks(chat: Chat) -> None:
    prop = brand_proposal(chat)
    assert prop["remember_options"] == ["quote_only", "tenant"]  # NURSERY has no customer
    apply_as(chat, prop["proposal_id"], "customer", 422)
    assert memory(chat) == []


def test_other_changes_are_this_quote_only(chat: Chat) -> None:
    f22 = line_id(chat, "fixture:f22")
    chat.model(
        [
            calls(("query_lines", {"text": "S203M"})),
            calls(
                (
                    "propose_change",
                    {
                        "changes": [{"type": "set_quantity", "target": {"lines": ["L1"]}, "qty": 7}],
                        "summary_he": "כמות",
                    },
                )
            ),
            {"answer": {"text": "-"}},
        ]
    )
    turn = chat.say("כמות 7", selected_line_ids=[f22])
    assert turn["proposals"][0]["remember_options"] == ["quote_only"]
    apply_as(chat, turn["proposals"][0]["proposal_id"], "tenant", 422)


def test_remember_for_the_factory_writes_memory_that_undo_takes_back(chat: Chat) -> None:
    rows = {r.id: r for r in lines_of(chat, "NURSERY")}
    prop = brand_proposal(chat)
    moved = swapped(prop)
    assert moved
    done = apply_as(chat, prop["proposal_id"], "tenant")
    assert "נזכור את זה במפעל" in done["message"]
    assert done["proposal"]["remembered"] == "tenant"
    want = sorted(
        {(None, rows[i].signature, rows[i].brand_context, sku, 1) for i, sku in moved.items() if rows[i].signature},
        key=lambda x: str(x[1]),
    )
    assert memory(chat) == want
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        ev = s.scalars(select(m.CorrectionEvent).where(m.CorrectionEvent.type == "memory_saved")).one()
        assert ev.source == "chat" and ev.after["proposal"] == prop["proposal_id"] and ev.after["scope"] == "tenant"
    chat.undo(str(done["event_id"]))
    assert memory(chat) == []


def test_remember_replaces_an_earlier_memory_and_undo_puts_it_back(chat: Chat) -> None:
    rows = {r.id: r for r in lines_of(chat, "NURSERY")}
    prop = brand_proposal(chat)
    line, _ = next(iter(swapped(prop).items()))
    sig, context = rows[line].signature, rows[line].brand_context
    assert sig
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        s.add(
            m.MatchMemory(
                id=new_id("mm"),
                tenant_id=chat.tenant.tenant_id,
                signature=sig,
                brand_context=context,
                sku="OLD-SKU",
                approved_count=4,
            )
        )
    done = apply_as(chat, prop["proposal_id"], "tenant")
    assert ("OLD-SKU", 4) not in [(x[3], x[4]) for x in memory(chat)]
    chat.undo(str(done["event_id"]))
    assert [(x[1], x[3], x[4]) for x in memory(chat)] == [(sig, "OLD-SKU", 4)]


def test_remember_for_the_customer_and_stage_5_recalls_it(chat: Chat) -> None:
    from konboro.devtools.fixtures.nursery import sign
    from konboro.pipeline.association import schemas
    from konboro.pipeline.matching import catalog, factory, match, notes
    from konboro.services import review_picker

    customer = set_customer(chat)
    f22 = line_id(chat, "fixture:f22")
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:  # F22's drawing gives 3X16A, no brand or series
        row = s.get(m.QuoteLine, f22)
        assert row is not None and row.component_id
        component_id = row.component_id
        cmp = s.get(m.Component, component_id)
        assert cmp is not None
        cmp.explicit_texts, cmp.brand_hint = ["F22 … F25, F30", "3X16A"], None
        version = s.get(m.QuoteVersion, row.quote_version_id)
        assert version is not None
        sign(s, chat.tenant.tenant_id, version)
    prop = brand_proposal(chat)
    assert prop["remember_options"] == ["quote_only", "customer", "tenant"]
    moved = swapped(prop)
    assert f22 in moved
    apply_as(chat, prop["proposal_id"], "customer")
    saved = memory(chat)
    assert saved and all(x[0] == customer for x in saved)
    # the customer's next drawing: stage 5 picks the remembered SKU for the same component, by memory; another
    # customer's does not, and a drawing that names a brand itself wins over the memory (05 §5.3)
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s:
        cmp = s.get(m.Component, component_id)
        assert cmp is not None
        c = review_picker.component_from_row(cmp)
        named = c.model_copy(update={"brand_hint": "ABB"})
        cat = catalog.load(s)
        for comp, who, recalled in ((c, customer, True), (c, None, False), (named, customer, False)):
            inp = match.Inputs(
                catalog=cat,
                factory=factory.load(s, chat.tenant.tenant_id, cat, who),
                schemas=schemas.load(s),
                notes=notes.read([]),
                components={comp.component_id: comp},
                ask=None,
            )
            got = match.finish(comp, match.decide_prepared(match.prepare(comp, inp, {}, {}), inp), inp.cfg)
            assert (got.method == "memory") is recalled, (who, comp.brand_hint, got.method)
            if recalled:
                assert got.chosen_sku == moved[f22]


def test_remember_for_the_factory_needs_the_settings_permission(chat: Chat) -> None:
    from konboro.chat import proposals
    from konboro.services import review

    prop = brand_proposal(chat)
    with tenant_session(chat.tenant.tenant_id, chat.api.engine) as s, pytest.raises(proposals.ProposalError) as e:
        proposals.apply(
            s,
            chat.api.app.state.storage,
            review.Actor(chat.tenant.tenant_id, chat.tenant.user_id),
            prop["proposal_id"],
            remember="tenant",
            role="estimator",  # a role with no settings permission (v1.0 has only the owner, 00 §14.1)
        )
    assert (e.value.status, e.value.code) == (403, "forbidden")
