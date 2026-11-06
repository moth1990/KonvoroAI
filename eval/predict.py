"""The pipeline's own contracts, in the canonical shape the metrics read."""

from konboro.contracts.audit import Difference
from konboro.contracts.detection import DetectionResult
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import ComponentMatch, MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult

from .canonical import (
    CanonComponent,
    CanonDetection,
    CanonDifference,
    CanonMatch,
    CanonPage,
    CanonPanel,
    DifferenceType,
    Prediction,
)

# The audit's types (11 §5.4) as the golden quotes name them: a short, an over or a double count is a quantity that
# differs. A drawing conflict and auxiliary material are not differences, so they are left out.
AUDIT_TYPES: dict[str, DifferenceType] = {
    "missing_in_quote": "missing_in_quote",
    "qty_short": "quantity_mismatch",
    "qty_over": "quantity_mismatch",
    "possible_double_count": "quantity_mismatch",
    "attribute_mismatch": "attribute_mismatch",
    "extra_in_quote": "extra_in_quote",
    "arithmetic": "arithmetic",
}


def audit_differences(differences: list[Difference]) -> tuple[CanonDifference, ...]:
    return tuple(
        CanonDifference(
            type=AUDIT_TYPES[d.type],
            item=d.message,
            designators=tuple(d.designators),
            value_at_risk=d.amount if d.amount is not None and d.amount > 0 else None,
            confidence=d.confidence,
            quote_lines=() if d.quote_line_index is None else (d.quote_line_index,),
            family=d.family,
        )
        for d in differences
        if d.type in AUDIT_TYPES
    )


def prediction(
    intake: IntakeResult,
    merge: MergeResult,
    quote: QuoteVersionResult,
    extraction: ExtractionResult | None = None,
    detection: DetectionResult | None = None,
    audit: list[Difference] | None = None,
    matching: MatchingResult | None = None,
    labelled: tuple[CanonMatch, ...] | None = None,
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
                ref=c.component_id,
            )
        )
    families = {c.component_id: c.family for c in merge.components}
    return Prediction(
        pages=tuple(CanonPage(no=p.page_no, kind=p.page_kind, route=p.route) for p in intake.pages),
        input_kind=intake.input_kind,
        panels=tuple(CanonPanel(name=names.get(pid, pid), components=tuple(cs)) for pid, cs in by_panel.items()),
        audit=audit_differences(audit) if audit is not None else None,
        quote_total=quote.totals.net_total,
        title_block=intake.title_block.model_dump(exclude={"designer"}) if intake.title_block else {},
        needs_confirmation=intake.needs_confirmation,
        span_texts=tuple(s.text for p in extraction.pages for s in p.text_spans) if extraction else None,
        extraction=_extraction_counts(extraction) if extraction else {},
        detections=_detections(intake, detection) if detection else None,
        detection=_detection_counts(detection) if detection else {},
        merge=merge_counts(merge),
        matches=tuple(canon_match(x, families.get(x.component_id, "")) for x in matching.matches) if matching else None,
        matching=matching_counts(matching) if matching else {},
        auxiliary=tuple(matching.auxiliary) if matching else (),
        line_colours=line_colours(quote),
        labelled_matches=labelled,
    )


RANK = {"green": 0, "yellow": 1, "red": 2}


def line_colours(quote: QuoteVersionResult) -> dict[str, str]:
    """Each component line's colour from every reason but the price (07 §7.5), by component (a merged line's too)."""
    out: dict[str, str] = {}
    for panel in quote.panels:
        for ln in panel.lines:
            if ln.line_type != "component":
                continue
            reasons = [r.status for r in ln.status_reasons if r.source != "price"]
            colour = max(reasons, key=RANK.__getitem__, default="green")
            for cid in ln.component_ids or ([ln.component_id] if ln.component_id else []):
                out[cid] = colour
    return out


def canon_match(x: ComponentMatch, family: str, **extra: object) -> CanonMatch:
    return CanonMatch(
        ref=x.component_id,
        family=family,
        status=x.status,
        sku=x.chosen_sku,
        item=dict(x.catalog_item.attributes) if x.catalog_item else {},
        method=x.method,
        signature=x.signature,
        **extra,  # type: ignore[arg-type]
    )


def matching_counts(result: MatchingResult) -> dict[str, int]:
    """Stage 5's counts (05 §6.2, §9): signatures, the ones the agent decided, components by status and by method."""
    s = result.stats
    out = {"components": s.components, "signatures": s.signatures, "llm_signatures": s.llm_signatures}
    out |= {f"status_{k}": v for k, v in sorted(s.by_status.items())}
    out |= {f"method_{k}": v for k, v in sorted(s.by_method.items())}
    out["auxiliary"] = s.auxiliary
    return out


EVIDENCE_SOURCES = frozenset({"drawing", "cad_attrib", "shared_label", "bom"})


def _evidenced(source: str | None, span_ids: list[str], has_row: bool) -> bool:
    if source is None:
        return False
    if source not in EVIDENCE_SOURCES:
        return True  # graphic poles need no span
    return bool(span_ids) or (source == "bom" and has_row)


def merge_counts(merge: MergeResult) -> dict[str, int]:
    """Stage 4's counts (04 §6.1, §10). A value with no evidence: one with no source, or read from text with no span
    to show for it (graphic poles need none). A BOM row's value has its row for evidence, not a span (01 §5.8). 04 §10
    wants 0."""
    rows = {i.instance_id for i in merge.instances if i.method == "bom" and i.rows}
    attrs = [(a, i.instance_id in rows) for i in merge.instances for a in i.attributes.values()]
    attrs += [
        (a, bool(c.instance_ids) and all(i in rows for i in c.instance_ids))
        for c in merge.components
        for a in c.attributes.values()
    ]
    attrs += [(a, False) for x in merge.missing for a in x.attributes.values()]
    unproven = sum(1 for a, has_row in attrs if a.value is not None and not _evidenced(a.source, a.span_ids, has_row))
    return {
        "instances": merge.stats.instance_count,
        "components": merge.stats.component_count,
        "missing": merge.stats.missing_count,
        "tiles": merge.stats.tiles_total,
        "agent_tiles": merge.stats.tiles_with_agent,
        "agent_instances": merge.stats.by_method.get("agent", 0),
        "citation_mismatches": merge.stats.citation_mismatches,
        "cited_values": _cited(merge),
        "shared_labels": merge.stats.shared_labels,
        "values_without_evidence": unproven,
    }


def _cited(merge: MergeResult) -> int:
    """Values the agent cited a span for, kept or refused: the citation_mismatch rate's denominator (04 §10)."""
    kept = sum(
        1
        for i in merge.instances
        if i.method == "agent"
        for a in i.attributes.values()
        if a.value is not None and a.source != "graphic"
    )
    return kept + merge.stats.citation_mismatches


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
