"""Stage 7 stub (07): a quote with zero lines, version 1, draft, linked to the drawing. Pricing arrives in S22.

The quote is named after the project, or else the first file, so home's recent work and the review link work.
When stages 2–7 run again (a page moved to another route, S08), the drawing keeps its quote and version 1.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from konboro.contracts.intake import IntakeResult
from konboro.contracts.pricing import PanelTotals, QuotePanel, QuoteTotals, QuoteVersionResult
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.db.ids import new_id

from ..context import StageContext

ZERO = Decimal("0")


def run(ctx: StageContext) -> QuoteVersionResult:
    ctx.output(6, ValidationResult)
    intake = ctx.output(1, IntakeResult)
    s, d = ctx.session, ctx.drawing
    project = s.get(m.Project, d.project_id) if d.project_id else None
    name = (project.name if project else "") or (intake.source_files[0].original_name if intake.source_files else "")
    today = datetime.now(UTC).date()
    existing = s.scalar(select(m.Quote.id).where(m.Quote.drawing_id == d.id))
    quote_id = existing or new_id("quo")
    if existing is None:
        s.add(m.Quote(id=quote_id, tenant_id=ctx.tenant_id, drawing_id=d.id, name=name or quote_id))
        s.flush()
        s.add(m.QuoteVersion(id=new_id("qv"), tenant_id=ctx.tenant_id, quote_id=quote_id, version=1, quote_date=today))
    vat = s.scalar(select(m.VatRate.rate).where(m.VatRate.valid_from <= today).order_by(m.VatRate.valid_from.desc()))
    zero_panel = PanelTotals(cost_total=ZERO, price_total=ZERO)
    return QuoteVersionResult(
        quote_id=quote_id,
        version=1,
        status="draft",
        drawing_id=d.id,
        tenant_id=ctx.tenant_id,
        customer_id=project.customer_id if project else None,
        quote_date=today,
        panels=[QuotePanel(panel_id=p.panel_id, name=p.name, totals=zero_panel) for p in intake.panels],
        totals=QuoteTotals(
            cost_total=ZERO,
            price_total=ZERO,
            net_total=ZERO,
            margin_abs=ZERO,
            margin_pct=None,
            vat_rate=vat if vat is not None else ZERO,
            vat=ZERO,
            gross_total=ZERO,
        ),
        trace_id=ctx.trace_id,
    )
