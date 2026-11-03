"""06 §6.3 "after a user action": the validator again, rules only, on the one panel an edit touched, under a second
(06 §9). S23's edit routes call it with the edited stage-4 and stage-5 results; by default it reads the stored ones.

It writes the new result over the stage-6 output, and brings the panel's `findings` rows in line: a finding that no
longer holds is `resolved`, a new one is added on the same quote version, one the user dismissed stays dismissed.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.contracts import STAGE_OUTPUTS
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.pipeline.association import schemas
from konboro.pipeline.stages.s6_validation import finding_row
from konboro.pipeline.validation import engine
from konboro.pipeline.validation import pack as pack_mod
from konboro.pipeline.validation.model import build

from .storage import Storage


def _output(session: Session, storage: Storage, tenant_id: str, drawing_id: str, stage: int) -> tuple[str, object]:
    run = session.get_one(m.StageRun, (tenant_id, drawing_id, stage))
    if run.output_key is None:
        raise LookupError(f"stage {stage} has no output for {drawing_id}")
    return run.output_key, STAGE_OUTPUTS[stage].model_validate_json(storage.get(tenant_id, run.output_key))


def revalidate_panel(
    session: Session,
    storage: Storage,
    tenant_id: str,
    drawing_id: str,
    panel_id: str,
    merge: MergeResult | None = None,
    matching: MatchingResult | None = None,
) -> ValidationResult:
    """Inside the tenant's session (RLS). Raises LookupError when the drawing has no stage-6 result yet."""
    _, intake = _output(session, storage, tenant_id, drawing_id, 1)
    _, extraction = _output(session, storage, tenant_id, drawing_id, 2)
    if merge is None:
        merge = _output(session, storage, tenant_id, drawing_id, 4)[1]  # type: ignore[assignment]
    if matching is None:
        matching = _output(session, storage, tenant_id, drawing_id, 5)[1]  # type: ignore[assignment]
    key, previous = _output(session, storage, tenant_id, drawing_id, 6)
    assert isinstance(intake, IntakeResult) and isinstance(extraction, ExtractionResult)  # noqa: S101
    assert isinstance(previous, ValidationResult) and merge is not None and matching is not None  # noqa: S101
    sch = schemas.load(session)
    pack = pack_mod.for_tenant(session, tenant_id)
    skus = sorted({x.chosen_sku for x in matching.matches if x.chosen_sku})
    classes = {
        sku: cls
        for sku, cls in session.execute(
            select(m.CatalogItem.sku, m.CatalogItem.symbol_class).where(m.CatalogItem.sku.in_(skus))
        )
        if cls
    }
    coverage = pack.rules.get("TEXT_COVERAGE_LOW")
    tags = tuple(coverage.params.get("tags", ("current_a",))) if coverage else ("current_a",)
    drawing = build(intake, merge, matching, sch, extraction, classes, tags)
    result = engine.revalidate(previous, drawing, panel_id, pack, sch)
    storage.put(tenant_id, key, result.model_dump_json().encode(), "application/json")
    _sync(session, tenant_id, drawing_id, panel_id, result, intake)
    return result


def _sync(
    session: Session, tenant_id: str, drawing_id: str, panel_id: str, result: ValidationResult, intake: IntakeResult
) -> None:
    rows = {
        f.id: f
        for f in session.scalars(
            select(m.Finding).where(
                m.Finding.drawing_id == drawing_id, m.Finding.source.in_(("rule", "bom_crosscheck"))
            )
        )
    }
    version = next((f.quote_version_id for f in rows.values() if f.quote_version_id), None)
    panels = set(session.scalars(select(m.Panel.id).where(m.Panel.drawing_id == drawing_id)))
    pages = {p.page_id for p in intake.pages}
    for i in result.issues:
        if i.panel_id != panel_id or i.source != "rule":
            continue
        row = rows.get(i.issue_id)
        if row is None:
            new = finding_row(tenant_id, drawing_id, i, pages, panels)
            new.quote_version_id = version
            session.add(new)
        else:
            row.status = i.status
    session.flush()
