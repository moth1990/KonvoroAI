"""08 §5.2.1: the history by token budget, earlier tool results as one line each, and compaction with no amounts."""

from typing import Any

from konboro.chat import history
from konboro.db import models as m
from konboro.devtools.fake_llm import fake_providers
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider


def conv(**state: Any) -> m.ChatConversation:
    return m.ChatConversation(id="cnv_1", tenant_id="tnt_1", quote_id="quo_1", status="active", state=state)


def turn_pair(seq: int, text: str, answer: str, tools: list[str] | None = None) -> list[m.ChatMessage]:
    return [
        m.ChatMessage(id=f"msg_u{seq}", role="user", content={"seq": seq, "model_text": text}),
        m.ChatMessage(
            id=f"msg_a{seq}",
            role="assistant",
            content={"seq": seq + 1, "answer_text": answer, "tool_summaries": tools or []},
        ),
    ]


def test_turns_come_newest_back_with_one_line_per_earlier_tool_call():
    msgs = turn_pair(1, "ראשונה", "תשובה 1", ["query_lines: 12 שורות"]) + turn_pair(3, "שנייה", "תשובה 2")
    turns = history.build(conv(), msgs, fixed_tokens=0, budget=10_000, llm=None, tenant_id="tnt_1")
    assert [(t.role, t.text) for t in turns] == [
        ("user", "ראשונה"),
        ("assistant", "[query_lines: 12 שורות] תשובה 1"),
        ("user", "שנייה"),
        ("assistant", "תשובה 2"),
    ]
    assert all(not t.tool_results for t in turns)  # only the current turn's results go in full


def test_what_does_not_fit_is_compacted_once_and_the_summary_has_no_amounts():
    fake = FakeProvider([{"summary": "ביקשו להחליף לשניידר, המחיר ₪1,250.50 ו-{{$T1}}, הוכנה CH1"}])
    llm = LLMClient({"anthropic": fake})
    c = conv()
    old = turn_pair(1, "א" * 3000, "ב" * 3000)
    new = turn_pair(3, "שאלה", "תשובה")
    turns = history.build(
        c,
        old + new,
        fixed_tokens=0,
        budget=history.tokens("שאלה") + history.tokens("תשובה") + 5,
        llm=llm,
        tenant_id="tnt_1",
    )
    assert [t.text for t in turns] == ["שאלה", "תשובה"]
    assert c.summary is not None and "1,250" not in c.summary and "$T1" not in c.summary and "CH1" in c.summary
    assert c.state["compacted_through"] == 1
    assert fake.requests[0].stage == "chat_compaction"
    # the next turn keeps the summary and does not compact the same turns again
    again = history.build(c, old + new, fixed_tokens=0, budget=10_000, llm=llm, tenant_id="tnt_1")
    assert [t.text for t in again] == ["שאלה", "תשובה"] and len(fake.requests) == 1


def test_the_stand_in_answers_the_chat_and_its_compaction():
    llm = LLMClient(fake_providers())
    c = conv()
    history.build(c, turn_pair(1, "א" * 900, "ב"), fixed_tokens=0, budget=10, llm=llm, tenant_id="tnt_1")
    assert c.summary == "סיכום של מודל הדמה."
    assert history.with_summary("סיכום", "הודעה") == "(סיכום השיחה עד כאן: סיכום)\n\nהודעה"
