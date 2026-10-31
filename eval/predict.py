"""The pipeline's own contracts, in the canonical shape the metrics read."""

from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult

from .canonical import CanonComponent, CanonPage, CanonPanel, Prediction


def prediction(intake: IntakeResult, merge: MergeResult, quote: QuoteVersionResult) -> Prediction:
    names = {p.panel_id: p.name for p in intake.panels}
    by_panel: dict[str, list[CanonComponent]] = {panel_id: [] for panel_id in names}
    for c in merge.components:
        by_panel.setdefault(c.panel_id, []).append(
            CanonComponent(
                family=c.family,
                designators=tuple(c.designators),
                attributes={k: a.value for k, a in c.attributes.items() if a.value is not None},
                qty=c.quantity,
                supply_scope=c.supply_scope,
                label=" ".join(c.explicit_texts),
            )
        )
    return Prediction(
        pages=tuple(CanonPage(no=p.page_no, kind=p.page_kind, route=p.route) for p in intake.pages),
        input_kind=intake.input_kind,
        panels=tuple(CanonPanel(name=names.get(pid, pid), components=tuple(cs)) for pid, cs in by_panel.items()),
        audit=None,  # the audit flow (11) arrives with its own session
        quote_total=quote.totals.net_total,
    )
