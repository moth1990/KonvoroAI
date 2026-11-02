"""A new upload (01 §4.1–4.5): reserve the quota, check the files, store them, record the drawing.

Everything happens in the caller's tenant transaction. If a check fails, the caller raises and the transaction
rolls back: the reservation, the drawing and the file rows never existed, so a rejected upload leaves no quota
trace (01 §4.5: "not counted"). Stage 1 is queued only after the commit, by the caller.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db.ids import new_id
from konboro.db.models import Component, Customer, Drawing, DrawingFile, Page, Panel, Project, Quote, StageRun
from konboro.services import plan, quota
from konboro.services.intake import CheckedFile, Limits, UploadCheck, check_upload

__all__ = ["CheckedFile", "NewUpload", "RevisionNotFoundError", "UploadRejectedError", "create_upload"]
from konboro.services.storage import Storage, drawing_key

EXTENSIONS = {"pdf": "pdf", "png": "png", "jpg": "jpg", "webp": "webp", "heic": "heic", "xlsx": "xlsx", "csv": "csv"}


class UploadRejectedError(Exception):
    """At least one file failed a check (01 §4.3): nothing is processed."""

    def __init__(self, check: UploadCheck) -> None:
        super().__init__("upload rejected")
        self.check = check


class RevisionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class NewUpload:
    drawing: Drawing
    files: list[CheckedFile]
    reason: Literal["new_drawing", "revision"]


def _project(session: Session, tenant_id: str, customer_name: str | None, project_name: str | None) -> str | None:
    """Optional names from the form (01 §4.6 item 2). An existing customer with the same name is reused."""
    customer_name, project_name = (customer_name or "").strip(), (project_name or "").strip()
    if not customer_name and not project_name:
        return None
    customer_id = None
    if customer_name:
        customer_id = session.scalar(
            select(Customer.id).where(Customer.tenant_id == tenant_id, Customer.name == customer_name)
        )
        if customer_id is None:
            customer_id = new_id("cus")
            session.add(Customer(id=customer_id, tenant_id=tenant_id, name=customer_name))
            session.flush()
    project_id = new_id("prj")
    session.add(Project(id=project_id, tenant_id=tenant_id, customer_id=customer_id, name=project_name))
    session.flush()
    return project_id


def create_upload(
    session: Session,
    storage: Storage,
    *,
    tenant_id: str,
    user_id: str,
    files: list[tuple[str, bytes]],
    customer_name: str | None = None,
    project_name: str | None = None,
    revision_of: str | None = None,
) -> NewUpload:
    """Raises `quota.QuotaReachedError`, `UploadRejectedError` or `RevisionNotFoundError`; the caller rolls back."""
    drawing_id, trace_id = new_id("drw"), new_id("trc")
    previous = None
    if revision_of:
        previous = session.scalar(
            select(Drawing).where(Drawing.tenant_id == tenant_id, Drawing.id == revision_of, Drawing.purpose == "quote")
        )
        if previous is None:
            raise RevisionNotFoundError(revision_of)

    project_id = previous.project_id if previous else _project(session, tenant_id, customer_name, project_name)
    drawing = Drawing(
        id=drawing_id,
        tenant_id=tenant_id,
        project_id=project_id,
        revision_of=previous.id if previous else None,
        status="uploaded",
        progress=0,
        trace_id=trace_id,
        created_by=user_id,
    )
    session.add(drawing)
    session.flush()

    # 01 §4.3 check 1, the quota, before the files. A new version is trusted not to count until S08 can compare
    # title blocks and page hashes (S05 decision), so it reserves nothing.
    reason: Literal["new_drawing", "revision"] = "revision" if previous else "new_drawing"
    reservation_id = None
    if previous is None:
        reservation_id = quota.reserve(session, tenant_id, created_by=user_id, drawing_id=drawing_id)

    check = check_upload(files, Limits(max_pages_per_file=plan.max_pages_per_file(session, tenant_id)))
    if not check.ok:
        raise UploadRejectedError(check)

    for f in check.files:
        file_id = new_id("fil")
        # Stored under its id, never the uploaded name, so a crafted name can't shape the S3 key.
        key = drawing_key(tenant_id, drawing_id, "files", f"{file_id}.{EXTENSIONS.get(f.detected_format or '', 'bin')}")
        storage.put(tenant_id, key, f.data)
        session.add(
            DrawingFile(
                id=file_id,
                tenant_id=tenant_id,
                drawing_id=drawing_id,
                original_name=f.name,
                detected_format=f.detected_format,
                sha256=f.sha256,
                size_bytes=f.size_bytes,
                page_count=f.page_count,
                storage_key=key,
            )
        )
    for stage in range(1, 8):
        # Stage 1's message is sent once this transaction commits; the others when the stage before them ends.
        sent_at = datetime.now(UTC) if stage == 1 else None
        session.add(StageRun(tenant_id=tenant_id, drawing_id=drawing_id, stage=stage, status="queued", sent_at=sent_at))
    drawing.quota = {"counted": False, "reason": reason, "reservation_id": reservation_id, "quota_event_id": None}
    session.flush()
    return NewUpload(drawing, check.files, reason)


# --- reading a run back (GET /drawings/{id}/progress) -----------------------------------------------------------


def _count_text(n: int, one: str, many: str) -> str:
    return one if n == 1 else f"{n} {many}"


@dataclass(frozen=True)
class Progress:
    drawing: Drawing
    name: str
    files: list[DrawingFile]
    runs: list[StageRun]
    pages: list[tuple[Page, str]]  # with the file's original name
    panels: list[str]
    quote_id: str | None
    # stage 4's components in the panel: (devices, products, whether any has a tag); None before stage 4 ran
    components: tuple[int, int, bool] | None = None


def progress(session: Session, tenant_id: str, drawing_id: str) -> Progress | None:
    drawing = session.scalar(select(Drawing).where(Drawing.tenant_id == tenant_id, Drawing.id == drawing_id))
    if drawing is None:
        return None
    files = list(
        session.scalars(select(DrawingFile).where(DrawingFile.drawing_id == drawing_id).order_by(DrawingFile.id))
    )
    names = {f.id: f.original_name for f in files}
    runs = list(session.scalars(select(StageRun).where(StageRun.drawing_id == drawing_id).order_by(StageRun.stage)))
    pages = session.scalars(
        select(Page).where(Page.drawing_id == drawing_id).order_by(Page.file_id, Page.page_no)
    ).all()
    panels = list(session.scalars(select(Panel.name).where(Panel.drawing_id == drawing_id).order_by(Panel.id)))
    quote_id = session.scalar(select(Quote.id).where(Quote.drawing_id == drawing_id))
    project = session.get(Project, drawing.project_id) if drawing.project_id else None
    name = (project.name if project else "") or (files[0].original_name if files else drawing_id)
    rows = session.execute(
        select(Component.quantity, Component.designators).where(
            Component.drawing_id == drawing_id, Component.supply_scope == "in_panel"
        )
    ).all()
    components = (int(sum(q for q, _ in rows)), len(rows), any(t for _, t in rows))
    return Progress(
        drawing, name, files, runs, [(p, names.get(p.file_id, "")) for p in pages], panels, quote_id, components
    )


def stage_summary(p: Progress, stage: int) -> str | None:
    """Stages 1 to 4 are the real ones so far (prototype STAGES, lines 761–764)."""
    if stage == 2:
        return _extraction_summary(p)
    if stage == 3:
        return _symbols_summary(p)
    if stage == 4:
        return _merge_summary(p)
    if stage != 1:
        return None
    # "9 עמודים · 2 תבניות של המפעל · לוח אחד"; the templates part only when there are any
    parts = [_count_text(len(p.pages), "עמוד אחד", "עמודים")]
    factory = sum(1 for page, _ in p.pages if page.page_kind == "factory_template")
    if factory:
        parts.append(_count_text(factory, "תבנית אחת של המפעל", "תבניות של המפעל"))
    parts.append(_count_text(len(p.panels), "לוח אחד", "לוחות"))
    return " · ".join(parts)


def _extraction_summary(p: Progress) -> str:
    """ "שכבת טקסט חסרה, OCR על 6 עמודים · 58 אריחים": how the text was read, and the tiles that go on to detection
    (02 §2.6, the ones that are not blank)."""
    process = [page for page, _ in p.pages if page.route == "process"]
    by_ocr = [page for page in process if page.text_source in ("ocr", "mixed")]
    tiles = _count_text(sum(page.tile_count or 0 for page in process), "אריח אחד", "אריחים")
    if not by_ocr:
        return f"טקסט מהקובץ · {tiles}"
    layer = "חסרה" if all(page.text_source == "ocr" for page in process) else "חלקית"
    return f"שכבת טקסט {layer}, OCR על {_count_text(len(by_ocr), 'עמוד אחד', 'עמודים')} · {tiles}"


def _symbols_summary(p: Progress) -> str:
    """ "61 סימנים · 54 בזיהוי ישיר, 7 בהכרעת מודל": the prototype's "מהספרייה" is the similarity index (03 §3.3),
    which arrives in phase 4; until then the first look is the model's (S12)."""
    process = [page for page, _ in p.pages if page.route == "process"]
    total = sum(page.symbol_count or 0 for page in process)
    decided = sum(page.symbol_llm_count or 0 for page in process)
    symbols = _count_text(total, "סימן אחד", "סימנים")
    if not decided:
        return symbols
    return f"{symbols} · {total - decided} בזיהוי ישיר, {decided} בהכרעת מודל"


def _merge_summary(p: Progress) -> str | None:
    """ "איחוד לפי תגים: 44 מכשירים ב-13 מוצרים" (prototype line 764): the devices in the panel and the components
    they merged into; the tags part only when the drawing has tags (04 §5.8)."""
    if p.components is None:
        return None
    devices, products, tagged = p.components
    where = "במוצר אחד" if products == 1 else f"ב-{products} מוצרים"
    text = f"{_count_text(devices, 'מכשיר אחד', 'מכשירים')} {where}"
    return f"איחוד לפי תגים: {text}" if tagged else text


def revisable(session: Session, tenant_id: str, limit: int = 50) -> list[tuple[Drawing, Quote]]:
    """Finished quote drawings, newest first: what a "new version" can follow."""
    rows = session.execute(
        select(Drawing, Quote)
        .join(Quote, (Quote.tenant_id == Drawing.tenant_id) & (Quote.drawing_id == Drawing.id))
        .where(Drawing.tenant_id == tenant_id, Drawing.status == "ready", Drawing.purpose == "quote")
        .order_by(Drawing.updated_at.desc(), Drawing.id.desc())
        .limit(limit)
    ).all()
    return [(d, q) for d, q in rows]
