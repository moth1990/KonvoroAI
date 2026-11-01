"""Stage 3 (03): symbol detection, for every page stage 2 extracted, one page at a time (its tiles in parallel).

For each page, in this order:
1. The search (3.2, interim: S12 decision): every non-blank tile goes to the `symbol_detection` route with the
   reference sheet, and code checks every answer (`detection/search.py`).
2. De-duplication across overlapping tiles (3.5, `detection/candidates.py`).
3. Text with no symbol near it (3.6, `detection/orphans.py`): one more search around it, else an `orphan_text`.
4. The disambiguation call for what the first look left open (3.4, `detection/disambiguate.py`), within budget.
5. Designators (3.7, `detection/designators.py`), the owner tile, the panel, the crop, the confidence and status
   (6.3), and the page's issues (8).

The dedicated family detector and the similarity index (3.2–3.3) arrive in phase 4; CAD blocks (3.1) with 2.0.
"""

import io
import logging
from collections import Counter
from typing import Any

from PIL import Image

from konboro.contracts.common import StageIssue
from konboro.contracts.detection import ClassCandidate, Detection, DetectionResult, DetectionStats, PageDetections
from konboro.contracts.extraction import ExtractionResult, PageExtraction
from konboro.contracts.intake import IntakeResult, Page
from konboro.db import models as m
from konboro_llm import ImageInput

from ..context import StageContext
from ..detection import designators, disambiguate, library, orphans, search
from ..detection.candidates import Candidate, centre, deduplicate, owner_tile
from ..detection.config import DEFAULT, DEVICE_TAGS, DetectionConfig
from ..detection.sheets import load_curated, png, reference_sheet
from ..extraction.geometry import contains
from ..extraction.tiles import TileGeom, cut
from .s2_extraction import Uploads, page_key

log = logging.getLogger("konboro.pipeline.s3")

Image.MAX_IMAGE_PIXELS = None  # stage 2 renders large sheets on purpose (6199-2-50 is 84 MP)

DETECTOR = "symbol_detection"  # the route, as `detector_model` (03 §6.1): the interim model, not a trained one

ISSUE_MESSAGES = {
    "no_symbols_found": "לא מצאנו רכיבים בעמוד {page}. ייתכן שהעמוד סווג לא נכון, בדקו את סיווג העמוד.",
    "high_unknown_ratio": "יש בעמוד {page} סימנים שלא זיהינו. סמנו אותם פעם אחת והמערכת תלמד.",
    "llm_budget_exceeded": "בעמוד {page} נשארו {count} סימנים לא ודאיים שלא נבדקו שוב. בדקו את השורות הצהובות.",
    "many_orphan_texts": "בעמוד {page} יש {count} ערכים חשמליים בלי סימן לידם. ייתכן שפספסנו רכיבים.",
}


def _issue(code: str, page: Page, **values: Any) -> StageIssue:
    message = ISSUE_MESSAGES[code].format(page=page.page_no, **values)
    return StageIssue(code=code, severity="warning", page_id=page.page_id, message=message)


def status(confidence: float, symbol_class: str, cfg: DetectionConfig) -> str:
    if symbol_class == library.UNKNOWN or confidence < cfg.uncertain_from:
        return "unknown"
    return "accepted" if confidence >= cfg.accepted_from else "uncertain"


def _crop(render: Image.Image, c: Candidate, px_per_pt: float, cfg: DetectionConfig) -> bytes:
    x0, y0, x1, y1 = (v * px_per_pt for v in c.bbox)
    m_ = cfg.crop_margin * max(x1 - x0, y1 - y0)
    box = (
        max(0, int(x0 - m_)),
        max(0, int(y0 - m_)),
        min(render.width, int(x1 + m_) + 1),
        min(render.height, int(y1 + m_) + 1),
    )
    out = io.BytesIO()
    render.crop(box).convert("RGB").save(out, "PNG", compress_level=6)
    return out.getvalue()


def detect_page(
    ctx: StageContext,
    page: Page,
    seq: int,
    extraction: PageExtraction,
    lib: library.Library,
    searcher: search.Searcher,
    decide: disambiguate.Decide,
    cfg: DetectionConfig = DEFAULT,
) -> tuple[PageDetections, list[Candidate]]:
    """The page's detections, and the candidates they came from, in the same order."""
    render_info = extraction.render
    if render_info is None:  # stage 2 couldn't render it (`render_failed`): nothing to search
        return PageDetections(page_id=page.page_id, drawing_id=ctx.drawing.id, trace_id=ctx.trace_id), []
    render = Image.open(io.BytesIO(ctx.storage.get(ctx.tenant_id, render_info.image_uri))).convert("RGB")
    px_per_pt = render_info.px_per_pt
    key = f"{page.sha256 or page.page_id}:{page.rotation_applied}:{render_info.dpi}"
    issues: list[StageIssue] = []

    # 1. the search
    images = [
        search.SearchImage(
            cut(render, TileGeom(t.row, t.col, t.bbox_px, t.padding_px)),
            (t.bbox_px[0], t.bbox_px[1]),
            t.padding_px,
            render.size,
            f"{key}:tile:{t.bbox_px}",
            t.tile_id,
        )
        for t in extraction.tiles
        if not t.is_blank
    ]
    found = [c for cs in searcher([(img, "") for img in images], px_per_pt) for c in cs]
    sightings = len(found)

    # 2. one copy per symbol
    found, removed = deduplicate(found, cfg)

    # 3. text with no symbol near it
    recovered, orphan_texts, orphan_searches = orphans.recover(
        found,
        extraction.text_spans,
        render,
        px_per_pt,
        page.size_pt,
        key,
        lambda jobs: searcher(jobs, px_per_pt),
        cfg,
    )
    found += recovered

    # 4. the disambiguation call
    found, llm_calls, over_budget = disambiguate.resolve(found, decide, render, px_per_pt, lib, cfg)
    if over_budget:
        left = sum(1 for c in found if c.needs_decision)
        issues.append(_issue("llm_budget_exceeded", page, count=left))

    # 5. designators, owner tile, panel, crops
    for c in found:
        designators.link(c, extraction.text_spans, cfg)
    tiles = [(t.tile_id, t.bbox_pt) for t in extraction.tiles]
    found.sort(key=lambda c: (round(c.bbox[1]), c.bbox[0]))
    uploads = Uploads()
    detections: list[Detection] = []
    for n, c in enumerate(found, start=1):
        det_id = f"det_{seq:03d}_{n:04d}"
        owner = owner_tile(c.bbox, tiles) or (c.tile_id or tiles[0][0])
        seen = c.seen_in or [owner]
        crop_key = page_key(ctx, page.page_id, "crops", f"{det_id}.png")
        uploads.add(crop_key, _crop(render, c, px_per_pt, cfg), "image/png")
        cx, cy = centre(c.bbox)
        panel = next((p.panel_id for p in page.panels if contains(p.bbox, (cx, cy, cx, cy))), None)
        cls = lib.classes.get(c.symbol_class)
        billable = cls.billable if cls else next((x.billable for x in lib.families.get(c.family, [])), True)
        confidence = round(min(1.0, c.confidence), 4)
        detections.append(
            Detection(
                det_id=det_id,
                page_id=page.page_id,
                bbox=c.bbox,
                orientation=c.orientation,  # type: ignore[arg-type]
                family=c.family,
                symbol_class=c.symbol_class,
                billable=billable,
                method=c.method,  # type: ignore[arg-type]
                detector_score=c.detector_score,
                class_score=round(c.class_score, 4),
                confidence=confidence,
                class_candidates=[ClassCandidate(symbol_class=s, score=round(v, 4)) for s, v in c.candidates[:3]],
                status=status(confidence, c.symbol_class, cfg),  # type: ignore[arg-type]
                owner_tile_id=owner,
                seen_in_tile_ids=sorted(set(seen) | {owner}),
                panel_id=panel,
                designator=c.designator,
                designator_span_id=c.designator_span_id,
                role=c.role,  # type: ignore[arg-type]
                crop_uri=crop_key,
                llm_decision=c.llm_decision,
            )
        )
    uploads.send(ctx)

    # issues (03 §8)
    if not any(d.billable for d in detections):
        issues.append(_issue("no_symbols_found", page))
    unknown = sum(1 for d in detections if d.status == "unknown")
    if detections and unknown > cfg.high_unknown_share * len(detections):
        issues.append(_issue("high_unknown_ratio", page))
    device_spans = [s for s in extraction.text_spans if any(k in s.tags for k in DEVICE_TAGS)]
    if device_spans and len(orphan_texts) > cfg.many_orphans_share * len(device_spans):
        issues.append(_issue("many_orphan_texts", page, count=len(orphan_texts)))

    stored = ctx.session.get_one(m.Page, page.page_id)
    stored.symbol_count = len(detections)
    stored.symbol_llm_count = sum(1 for d in detections if d.method == "detector_llm")
    log.info(
        "page %s: %d sightings, %d symbols (%d duplicates), %d recovered from %d orphan searches, %d decided by the "
        "model, %d orphan texts",
        page.page_id,
        sightings,
        len(detections),
        removed,
        len(recovered),
        orphan_searches,
        llm_calls,
        len(orphan_texts),
    )
    result = PageDetections(
        page_id=page.page_id,
        drawing_id=ctx.drawing.id,
        detector_model=DETECTOR,
        embedding_model=None,
        library_version=lib.version,
        detections=detections,
        orphan_texts=orphan_texts,
        stats=DetectionStats(
            detection_count=len(detections),
            by_method=dict(Counter(d.method for d in detections)),
            by_status=dict(Counter(d.status for d in detections)),
            duplicates_removed=removed,
            orphan_text_count=len(orphan_texts),
            llm_calls=llm_calls,
        ),
        issues=issues,
        trace_id=ctx.trace_id,
    )
    return result, found


def run(ctx: StageContext, cfg: DetectionConfig = DEFAULT) -> DetectionResult:
    intake = ctx.output(1, IntakeResult)
    extraction = ctx.output(2, ExtractionResult)
    designer = intake.title_block.designer if intake.title_block else None
    lib = library.load(ctx.session, designer)
    sheet = ImageInput(png(reference_sheet(lib, load_curated)), key=f"{lib.version}:sheet")
    prompt = search.Prompt(lib, sheet)
    ask = search.model_asker(ctx.llm, prompt, ctx.tenant_id)
    legend = "\n\n".join(a.content for a in intake.context_artifacts if a.kind == "legend")
    pages = {p.page_id: p for p in intake.pages}

    searcher = search.searcher(ask, lib, cfg)

    everything: list[tuple[PageDetections, list[Candidate]]] = []
    for seq, pe in enumerate(extraction.pages, start=1):
        page = pages[pe.page_id]
        decide = disambiguate.model_decider(
            ctx.llm,
            lib,
            load_curated,
            legend,
            f"{page.sha256 or page.page_id}:{page.rotation_applied}",
            ctx.tenant_id,
        )
        everything.append(detect_page(ctx, page, seq, pe, lib, searcher, decide, cfg))

    # 03 §3.7: on a drawing where most devices carry a tag, flag the ones that don't
    billable = {c.symbol_class: c.billable for c in lib.classes.values()}
    designators.flag_untagged([c for _, cs in everything for c in cs], billable, cfg)
    out = [
        result.model_copy(
            update={
                "detections": [
                    d.model_copy(update={"flags": c.flags}) for d, c in zip(result.detections, cs, strict=True)
                ]
            }
        )
        for result, cs in everything
    ]
    return DetectionResult(drawing_id=ctx.drawing.id, pages=out, trace_id=ctx.trace_id)
