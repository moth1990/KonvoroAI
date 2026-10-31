"""Stage 2 stub (02): one empty extraction per `process` page. Text, CAD blocks and tiles arrive in S10."""

from konboro.contracts.extraction import ExtractionResult, PageExtraction
from konboro.contracts.intake import IntakeResult

from ..context import StageContext


def run(ctx: StageContext) -> ExtractionResult:
    intake = ctx.output(1, IntakeResult)
    pages = [
        PageExtraction(page_id=p.page_id, drawing_id=ctx.drawing.id, render=None, trace_id=ctx.trace_id)
        for p in intake.pages
        if p.route == "process"
    ]
    return ExtractionResult(drawing_id=ctx.drawing.id, pages=pages, trace_id=ctx.trace_id)
