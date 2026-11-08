"""Uploads and their pipeline runs: the new-quote screen (01 §4.6, prototype `vNew`)."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Query, Request, UploadFile, status

from konboro.domain.flags import LIVE_RUN, is_enabled
from konboro.domain.permissions import Permission
from konboro.pipeline import coordinator
from konboro.pipeline.bom.table import BomTable, items
from konboro.pipeline.intake import corrections
from konboro.pipeline.intake.routing import CONFIRM_THRESHOLD
from konboro.pipeline.stages import NAMES
from konboro.pipeline.stages.s1_intake import thumbnail_key
from konboro.services import drawings, onboarding, quota, run_estimate, run_live
from konboro.services.intake import MB, Limits, check_upload
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import (
    BomColumnOut,
    BomColumnsIn,
    BomTableOut,
    CheckOut,
    EstimateOut,
    LiveMessageOut,
    LiveModelOut,
    LiveOut,
    LiveStageOut,
    LiveViewOut,
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
    if onboarding.required(actor.session, actor.tenant_id):  # the data terms come first (10 §5.1)
        raise ApiError(409, "data_terms_required")
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
    onboarding.note_drawing(actor.session, actor.tenant_id)
    # After the commit (the tenant transaction ends with this function), so the worker finds the rows.
    message = StageMessage(drawing_id=d.id, tenant_id=d.tenant_id, stage=1, trace_id=str(d.trace_id))
    queue: Queue = request.app.state.queue
    background.add_task(queue.send, message)
    return UploadOut(drawing_id=d.id, status=d.status, files=[_file_out(f) for f in new.files], counted_as=new.reason)


@router.post("/drawings/check", dependencies=[Depends(require_flag(LIVE_RUN))])
def check(
    request: Request,
    actor: Writer,
    files: Annotated[list[UploadFile], File(description="The files the user picked")],
    purpose: Annotated[Literal["quote", "audit"], Form()] = "quote",
) -> CheckOut:
    """The upload's checks and the start bar's estimate before "התחל פענוח" (01 §4.6 item 4, S28c decision 1): the
    page count, the rejections, the expected time and cost by page count and size. Nothing is stored or counted."""
    received = [(f.filename or "file", f.file.read(_READ_LIMIT)) for f in files]
    result = check_upload(received, drawings.limits_for(actor.session, actor.tenant_id))
    estimate = None
    if result.ok:
        sizes = [size for f in result.files for size in f.page_sizes_pt]
        units = run_estimate.units_before(sizes, result.total_pages)
        stages = [1, 2, 3, 4, 8] if purpose == "audit" else [*range(1, 8)]
        rates = run_estimate.rates(actor.session, actor.tenant_id)
        found = run_estimate.estimate(stages, units, rates)
        estimate = EstimateOut(pages=result.total_pages, seconds=round(found.seconds), cost_usd=found.usd)
    return CheckOut(
        files=[_file_out(f) for f in result.files], error=result.error, message=result.message, estimate=estimate
    )


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
def get_progress(
    request: Request,
    actor: Reader,
    drawing_id: DrawingId,
    shown_left: Annotated[int | None, Query(ge=0, description="The time left the screen shows now (live_run)")] = None,
) -> ProgressOut:
    """Polled every second by the new-quote screen (S05 decision), every two with `live_run` (01 §4.6)."""
    return _progress_out(actor, request.app.state.storage, drawing_id, shown_left)


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
    """The user confirmed the pages (01 §5.6, "אשר והמשך"): decoding goes on from stage 2. A BOM column mapping they
    were shown is settled with it, and one with no item or no quantity column is refused (S14 decision 1)."""
    try:
        corrections.settle_bom_mappings(actor.session, request.app.state.storage, actor.tenant_id, drawing_id)
        message = coordinator.confirm(actor.session, actor.tenant_id, drawing_id)
    except LookupError as e:
        raise ApiError(404, "not_found") from e
    except coordinator.NotAwaitingError as e:
        raise ApiError(409, "not_awaiting_confirmation") from e
    except corrections.BomMappingIncompleteError as e:
        raise ApiError(409, "bom_mapping_incomplete") from e
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


@router.put(
    "/drawings/{drawing_id}/pages/{page_id}/bom-columns", dependencies=[Depends(require_flag("bom_column_mapping"))]
)
def set_bom_columns(
    request: Request,
    background: BackgroundTasks,
    actor: Writer,
    drawing_id: DrawingId,
    page_id: Annotated[str, Path(pattern=r"^pg_[0-9A-Z]{26}$")],
    body: BomColumnsIn,
) -> ProgressOut:
    """The user sets the roles of a BOM spreadsheet's columns (01 §5.8, S14 decision 1). On a finished drawing
    stages 2–7 run again."""
    storage: Storage = request.app.state.storage
    roles = {c.index: c.role for c in body.columns}
    try:
        change = corrections.set_bom_columns(
            actor.session, storage, actor.tenant_id, actor.user_id, drawing_id, page_id, roles
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


SAMPLES = 2


def _bom_out(table: BomTable) -> BomTableOut:
    return BomTableOut(
        source=table.source,
        sheet=table.sheet,
        mapping_sure=table.mapping_sure,
        columns=[
            BomColumnOut(
                index=c.index,
                letter=c.letter,
                header=c.header,
                role=c.role,
                by=c.by,
                samples=[x for r in table.rows if c.index < len(r.cells) and (x := r.cells[c.index])][:SAMPLES],
            )
            for c in table.columns
        ],
        rows=len(items(table)),
    )


def _live_out(actor: Actor, storage: Storage, p: drawings.Progress, shown_left: int | None) -> LiveOut:
    x = run_live.live(actor.session, storage, p, shown_left=shown_left)
    return LiveOut(
        started_at=x.started_at,
        elapsed_s=x.elapsed_s,
        seconds_left=x.seconds_left,
        seconds_expected=x.seconds_expected,
        fraction=x.fraction,
        cost_usd=x.cost_usd,
        cost_estimate_usd=x.cost_estimate_usd,
        cost_per_page_usd=x.cost_per_page_usd,
        stages=[
            LiveStageOut(
                stage=st.stage,
                seconds=st.seconds,
                cost_usd=st.cost_usd,
                calls=st.calls,
                models=[LiveModelOut(label=k, calls=v) for k, v in st.models.items()],
            )
            for st in x.stages
        ],
        messages=[LiveMessageOut(stage=msg.stage, text=msg.text, at_s=msg.at_s) for msg in x.messages],
        counters=x.counters,
        view=LiveViewOut(
            page_id=x.view.page_id,
            page_no=x.view.page_no,
            image_url=x.view.image_url,
            size=x.view.size,
            boxes=x.view.boxes,
        )
        if x.view
        else None,
    )


def _progress_out(actor: Actor, storage: Storage, drawing_id: str, shown_left: int | None = None) -> ProgressOut:
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
            for n in drawings.stage_numbers(p)
        ],
        quote_id=p.quote_id if ready else None,
        audit_id=p.audit.id if p.audit else None,
        error=failed if d.status == "failed" else None,
        summary=ProgressSummaryOut(
            input_kind=d.input_kind,
            panels=p.panels,
            page_count=len(p.pages),
            pages_by_route={r: routes.count(r) for r in ("process", "context", "skip")},
            products=p.lines[0],
            priced=p.lines[1],
            findings=p.findings,
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
                # stage 2 points `render_key` at the full render; the thumbnail stays where stage 1 put it (BUG-023)
                thumbnail_url=storage.presigned_get(
                    actor.tenant_id, thumbnail_key(actor.tenant_id, drawing_id, page.id)
                )
                if page.render_key
                else None,
                bom=_bom_out(p.bom[page.id]) if page.id in p.bom else None,
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
        live=_live_out(actor, storage, p, shown_left) if is_enabled(actor.flags, LIVE_RUN) else None,
    )
