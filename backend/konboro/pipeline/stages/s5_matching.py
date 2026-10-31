"""Stage 5 stub (05): one match per component, and there are none yet. Catalog matching arrives in S20."""

from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult

from ..context import StageContext


def run(ctx: StageContext) -> MatchingResult:
    merge = ctx.output(4, MergeResult)
    if merge.components:
        raise NotImplementedError("catalog matching arrives in S20")
    return MatchingResult(drawing_id=ctx.drawing.id, matches=[], trace_id=ctx.trace_id)
