"""Stage 5 stub (05): no catalog matching yet, so no matches. Catalog matching arrives in S20.

Stage 4 sends real components since S13; until S20 they pass through unmatched, and the quote stays at zero lines
(stage 7, S22).
"""

from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult

from ..context import StageContext


def run(ctx: StageContext) -> MatchingResult:
    ctx.output(4, MergeResult)  # read anyway: the stub keeps the chain's shape
    return MatchingResult(drawing_id=ctx.drawing.id, matches=[], trace_id=ctx.trace_id)
