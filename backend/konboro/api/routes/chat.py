"""The chat on the review screen (08, S25), behind `chat_layer`.

The model is called from the request, inside the tenant's session: its tools read the quote and make proposals in
that transaction. Applying a proposal is the estimator's click on this API, never a tool (08 §4).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from konboro.chat import proposals, turn
from konboro.chat.state import ChatState
from konboro.db import models as m
from konboro.domain.permissions import Permission
from konboro.services import llm as llm_service
from konboro.services import quote_versions, review
from konboro_llm import LLMClient

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import ChatApplyOut, ChatMessageIn, ChatMessageOut, ChatOut, ChatProposalOut, ChatTurnOut
from .quotes import quote_out

FLAG = "chat_layer"
router = APIRouter(tags=["chat"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(FLAG))])

Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
Writer = Annotated[Actor, Depends(require(Permission.QUOTES_WRITE))]
QuoteId = Annotated[str, Path(pattern=r"^quo_[0-9A-Z]{26}$")]
ProposalId = Annotated[str, Path(pattern=r"^prp_[0-9A-Z]{26}$")]


def _errors(call: Any) -> Any:
    try:
        return call()
    except (turn.ChatError, proposals.ProposalError, quote_versions.VersionError, review.ReviewError) as e:
        raise ApiError(e.status, e.code) from e


def _chat(actor: Actor, quote_id: str) -> ChatOut:
    conv = turn.active(actor.session, actor.tenant_id, quote_id, create=False)
    closed = turn.closed_count(actor.session, actor.tenant_id, quote_id)
    if conv is None:
        return ChatOut(conversation_id=None, messages=[], proposals=[], closed_count=closed)
    state = ChatState.load(conv.state)
    rows = turn.conversation_proposals(actor.session, actor.tenant_id, conv.id)
    return ChatOut(
        conversation_id=conv.id,
        messages=[
            ChatMessageOut.model_validate(turn.message_out(actor.session, actor.tenant_id, r, state))
            for r in turn.messages(actor.session, actor.tenant_id, conv.id)
        ],
        proposals=[ChatProposalOut.model_validate(turn.proposal_out(p, state)) for p in rows],
        closed_count=closed,
    )


@router.get("/quotes/{quote_id}/chat")
def get_chat(actor: Reader, quote_id: QuoteId) -> ChatOut:
    """The active conversation, its messages and proposals; pending proposals the quote has moved past come back
    `expired` (08 §7.5)."""
    return _errors(lambda: _chat(actor, quote_id))  # type: ignore[no-any-return]


@router.post("/quotes/{quote_id}/chat/messages")
def send_message(actor: Reader, quote_id: QuoteId, body: ChatMessageIn, request: Request) -> ChatTurnOut:
    """One turn (08 §4–§8): the answer's blocks, with the amounts of the money references they use."""
    settings = request.app.state.settings
    llm = LLMClient(
        request.app.state.llm_providers, on_call=llm_service.usage_recorder(request.app.state.engine, actor.tenant_id)
    )

    def run() -> ChatTurnOut:
        ui = turn.UiContext(
            body.ui_context.panel_id, list(body.ui_context.selected_line_ids), body.ui_context.active_filter
        )
        out = turn.run(
            actor.session,
            request.app.state.storage,
            llm,
            review.Actor(actor.tenant_id, actor.user_id),
            actor.role,
            quote_id,
            body.message,
            ui,
            settings.chat_context_budget_tokens,
        )
        conv = turn.active(actor.session, actor.tenant_id, quote_id, create=False)
        assert conv is not None  # noqa: S101
        state = ChatState.load(conv.state)
        rows = turn.messages(actor.session, actor.tenant_id, conv.id)
        user = next(r for r in reversed(rows) if r.role == "user")
        made = {b["proposal_id"] for b in out["blocks"] if b["type"] == "proposal"}
        props = [p for p in turn.conversation_proposals(actor.session, actor.tenant_id, conv.id) if p.id in made]
        return ChatTurnOut(
            user=ChatMessageOut.model_validate(turn.message_out(actor.session, actor.tenant_id, user, state)),
            assistant=ChatMessageOut.model_validate(out),
            proposals=[ChatProposalOut.model_validate(turn.proposal_out(p, state)) for p in props],
        )

    return _errors(run)  # type: ignore[no-any-return]


@router.post("/quotes/{quote_id}/chat/new")
def new_conversation(actor: Reader, quote_id: QuoteId) -> ChatOut:
    """ "שיחה חדשה": the active conversation is closed and kept read only; its pending proposals expire."""

    def run() -> ChatOut:
        turn.new_conversation(actor.session, actor.tenant_id, quote_id)
        return _chat(actor, quote_id)

    return _errors(run)  # type: ignore[no-any-return]


def _proposal_out(actor: Actor, p: m.ChatProposal) -> ChatProposalOut:
    row = actor.session.get(m.ChatConversation, p.conversation_id) if p.conversation_id else None
    state = ChatState.load(row.state if row is not None and row.tenant_id == actor.tenant_id else {})
    return ChatProposalOut.model_validate(turn.proposal_out(p, state))


@router.post("/chat/proposals/{proposal_id}/apply")
def apply_proposal(actor: Writer, proposal_id: ProposalId, request: Request) -> ChatApplyOut:
    """08 §7.5: the estimator approved the card. The same actions as the screen's, as one undoable change; a sent
    version opens N+1 first. A proposal the quote has moved past answers 409 `proposal_expired`."""
    storage = request.app.state.storage

    def run() -> ChatApplyOut:
        p, done = proposals.apply(actor.session, storage, review.Actor(actor.tenant_id, actor.user_id), proposal_id)
        return ChatApplyOut(
            quote=quote_out(actor, p.quote_id, storage),
            message=done.message,
            event_id=done.event_id,
            count=done.count,
            proposal=_proposal_out(actor, p),
        )

    return _errors(run)  # type: ignore[no-any-return]


@router.post("/chat/proposals/{proposal_id}/dismiss")
def dismiss_proposal(actor: Writer, proposal_id: ProposalId) -> ChatProposalOut:
    return _errors(lambda: _proposal_out(actor, proposals.dismiss(actor.session, actor.tenant_id, proposal_id)))  # type: ignore[no-any-return]
