"""The chat quote builder (13 §4.2, S27), behind `chat_quote_builder`.

A build is keyed by its drawing: the quote exists only from the first line (decision 2). Each message runs
`chat_bom_extraction` and stages 4–7 in the request (`services/build.py`); the answer is the whole build, its quote
as the review screen reads it, so the draft's table and the review show the same lines.
"""

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile

from konboro.db import models as m
from konboro.domain.permissions import Permission
from konboro.services import build, transcribe
from konboro.services import llm as llm_service
from konboro_llm import LLMClient

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import BuildMessageIn, BuildMessageOut, BuildOut
from .quotes import quote_out

log = logging.getLogger("konboro.build")

FLAG = "chat_quote_builder"
router = APIRouter(tags=["build"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(FLAG))])

Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
Writer = Annotated[Actor, Depends(require(Permission.QUOTES_WRITE))]
DrawingId = Annotated[str, Path(pattern=r"^drw_[0-9A-Z]{26}$")]
MessageId = Annotated[str, Path(pattern=r"^bmg_[0-9A-Z]{26}$")]


def _llm(request: Request, actor: Actor) -> LLMClient:
    return LLMClient(
        request.app.state.llm_providers, on_call=llm_service.usage_recorder(request.app.state.engine, actor.tenant_id)
    )


def _actor(actor: Actor) -> build.Actor:
    return build.Actor(actor.tenant_id, actor.user_id)


def _message_out(row: m.BuildMessage) -> BuildMessageOut:
    c = row.content
    return BuildMessageOut.model_validate(
        {
            "message_id": row.id,
            "role": row.role,
            "text": c.get("text", ""),
            "heard": c.get("heard"),
            "status": row.status,
            "created_at": row.created_at,
            "items": c.get("items", []) if row.role == "user" else [],
            "changes": c.get("changes", []) if row.role == "user" else [],
            "dropped": c.get("dropped", []) if row.role == "user" else [],
            "question": c.get("question") if row.role == "user" else None,
        }
    )


def build_out(actor: Actor, request: Request, b: build.Build) -> BuildOut:
    rows = build.messages(actor.session, b)
    return BuildOut(
        drawing_id=b.drawing.id,
        quote_id=b.quote.id if b.quote else None,
        messages=[_message_out(r) for r in rows],
        quote=quote_out(actor, b.quote.id, request.app.state.storage) if b.quote else None,
        can_undo=any(r.role == "user" and r.status == "applied" and "rows" in r.content for r in rows),
        voice_stand_in=bool(getattr(request.app.state, "transcriber_is_stand_in", True)),
    )


def _run(actor: Actor, request: Request, call: Callable[[], build.Build]) -> BuildOut:
    try:
        b = call()
    except build.BuildError as e:
        raise ApiError(e.status, e.code) from e
    return build_out(actor, request, b)


@router.post("/builds")
def start_build(actor: Writer, body: BuildMessageIn, request: Request) -> BuildOut:
    """A new build from its first message. Nothing is counted until a message adds a line (decision 2)."""
    storage: Any = request.app.state.storage
    return _run(
        actor,
        request,
        lambda: build.message(actor.session, storage, _llm(request, actor), _actor(actor), None, body.text),
    )


@router.get("/builds/{drawing_id}")
def get_build(actor: Reader, drawing_id: DrawingId, request: Request) -> BuildOut:
    return _run(
        actor, request, lambda: build.load(actor.session, request.app.state.storage, actor.tenant_id, drawing_id)
    )


@router.post("/builds/{drawing_id}/messages")
def send_build_message(actor: Writer, drawing_id: DrawingId, body: BuildMessageIn, request: Request) -> BuildOut:
    """A typed message: its lines and changes applied at once, stages 4–7 again, and the reply."""
    storage: Any = request.app.state.storage
    return _run(
        actor,
        request,
        lambda: build.message(actor.session, storage, _llm(request, actor), _actor(actor), drawing_id, body.text),
    )


@router.post("/builds/{drawing_id}/messages/{message_id}/apply")
def apply_build_message(actor: Writer, drawing_id: DrawingId, message_id: MessageId, request: Request) -> BuildOut:
    """ "הוסף" on a recording's card (decision 1)."""
    storage: Any = request.app.state.storage
    return _run(
        actor,
        request,
        lambda: build.apply_pending(
            actor.session, storage, _llm(request, actor), _actor(actor), drawing_id, message_id
        ),
    )


@router.post("/builds/{drawing_id}/messages/{message_id}/dismiss")
def dismiss_build_message(actor: Writer, drawing_id: DrawingId, message_id: MessageId, request: Request) -> BuildOut:
    """ "תקן": the recording is not added."""
    storage: Any = request.app.state.storage
    return _run(
        actor, request, lambda: build.dismiss_pending(actor.session, storage, _actor(actor), drawing_id, message_id)
    )


@router.post("/builds/{drawing_id}/undo")
def undo_build_message(actor: Writer, drawing_id: DrawingId, request: Request) -> BuildOut:
    """The last applied message taken back."""
    storage: Any = request.app.state.storage
    return _run(
        actor, request, lambda: build.undo(actor.session, storage, _llm(request, actor), _actor(actor), drawing_id)
    )


# --- voice (13 §4.2, behind `voice_input` too; S27 decision 1) --------------------------------------------------------

VOICE = [Depends(require_flag("voice_input"))]
Recording = Annotated[UploadFile, File(description="WebM/Opus, Ogg, MP4/AAC, MPEG or WAV, up to 2 MB (about a minute)")]
Seconds = Annotated[float | None, Form(ge=0, le=transcribe.MAX_SECONDS + 5)]


async def _heard(request: Request, actor: Actor, recording: UploadFile, seconds: float | None) -> str:
    """The recording's words. The recording itself is read here and dropped: it is never stored."""
    audio = await recording.read(transcribe.MAX_BYTES + 1)
    try:
        kind = transcribe.check(audio, recording.content_type)
    except transcribe.RecordingError as e:
        raise ApiError(422, "recording_invalid") from e
    words = request.app.state.transcriber.transcribe(audio, kind).strip()
    log.info(
        "build voice",
        extra={"tenant_id": actor.tenant_id, "user_id": actor.user_id, "bytes": len(audio), "seconds": seconds},
    )
    if not words:
        raise ApiError(422, "recording_invalid")
    return str(words)


@router.post("/builds/voice", dependencies=VOICE)
async def start_build_by_voice(
    actor: Writer, recording: Recording, request: Request, seconds: Seconds = None
) -> BuildOut:
    """A new build from a recording: what was heard and understood waits for "הוסף" (decision 1)."""
    heard = await _heard(request, actor, recording, seconds)
    storage: Any = request.app.state.storage
    return _run(
        actor,
        request,
        lambda: build.message(actor.session, storage, _llm(request, actor), _actor(actor), None, heard, heard=heard),
    )


@router.post("/builds/{drawing_id}/voice", dependencies=VOICE)
async def send_build_voice(
    actor: Writer, drawing_id: DrawingId, recording: Recording, request: Request, seconds: Seconds = None
) -> BuildOut:
    heard = await _heard(request, actor, recording, seconds)
    storage: Any = request.app.state.storage
    return _run(
        actor,
        request,
        lambda: build.message(
            actor.session, storage, _llm(request, actor), _actor(actor), drawing_id, heard, heard=heard
        ),
    )
