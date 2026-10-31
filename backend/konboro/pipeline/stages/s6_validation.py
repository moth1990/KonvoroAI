"""Stage 6 stub (06): no findings yet. Validation rules arrive in S21."""

from konboro.contracts.matching import MatchingResult
from konboro.contracts.validation import ValidationResult

from ..context import StageContext


def run(ctx: StageContext) -> ValidationResult:
    ctx.output(5, MatchingResult)
    return ValidationResult(drawing_id=ctx.drawing.id, trace_id=ctx.trace_id)
