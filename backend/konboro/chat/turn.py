"""One chat turn end to end (08 §4–§8), and the conversation it belongs to.

1. The quote is read again; the brief and the screen context are built from it (08 §5.2).
2. The history goes in by budget (`history`).
3. The coordinator runs its tool loop (`konboro_llm.LLMClient.run_tools`); every tool is code (`tools`).
4. The answer is checked (`check`, 08 §8.2). An amount written as a number sends the text back once; if it comes back
   with one again, the number is removed.
5. The blocks the screen shows are put together by code (08 §8.1): the text, a clarification, the proposals made in
   this turn, the UI actions, the settings buttons. The money references in them come with their amounts, for the
   screen only: they are never sent to the model.

Every turn is kept (08 §10 `יומן`): the message, the tools called with their arguments, the proposals and the answer.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.services import home_route, review
from konboro.services.storage import Storage
from konboro_llm import LLMClient, LLMError, ToolLoopRequest, Turn
from konboro_llm.stages import chat_command as cc

from . import history, proposals
from .brief import brief
from .check import MONEY_REF, check, for_model, strip_amounts
from .lines import load
from .state import ChatState
from .tools import Tools, specs

log = logging.getLogger("konboro.chat")

STATUS_HE = {"red": "אדום", "yellow": "צהוב", "green": "ירוק"}
FAILED = "לא הצלחתי לבצע את זה. אפשר לנסות שוב, או לבצע במסך."
AMOUNT_RETRY = (
    "Your answer wrote an amount of money as a number ({found}). Write the same answer again, using only the "
    "{{{{$…}}}} references the tools gave you for amounts, or leave the amount out."
)


class ChatError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass
class UiContext:
    panel_id: str | None = None
    selected_line_ids: list[str] = field(default_factory=list)
    active_filter: str | None = None


# --- the conversation ------------------------------------------------------------------------------------------------


def _quote(session: Session, tenant_id: str, quote_id: str) -> m.Quote:
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id))
    if quote is None:
        raise ChatError(404, "not_found")
    return quote


def active(session: Session, tenant_id: str, quote_id: str, create: bool = True) -> m.ChatConversation | None:
    """08 §5.2.1: one active conversation per quote."""
    _quote(session, tenant_id, quote_id)
    row = session.scalar(
        select(m.ChatConversation).where(
            m.ChatConversation.tenant_id == tenant_id,
            m.ChatConversation.quote_id == quote_id,
            m.ChatConversation.status == "active",
        )
    )
    if row is None and create:
        row = m.ChatConversation(id=new_id("cnv"), tenant_id=tenant_id, quote_id=quote_id, status="active", state={})
        session.add(row)
        session.flush()
    return row


def new_conversation(session: Session, tenant_id: str, quote_id: str) -> m.ChatConversation:
    """ "שיחה חדשה": the active one is closed, read only; the decisions made in it are in the quote already."""
    old = active(session, tenant_id, quote_id, create=False)
    if old is not None:
        old.status = "closed"
        for p in session.scalars(
            select(m.ChatProposal).where(
                m.ChatProposal.tenant_id == tenant_id,
                m.ChatProposal.conversation_id == old.id,
                m.ChatProposal.status == "pending",
            )
        ):
            p.status, p.resolved_at = "expired", review.now()
        session.flush()
    created = active(session, tenant_id, quote_id)
    assert created is not None  # noqa: S101
    return created


def closed_count(session: Session, tenant_id: str, quote_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(m.ChatConversation)
            .where(
                m.ChatConversation.tenant_id == tenant_id,
                m.ChatConversation.quote_id == quote_id,
                m.ChatConversation.status == "closed",
            )
        )
        or 0
    )


def messages(session: Session, tenant_id: str, conversation_id: str) -> list[m.ChatMessage]:
    rows = session.scalars(
        select(m.ChatMessage).where(
            m.ChatMessage.tenant_id == tenant_id, m.ChatMessage.conversation_id == conversation_id
        )
    )
    return sorted(rows, key=lambda r: int(r.content.get("seq", 0)))


def conversation_proposals(session: Session, tenant_id: str, conversation_id: str) -> list[m.ChatProposal]:
    rows = list(
        session.scalars(
            select(m.ChatProposal).where(
                m.ChatProposal.tenant_id == tenant_id, m.ChatProposal.conversation_id == conversation_id
            )
        )
    )
    proposals.expire_stale(session, tenant_id, rows)
    return rows


# --- one turn --------------------------------------------------------------------------------------------------------


def _user_text(text: str, ui: UiContext, state: ChatState) -> str:
    """The message as the model gets it, with what the screen showed (08 §5.1, 09 §6.7)."""
    parts = []
    if ui.panel_id:
        parts.append(f"open panel {state.name('panel', ui.panel_id)}")
    if ui.selected_line_ids:
        parts.append("selected lines " + ", ".join(str(state.name("line", i)) for i in ui.selected_line_ids))
    if ui.active_filter and ui.active_filter in STATUS_HE:
        parts.append(f"table filtered to {ui.active_filter}")
    screen = f"[screen: {'; '.join(parts)}]\n" if parts else "[screen: nothing selected]\n"
    return screen + for_model(text.strip(), state)


def _seq(rows: list[m.ChatMessage]) -> int:
    return max((int(r.content.get("seq", 0)) for r in rows), default=0) + 1


def _ask_without_amounts(
    llm: LLMClient, request: ToolLoopRequest[cc.ChatAnswer], answer: cc.ChatAnswer, found: list[str], tools: Tools
) -> cc.ChatAnswer | None:
    retry = ToolLoopRequest(
        stage=request.stage,
        system=request.system,
        turns=[
            *request.turns,
            Turn("assistant", text=answer.model_dump_json()),
            Turn("user", text=AMOUNT_RETRY.format(found=", ".join(found[:3]))),
        ],
        tools=request.tools,
        output_schema=cc.ChatAnswer,
        context=request.context,
        tenant_id=request.tenant_id,
        max_steps=0,
    )
    try:
        return llm.run_tools(retry, tools.execute).data
    except LLMError:
        return None


def run(
    session: Session,
    storage: Storage,
    llm: LLMClient,
    actor: review.Actor,
    role: str,
    quote_id: str,
    text: str,
    ui: UiContext,
    budget: int,
) -> dict[str, Any]:
    text = text.strip()
    if not text or len(text) > 2000:
        raise ChatError(422, "invalid_message")
    ql = load(session, actor.tenant_id, quote_id)
    if ql is None:
        raise ChatError(404, "not_found")
    conv = active(session, actor.tenant_id, quote_id)
    assert conv is not None  # noqa: S101
    state = ChatState.load(conv.state)
    live = {ln.line_id for ln in ql.lines}
    ui = UiContext(
        panel_id=ui.panel_id if ui.panel_id in {p for p, _ in ql.panels()} else None,
        selected_line_ids=[i for i in ui.selected_line_ids if i in live],
        active_filter=ui.active_filter,
    )
    earlier = messages(session, actor.tenant_id, conv.id)
    seq = _seq(earlier)
    model_text = _user_text(text, ui, state)
    session.add(
        m.ChatMessage(
            id=new_id("msg"),
            tenant_id=actor.tenant_id,
            conversation_id=conv.id,
            role="user",
            content={"seq": seq, "text": text, "model_text": model_text, "ui_context": ui.__dict__},
            tokens=history.tokens(model_text),
        )
    )
    tools = Tools(session, storage, actor, role, quote_id, conv, state, llm=llm)
    context = "Quote brief (counts only):\n" + brief(ql, state)
    fixed = history.tokens(cc.SYSTEM) + history.tokens(context) + history.tokens(model_text) + 3000  # tools' schemas
    past = history.build(conv, earlier, fixed, budget, llm, actor.tenant_id)
    if conv.summary:
        if past:
            past[0] = Turn("user", text=history.with_summary(conv.summary, past[0].text or ""))
        else:
            model_text = history.with_summary(conv.summary, model_text)
    request = ToolLoopRequest(
        stage=cc.STAGE,
        system=cc.SYSTEM,
        turns=[*past, Turn("user", text=model_text)],
        tools=specs(),
        output_schema=cc.ChatAnswer,
        context=context,
        tenant_id=actor.tenant_id,
    )
    calls: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        result = llm.run_tools(request, tools.execute)
        answer: cc.ChatAnswer = result.data
        calls = [
            {
                "tool": c.name,
                "args": c.args,
                "error": r.content.get("error") if r.is_error or "error" in r.content else None,
            }
            for s in result.steps
            for c, r in zip(s.calls, s.results, strict=False)
        ]
    except LLMError as e:
        log.warning("chat turn failed: %s", e)
        answer = cc.ChatAnswer(text=FAILED)
        errors.append("tool_failed")

    # 08 §8.2: the answer check
    ql = load(session, actor.tenant_id, quote_id) or ql
    live = {ln.line_id for ln in ql.lines}
    located = set(tools.instances)
    keep = home_route.written_names(session, actor.tenant_id, text)  # a quote's name as typed is no amount (BUG-099)
    checked = check(answer.text, state, live, live_instances=located, keep=keep)
    if checked.amounts:
        again = _ask_without_amounts(llm, request, answer, checked.amounts, tools)
        if again is not None:
            answer = again
            checked = check(answer.text, state, live, live_instances=located, keep=keep)
        if checked.amounts:
            checked.text = strip_amounts(checked.text, keep)
            errors.append("amount_removed")
    if checked.invalid_refs:
        errors.append("invalid_ref")
        log.info("chat invalid_ref %s", checked.invalid_refs)

    blocks: list[dict[str, Any]] = [{"type": "text", "content": checked.text}]
    options = []
    for o in [o.strip() for o in answer.clarification_options if o.strip()][:4]:
        opt = check(strip_amounts(MONEY_REF.sub("", o), keep), state, live, live_instances=located, keep=keep)
        checked.invalid_refs += opt.invalid_refs
        if opt.text:
            options.append(opt.text)
    if options:
        blocks.append({"type": "clarification", "options": options})
    blocks += [{"type": "proposal", "proposal_id": pid} for pid in tools.proposals]
    for a in tools.ui_actions:
        a["line_ids"] = [i for i in a["line_ids"] if i in live]
        if a["line_ids"] or a.get("panel_id") or a.get("statuses") or a.get("instance_ids"):
            blocks.append(a)
    blocks += tools.settings_links

    conv.state = {**(conv.state or {}), **state.dump()}
    row = m.ChatMessage(
        id=new_id("msg"),
        tenant_id=actor.tenant_id,
        conversation_id=conv.id,
        role="assistant",
        content={
            "seq": seq + 1,
            "blocks": blocks,
            "answer_text": answer.text,
            "tool_summaries": tools.summaries,
            "tool_calls": calls,
            "money_refs": sorted(refs_in(blocks, session, actor.tenant_id)),
            # where each instance the answer points at is, for the drawing pane (S25b, 08 §6.4 `focus`)
            "instances": {i: tools.instances[i] for i in checked.instance_ids if i in tools.instances},
            "errors": errors,
        },
        tokens=history.tokens(answer.text),
    )
    session.add(row)
    session.flush()
    return message_out(session, actor.tenant_id, row, state)


# --- what the screen gets --------------------------------------------------------------------------------------------


def refs_in(blocks: list[dict[str, Any]], session: Session, tenant_id: str) -> set[str]:
    out: set[str] = set()
    for b in blocks:
        if b["type"] == "text":
            out |= set(MONEY_REF.findall(b["content"]))
        if b["type"] == "proposal":
            p = session.get(m.ChatProposal, b["proposal_id"])
            if p is not None and p.tenant_id == tenant_id:
                out |= _diff_refs(p.diff)
    return out


def _diff_refs(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith("$") and value[1:2].isalpha() else set()
    if isinstance(value, dict):
        return set().union(*(_diff_refs(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_diff_refs(v) for v in value)) if value else set()
    return set()


def message_out(session: Session, tenant_id: str, row: m.ChatMessage, state: ChatState) -> dict[str, Any]:
    c = row.content
    if row.role == "user":
        blocks = [{"type": "text", "content": c.get("text", "")}]  # a clicked option may name a quote
        return {
            "message_id": row.id,
            "role": "user",
            "blocks": blocks,
            "money": {},
            "quotes": quote_names(session, tenant_id, blocks),
            "instances": {},
        }
    return {
        "message_id": row.id,
        "role": "assistant",
        "blocks": c.get("blocks", []),
        "money": state.resolve(set(c.get("money_refs", []))),
        "quotes": quote_names(session, tenant_id, c.get("blocks", [])),
        "instances": dict(c.get("instances", {})),
    }


SCREEN_QUOTE = re.compile(r"\{\{\s*quote:\s*(quo_[0-9A-Z]+)\s*\}\}")


def quote_names(session: Session, tenant_id: str, blocks: list[dict[str, Any]]) -> dict[str, str]:
    """The names of the quotes an answer points at, for the screen only (S25b decision 1): the model never sees them.
    Read when the message is shown, under the tenant's RLS."""
    ids: set[str] = set()
    for b in blocks:
        texts = [b.get("content", "")] if b["type"] == "text" else list(b.get("options", []))
        for t in texts:
            ids |= set(SCREEN_QUOTE.findall(t))
    if not ids:
        return {}
    rows = session.execute(select(m.Quote.id, m.Quote.name).where(m.Quote.tenant_id == tenant_id, m.Quote.id.in_(ids)))
    return {qid: name for qid, name in rows}


def proposal_out(p: m.ChatProposal, state: ChatState) -> dict[str, Any]:
    return {
        "proposal_id": p.id,
        "summary_he": p.summary_he,
        "status": p.status,
        "affected_line_count": p.affected_line_count,
        "warnings": list(p.warnings),
        "diff": p.diff,
        "base_version": p.base_version,
        "money": state.resolve(_diff_refs(p.diff)),
        "remember_options": list(p.remember_options or ["quote_only"]),
        "remembered": p.remembered,
    }
