"""A user changes a page's kind (01 §5.6): on the confirmation step, on the done step, or later.

The change is the user's word on the page: confidence 1, `classified_by` `user`, and the route that kind takes
(01 §7). It is recorded as a `page_reclassified` correction event, for training the classifier (01 §5.6). The
drawing's panels are rebuilt from what the classifier found on every page, and stage 1's output is rewritten, so
the stages after it read the corrected pages. If the route changed on a finished drawing, stages 2–7 run again
(S08 decision); while the drawing waits for confirmation, the next stage hasn't run yet, so nothing re-runs.
A page the user marks as a factory template becomes one (01 §5.7 item 1).

The user also settles a BOM spreadsheet's column mapping (01 §5.8, S14 decision 1): a role they pick replaces the
code's or the model's (`bom_columns_mapped` correction event), and confirming the pages settles every mapping they
were shown. A BOM-only drawing's panels come from its tables, so a changed panel column rebuilds them.
"""

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.contracts.intake import ContextArtifact, IntakeResult, PageKind, PagePanel, Panel, Region
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.services.llm import STAND_IN_PREFIX
from konboro.services.queue import StageMessage
from konboro.services.storage import Storage
from konboro_llm.stages.table_transcription import Role

from .. import coordinator
from ..bom import review as bom_review
from ..bom import table as bom_table
from . import classify, routing, templates
from .drawing import MergedPanel, PagePanels, is_factory_set, merge_panels, name_key
from .pages import read_pages, render

USER_CONFIDENCE = 1.0


class BomMappingIncompleteError(Exception):
    """Confirming a BOM whose mapping has no item or no quantity column: it would read no product."""

    def __init__(self, page_ids: list[str]):
        super().__init__(", ".join(page_ids))
        self.page_ids = page_ids


@dataclass(frozen=True)
class KindChange:
    route_changed: bool
    message: StageMessage | None  # stages 2–7 again; the caller sends it after the commit


def _lock(session: Session, tenant_id: str, drawing_id: str) -> m.Drawing:
    drawing = session.scalar(select(m.Drawing).where(m.Drawing.id == drawing_id).with_for_update(key_share=True))
    if drawing is None or drawing.tenant_id != tenant_id:
        raise LookupError(drawing_id)
    if drawing.status in ("failed", "cancelled"):
        raise coordinator.DrawingFinishedError(drawing.status)
    if drawing.status not in ("ready", "awaiting_confirmation"):
        raise coordinator.DrawingBusyError(drawing.status)
    return drawing


def change_page_kind(
    session: Session, storage: Storage, tenant_id: str, user_id: str, drawing_id: str, page_id: str, kind: PageKind
) -> KindChange:
    drawing = _lock(session, tenant_id, drawing_id)
    page = session.get(m.Page, page_id)
    if page is None or page.drawing_id != drawing_id:
        raise LookupError(page_id)
    before = {"page_kind": page.page_kind, "route": page.route, "confidence": page.page_kind_confidence}
    if page.page_kind == kind and page.classified_by == "user":
        return KindChange(False, None)
    route = routing.route(kind, USER_CONFIDENCE)
    page.page_kind, page.page_kind_confidence, page.route = kind, USER_CONFIDENCE, route
    # The kind is now the person's, but the title block and the tag reading on the page are still the model's.
    # If the stand-in read them, keep its mark, so a run on the real model reads the page again (BUG-042).
    stand_in = page.model is not None and page.model.startswith(STAND_IN_PREFIX)
    page.classified_by, page.model = "user", page.model if stand_in else None
    quote = session.scalar(select(m.Quote).where(m.Quote.drawing_id == drawing_id))
    session.add(
        m.CorrectionEvent(
            id=new_id("evt"),
            tenant_id=tenant_id,
            quote_id=quote.id if quote else None,
            quote_version=quote.current_version if quote else None,
            user_id=user_id,
            source="new_quote",
            type="page_reclassified",
            page_id=page_id,
            before=before,
            after={"page_kind": kind, "route": route, "confidence": USER_CONFIDENCE},
        )
    )
    if kind == "factory_template":
        _save_template(session, storage, tenant_id, drawing, page)
    session.flush()
    panels = _rebuild_panels(session, tenant_id, drawing)
    _rewrite_intake(session, storage, tenant_id, drawing, panels)
    changed = before["route"] != route
    message = coordinator.rerun(session, tenant_id, drawing_id) if changed and drawing.status == "ready" else None
    return KindChange(changed, message)


def _save_template(session: Session, storage: Storage, tenant_id: str, drawing: m.Drawing, page: m.Page) -> None:
    file = session.get_one(m.DrawingFile, page.file_id)
    if file.detected_format in ("xlsx", "csv"):
        return
    data = storage.get(tenant_id, file.storage_key)
    read = read_pages(file.id, file.detected_format, data)[page.page_no - 1]
    read.extra_rotation = (page.rotation_applied - read.rotation) % 360
    fp = templates.fingerprint(render(read, data, 1024))
    _, regions = classify.from_stored(page.regions)
    block = next((r for r in regions if r.region_kind == "title_block"), None)
    w, h = page.width_pt or 1.0, page.height_pt or 1.0
    mask = [block.bbox[0] / w, block.bbox[1] / h, block.bbox[2] / w, block.bbox[3] / h] if block else None
    producer = templates.producer_key((drawing.title_block or {}).get("designer"))
    templates.save(session, tenant_id, page.id, producer, fp, mask)


def _rebuild_panels(session: Session, tenant_id: str, drawing: m.Drawing) -> list[tuple[str, Any]]:
    """The panels again from every page's stored findings, keeping the ids of panels whose name stays."""
    pages = session.scalars(select(m.Page).where(m.Page.drawing_id == drawing.id).order_by(m.Page.page_no)).all()
    found = [
        PagePanels(
            p.id, p.route or "process", [(f.name, f.bbox, f.confidence) for f in classify.from_stored(p.regions)[0]]
        )
        for p in pages
    ]
    if drawing.input_kind in ("factory_drawing", "designer_plan"):  # a page's kind decides it (01 §4.4, S28b)
        factory = is_factory_set([p.page_kind or "" for p in pages])
        drawing.input_kind = "factory_drawing" if factory else "designer_plan"
    merged = merge_panels(
        found, (drawing.title_block or {}).get("panel_name"), one_panel=drawing.input_kind == "factory_drawing"
    )
    if not merged and drawing.input_kind == "bom_only":
        artifacts = session.scalars(
            select(m.ContextArtifact).where(
                m.ContextArtifact.drawing_id == drawing.id, m.ContextArtifact.kind == "bom_table"
            )
        ).all()
        tables = [(a.page_id, bom_table.BomTable.model_validate_json(a.content)) for a in artifacts if a.page_id]
        named = bom_table.panels(sorted(tables), (drawing.title_block or {}).get("panel_name"))
        merged = [MergedPanel(name=name, page_ids=pages) for name, pages in named]
    existing = {name_key(p.name): p for p in session.scalars(select(m.Panel).where(m.Panel.drawing_id == drawing.id))}
    out: list[tuple[str, Any]] = []
    for mp in merged:
        row = existing.pop(name_key(mp.name), None)
        if row is None:
            row = m.Panel(id=new_id("pnl"), tenant_id=tenant_id, drawing_id=drawing.id, name=mp.name)
            session.add(row)
        row.page_ids, row.bboxes, row.confidence = mp.page_ids, mp.bboxes, mp.confidence
        out.append((row.id, mp))
    for gone in existing.values():  # no page of its own left (stages 2–7 run again before anything points at it)
        session.delete(gone)
    session.flush()
    return out


def _kept(panel_id: str | None, ids: dict[str, str]) -> str | None:
    return panel_id if panel_id in ids.values() else None


def _rewrite_intake(
    session: Session, storage: Storage, tenant_id: str, drawing: m.Drawing, panels: list[tuple[str, Any]]
) -> None:
    run = session.get_one(m.StageRun, (tenant_id, drawing.id, 1))
    if run.output_key is None:
        return
    intake = IntakeResult.model_validate_json(storage.get(tenant_id, run.output_key))
    rows = {p.id: p for p in session.scalars(select(m.Page).where(m.Page.drawing_id == drawing.id))}
    ids = {name_key(mp.name): pid for pid, mp in panels}
    # A factory drawing's one panel (S28b decision 1) takes the references of the parts it replaced.
    only = next(iter(ids.values())) if drawing.input_kind == "factory_drawing" and len(ids) == 1 else None

    def kept(ref: str | None) -> str | None:
        return ref if ref in ids.values() else (only if ref else None)

    pages = []
    for page in intake.pages:
        row = rows[page.page_id]
        found, _ = classify.from_stored(row.regions)
        owned = [
            PagePanel(panel_id=pid, name=mp.name, bbox=f.bbox, confidence=f.confidence)
            for f in found
            for pid, mp in panels
            if list(f.bbox) in mp.bboxes.get(page.page_id, [])
        ]
        other = [r for r in page.regions if r.region_kind != "panel"]
        pages.append(
            page.model_copy(
                update={
                    "page_kind": row.page_kind,
                    "page_kind_confidence": row.page_kind_confidence,
                    "route": row.route,
                    "classified_by": row.classified_by,
                    "model": row.model,
                    "panels": owned,
                    "regions": [Region(region_kind="panel", bbox=p.bbox, panel_ref=p.panel_id) for p in owned]
                    + [r.model_copy(update={"panel_ref": kept(r.panel_ref)}) for r in other],
                }
            )
        )
    reasons = routing.confirmation_reasons(
        [routing.RoutedPage(p.page_kind, p.page_kind_confidence, p.classified_by) for p in pages], len(panels)
    )
    stored = {
        a.id: a for a in session.scalars(select(m.ContextArtifact).where(m.ContextArtifact.drawing_id == drawing.id))
    }
    if only:  # a notes block of a part now belongs to the one panel
        for art in stored.values():
            content = json.loads(art.content) if art.kind == "notes_block" else None
            if content and content.get("panel_id") and content["panel_id"] != only:
                art.content = json.dumps({**content, "panel_id": only}, ensure_ascii=False, sort_keys=True)
    artifacts = [
        a.model_copy(update={"content": stored[a.artifact_id].content}) if a.artifact_id in stored else a
        for a in intake.context_artifacts
    ]
    if bom_review.needs_user(session, tenant_id, artifacts):
        reasons.append("bom_mapping")
    updated = intake.model_copy(
        update={
            "pages": pages,
            "panels": [Panel(panel_id=pid, name=mp.name, page_ids=mp.page_ids) for pid, mp in panels],
            "context_artifacts": artifacts,
            "needs_confirmation": bool(reasons),
            "input_kind": drawing.input_kind,
        }
    )
    storage.put(tenant_id, run.output_key, updated.model_dump_json().encode(), "application/json")
    issues = [i for i in drawing.issues if i.get("code") != "needs_confirmation"]
    if reasons:
        issues.append({"code": "needs_confirmation", "severity": "info", "stage": 1, "reasons": reasons})
    drawing.issues = issues


def _bom_artifact(session: Session, drawing_id: str, page_id: str) -> m.ContextArtifact:
    row = session.scalar(
        select(m.ContextArtifact).where(
            m.ContextArtifact.drawing_id == drawing_id,
            m.ContextArtifact.page_id == page_id,
            m.ContextArtifact.kind == "bom_table",
        )
    )
    if row is None:
        raise LookupError(page_id)
    return row


def set_bom_columns(
    session: Session,
    storage: Storage,
    tenant_id: str,
    user_id: str,
    drawing_id: str,
    page_id: str,
    roles: dict[int, Role],
) -> KindChange:
    """The user's roles for a spreadsheet's columns. Settled when it has one item and one quantity column. On a
    finished drawing stages 2–7 run again, as after a page-kind change."""
    drawing = _lock(session, tenant_id, drawing_id)
    row = _bom_artifact(session, drawing_id, page_id)
    table = bom_table.BomTable.model_validate_json(row.content)
    if table.source != "spreadsheet" or any(i not in {c.index for c in table.columns} for i in roles):
        raise LookupError(page_id)
    before = {c.letter: c.role for c in table.columns}
    updated = bom_table.with_roles(table, roles)
    updated = updated.model_copy(update={"mapping_sure": bom_table.mapping_complete(updated)})
    row.content = updated.model_dump_json()
    quote = session.scalar(select(m.Quote).where(m.Quote.drawing_id == drawing_id))
    session.add(
        m.CorrectionEvent(
            id=new_id("evt"),
            tenant_id=tenant_id,
            quote_id=quote.id if quote else None,
            quote_version=quote.current_version if quote else None,
            user_id=user_id,
            source="new_quote",
            type="bom_columns_mapped",
            page_id=page_id,
            before=before,
            after={c.letter: c.role for c in updated.columns},
        )
    )
    session.flush()
    panels = _rebuild_panels(session, tenant_id, drawing)
    _rewrite_intake(session, storage, tenant_id, drawing, panels)
    message = coordinator.rerun(session, tenant_id, drawing_id) if drawing.status == "ready" else None
    return KindChange(False, message)


def settle_bom_mappings(session: Session, storage: Storage, tenant_id: str, drawing_id: str) -> None:
    """On "אשר והמשך": the user saw every unsure mapping, so they are settled, unless one would read no product
    (`BomMappingIncompleteError`). With `bom_column_mapping` off the user was shown none, and nothing changes."""
    if not bom_review.flag_on(session, tenant_id):
        return
    rows = session.scalars(
        select(m.ContextArtifact).where(
            m.ContextArtifact.drawing_id == drawing_id, m.ContextArtifact.kind == "bom_table"
        )
    ).all()
    artifacts = [
        ContextArtifact(artifact_id=r.id, page_id=r.page_id, kind=r.kind, format=r.format, content=r.content)  # type: ignore[arg-type]
        for r in rows
    ]
    missing = bom_review.incomplete(artifacts)
    if missing:
        raise BomMappingIncompleteError(missing)
    open_ = {a.artifact_id for a, _ in bom_review.unsure(artifacts)}
    if not open_:
        return
    for r in rows:
        if r.id in open_:
            r.content = (
                bom_table.BomTable.model_validate_json(r.content)
                .model_copy(update={"mapping_sure": True})
                .model_dump_json()
            )
    session.flush()
    drawing = session.get_one(m.Drawing, drawing_id)
    _rewrite_intake(session, storage, tenant_id, drawing, _rebuild_panels(session, tenant_id, drawing))
