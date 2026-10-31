"""Stage 1 stub (01): pages, a thumbnail per page, one panel. Real classification arrives in S08.

What is real already: page sizes from the PDF, and a small thumbnail per page for the new-quote screen's done step
(S05 decision; S08 keeps the key). What is a placeholder: every drawing page is `other` → `process` (the routing
default of 01 §7), and BOM files are `bom_table` → `context`.
"""

import io
from datetime import UTC, datetime

import pypdfium2 as pdfium
from PIL import Image
from sqlalchemy import select

from konboro.contracts.intake import IntakeResult, Page, Panel, QuotaOutcome, SourceFile
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.services.storage import drawing_key

from ..context import StageContext

THUMB_PX = 300  # the longer side
MODEL = "stub-s05"


def thumbnail_key(tenant_id: str, drawing_id: str, page_id: str) -> str:
    return drawing_key(tenant_id, drawing_id, "pages", page_id, "thumb.png")


def _png(image: Image.Image) -> bytes:
    image.thumbnail((THUMB_PX, THUMB_PX))
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


PageImage = tuple[tuple[float, float], bytes | None]  # size in points, thumbnail PNG


def _pages_of(fmt: str, data: bytes) -> list[PageImage]:
    if fmt == "pdf":
        pdf = pdfium.PdfDocument(data)
        try:
            out: list[PageImage] = []
            for i in range(len(pdf)):
                page = pdf[i]
                w, h = page.get_size()
                out.append(((float(w), float(h)), _png(page.render(scale=THUMB_PX / max(w, h)).to_pil())))
            return out
        finally:
            pdf.close()
    if fmt in ("png", "jpg", "webp"):
        image = Image.open(io.BytesIO(data))
        w, h = image.size  # pixels; real DPI handling is S08's (01 §6.4)
        return [((float(w), float(h)), _png(image))]
    return [((0.0, 0.0), None)]  # heic needs a plugin until S08; xlsx/csv are tables, not pictures


def run(ctx: StageContext) -> IntakeResult:
    s, d = ctx.session, ctx.drawing
    files = s.scalars(select(m.DrawingFile).where(m.DrawingFile.drawing_id == d.id).order_by(m.DrawingFile.id)).all()
    pages: list[Page] = []
    for f in files:
        bom = f.detected_format in ("xlsx", "csv")
        rendered = (
            [((0.0, 0.0), None)] * (f.page_count or 1)
            if bom
            else _pages_of(f.detected_format, ctx.storage.get(ctx.tenant_id, f.storage_key))
        )
        for page_no, (size, thumb) in enumerate(rendered, start=1):
            page_id = new_id("pg")
            key = thumbnail_key(ctx.tenant_id, d.id, page_id) if thumb else None
            if thumb and key:
                ctx.storage.put(ctx.tenant_id, key, thumb, "image/png")
            page = Page(
                page_id=page_id,
                file_id=f.id,
                page_no=page_no,
                sha256=None,
                size_pt=size,
                geometry_source=None,
                text_source=None,
                quality="ok",
                page_kind="bom_table" if bom else "other",
                page_kind_confidence=0.0,
                route="context" if bom else "process",
                classified_by="model",
                model=MODEL,
            )
            pages.append(page)
            s.add(
                m.Page(
                    id=page_id,
                    tenant_id=ctx.tenant_id,
                    drawing_id=d.id,
                    file_id=f.id,
                    page_no=page_no,
                    width_pt=size[0] or None,
                    height_pt=size[1] or None,
                    quality=page.quality,
                    page_kind=page.page_kind,
                    page_kind_confidence=page.page_kind_confidence,
                    route=page.route,
                    classified_by=page.classified_by,
                    model=MODEL,
                    render_key=key,
                )
            )
    s.flush()

    process = [p.page_id for p in pages if p.route == "process"]
    panels: list[Panel] = []
    if process:
        project = s.get(m.Project, d.project_id) if d.project_id else None
        name = (project.name if project else "") or "לוח 1"
        panel_id = new_id("pnl")
        s.add(m.Panel(id=panel_id, tenant_id=ctx.tenant_id, drawing_id=d.id, name=name, page_ids=process))
        panels.append(Panel(panel_id=panel_id, name=name, page_ids=process))
    # 01 §4.4: spreadsheets only means a BOM-only request; otherwise a drawing. Telling a factory drawing from a
    # designer's plan needs the symbols (S08).
    d.input_kind = "bom_only" if all(f.detected_format in ("xlsx", "csv") for f in files) else "designer_plan"

    quota = d.quota or {}
    return IntakeResult(
        drawing_id=d.id,
        tenant_id=ctx.tenant_id,
        project_id=d.project_id,
        status="ready",
        created_at=d.created_at or datetime.now(UTC),
        revision_of=d.revision_of,
        input_kind=d.input_kind,  # type: ignore[arg-type]
        source_files=[
            SourceFile(
                file_id=f.id,
                original_name=f.original_name,
                detected_format=f.detected_format,  # type: ignore[arg-type]
                sha256=f.sha256,
                page_count=f.page_count or 0,
            )
            for f in files
        ],
        pages=pages,
        panels=panels,
        quota=QuotaOutcome(counted=bool(quota.get("reservation_id")), reason=quota.get("reason", "new_drawing")),
        trace_id=ctx.trace_id,
    )
