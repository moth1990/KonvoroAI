"""Stage 6 (06): the results of stages 1–5 checked as a whole. It flags, never fixes (06 §1).

Reads stage 1's panels and context (front views, notes, technical data, the feed diagram, the designer's BOM), stage
2's wire graphs and text spans, stage 4's components and instances and stage 5's matches; the rule pack (global, with
the factory's overrides) and the catalog's class for each chosen SKU. The rules and the BOM cross-check are code
(`pipeline/validation/`); the `validator_review` model takes one look at each panel with five components or more,
shown no price (06 §12), and code checks what it says.

The findings are written as `findings` rows on the drawing, with no quote version yet: stage 7 attaches them to the
version it makes (S21 decision 1), and the run step counts them as soon as this stage is done.
"""

import io
import logging

from PIL import Image
from sqlalchemy import delete, select

from konboro.contracts.extraction import ExtractionResult, PageExtraction
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.validation import Issue, ValidationResult
from konboro.db import models as m
from konboro_llm import ImageInput
from konboro_llm.stages import validator_review

from ..association import schemas
from ..context import StageContext
from ..detection.sheets import png
from ..validation import pack as pack_mod
from ..validation.agent import LONG_SIDE
from ..validation.engine import AgentCall, validate
from ..validation.model import PanelModel, build

log = logging.getLogger("konboro.pipeline.s6")


def classes(ctx: StageContext, matching: MatchingResult) -> dict[str, str]:
    """The catalog's class of each chosen SKU: an untyped "מפסק" that stage 5 typed by its current (05 §5.5.1)."""
    skus = sorted({x.chosen_sku for x in matching.matches if x.chosen_sku})
    if not skus:
        return {}
    rows = ctx.session.execute(
        select(m.CatalogItem.sku, m.CatalogItem.symbol_class).where(m.CatalogItem.sku.in_(skus))
    ).all()
    return {sku: cls for sku, cls in rows if cls}


def picture_for(
    ctx: StageContext, intake: IntakeResult, extraction: ExtractionResult, panel: PanelModel
) -> tuple[ImageInput, tuple[int, int], tuple[float, float], float, str] | None:
    """The panel's area on its first drawn page, its long side 1568 px (06 §6.4): (image, size, origin in points,
    points per pixel, page id)."""
    pages = {p.page_id: p for p in intake.pages}
    drawn: dict[str, PageExtraction] = {pe.page_id: pe for pe in extraction.pages if pe.render is not None}
    page_id = next((pid for pid in panel.page_ids if pid in drawn), None)
    if page_id is None:
        page_id = next((i.page_id for i in panel.instances if i.page_id in drawn), None)
    if page_id is None:
        return None
    pe, page = drawn[page_id], pages.get(page_id)
    render = pe.render
    assert render is not None  # noqa: S101
    box = next((pp.bbox for pp in page.panels if pp.panel_id == panel.panel_id), None) if page else None
    w_pt, h_pt = render.width_px / render.px_per_pt, render.height_px / render.px_per_pt
    x0, y0, x1, y1 = box or (0.0, 0.0, w_pt, h_pt)
    image = Image.open(io.BytesIO(ctx.storage.get(ctx.tenant_id, render.image_uri))).convert("RGB")
    crop = image.crop(
        (
            max(0, int(x0 * render.px_per_pt)),
            max(0, int(y0 * render.px_per_pt)),
            min(render.width_px, int(x1 * render.px_per_pt)),
            min(render.height_px, int(y1 * render.px_per_pt)),
        )
    )
    scale = LONG_SIDE / max(crop.size)
    if scale < 1:
        size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(size, Image.Resampling.LANCZOS)
    pt_per_px = (x1 - x0) / crop.width
    sha = page.sha256 if page and page.sha256 else page_id
    rotation = page.rotation_applied if page else 0
    key = f"{sha}:{rotation}:{render.dpi}:{round(x0)},{round(y0)},{round(x1)},{round(y1)}:review"
    return ImageInput(png(crop), key=key), crop.size, (x0, y0), pt_per_px, page_id


def write_findings(ctx: StageContext, result: ValidationResult, known_pages: set[str], known_panels: set[str]) -> None:
    """The drawing's stage-6 findings, replaced on every run (a rerun after a page moved, S08)."""
    s = ctx.session
    s.execute(
        delete(m.Finding).where(
            m.Finding.tenant_id == ctx.tenant_id,
            m.Finding.drawing_id == ctx.drawing.id,
            m.Finding.source.in_(("rule", "bom_crosscheck", "agent")),
        )
    )
    for i in result.issues:
        s.add(finding_row(ctx.tenant_id, ctx.drawing.id, i, known_pages, known_panels))
    s.flush()


def finding_row(tenant_id: str, drawing_id: str, i: Issue, pages: set[str], panels: set[str]) -> m.Finding:
    return m.Finding(
        id=i.issue_id,
        tenant_id=tenant_id,
        drawing_id=drawing_id,
        source=i.source,
        rule_id=i.rule_id,
        rule_version=i.rule_version,
        category=i.category,
        severity=i.severity,
        code=i.rule_id,
        panel_id=i.panel_id if i.panel_id in panels else None,
        component_ids=i.component_ids,
        instance_ids=i.instance_ids,
        page_id=i.page_id if i.page_id in pages else None,
        bbox=list(i.bbox) if i.bbox and i.page_id in pages else None,
        message=i.message,
        values={**i.values, "title": i.title},
        confidence=i.confidence,
        status=i.status,
    )


def run(ctx: StageContext) -> ValidationResult:
    intake = ctx.output(1, IntakeResult)
    extraction = ctx.output(2, ExtractionResult)
    merge = ctx.output(4, MergeResult)
    matching = ctx.output(5, MatchingResult)
    sch = schemas.load(ctx.session)
    pack = pack_mod.for_tenant(ctx.session, ctx.tenant_id)
    coverage = pack.rules.get("TEXT_COVERAGE_LOW")
    tags = tuple(coverage.params.get("tags", ("current_a",))) if coverage else ("current_a",)
    drawing = build(intake, merge, matching, sch, extraction, classes(ctx, matching), tags)

    def agent_for(panel: PanelModel) -> AgentCall:
        pic = picture_for(ctx, intake, extraction, panel)
        image, size, origin, scale, page_id = pic if pic else (None, None, (0.0, 0.0), 1.0, None)

        def look(name: str, components: str, tree: str, bom: str, findings: str) -> validator_review.ReviewAnswer:
            return validator_review.review(
                ctx.llm, name, components, tree, bom, findings, image, size, ctx.tenant_id
            ).data

        def to_points(b: list[float]) -> tuple[float, float, float, float]:
            ox, oy = origin
            return (ox + b[0] * scale, oy + b[1] * scale, ox + b[2] * scale, oy + b[3] * scale)

        return AgentCall(look, size, to_points if pic else None, page_id)

    result = validate(drawing, pack, sch, agent_for, ctx.trace_id)
    known_panels = set(ctx.session.scalars(select(m.Panel.id).where(m.Panel.drawing_id == ctx.drawing.id)))
    write_findings(ctx, result, {p.page_id for p in intake.pages}, known_panels)
    counts = {s: sum(1 for i in result.issues if i.severity == s) for s in ("error", "warning", "info")}
    log.info(
        "drawing %s: %s, %d checks skipped, %d agent calls",
        ctx.drawing.id,
        counts,
        len(result.checks_skipped),
        result.agent_calls,
    )
    return result.model_copy(update={"drawing_id": ctx.drawing.id})
