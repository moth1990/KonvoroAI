"""Uploads and their pipeline runs: the new-quote screen (01 §4.6, prototype `vNew`)."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Request, UploadFile, status

from konboro.domain.permissions import Permission
from konboro.pipeline import coordinator
from konboro.pipeline.intake import corrections
from konboro.pipeline.intake.routing import CONFIRM_THRESHOLD
from konboro.pipeline.stages import NAMES
from konboro.services import drawings, quota
from konboro.services.intake import MB, Limits
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage

from ..deps import Actor, require
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import (
    NoticeOut,
    PageKindIn,
    ProgressFileOut,
    ProgressOut,
    ProgressPageOut,
    ProgressSummaryOut,
    RevisableOut,
    StageOut,
    UploadedFileOut,
    UploadOut,
)

router = APIRouter(tags=["drawings"], responses=ERROR_RESPONSES)

Writer = Annotated[Actor, Depends(require(Permission.DRAWINGS_WRITE))]
Reader = Annotated[Actor, Depends(require(Permission.DRAWINGS_READ))]
DrawingId = Annotated[str, Path(pattern=r"^drw_[0-9A-Z]{26}$")]

# Read one byte past the limit: enough to know a file is too large without holding all of it.
_READ_LIMIT = Limits().max_file_size_mb * MB + 1


@router.post("/drawings", status_code=status.HTTP_201_CREATED)
def upload(
    request: Request,
    background: BackgroundTasks,
    actor: Writer,
    files: Annotated[list[UploadFile], File(description="The drawing: PDF, images, XLSX, CSV or ZIP")],
    customer: Annotated[str | None, Form(max_length=200)] = None,
    project: Annotated[str | None, Form(max_length=200)] = None,
    revision_of: Annotated[str | None, Form(pattern=r"^drw_[0-9A-Z]{26}$")] = None,
) -> UploadOut:
    """Checks run in the order of 01 §4.3: quota, size, format, pages. One failing file rejects the upload."""
    received = [(f.filename or "file", f.file.read(_READ_LIMIT)) for f in files]
    try:
        new = drawings.create_upload(
            actor.session,
            request.app.state.storage,
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            files=received,
            customer_name=customer,
            project_name=project,
            revision_of=revision_of,
        )
    except quota.QuotaReachedError as e:
        raise ApiError(403, "quota_reached") from e
    except drawings.RevisionNotFoundError as e:
        raise ApiError(404, "not_found", [{"field": "revision_of"}]) from e
    except drawings.UploadRejectedError as e:
        check = e.check
        details = [_file_out(f).model_dump() for f in check.files]
        if check.error:
            details.insert(0, {"code": check.error, "message": check.message})
        raise ApiError(422, "upload_rejected", details) from e

    d = new.drawing
    # After the commit (the tenant transaction ends with this function), so the worker finds the rows.
    message = StageMessage(drawing_id=d.id, tenant_id=d.tenant_id, stage=1, trace_id=str(d.trace_id))
    queue: Queue = request.app.state.queue
    background.add_task(queue.send, message)
    return UploadOut(drawing_id=d.id, status=d.status, files=[_file_out(f) for f in new.files], counted_as=new.reason)


def _file_out(f: drawings.CheckedFile) -> UploadedFileOut:
    return UploadedFileOut(
        name=f.name,
        size_bytes=f.size_bytes,
        detected_format=f.detected_format,
        page_count=f.page_count,
        error=f.error,
        message=f.message,
    )


@router.get("/drawings/revisable")
def list_revisable(actor: Reader) -> list[RevisableOut]:
    """Finished drawings a new version can follow, newest first (the "new version" picker)."""
    return [
        RevisableOut(drawing_id=d.id, name=q.name, version=q.current_version, updated_at=d.updated_at)
        for d, q in drawings.revisable(actor.session, actor.tenant_id)
    ]


@router.get("/drawings/{drawing_id}/progress")
def get_progress(request: Request, actor: Reader, drawing_id: DrawingId) -> ProgressOut:
    """Polled every second by the new-quote screen (S05 decision)."""
    return _progress_out(actor, request.app.state.storage, drawing_id)


@router.post("/drawings/{drawing_id}/cancel")
def cancel(request: Request, actor: Writer, drawing_id: DrawingId) -> ProgressOut:
    """Stops the pipeline at the next stage boundary and gives the quota back; the files stay (01 §4.6)."""
    try:
        coordinator.cancel(actor.session, actor.tenant_id, drawing_id)
    except LookupError as e:
        raise ApiError(404, "not_found") from e
    except coordinator.DrawingFinishedError as e:
        raise ApiError(409, "drawing_finished") from e
    actor.session.flush()
    return _progress_out(actor, request.app.state.storage, drawing_id)


@router.post("/drawings/{drawing_id}/confirm")
def confirm(request: Request, background: BackgroundTasks, actor: Writer, drawing_id: DrawingId) -> ProgressOut:
    """The user confirmed the pages (01 §5.6, "אשר והמשך"): decoding goes on from stage 2."""
    try:
        message = coordinator.confirm(actor.session, actor.tenant_id, drawing_id)
    except LookupError as e:
        raise ApiError(404, "not_found") from e
    except coordinator.NotAwaitingError as e:
        raise ApiError(409, "not_awaiting_confirmation") from e
    actor.session.flush()
    background.add_task(request.app.state.queue.send, message)  # after the commit
    return _progress_out(actor, request.app.state.storage, drawing_id)


@router.patch("/drawings/{drawing_id}/pages/{page_id}")
def change_page_kind(
    request: Request,
    background: BackgroundTasks,
    actor: Writer,
    drawing_id: DrawingId,
    page_id: Annotated[str, Path(pattern=r"^pg_[0-9A-Z]{26}$")],
    body: PageKindIn,
) -> ProgressOut:
    """The user changes a page's kind (01 §5.6). A changed route on a finished drawing runs stages 2–7 again."""
    storage: Storage = request.app.state.storage
    try:
        change = corrections.change_page_kind(
            actor.session, storage, actor.tenant_id, actor.user_id, drawing_id, page_id, body.page_kind
        )
    except LookupError as e:
        raise ApiError(404, "not_found") from e
    except coordinator.DrawingFinishedError as e:
        raise ApiError(409, "drawing_finished") from e
    except coordinator.DrawingBusyError as e:
        raise ApiError(409, "drawing_busy") from e
    actor.session.flush()
    if change.message is not None:
        background.add_task(request.app.state.queue.send, change.message)  # after the commit
    return _progress_out(actor, storage, drawing_id)


def _progress_out(actor: Actor, storage: Storage, drawing_id: str) -> ProgressOut:
    p = drawings.progress(actor.session, actor.tenant_id, drawing_id)
    if p is None:
        raise ApiError(404, "not_found")
    d = p.drawing
    q = d.quota or {}
    statuses = {r.stage: r.status for r in p.runs}
    ready = d.status == "ready"
    classified = d.status in ("ready", "awaiting_confirmation")
    errors = [i for i in d.issues if i.get("severity") == "error" and i.get("message")]
    failed = errors[0]["message"] if errors else None
    stage_1 = [i for i in d.issues if i.get("stage") == 1 and i.get("message") and i.get("severity") != "error"]
    reasons: list[Any] = next((i["reasons"] for i in d.issues if i.get("code") == "needs_confirmation"), [])
    routes = [page.route or "process" for page, _ in p.pages]
    return ProgressOut(
        drawing_id=d.id,
        name=p.name,
        status=d.status,  # type: ignore[arg-type]
        current_stage=d.current_stage,
        progress=d.progress,
        counted_as=q.get("reason", "new_drawing"),
        counted=bool(q.get("counted")),
        files=[ProgressFileOut(name=f.original_name, page_count=f.page_count) for f in p.files],
        stages=[
            StageOut(
                stage=n,
                name=NAMES[n],
                status=statuses.get(n, "queued"),  # type: ignore[arg-type]
                summary=drawings.stage_summary(p, n) if statuses.get(n) == "done" else None,
            )
            for n in range(1, 8)
        ],
        quote_id=p.quote_id if ready else None,
        error=failed if d.status == "failed" else None,
        summary=ProgressSummaryOut(
            input_kind=d.input_kind,
            panels=p.panels,
            page_count=len(p.pages),
            pages_by_route={r: routes.count(r) for r in ("process", "context", "skip")},
            products=0,
            priced=0,
            findings=0,
        )
        if ready
        else None,
        pages=[
            ProgressPageOut(
                page_id=page.id,
                page_no=page.page_no,
                file_name=file_name,
                route=page.route,  # type: ignore[arg-type]
                page_kind=page.page_kind,  # type: ignore[arg-type]
                page_kind_confidence=page.page_kind_confidence,
                classified_by=page.classified_by,  # type: ignore[arg-type]
                unsure=page.classified_by != "user" and (page.page_kind_confidence or 0) < CONFIRM_THRESHOLD,
                thumbnail_url=storage.presigned_get(actor.tenant_id, page.render_key) if page.render_key else None,
            )
            for page, file_name in p.pages
        ]
        if classified
        else [],
        confirmation_reasons=reasons if d.status == "awaiting_confirmation" else [],
        notices=[
            NoticeOut(code=i["code"], severity=i["severity"], page_id=i.get("page_id"), message=i["message"])
            for i in stage_1
        ]
        if classified
        else [],
    )
