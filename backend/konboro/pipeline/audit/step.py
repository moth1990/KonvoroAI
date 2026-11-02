"""The audit step (11 §5, S15 decision 2): after stage 4 of a drawing uploaded for an audit, compare the factory's
own quote with the drawing's components, and write the audit.

1. The drawing side: stage 4's components that go in the panel (04 §5.1.2 `in_panel`), with their written values,
   where each instance is drawn (stage 1's page numbers), and the values that disagree inside the drawing.
2. The quote side (`quote.py`): the file uploaded as `audited_quote`, read in code or, for a picture or a scan,
   through `table_transcription.transcribe_quote` (S15 decision 1).
3. Matching, differences and money in code (`differences.audit`), with the tenant's auxiliary families.
4. The rows: `audits` (quote reference, summary, `ready`), `audit_quote_lines`, `audit_differences`. A rerun
   replaces them; a difference the user already decided keeps its decision when the same difference comes back.
"""

import io
import logging
from datetime import UTC, datetime
from typing import Any

import pdfplumber
from sqlalchemy import delete, select

from konboro.contracts.audit import AuditResult, QuoteRef
from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import MergeResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro_llm import ImageInput, LLMClient
from konboro_llm.stages import table_transcription

from ..bom import sheets as bom_sheets
from ..context import StageContext
from ..extraction.vector import visual_to_logical
from ..intake.pages import png, read_pages, render
from . import quote as q
from .differences import Outcome, audit
from .match import DrawnComponent

log = logging.getLogger(__name__)

DETAIL_PX = 1568  # as stage 1 reads a BOM page (s1_intake.DETAIL_PX)
TEXT_LAYER_CHARS = 40  # fewer characters than this on a page: read it from its picture


def drawn_components(page_no: dict[str, int], merge: MergeResult) -> list[DrawnComponent]:
    """`page_no`: stage 1's page id → page number."""
    instances = {i.instance_id: i for i in merge.instances}
    out: list[DrawnComponent] = []
    for c in merge.components:
        if c.supply_scope != "in_panel":
            continue  # supplied elsewhere or by others: no quote line expected (04 §5.1.2)
        own = [instances[i] for i in c.instance_ids if i in instances]
        conflicts: list[str] = []
        for i in own:
            for issue in i.issues:
                if issue.code == "attribute_conflict":
                    names = _conflict_names(issue.message) or ["values"]
                    conflicts += [n for n in names if n not in conflicts]
        out.append(
            DrawnComponent(
                component_id=c.component_id,
                family=c.family,
                cls=c.symbol_class,
                values={k: a.value for k, a in c.attributes.items() if a.value is not None},
                quantity=c.quantity,
                designators=list(c.designators),
                confidence=c.confidence,
                instances=[(i.instance_id, page_no.get(i.page_id, 0)) for i in own],
                conflicts=conflicts,
                texts=list(c.explicit_texts),
            )
        )
    return out


def _conflict_names(message: str) -> list[str]:
    """The attribute names stage 4 put in its `attribute_conflict` message ("… עבור poles, current_a. נבחר: …")."""
    head = message.split("עבור", 1)[-1].split(".", 1)[0]
    return [n.strip() for n in head.split(",") if n.strip().isidentifier()]


def read_quote(ctx: StageContext, file: m.DrawingFile) -> q.QuoteRead:
    data = ctx.storage.get(ctx.tenant_id, file.storage_key)
    return read_quote_bytes(ctx.llm, ctx.tenant_id, file.detected_format, data, file.id, file.sha256)


def read_quote_bytes(llm: LLMClient, tenant_id: str, fmt: str, data: bytes, file_id: str, sha256: str) -> q.QuoteRead:
    """The quote file's pages, each read the cheapest way it can be (module docstring of `quote.py`). The eval
    calls this too, on the golden quotes (S15)."""
    if fmt in ("xlsx", "csv"):
        try:
            sheets = bom_sheets.read(fmt, data)
        except bom_sheets.UnreadableSheetError:
            return q.QuoteRead(source="spreadsheet", issues=["quote_unreadable"])

        def ask(columns: str) -> table_transcription.MappingAnswer:
            return table_transcription.map_columns(llm, columns, tenant_id=tenant_id).data

        return q.join([q.from_sheet(sheet, ask) for sheet in sheets if sheet.rows])
    pages: list[q.QuoteRead] = []
    for read in read_pages(file_id, fmt, data):
        table = _text_table(data, read.index) if fmt == "pdf" and read.chars >= TEXT_LAYER_CHARS else None
        if table is not None:
            pages.append(table)
            continue
        image = ImageInput(png(render(read, data, DETAIL_PX)), key=f"{sha256}:{read.page_no}:{DETAIL_PX}")
        answer = table_transcription.transcribe_quote(llm, image, tenant_id=tenant_id)
        first = sum(len(p.lines) for p in pages) + 1
        pages.append(q.from_answer(answer.data, read.size_pt, read.page_no, first))
    return q.join(pages)


def _text_table(data: bytes, index: int) -> q.QuoteRead | None:
    """A PDF page's own table, read in code (pdfplumber, its words in reading order)."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:  # pdfminer, not PDFium: no lock (BUG-010)
        page = pdf.pages[index]
        tables = page.extract_tables()
        text = page.extract_text() or ""
    above = [visual_to_logical(line) for line in text.splitlines()]
    for t in sorted(tables, key=len, reverse=True):
        rows = [[visual_to_logical(c) if c else None for c in r] for r in t]
        read = q.from_text_table(rows, above)
        if read is not None and read.lines:
            return read
    return None


def run(ctx: StageContext) -> AuditResult:
    s, d = ctx.session, ctx.drawing
    intake = ctx.output(1, IntakeResult)
    merge = ctx.output(4, MergeResult)
    record = s.scalars(select(m.Audit).where(m.Audit.drawing_id == d.id)).one()
    file = s.scalars(
        select(m.DrawingFile).where(m.DrawingFile.id == record.quote_file_id, m.DrawingFile.drawing_id == d.id)
    ).one()
    read = read_quote(ctx, file)
    settings = s.get(m.TenantSettings, ctx.tenant_id)
    auxiliary = frozenset(settings.auxiliary_families if settings else ("terminal",))
    pages = {p.page_id: p.page_no for p in intake.pages}
    outcome = audit(read, drawn_components(pages, merge), auxiliary)
    ref = QuoteRef(number=read.number, date=read.date, total_before_vat=read.total_before_vat)
    _store(ctx, record, outcome, ref, intake.input_kind, read.issues)
    return AuditResult(
        audit_id=record.id,
        tenant_id=ctx.tenant_id,
        drawing_id=d.id,
        quote_ref=ref,
        input_kind=intake.input_kind,
        summary=outcome.summary,
        differences=outcome.differences,
        lines=outcome.lines,
        issues=read.issues,
        trace_id=ctx.trace_id,
    )


def _key(d: m.AuditDifference | Any) -> tuple[Any, ...]:
    return (d.type, tuple(sorted(d.designators or [])), d.quote_line_index)


def _store(
    ctx: StageContext, record: m.Audit, outcome: Outcome, ref: QuoteRef, input_kind: str | None, issues: list[str]
) -> None:
    s = ctx.session
    decided = {
        _key(old): old
        for old in s.scalars(select(m.AuditDifference).where(m.AuditDifference.audit_id == record.id))
        if old.status != "open"
    }
    s.execute(delete(m.AuditDifference).where(m.AuditDifference.audit_id == record.id))
    s.execute(delete(m.AuditQuoteLine).where(m.AuditQuoteLine.audit_id == record.id))
    s.flush()
    for ln in outcome.lines:
        s.add(
            m.AuditQuoteLine(
                id=new_id("aql"),
                tenant_id=ctx.tenant_id,
                audit_id=record.id,
                line_index=ln.index,
                description=ln.text,
                qty=ln.qty,
                unit_price=ln.unit_price,
                line_total=ln.total,
                confidence=ln.confidence,
                page_no=ln.page_no,
                rows=ln.rows,
                bbox=list(ln.bbox) if ln.bbox else None,
                signature=ln.signature,
                status=ln.status,
                component_ids=ln.component_ids,
                matched_qty=ln.matched_qty,
            )
        )
    for diff in outcome.differences:
        before = decided.get(_key(diff))
        s.add(
            m.AuditDifference(
                id=diff.diff_id,
                tenant_id=ctx.tenant_id,
                audit_id=record.id,
                type=diff.type,
                severity=diff.severity,
                confidence=diff.confidence,
                family=diff.family,
                designators=diff.designators,
                drawing_qty=diff.drawing_qty,
                quote_qty=diff.quote_qty,
                quote_line_index=diff.quote_line_index,
                evidence=[e.model_dump(mode="json") for e in diff.evidence],
                suggested_line=diff.suggested_line.model_dump(mode="json") if diff.suggested_line else None,
                message=diff.message,
                amount=diff.amount,
                component_ids=diff.component_ids,
                status=before.status if before else "open",
                reject_reason=before.reject_reason if before else None,
                reject_note=before.reject_note if before else None,
                decided_by=before.decided_by if before else None,
                decided_at=before.decided_at if before else None,
            )
        )
    record.quote_ref = ref.model_dump(mode="json")
    record.input_kind = input_kind
    record.summary = outcome.summary.model_dump(mode="json")
    record.issues = issues
    record.status = "ready"
    record.updated_at = datetime.now(UTC)
    s.flush()
