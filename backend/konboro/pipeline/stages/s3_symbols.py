"""Stage 3 stub (03): no detections yet, one entry per extracted page. Symbol detection arrives in S12."""

from konboro.contracts.detection import DetectionResult, PageDetections
from konboro.contracts.extraction import ExtractionResult

from ..context import StageContext


def run(ctx: StageContext) -> DetectionResult:
    extraction = ctx.output(2, ExtractionResult)
    pages = [
        PageDetections(page_id=p.page_id, drawing_id=ctx.drawing.id, trace_id=ctx.trace_id) for p in extraction.pages
    ]
    return DetectionResult(drawing_id=ctx.drawing.id, pages=pages, trace_id=ctx.trace_id)
