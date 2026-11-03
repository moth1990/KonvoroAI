"""Stage 7 (07): the priced quote version, in code only, with no model (07 §1 principle 1).

Reads stages 1, 4, 5 and 6 and the factory's price list, margin rules, derived-item rules and settings, and prices
the drawing's quote (`pipeline/pricing/`): lines, cost and sale price, derived items and labor, each line's final
colour with all its reasons, totals with discount and VAT, and the version's snapshot. Which version is priced, and
what a rerun keeps of the user's edits, is `pricing/run.py`'s (07 §7.7, S22 decision 5).

The quote is named after the project, or else the first file, so home's recent work and the review link work.
"""

import logging

from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.pipeline.pricing.run import Outputs, contract, price_drawing

from ..context import StageContext

log = logging.getLogger(__name__)


def run(ctx: StageContext) -> QuoteVersionResult:
    intake = ctx.output(1, IntakeResult)
    out = Outputs(intake, ctx.output(4, MergeResult), ctx.output(5, MatchingResult), ctx.output(6, ValidationResult))
    d = ctx.drawing
    project = ctx.session.get(m.Project, d.project_id) if d.project_id else None
    name = (project.name if project else "") or (intake.source_files[0].original_name if intake.source_files else "")
    priced = price_drawing(ctx.session, ctx.tenant_id, d, out, name or d.id)
    totals = priced.priced.totals
    log.info(
        "drawing %s: quote %s v%d, %d lines, %d unpriced, net %s",
        d.id,
        priced.quote.id,
        priced.version.version,
        len(priced.priced.lines),
        totals.sums.unpriced_count,
        totals.net_total,
    )
    return contract(priced, d.id, ctx.trace_id)
