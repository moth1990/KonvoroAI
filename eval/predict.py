"""The pipeline's own contracts, in the canonical shape the metrics read."""

from konboro.contracts.detection import DetectionResult
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult

from .canonical import CanonComponent, CanonDetection, CanonPage, CanonPanel, Prediction


def prediction(
    intake: IntakeResult,
    merge: MergeResult,
    quote: QuoteVersionResult,
    extraction: ExtractionResult | None = None,
    detection: DetectionResult | None = None,
) -> Prediction:
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
        title_block=intake.title_block.model_dump(exclude={"designer"}) if intake.title_block else {},
        needs_confirmation=intake.needs_confirmation,
        span_texts=tuple(s.text for p in extraction.pages for s in p.text_spans) if extraction else None,
        extraction=_extraction_counts(extraction) if extraction else {},
        detections=_detections(intake, detection) if detection else None,
        detection=_detection_counts(detection) if detection else {},
    )


def _detections(intake: IntakeResult, detection: DetectionResult) -> tuple[CanonDetection, ...]:
    page_no = {p.page_id: p.page_no for p in intake.pages}
    return tuple(
        CanonDetection(
            page_no=page_no[d.page_id],
            family=d.family,
            role=d.role,
            designator=d.designator,
            bbox=d.bbox,
            billable=d.billable,
        )
        for p in detection.pages
        for d in p.detections
    )


def _detection_counts(detection: DetectionResult) -> dict[str, int]:
    pages = detection.pages
    return {
        "detections": sum(p.stats.detection_count for p in pages),
        "accepted": sum(p.stats.by_status.get("accepted", 0) for p in pages),
        "uncertain": sum(p.stats.by_status.get("uncertain", 0) for p in pages),
        "unknown": sum(p.stats.by_status.get("unknown", 0) for p in pages),
        "duplicates_removed": sum(p.stats.duplicates_removed for p in pages),
        "orphan_recovered": sum(p.stats.by_method.get("orphan_recovery", 0) for p in pages),
        "orphan_texts": sum(p.stats.orphan_text_count for p in pages),
        "disambiguation_calls": sum(p.stats.llm_calls for p in pages),
    }


def _extraction_counts(extraction: ExtractionResult) -> dict[str, int]:
    pages = extraction.pages
    return {
        "pages": len(pages),
        "tiles": sum(p.stats.tile_count for p in pages),
        "blank_tiles": sum(p.stats.blank_tile_count for p in pages),
        "spans": sum(p.stats.span_count for p in pages),
        "ocr_spans": sum(p.stats.ocr_span_count for p in pages),
        "corrected_spans": sum(p.stats.corrected_span_count for p in pages),
        "wire_edges": sum(p.wire_graph.edge_count for p in pages if p.wire_graph),
    }
