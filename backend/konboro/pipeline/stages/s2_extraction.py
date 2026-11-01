"""Stage 2 (02): extraction and tiling, for every `process` page, one page at a time (its tiles in parallel).

For each page, in this order:
1. The PDF's own content (2.2), when stage 1 says it has some: words if the text layer is reliable, lines and
   shapes always for vector pages, and the layer names. Their text height sets the DPI.
2. The render (2.1) at the chosen DPI, upright, to S3, with `px_per_pt = dpi / 72`.
3. Tiles (2.6) over the whole page (BUG-019), and which are blank.
4. OCR (2.3) when the text has no reliable layer: every non-blank tile, then the re-read. On a `mixed` page the
   PDF's word wins where both read the same place (02 §2.4).
5. Normalization (2.4): units, fixes, tags, merged neighbours.
6. The wire graph (2.5), vector pages only.
7. The tiles, the wire graph and the viewer's pyramid (12 §6, packed: `extraction/deepzoom.py`) to S3; the page row
   gets its keys and tile count.

The OCR engine is `ClaudeVisionOcr` until S31 (S10 decision); `ENGINE` builds it from the stage's context.
"""

import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from konboro.contracts.common import Bbox, StageIssue
from konboro.contracts.extraction import (
    ExtractionResult,
    ExtractionStats,
    Layer,
    PageExtraction,
    Render,
    TextSpan,
    Tile,
    Vector,
    WireGraph,
)
from konboro.contracts.intake import IntakeResult, Page
from konboro.db import models as m
from konboro.services.pdf import PdfiumError
from konboro.services.storage import drawing_key

from ..context import StageContext
from ..extraction import deepzoom, normalize, ocr, render, tiles, vector, wires
from ..extraction.config import DEFAULT, ExtractionConfig
from ..extraction.geometry import intersection, overlap_of_smaller, unturn_fraction
from ..intake.pages import PageRead, read_pages, render_at

log = logging.getLogger("konboro.pipeline.s2")

UPLOAD_WORKERS = 16
LOW_CONFIDENCE = 0.6  # 02 §8 `ocr_low_confidence`

ENGINE: Callable[[StageContext], ocr.OcrEngine] = lambda ctx: ocr.ClaudeVisionOcr(ctx.llm, ctx.tenant_id)  # noqa: E731

ISSUE_MESSAGES = {
    "render_failed": "לא הצלחנו לעבד את עמוד {page}.",
    "vector_too_complex": "עמוד {page} מורכב מדי לבניית מפת החיבורים. הבדיקה תרוץ בלעדיה.",
    "ocr_low_confidence": "הטקסט בעמוד {page} קשה לקריאה, בדקו את השורות הצהובות.",
    "text_layer_mismatch": "בעמוד {page} הטקסט בקובץ וה-OCR לא הסכימו ב-{count} מקומות. נשאר הטקסט מהקובץ.",
    "no_text_found": "לא מצאנו טקסט בתחום הלוחות בעמוד {page}. בדקו את סיווג העמוד.",
}
SEVERITY = {
    "render_failed": "error",
    "vector_too_complex": "warning",
    "ocr_low_confidence": "warning",
    "text_layer_mismatch": "info",
    "no_text_found": "warning",
}


def tile_key(ctx: StageContext, page_id: str, name: str) -> str:
    return drawing_key(ctx.tenant_id, ctx.drawing.id, "pages", page_id, "tiles", name)


def page_key(ctx: StageContext, page_id: str, *parts: str) -> str:
    return drawing_key(ctx.tenant_id, ctx.drawing.id, "pages", page_id, *parts)


@dataclass
class Uploads:
    """What a page writes to S3, sent together on a thread pool."""

    items: list[tuple[str, bytes, str]] = field(default_factory=list)

    def add(self, key: str, body: bytes, content_type: str) -> None:
        self.items.append((key, body, content_type))

    def send(self, ctx: StageContext) -> None:
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            list(pool.map(lambda it: ctx.storage.put(ctx.tenant_id, *it), self.items))
        self.items.clear()


def _issue(code: str, page: Page, **values: Any) -> StageIssue:
    message = ISSUE_MESSAGES[code].format(page=page.page_no, **values)
    return StageIssue(code=code, severity=SEVERITY[code], page_id=page.page_id, message=message)  # type: ignore[arg-type]


def _png(image: Image.Image) -> bytes:
    """Faster than the stage-1 `png` (no `optimize`): a page writes hundreds of these."""
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", compress_level=6)
    return out.getvalue()


def extract_page(
    ctx: StageContext,
    page: Page,
    seq: int,
    read: PageRead,
    data: bytes,
    engine: ocr.OcrEngine,
    cfg: ExtractionConfig = DEFAULT,
) -> PageExtraction:
    issues: list[StageIssue] = []
    uploads = Uploads()
    turn = (page.rotation_applied - read.rotation) % 360
    read.extra_rotation = turn
    size = page.size_pt
    key = f"{page.sha256 or read.sha256}:{turn}"

    # 1. the PDF's own content
    vp = vector.VectorPage()
    if read.fmt == "pdf" and page.geometry_source in ("vector", "mixed"):
        vp = vector.read(data, read.index, turn, with_text=page.text_source in ("pdf_text", "mixed"))
    too_complex = len(vp.paths) > cfg.vector_too_complex

    # 2. the render
    photo_dpi = read.dpi if read.fmt != "pdf" else None
    dpi = render.choose_dpi(page, vp.text_height_pt, cfg, photo_dpi)
    try:
        image = render_at(read, data, dpi)
    except (PdfiumError, OSError, ValueError, MemoryError):
        log.exception("page %s: render at %d DPI failed (render_failed)", page.page_id, dpi)
        return PageExtraction(
            page_id=page.page_id,
            drawing_id=ctx.drawing.id,
            render=None,
            issues=[_issue("render_failed", page)],
            trace_id=ctx.trace_id,
        )
    px_per_pt = dpi / 72.0
    render_key = page_key(ctx, page.page_id, "render.png")
    uploads.add(render_key, _png(image), "image/png")

    # 3. tiles
    area = (0, 0, image.width, image.height)  # the whole page (BUG-019)
    geoms = tiles.grid(area, image.size, cfg.tile_size_px, cfg.overlap_px)
    cut = [(t, tiles.cut(image, t)) for t in geoms]
    blank = {t: tiles.white_share(img) > cfg.blank_threshold for t, img in cut}

    # 4. text: the PDF's words, then OCR where there is no reliable text layer
    texts = [
        normalize.Text(
            raw_text=w.text,
            bbox=w.bbox,
            rotation=w.rotation,
            confidence=1.0,
            source="pdf_text",
            font_size_pt=w.font_size_pt,
            color=w.color,
        )
        for w in vp.words
    ]
    mismatches = 0
    if page.text_source in ("ocr", "mixed"):
        readings = ocr.read_page(engine, image, [(t, img) for t, img in cut if not blank[t]], px_per_pt, key, cfg)

        def crop(box: Bbox, crop_dpi: int) -> Image.Image:
            return render_at(read, data, crop_dpi, unturn_fraction(box, size, turn))

        changed = ocr.reread(engine, readings, crop, size, key, cfg)
        log.info("page %s: %d OCR spans, %d changed by the re-read", page.page_id, len(readings), changed)
        for r in readings:
            vector_word = next((t for t in texts if overlap_of_smaller(t.bbox, r.bbox) > 0.5), None)
            if vector_word is None:
                texts.append(ocr.as_text(r))
            elif normalize.canonical(vector_word.raw_text) != normalize.canonical(r.text):
                mismatches += 1
                log.info(
                    "page %s: text layer %r, OCR %r (text_layer_mismatch)", page.page_id, vector_word.raw_text, r.text
                )
    if mismatches:
        issues.append(_issue("text_layer_mismatch", page, count=mismatches))

    # 5. normalization
    for n, t in enumerate(texts, start=1):
        normalize.normalize(t)
        t.span_id = f"ts_{seq:03d}_{n:04d}"
    merged = normalize.merge(texts, size)
    next_id = len(texts) + 1
    for t in merged:
        if t.merged_from:
            t.span_id, next_id = f"ts_{seq:03d}_{next_id:04d}", next_id + 1
    spans = [
        TextSpan(
            span_id=t.span_id,
            text=t.text,
            raw_text=t.raw_text,
            bbox=t.bbox,
            rotation=t.rotation,  # type: ignore[arg-type]
            font_size_pt=t.font_size_pt,
            source=t.source,  # type: ignore[arg-type]
            confidence=t.confidence,
            color=t.color,
            tags=t.tags,
            corrections=t.corrections,
            merged_from=t.merged_from,
        )
        for t in merged
    ]

    # 6. the wire graph
    vector_out: Vector | None = None
    wire_graph = WireGraph(uri=None, status="not_supported")
    if vp.paths:
        paths_key = page_key(ctx, page.page_id, "paths.json.gz")
        uploads.add(paths_key, vector.paths_json(vp.paths), "application/gzip")
        vector_out = Vector(
            paths_uri=paths_key, path_count=len(vp.paths), layers=[Layer(name=n, visible=v) for n, v in vp.layers]
        )
    if page.geometry_source in ("vector", "mixed"):
        if too_complex:
            wire_graph = WireGraph(uri=None, status="skipped")
            issues.append(_issue("vector_too_complex", page))
        else:
            title_blocks = [r.bbox for r in page.regions if r.region_kind == "title_block"]
            graph = wires.build(wires.wiring_segments(vp.paths, size, [s.bbox for s in spans], title_blocks))
            wires_key = page_key(ctx, page.page_id, "wires.json.gz")
            uploads.add(wires_key, graph.to_json(), "application/gzip")
            wire_graph = WireGraph(
                uri=wires_key, node_count=len(graph.nodes), edge_count=len(graph.edges), status="built"
            )

    # 7. tiles, the pyramid, the page row
    tiles_prefix = page_key(ctx, page.page_id, "tiles") + "/"
    out_tiles: list[Tile] = []
    for g, img in cut:
        bbox_pt = g.bbox_pt(px_per_pt)
        name = f"r{g.row}c{g.col}.png"
        uploads.add(tile_key(ctx, page.page_id, name), _png(img), "image/png")
        out_tiles.append(
            Tile(
                tile_id=f"tl_{seq:03d}_r{g.row}c{g.col}",
                row=g.row,
                col=g.col,
                bbox_pt=bbox_pt,
                bbox_px=g.bbox_px,
                image_uri=tile_key(ctx, page.page_id, name),
                padding_px=g.padding_px,
                panel_ids=[p.panel_id for p in page.panels if intersection(p.bbox, bbox_pt) > 0],
                is_blank=blank[g],
                span_ids=[s.span_id for s in spans if intersection(s.bbox, bbox_pt) > 0],
            )
        )
    dzi_key = page_key(ctx, page.page_id, "dz", "page.dzi")
    uploads.add(
        dzi_key, deepzoom.descriptor(image.width, image.height, cfg.dzi_tile_px, cfg.dzi_overlap_px), "application/xml"
    )
    packed, index = deepzoom.pack(image, cfg.dzi_tile_px, cfg.dzi_overlap_px)
    uploads.add(page_key(ctx, page.page_id, "dz", "tiles.bin"), packed, "application/octet-stream")
    uploads.add(page_key(ctx, page.page_id, "dz", "index.json"), index, "application/json")
    uploads.send(ctx)

    panels_pt = [p.bbox for p in page.panels] or [(0.0, 0.0, *size)]
    if not any(intersection(s.bbox, b) > 0 for s in spans for b in panels_pt):  # 02 §8: none in the panels' area
        issues.append(_issue("no_text_found", page))
    ocr_spans = [s for s in spans if s.source == "ocr"]
    low = [s for s in ocr_spans if s.confidence < LOW_CONFIDENCE]
    if ocr_spans and len(low) > cfg.low_confidence_share * len(ocr_spans):
        issues.append(_issue("ocr_low_confidence", page))
    stored = ctx.session.get_one(m.Page, page.page_id)
    stored.render_key, stored.tiles_prefix = render_key, tiles_prefix
    stored.tile_count = sum(1 for t in out_tiles if not t.is_blank)

    return PageExtraction(
        page_id=page.page_id,
        drawing_id=ctx.drawing.id,
        render=Render(
            dpi=dpi,
            px_per_pt=round(px_per_pt, 4),
            width_px=image.width,
            height_px=image.height,
            image_uri=render_key,
            dzi_uri=dzi_key,
        ),
        text_spans=spans,
        vector=vector_out,
        wire_graph=wire_graph,
        tiles=out_tiles,
        stats=ExtractionStats(
            span_count=len(spans),
            ocr_span_count=len(ocr_spans),
            corrected_span_count=sum(1 for s in spans if s.corrections),
            low_confidence_span_count=len(low),
            tile_count=len(out_tiles),
            blank_tile_count=sum(1 for t in out_tiles if t.is_blank),
        ),
        issues=issues,
        trace_id=ctx.trace_id,
    )


def run(ctx: StageContext, cfg: ExtractionConfig = DEFAULT) -> ExtractionResult:
    intake = ctx.output(1, IntakeResult)
    process = [p for p in intake.pages if p.route == "process"]
    engine = ENGINE(ctx)
    files: dict[str, tuple[bytes, list[PageRead]]] = {}
    pages: list[PageExtraction] = []
    for seq, page in enumerate(process, start=1):
        if page.file_id not in files:
            f = ctx.session.get_one(m.DrawingFile, page.file_id)
            data = ctx.storage.get(ctx.tenant_id, f.storage_key)
            files[page.file_id] = (data, read_pages(f.id, f.detected_format, data))
        data, reads = files[page.file_id]
        pages.append(extract_page(ctx, page, seq, reads[page.page_no - 1], data, engine, cfg))
    return ExtractionResult(drawing_id=ctx.drawing.id, pages=pages, trace_id=ctx.trace_id)
