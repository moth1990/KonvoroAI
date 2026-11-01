"""Stage 1 (01): intake and page classification.

For every page, in this order:
1. Read it in code: size, rotation, content hash, text layer, drawing operations (01 §5.1–5.2).
2. Check it in code: geometry and text source, and for pictures readability; a blurry page stops the whole
   drawing within seconds and the upload doesn't count (01 §5.3, §4.5).
3. Classify it: the same page already classified in this tenant is reused (01 §5.1, §11); a saved factory
   template is matched without a model (01 §5.7); anything else goes to `page_classification` (01 §5.4), which
   code checks afterwards.
Then for the drawing: the title block, read once from a crop of the region the classifier found (S08 decision);
routing (01 §7); the panels; context from non-diagram pages and from notes and feed regions (01 §5.5); the input
kind (01 §4.4); whether a marked new version is one (01 §4.5); and whether the user must confirm (01 §5.6).

The thumbnail key is the one S05 introduced: `pages/{page_id}/thumb.png`.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from PIL import Image
from sqlalchemy import select

from konboro.contracts.common import StageIssue
from konboro.contracts.intake import (
    ContextArtifact,
    IntakeResult,
    Page,
    PageKind,
    PagePanel,
    Panel,
    QuotaOutcome,
    Region,
    SourceFile,
    TitleBlock,
)
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.services.storage import drawing_key
from konboro_llm import ImageInput
from konboro_llm.stages import context_extraction, page_classification

from ..context import StageContext
from ..intake import checks, classify, routing, templates
from ..intake.drawing import PagePanels, input_kind, is_revision, merge_panels, name_key
from ..intake.pages import PageRead, png, read_pages, render

log = logging.getLogger("konboro.pipeline.s1")

THUMB_PX = 300  # the longer side
OVERVIEW_PX = 1024  # what the classifier sees (01 §5.4)
DETAIL_PX = 1568  # title blocks, data sheets and regions, read for their text
REGION_MARGIN = 0.01  # a crop keeps this much of the page around the region
CLASSIFY_WORKERS = 4  # pages classified at the same time (01 §9)
CONTEXT_PAGE_KINDS = ("technical_data", "panel_front_view", "general_notes")
CONTEXT_REGION_KINDS = ("notes_block", "feed_diagram")
TEMPLATE_CONFIDENCE = 1.0

ISSUE_MESSAGES = {
    "blurry": "עמוד {page} לא קריא. העלו את ה-PDF המקורי במקום צילום.",
    "low_resolution": "עמוד {page} ברזולוציה נמוכה. ייתכנו טעויות בקריאת הטקסט.",
    "cropped": "נראה שחלק מעמוד {page} חסר.",
    "no_diagram_pages": "לא מצאנו תוכנית חד-קווית. בדקו את הסיווג.",
    "drawing_not_final": "השרטוט מסומן 'לעיון'. ייתכנו שינויים לפני הביצוע.",
    "revision_counted_as_new": "השרטוט שונה מהגרסה הקודמת, ולכן ייספר כהצעה חדשה.",
}


def thumbnail_key(tenant_id: str, drawing_id: str, page_id: str) -> str:
    return drawing_key(tenant_id, drawing_id, "pages", page_id, "thumb.png")


@dataclass
class Work:
    """One page on its way through the stage."""

    page_id: str
    file: m.DrawingFile
    page_no: int
    read: PageRead | None  # None for a spreadsheet's sheet
    data: bytes = b""
    sha256: str | None = None
    size_pt: tuple[float, float] = (0.0, 0.0)
    rotation: int = 0
    geometry: checks.GeometrySource | None = None
    text: checks.TextSource | None = None
    quality: checks.Quality = "ok"
    overview: bytes | None = None
    fingerprint: str | None = None
    kind: PageKind = "other"
    confidence: float = 0.0
    classified_by: str = "model"
    model: str | None = None
    labels: str = "not_applicable"
    panels: list[classify.FoundPanel] = field(default_factory=list)
    regions: list[classify.FoundRegion] = field(default_factory=list)
    title_block: TitleBlock | None = None
    reused_from: str | None = None
    template: templates.Template | None = None
    artifacts: list[ContextArtifact] = field(default_factory=list)

    def key(self, *parts: object) -> str:
        """A stable image key for cassettes: content hash plus how it was rendered (konboro_llm.ImageInput)."""
        return ":".join(str(p) for p in (self.sha256, self.read.extra_rotation if self.read else 0, *parts))

    def image(self, long_side: int, crop: tuple[float, float, float, float] | None = None) -> bytes:
        assert self.read is not None  # noqa: S101
        return png(render(self.read, self.data, long_side, crop))


def _issue(code: str, severity: str, page: Work | None = None) -> StageIssue:
    message = ISSUE_MESSAGES[code].format(page=page.page_no if page else "")
    return StageIssue(code=code, severity=severity, page_id=page.page_id if page else None, message=message)  # type: ignore[arg-type]


def _read(ctx: StageContext, files: list[m.DrawingFile]) -> list[Work]:
    works: list[Work] = []
    for f in files:
        if f.detected_format in ("xlsx", "csv"):
            # A spreadsheet is a BOM table by its nature (01 §4.2): code decides, no model. Its import is S14.
            for n in range(1, (f.page_count or 1) + 1):
                works.append(Work(new_id("pg"), f, n, None, sha256=f"{f.sha256}:{n}", kind="bom_table", confidence=1.0))
            continue
        data = ctx.storage.get(ctx.tenant_id, f.storage_key)
        for read in read_pages(f.id, f.detected_format, data):
            read.extra_rotation = checks.text_rotation(read)
            works.append(Work(new_id("pg"), f, read.page_no, read, data=data, sha256=read.sha256))
    return works


def _check(ctx: StageContext, w: Work) -> None:
    """Code checks, the thumbnail and the classifier's image. A blurry picture is found here, before any model."""
    assert w.read is not None  # noqa: S101
    w.geometry = checks.geometry_source(w.read)
    w.text = checks.text_source(w.read)
    if checks.garbage_ratio(w.read.text) > checks.GARBAGE_RATIO:
        log.info("page %s: garbled text layer, read by OCR (garbled_text)", w.page_id)
    overview = render(w.read, w.data, OVERVIEW_PX)
    w.quality = checks.quality(w.read, w.geometry, overview).quality
    w.overview = png(overview)
    w.fingerprint = templates.fingerprint(overview)
    w.rotation = (w.read.rotation + w.read.extra_rotation) % 360
    w.size_pt = classify.turned_size(w.read.size_pt, w.read.extra_rotation)
    _store_thumbnail(ctx, w, overview)


def _store_thumbnail(ctx: StageContext, w: Work, image: Image.Image) -> None:
    thumb = image.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX))
    ctx.storage.put(ctx.tenant_id, thumbnail_key(ctx.tenant_id, ctx.drawing.id, w.page_id), png(thumb), "image/png")


def _reuse(ctx: StageContext, works: list[Work]) -> None:
    """The same page, classified before in this tenant, keeps that classification (01 §5.1). RLS limits the query
    to this tenant, and the explicit filter says so too (01 §11)."""
    s = ctx.session
    for w in works:
        if w.read is None or w.sha256 is None:
            continue
        prev = s.scalars(
            select(m.Page)
            .where(
                m.Page.tenant_id == ctx.tenant_id,
                m.Page.sha256 == w.sha256,
                m.Page.drawing_id != ctx.drawing.id,
                m.Page.page_kind.is_not(None),
            )
            .order_by(m.Page.created_at.desc())
            .limit(1)
        ).first()
        if prev is None:
            continue
        w.kind, w.confidence = prev.page_kind, prev.page_kind_confidence or 0.0  # type: ignore[assignment]
        w.classified_by, w.model, w.reused_from = "reused", prev.model, prev.id
        w.title_block = TitleBlock.model_validate(prev.title_block) if prev.title_block else None
        w.labels = prev.component_labels or "not_applicable"
        w.panels, w.regions = classify.from_stored(prev.regions)
        for art in s.scalars(select(m.ContextArtifact).where(m.ContextArtifact.page_id == prev.id)):
            w.artifacts.append(
                ContextArtifact(
                    artifact_id=new_id("ctx"),
                    page_id=w.page_id,
                    kind=art.kind,
                    format=art.format,  # type: ignore[arg-type]
                    content=art.content,
                )
            )


def _saved_templates(ctx: StageContext) -> list[templates.Template]:
    rows = ctx.session.scalars(select(m.PageTemplate).where(m.PageTemplate.tenant_id == ctx.tenant_id)).all()
    return [
        templates.Template(r.id, r.producer, r.page_kind, r.fingerprint, tuple(r.mask) if r.mask else None)  # type: ignore[arg-type]
        for r in rows
    ]


def _match_templates(works: list[Work], saved: list[templates.Template]) -> None:
    for w in works:
        if w.classified_by != "model" or w.fingerprint is None or w.read is None:
            continue
        found = templates.best_match(w.fingerprint, saved)
        if found is not None:
            w.template = found[0]
            w.kind, w.confidence, w.classified_by, w.model = found[0].page_kind, TEMPLATE_CONFIDENCE, "template", None  # type: ignore[assignment]


def _classify(ctx: StageContext, works: list[Work], total: int) -> None:
    def one(w: Work) -> tuple[Work, Any]:
        assert w.overview is not None and w.read is not None  # noqa: S101
        excerpt = w.read.text if w.text != "ocr" else ""
        image = ImageInput(w.overview, key=w.key(OVERVIEW_PX))
        result = page_classification.classify_page(
            ctx.llm, image, w.page_no, total, w.file.original_name, excerpt, tenant_id=ctx.tenant_id
        )
        return w, result

    todo = [w for w in works if w.read is not None and w.classified_by == "model"]
    with ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as pool:
        for w, result in pool.map(one, todo):
            checked = classify.check(result.data, w.size_pt)
            if checked.orientation:
                assert w.read is not None  # noqa: S101
                w.read.extra_rotation = (w.read.extra_rotation + checked.orientation) % 360
                w.rotation = (w.read.rotation + w.read.extra_rotation) % 360
                w.size_pt = classify.turned_size(w.size_pt, checked.orientation)
                _store_thumbnail(ctx, w, render(w.read, w.data, THUMB_PX))
            w.kind, w.confidence, w.model = checked.page_kind, checked.confidence, result.model
            w.labels, w.panels, w.regions, w.title_block = (
                checked.component_labels,
                checked.panels,
                checked.regions,
                checked.title_block,
            )
            if checked.dropped:
                log.info("page %s: %s boxes dropped by the answer check", w.page_id, checked.dropped)


def _fraction(w: Work, bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """A box in points on the upright page, as fractions of the page as the renderer sees it (before the
    classifier's turn), with a margin."""
    w_pt, h_pt = w.size_pt
    x0, y0, x1, y1 = bbox[0] / w_pt, bbox[1] / h_pt, bbox[2] / w_pt, bbox[3] / h_pt
    turn = w.read.extra_rotation if w.read else 0  # the renderer turns the page after it crops
    for _ in range((turn % 360) // 90):  # undo one clockwise quarter turn at a time
        x0, y0, x1, y1 = y0, 1 - x1, y1, 1 - x0
    m_ = REGION_MARGIN
    return (max(0.0, x0 - m_), max(0.0, y0 - m_), min(1.0, x1 + m_), min(1.0, y1 + m_))


def _render_for(w: Work, crop: tuple[float, float, float, float] | None) -> ImageInput:
    """An image for a context call. The classifier's own turn is applied by the renderer."""
    assert w.read is not None  # noqa: S101
    data = w.image(DETAIL_PX, crop)
    rounded = None if crop is None else tuple(round(c, 3) for c in crop)
    return ImageInput(data, key=w.key(DETAIL_PX, rounded))


def _title_block(ctx: StageContext, works: list[Work]) -> TitleBlock | None:
    """Read once per drawing, from the sharpest view of the title block a page offers (S08 decision): a 1024 px
    overview of a large sheet can't show it. Falls back to what the classifier read on the page, and when the
    classifier boxed no title block on any page, to the first process page read whole at the detail size (BUG-014)."""
    candidates = [w for w in works if w.read is not None and w.classified_by in ("model", "reused")]
    candidates.sort(key=lambda w: (routing.route(w.kind, w.confidence) != "process", w.page_no))
    boxed = False
    for w in candidates:
        region = next((r for r in w.regions if r.region_kind == "title_block"), None)
        if region is None:
            continue
        boxed = True
        block = _read_title_block(ctx, w, _fraction(w, region.bbox))
        if block is not None:
            return block
    seen = next((w.title_block for w in candidates if w.title_block is not None), None)
    first = candidates[0] if candidates else None
    if seen is not None or boxed or first is None or routing.route(first.kind, first.confidence) != "process":
        return seen  # a BOM form's heading is the BOM route's to read (01 §5.8, S14)
    return _read_title_block(ctx, first, None)


def _read_title_block(ctx: StageContext, w: Work, crop: tuple[float, float, float, float] | None) -> TitleBlock | None:
    result = context_extraction.extract(ctx.llm, "title_block", _render_for(w, crop), tenant_id=ctx.tenant_id)
    return classify.title_block(result.data)  # type: ignore[arg-type]


def _check_templates(ctx: StageContext, works: list[Work], producer: str | None, total: int) -> None:
    """A template matched without a model counts only for the producer it came from (01 §5.7 item 3). For any
    other producer the page goes to the model after all."""
    wrong = [w for w in works if w.template is not None and w.template.producer != producer]
    for w in wrong:
        w.template, w.kind, w.confidence, w.classified_by = None, "other", 0.0, "model"
    if wrong:
        _classify(ctx, wrong, total)


def _save_templates(ctx: StageContext, works: list[Work], producer: str | None) -> None:
    """01 §5.7 item 1: a page the model is sure is a factory template becomes one."""
    for w in works:
        if w.kind != "factory_template" or w.classified_by != "model" or w.fingerprint is None:
            continue
        if w.confidence < routing.CONFIRM_THRESHOLD:
            continue
        templates.save(ctx.session, ctx.tenant_id, w.page_id, producer, w.fingerprint, _mask(w))


def _mask(w: Work) -> list[float] | None:
    region = next((r for r in w.regions if r.region_kind == "title_block"), None)
    if region is None or not w.size_pt[0]:
        return None
    wp, hp = w.size_pt
    return [region.bbox[0] / wp, region.bbox[1] / hp, region.bbox[2] / wp, region.bbox[3] / hp]


def _context(ctx: StageContext, works: list[Work], panel_ids: dict[str, str]) -> None:
    """01 §5.5: structured content for the stages after this one. Legends (S12) and BOM tables (S14) wait."""
    for w in works:
        if w.classified_by == "reused":
            w.artifacts = [_repointed(a, panel_ids) for a in w.artifacts]
        if w.read is None or w.classified_by == "reused":
            continue
        route = routing.route(w.kind, w.confidence, bool(w.panels))
        if route == "context" and w.kind in CONTEXT_PAGE_KINDS:
            result = context_extraction.extract(ctx.llm, w.kind, _render_for(w, None), tenant_id=ctx.tenant_id)  # type: ignore[arg-type]
            w.artifacts.append(_artifact(w, w.kind, result.data.model_dump(mode="json")))
        if route != "process":
            continue
        for r in w.regions:
            if r.region_kind not in CONTEXT_REGION_KINDS:
                continue
            result = context_extraction.extract(
                ctx.llm,
                r.region_kind,  # type: ignore[arg-type]
                _render_for(w, _fraction(w, r.bbox)),
                tenant_id=ctx.tenant_id,
            )
            content = result.data.model_dump(mode="json")
            if r.region_kind == "notes_block":
                ref = name_key(r.panel_ref) if r.panel_ref else None
                content = {"panel": r.panel_ref, "panel_id": panel_ids.get(ref) if ref else None, **content}
            w.artifacts.append(_artifact(w, r.region_kind, content))


def _repointed(a: ContextArtifact, panel_ids: dict[str, str]) -> ContextArtifact:
    """A notes block copied from an earlier drawing points at this drawing's panel of the same name."""
    if a.kind != "notes_block":
        return a
    content = json.loads(a.content)
    panel = content.get("panel")
    content["panel_id"] = panel_ids.get(name_key(panel)) if panel else None
    return a.model_copy(update={"content": json.dumps(content, ensure_ascii=False, sort_keys=True)})


def _artifact(w: Work, kind: str, content: dict[str, Any]) -> ContextArtifact:
    if kind == "general_notes":
        return ContextArtifact(
            artifact_id=new_id("ctx"), page_id=w.page_id, kind=kind, format="markdown", content=content["markdown"]
        )
    text = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return ContextArtifact(artifact_id=new_id("ctx"), page_id=w.page_id, kind=kind, format="json", content=text)


def _quota(
    ctx: StageContext, files: list[m.DrawingFile], works: list[Work], number: str | None
) -> tuple[QuotaOutcome, list[StageIssue]]:
    """01 §4.5. The coordinator moves the quota by this outcome when the stage commits."""
    s, d = ctx.session, ctx.drawing
    q = d.quota or {}
    issues: list[StageIssue] = []
    if d.revision_of:
        prev = s.get(m.Drawing, d.revision_of)
        prev_pages = set(s.scalars(select(m.Page.sha256).where(m.Page.drawing_id == d.revision_of)).all()) - {None}
        prev_number = (prev.title_block or {}).get("drawing_number") if prev else None
        if q.get("reason") == "revision" and not q.get("reservation_id"):
            if is_revision(prev_number, number, prev_pages, [w.sha256 for w in works if w.sha256]):  # type: ignore[arg-type]
                return QuotaOutcome(counted=False, reason="revision"), issues
            issues.append(_issue("revision_counted_as_new", "info"))
            return QuotaOutcome(counted=True, reason="new_drawing"), issues
    seen = set(
        s.scalars(
            select(m.DrawingFile.sha256)
            .join(m.StageRun, (m.StageRun.drawing_id == m.DrawingFile.drawing_id) & (m.StageRun.stage == 1))
            .where(
                m.DrawingFile.tenant_id == ctx.tenant_id,
                m.DrawingFile.drawing_id != d.id,
                m.StageRun.status == "done",
            )
        ).all()
    )
    if files and all(f.sha256 in seen for f in files):
        return QuotaOutcome(counted=False, reason="reuse"), issues
    return QuotaOutcome(counted=bool(q.get("reservation_id")), reason=q.get("reason", "new_drawing")), issues


def _auto_revision(ctx: StageContext, block: TitleBlock | None) -> None:
    """01 §5.1 item 6: an upload the user didn't mark, with the drawing number and project of an earlier drawing in
    this tenant, is linked to it. The quota is unchanged (S08 decision)."""
    s, drawing = ctx.session, ctx.drawing
    if drawing.revision_of or block is None or not block.drawing_number:
        return
    for prev in s.scalars(
        select(m.Drawing)
        .where(m.Drawing.id != drawing.id, m.Drawing.title_block.is_not(None))
        .order_by(m.Drawing.created_at.desc())
    ):
        tb = prev.title_block or {}
        if tb.get("drawing_number") == block.drawing_number and tb.get("project_name") == block.project_name:
            drawing.revision_of = prev.id
            return


def run(ctx: StageContext) -> IntakeResult:
    s, d = ctx.session, ctx.drawing
    files = list(s.scalars(select(m.DrawingFile).where(m.DrawingFile.drawing_id == d.id).order_by(m.DrawingFile.id)))
    works = _read(ctx, files)
    total = len(works)
    issues: list[StageIssue] = []

    for w in works:
        if w.read is not None:
            _check(ctx, w)
    blurry = [w for w in works if w.quality == "blurry"]
    if blurry:  # fail fast (01 §5.3): no model call, and the upload doesn't count (01 §4.5)
        issues = [_issue("blurry", "error", w) for w in blurry]
        return _result(ctx, files, works, [], issues, status="failed", block=None, quota=None)
    issues += [_issue(w.quality, "warning", w) for w in works if w.quality in ("low_resolution", "cropped")]

    _reuse(ctx, works)
    _match_templates(works, _saved_templates(ctx))
    _classify(ctx, works, total)
    block = _title_block(ctx, works)
    producer = templates.producer_key(block.designer if block else None)
    _check_templates(ctx, works, producer, total)
    _save_templates(ctx, works, producer)
    if block is not None and block.status == "for_info":
        issues.append(_issue("drawing_not_final", "warning"))
    _auto_revision(ctx, block)
    quota, quota_issues = _quota(ctx, files, works, block.drawing_number if block else None)
    issues += quota_issues
    return _result(ctx, files, works, issues, [], status="ready", block=block, quota=quota)


def _result(
    ctx: StageContext,
    files: list[m.DrawingFile],
    works: list[Work],
    issues: list[StageIssue],
    failed: list[StageIssue],
    *,
    status: str,
    block: TitleBlock | None,
    quota: QuotaOutcome | None,
) -> IntakeResult:
    s, d = ctx.session, ctx.drawing
    issues = failed or issues
    routes = {w.page_id: routing.route(w.kind, w.confidence, bool(w.panels)) for w in works}
    merged = (
        merge_panels(
            [
                PagePanels(w.page_id, routes[w.page_id], [(p.name, p.bbox, p.confidence) for p in w.panels])
                for w in works
            ],
            block.panel_name if block else None,
        )
        if status != "failed"
        else []
    )
    panel_ids = {name_key(p.name): new_id("pnl") for p in merged}
    if status != "failed":
        _context(ctx, works, panel_ids)

    page_rows: list[Page] = []
    for w in works:
        page_panels = []
        for p in w.panels:
            if routes[w.page_id] != "process":
                continue
            owner = next(
                (mp for mp in merged if w.page_id in mp.page_ids and list(p.bbox) in mp.bboxes.get(w.page_id, [])), None
            )
            if owner is not None:
                page_panels.append(
                    PagePanel(
                        panel_id=panel_ids[name_key(owner.name)], name=owner.name, bbox=p.bbox, confidence=p.confidence
                    )
                )
        regions = [Region(region_kind="panel", bbox=p.bbox, panel_ref=p.panel_id) for p in page_panels] + [
            Region(
                region_kind=r.region_kind,  # type: ignore[arg-type]
                bbox=r.bbox,
                panel_ref=panel_ids.get(name_key(r.panel_ref)) if r.panel_ref else None,
            )
            for r in w.regions
        ]
        page_rows.append(
            Page(
                page_id=w.page_id,
                file_id=w.file.id,
                page_no=w.page_no,
                sha256=w.sha256,
                reused_from=w.reused_from,
                size_pt=w.size_pt,
                rotation_applied=w.rotation,  # type: ignore[arg-type]
                geometry_source=w.geometry,
                text_source=w.text,
                quality=w.quality,
                page_kind=w.kind,
                page_kind_confidence=w.confidence,
                route=routes[w.page_id],
                panels=page_panels,
                regions=regions,
                title_block=w.title_block,
                context_artifact_ids=[a.artifact_id for a in w.artifacts],
                classified_by=w.classified_by,  # type: ignore[arg-type]
                model=w.model,
            )
        )
        s.add(
            m.Page(
                id=w.page_id,
                tenant_id=ctx.tenant_id,
                drawing_id=d.id,
                file_id=w.file.id,
                page_no=w.page_no,
                sha256=w.sha256,
                reused_from=w.reused_from,
                width_pt=w.size_pt[0] or None,
                height_pt=w.size_pt[1] or None,
                rotation_applied=w.rotation,
                geometry_source=w.geometry,
                text_source=w.text,
                quality=w.quality,
                page_kind=w.kind,
                page_kind_confidence=w.confidence,
                route=routes[w.page_id],
                classified_by=w.classified_by,
                model=w.model,
                component_labels=w.labels if w.classified_by in ("model", "reused") else None,
                title_block=w.title_block.model_dump(mode="json") if w.title_block else None,
                regions=classify.stored(w.panels, w.regions),
                render_key=thumbnail_key(ctx.tenant_id, d.id, w.page_id) if w.read is not None else None,
            )
        )
    s.flush()

    panels: list[Panel] = []
    for mp in merged:
        pid = panel_ids[name_key(mp.name)]
        s.add(
            m.Panel(
                id=pid,
                tenant_id=ctx.tenant_id,
                drawing_id=d.id,
                name=mp.name,
                page_ids=mp.page_ids,
                bboxes=mp.bboxes,
                confidence=mp.confidence,
            )
        )
        panels.append(Panel(panel_id=pid, name=mp.name, page_ids=mp.page_ids))
    artifacts = [a for w in works for a in w.artifacts]
    for a in artifacts:
        s.add(
            m.ContextArtifact(
                id=a.artifact_id,
                tenant_id=ctx.tenant_id,
                drawing_id=d.id,
                page_id=a.page_id,
                kind=a.kind,
                format=a.format,
                content=a.content,
            )
        )

    kinds = [w.kind for w in works]
    labels = [w.labels for w in works if routes[w.page_id] == "process" and w.labels != "not_applicable"]
    d.input_kind = input_kind([f.detected_format for f in files], kinds, labels)
    if status == "failed":
        d.input_kind = None
    d.title_block = block.model_dump(mode="json") if block else None
    reasons = (
        routing.confirmation_reasons(
            [routing.RoutedPage(w.kind, w.confidence, w.classified_by) for w in works], len(panels)
        )
        if status != "failed"
        else []
    )
    if "no_diagram_pages" in reasons:
        issues.append(_issue("no_diagram_pages", "warning"))
    needs_confirmation = bool(reasons)
    d.needs_confirmation = needs_confirmation
    d.issues = [
        *[i for i in d.issues if i.get("stage") != 1],
        *[{**i.model_dump(mode="json"), "stage": 1} for i in issues],
    ]
    if reasons:
        d.issues = [*d.issues, {"code": "needs_confirmation", "severity": "info", "stage": 1, "reasons": reasons}]
    final_status = status if status == "failed" else ("awaiting_confirmation" if needs_confirmation else "ready")
    return IntakeResult(
        drawing_id=d.id,
        tenant_id=ctx.tenant_id,
        project_id=d.project_id,
        status=final_status,  # type: ignore[arg-type]
        created_at=d.created_at or datetime.now(UTC),
        revision_of=d.revision_of,
        input_kind=d.input_kind,
        title_block=block,
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
        pages=page_rows,
        panels=panels,
        context_artifacts=artifacts,
        issues=issues,
        needs_confirmation=needs_confirmation,
        quota=quota,
        trace_id=ctx.trace_id,
    )
