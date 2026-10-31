"""Stage 4 stub (04): no components yet. Association and merge arrive in S13."""

from konboro.contracts.detection import DetectionResult
from konboro.contracts.merge import MergeResult

from ..context import StageContext


def run(ctx: StageContext) -> MergeResult:
    ctx.output(3, DetectionResult)  # read anyway: the stub keeps the chain's shape
    return MergeResult(drawing_id=ctx.drawing.id, trace_id=ctx.trace_id)
