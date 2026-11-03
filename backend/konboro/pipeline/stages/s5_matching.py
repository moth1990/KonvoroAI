"""Stage 5 (05): from a component's attributes to the SKU the factory buys and prices.

Reads stage 4's components and stage 1's notes, the master catalog (global) and the factory's preferences, defaults,
memory and price list (as yes or no), and matches every component in code (`pipeline/matching/match.py`); the
`catalog_disambiguation` model only chooses between candidates no rule decided (05 §5.8), shown no price (05 §12).

Components of the factory's auxiliary families (terminals by default) get no SKU: they are listed apart and stage 7
counts them as derived material (S20 decision 3). Each component row keeps its status and the catalog item chosen,
for the run step and for what points at a component.
"""

import logging

from sqlalchemy import update

from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.db import models as m
from konboro_llm.stages import catalog_disambiguation

from ..association import schemas
from ..context import StageContext
from ..matching import catalog, factory, notes
from ..matching.agent import Ask
from ..matching.match import Inputs, item_of, match_all

log = logging.getLogger("konboro.pipeline.s5")


def run(ctx: StageContext) -> MatchingResult:
    merge = ctx.output(4, MergeResult)
    intake = ctx.output(1, IntakeResult)
    cat = catalog.load(ctx.session)
    project = ctx.session.get(m.Project, ctx.drawing.project_id) if ctx.drawing.project_id else None
    fac = factory.load(ctx.session, ctx.tenant_id, cat, project.customer_id if project else None)

    def ask(component: str, candidates: str, context: str, error: str | None) -> catalog_disambiguation.CatalogAnswer:
        return catalog_disambiguation.choose(ctx.llm, component, candidates, context, ctx.tenant_id, error).data

    chooser: Ask = ask
    inputs = Inputs(
        catalog=cat,
        factory=fac,
        schemas=schemas.load(ctx.session),
        notes=notes.read(intake.context_artifacts),
        components={c.component_id: c for c in merge.components},
        ask=chooser,
    )
    result = match_all(merge.components, inputs)
    for match in result.matches:
        ctx.session.execute(
            update(m.Component)
            .where(m.Component.tenant_id == ctx.tenant_id, m.Component.id == match.component_id)
            .values(match_status=match.status, catalog_item_id=item_of(match, cat))
        )
    if result.auxiliary:
        ctx.session.execute(
            update(m.Component)
            .where(m.Component.tenant_id == ctx.tenant_id, m.Component.id.in_(result.auxiliary))
            .values(match_status="auxiliary", catalog_item_id=None)
        )
    log.info(
        "drawing %s: %d components, %d signatures, %d by the model, %s",
        ctx.drawing.id,
        result.stats.components,
        result.stats.signatures,
        result.stats.llm_signatures,
        result.stats.by_status,
    )
    return MatchingResult(
        drawing_id=ctx.drawing.id,
        matches=result.matches,
        auxiliary=result.auxiliary,
        stats=result.stats,
        issues=result.issues,
        trace_id=ctx.trace_id,
    )
