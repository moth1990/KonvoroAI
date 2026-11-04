"""The turns sent to the model (08 §5.2.1). The provider keeps no conversation: every call sends it again, and the
history, its cut and its summary are ours.

- **Budget.** `chat_context_budget_tokens` (30,000). The instructions, the tools and the quote brief come first;
  the history fills what is left, from the newest turn back.
- **Tool results.** Only the current turn's go in full (the tool loop's own steps). An earlier turn keeps one summary
  line per call ("query_lines: 12 שורות").
- **Compaction.** When older turns no longer fit, `chat_compaction` sums them up in one paragraph, saved with the
  conversation; amounts are stripped from it before it is saved (08 §5.4).

Tokens are estimated from characters (Hebrew runs about three characters a token); the budget is a ceiling, not an
invoice.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from konboro.db import models as m
from konboro_llm import LLMClient, LLMError, Turn
from konboro_llm.stages.chat_compaction import compact

from .check import MONEY_REF, strip_amounts

CHARS_PER_TOKEN = 3


def tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


@dataclass(frozen=True)
class Pair:
    """One finished turn: what the user said and what the assistant answered, as the model saw them."""

    user_id: str
    seq: int
    user: str
    assistant: str

    @property
    def tokens(self) -> int:
        return tokens(self.user) + tokens(self.assistant)


def assistant_text(content: dict[str, Any]) -> str:
    calls = list(content.get("tool_summaries") or [])
    text = str(content.get("answer_text") or "")
    if calls:
        return f"[{'; '.join(str(c) for c in calls)}] {text}"
    return text


def pairs(messages: Sequence[m.ChatMessage]) -> list[Pair]:
    rows = sorted(messages, key=lambda r: int(r.content.get("seq", 0)))
    out: list[Pair] = []
    pending: m.ChatMessage | None = None
    for r in rows:
        if r.role == "user":
            pending = r
        elif r.role == "assistant" and pending is not None:
            out.append(
                Pair(
                    pending.id,
                    int(pending.content.get("seq", 0)),
                    str(pending.content.get("model_text", "")),
                    assistant_text(r.content),
                )
            )
            pending = None
    return out


def clean_summary(text: str) -> str:
    return re.sub(r"\s{2,}", " ", strip_amounts(MONEY_REF.sub("", text))).strip()


def build(
    conversation: m.ChatConversation,
    messages: Sequence[m.ChatMessage],
    fixed_tokens: int,
    budget: int,
    llm: LLMClient | None,
    tenant_id: str,
) -> list[Turn]:
    """The history turns before the current message. Compacts what no longer fits, when there is a model to do it."""
    history = pairs(messages)
    state = conversation.state or {}
    through = int(state.get("compacted_through", 0))
    room = budget - fixed_tokens - tokens(conversation.summary or "")
    kept: list[Pair] = []
    for p in reversed(history):
        if p.seq <= through or room - p.tokens < 0:
            break
        kept.insert(0, p)
        room -= p.tokens
    dropped = [p for p in history if p.seq > through and p not in kept]
    if dropped and llm is not None:
        text = "\n".join(f"משתמש: {p.user}\nעוזר: {p.assistant}" for p in dropped)
        try:
            summary = compact(llm, conversation.summary, text, tenant_id).data.summary
        except LLMError:
            summary = None  # the turns are dropped without a summary; the decisions are in the quote anyway
        if summary is not None:
            conversation.summary = clean_summary(summary)[:4000]
        conversation.state = {**state, "compacted_through": dropped[-1].seq}
    turns: list[Turn] = []
    for p in kept:
        turns += [Turn("user", text=p.user), Turn("assistant", text=p.assistant or "…")]
    return turns


def with_summary(summary: str | None, text: str) -> str:
    return f"(סיכום השיחה עד כאן: {summary})\n\n{text}" if summary else text
