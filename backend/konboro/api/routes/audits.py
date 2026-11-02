"""The quote audit (11): upload a drawing with its existing quote, read the audit, decide each difference, and turn
it into a corrected quote. Every route is behind `quote_audit` (13 §3; S15). The screen is S16's."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Request, UploadFile, status

from konboro.db import models as m
from konboro.domain.permissions import Permission
from konboro.pipeline.audit.differences import SHOWN_FROM
from konboro.services import audits, drawings, quota
from konboro.services.queue import Queue, StageMessage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import (
    AuditDecisionIn,
    AuditDifferenceOut,
    AuditLineOut,
    AuditOut,
    AuditUploadOut,
    CorrectedQuoteOut,
)
from .drawings import _READ_LIMIT, _file_out

FLAG = "quote_audit"

router = APIRouter(tags=["audits"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(FLAG))])

Writer = Annotated[Actor, Depends(require(Permission.DRAWINGS_WRITE))]
Reader = Annotated[Actor, Depends(require(Permission.DRAWINGS_READ))]
AuditId = Annotated[str, Path(pattern=r"^aud_[0-9A-Z]{26}$")]
DiffId = Annotated[str, Path(pattern=r"^dif_[0-9A-Z]{26}$")]


@router.post("/audits", status_code=status.HTTP_201_CREATED)
def upload_audit(
    request: Request,
    background: BackgroundTasks,
    actor: Writer,
    files: Annotated[list[UploadFile], File(description="The drawing: PDF, images, XLSX, CSV or ZIP")],
    quote: Annotated[UploadFile, File(description="The existing quote: PDF, image, XLSX or CSV (11 §4)")],
    customer: Annotated[str | None, Form(max_length=200)] = None,
    project: Annotated[str | None, Form(max_length=200)] = None,
) -> AuditUploadOut:
    """The drawing is checked as any upload is (01 §4.3), the quote as one more file. Stages 1–4 run, then the
    audit step (S15 decision 2)."""
    received = [(f.filename or "file", f.file.read(_READ_LIMIT)) for f in files]
    quote_file = (quote.filename or "quote", quote.file.read(_READ_LIMIT))
    try:
        new = drawings.create_upload(
            actor.session,
            request.app.state.storage,
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            files=received,
            customer_name=customer,
            project_name=project,
            audited_quote=quote_file,
        )
    except quota.QuotaReachedError as e:
        raise ApiError(403, "quota_reached") from e
    except drawings.UploadRejectedError as e:
        check = e.check
        details = [_file_out(f).model_dump() for f in check.files]
        if check.error:
            details.insert(0, {"code": check.error, "message": check.message})
        raise ApiError(422, "upload_rejected", details) from e

    d = new.drawing
    assert new.audit is not None and new.quote_file is not None  # noqa: S101
    message = StageMessage(drawing_id=d.id, tenant_id=d.tenant_id, stage=1, trace_id=str(d.trace_id))
    queue: Queue = request.app.state.queue
    background.add_task(queue.send, message)
    return AuditUploadOut(
        audit_id=new.audit.id,
        drawing_id=d.id,
        status=d.status,
        files=[_file_out(f) for f in new.files],
        quote_file=_file_out(new.quote_file),
        counted_as="audit",
    )


@router.get("/audits/{audit_id}")
def get_audit(actor: Reader, audit_id: AuditId) -> AuditOut:
    """Another tenant's audit is 404, the same as one that does not exist."""
    view = audits.read_audit(actor.session, actor.tenant_id, audit_id)
    if view is None:
        raise ApiError(404, "not_found")
    a = view.audit
    ready = a.status == "ready"
    project = actor.session.get(m.Project, view.drawing.project_id) if view.drawing.project_id else None
    name = (project.name if project else "") or (view.quote_file.original_name if view.quote_file else a.drawing_id)
    return AuditOut(
        audit_id=a.id,
        drawing_id=a.drawing_id,
        status=a.status,  # type: ignore[arg-type]
        drawing_status=view.drawing.status,
        drawing_name=name,
        quote_file_name=view.quote_file.original_name if view.quote_file else None,
        input_kind=a.input_kind,
        quote_ref=a.quote_ref if ready else None,  # type: ignore[arg-type]
        summary=a.summary if ready else None,  # type: ignore[arg-type]
        issues=[str(i) for i in a.issues],
        lines=[_line(ln) for ln in view.lines],
        differences=[_difference(d) for d in view.differences],
        corrected_quote_id=a.corrected_quote_id,
    )


@router.patch("/audits/{audit_id}/differences/{diff_id}")
def decide(actor: Writer, audit_id: AuditId, diff_id: DiffId, body: AuditDecisionIn) -> AuditDifferenceOut:
    diff = audits.decide(
        actor.session,
        actor.tenant_id,
        audit_id,
        diff_id,
        actor.user_id,
        body.status,
        body.reject_reason,
        body.note,
    )
    if diff is None:
        raise ApiError(404, "not_found")
    return _difference(diff)


@router.post("/audits/{audit_id}/corrected-quote")
def corrected_quote(actor: Writer, audit_id: AuditId) -> CorrectedQuoteOut:
    """11 §8: the quote's lines and the confirmed differences, as a quote in the system. Asked again, the same one."""
    try:
        made = audits.corrected_quote(actor.session, actor.tenant_id, audit_id)
    except audits.AuditNotReadyError as e:
        raise ApiError(409, "audit_not_ready") from e
    if made is None:
        raise ApiError(404, "not_found")
    quote_id, created = made
    return CorrectedQuoteOut(quote_id=quote_id, created=created)


def _line(ln: m.AuditQuoteLine) -> AuditLineOut:
    sig: dict[str, Any] = ln.signature or {}
    return AuditLineOut(
        index=ln.line_index,
        description=ln.description,
        qty=ln.qty,
        unit_price=ln.unit_price,
        total=ln.line_total,
        confidence=ln.confidence,
        page_no=ln.page_no,
        status=ln.status,  # type: ignore[arg-type]
        includes=[i["text"] for i in sig.get("included", [])],
        component_ids=list(ln.component_ids),
        matched_qty=ln.matched_qty,
    )


def _difference(d: m.AuditDifference) -> AuditDifferenceOut:
    return AuditDifferenceOut(
        diff_id=d.id,
        type=d.type,  # type: ignore[arg-type]
        severity=d.severity,  # type: ignore[arg-type]
        confidence=d.confidence,
        shown=d.confidence >= SHOWN_FROM,
        family=d.family,
        designators=list(d.designators),
        drawing_qty=d.drawing_qty,
        quote_qty=d.quote_qty,
        quote_line_index=d.quote_line_index,
        evidence=d.evidence,
        suggested_line=d.suggested_line,  # type: ignore[arg-type]
        message=d.message,
        amount=d.amount,
        status=d.status,  # type: ignore[arg-type]
        reject_reason=d.reject_reason,  # type: ignore[arg-type]
        reject_note=d.reject_note,
        component_ids=list(d.component_ids),
    )
