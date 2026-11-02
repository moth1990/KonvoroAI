"""Audits for the API (11 §6–8): read one, record the user's decision on a difference, and turn an audit into a
corrected quote in the system.

Runs inside `tenant_session`; the explicit `tenant_id` filters are a second guard, as in `quotes.py`.

The corrected quote (11 §8, S15 decision 5):
1. every line of the audited quote, at its own price, as a manual line (green with a price, red without one);
2. for each confirmed difference: a missing item or a short quantity adds its suggested line, at the price 11 §5.5
   found (yellow) or none (red); an attribute mismatch replaces its line with the drawn product at the line's own
   price unless a better one was found; an over-count or a double count lowers its line's quantity to the drawing's.
   Arithmetic needs nothing: each line's total is quantity × unit price again (07 §7.6).
The quote is linked to the drawing, opens on the review screen (09), and is made once: asking again returns it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.models.learning import REJECT_REASONS
from konboro.services import quotes

Decision = Literal["open", "confirmed", "rejected"]


class AuditNotReadyError(Exception):
    pass


class RejectReasonError(ValueError):
    pass


@dataclass(frozen=True)
class AuditView:
    audit: m.Audit
    drawing: m.Drawing
    quote_file: m.DrawingFile | None
    lines: list[m.AuditQuoteLine]
    differences: list[m.AuditDifference]


TYPE_ORDER = (
    "missing_in_quote",
    "qty_short",
    "attribute_mismatch",
    "arithmetic",
    "possible_double_count",
    "qty_over",
    "extra_in_quote",
    "drawing_conflict",
    "not_a_difference",
)


def _get(session: Session, tenant_id: str, audit_id: str) -> m.Audit | None:
    return session.scalar(select(m.Audit).where(m.Audit.tenant_id == tenant_id, m.Audit.id == audit_id))


def read_audit(session: Session, tenant_id: str, audit_id: str) -> AuditView | None:
    audit = _get(session, tenant_id, audit_id)
    if audit is None:
        return None
    drawing = session.scalars(
        select(m.Drawing).where(m.Drawing.tenant_id == tenant_id, m.Drawing.id == audit.drawing_id)
    ).one()
    quote_file = session.scalar(
        select(m.DrawingFile).where(m.DrawingFile.tenant_id == tenant_id, m.DrawingFile.id == audit.quote_file_id)
    )
    lines = list(
        session.scalars(
            select(m.AuditQuoteLine)
            .where(m.AuditQuoteLine.tenant_id == tenant_id, m.AuditQuoteLine.audit_id == audit_id)
            .order_by(m.AuditQuoteLine.line_index)
        )
    )
    differences = list(
        session.scalars(
            select(m.AuditDifference).where(
                m.AuditDifference.tenant_id == tenant_id, m.AuditDifference.audit_id == audit_id
            )
        )
    )
    # 11 §7: what the quote leaves out first, then by confidence; below 0.6 apart (the screen groups them)
    differences.sort(key=lambda d: (TYPE_ORDER.index(d.type), -d.confidence, d.quote_line_index or 0, d.id))
    return AuditView(audit, drawing, quote_file, lines, differences)


def decide(
    session: Session,
    tenant_id: str,
    audit_id: str,
    diff_id: str,
    user_id: str,
    status: Decision,
    reason: str | None = None,
    note: str | None = None,
) -> m.AuditDifference | None:
    """11 §7: "נכון, זה הבדל" (`confirmed`), "לא נכון" with a reason (`rejected`), or back to `open`. Nothing in the
    quote changes (11 §1 principle 2)."""
    diff = session.scalar(
        select(m.AuditDifference).where(
            m.AuditDifference.tenant_id == tenant_id,
            m.AuditDifference.audit_id == audit_id,
            m.AuditDifference.id == diff_id,
        )
    )
    if diff is None:
        return None
    if status == "rejected" and reason not in REJECT_REASONS:
        raise RejectReasonError(reason)
    diff.status = status
    diff.reject_reason = reason if status == "rejected" else None
    diff.reject_note = (note or "").strip() or None if status == "rejected" else None
    diff.decided_by = user_id if status != "open" else None
    diff.decided_at = datetime.now(UTC) if status != "open" else None
    session.flush()
    return diff


def corrected_quote(session: Session, tenant_id: str, audit_id: str) -> tuple[str, bool] | None:
    """The quote's id, and whether it was made now. None: no such audit."""
    view = read_audit(session, tenant_id, audit_id)
    if view is None:
        return None
    audit = view.audit
    if audit.corrected_quote_id:
        return audit.corrected_quote_id, False
    if audit.status != "ready":
        raise AuditNotReadyError(audit.status)

    confirmed = [d for d in view.differences if d.status == "confirmed"]
    by_line = {d.quote_line_index: d for d in confirmed if d.quote_line_index is not None}
    panel_id = session.scalar(
        select(m.Panel.id).where(m.Panel.tenant_id == tenant_id, m.Panel.drawing_id == audit.drawing_id).limit(1)
    )
    number = (audit.quote_ref or {}).get("number")
    project = session.get(m.Project, view.drawing.project_id) if view.drawing.project_id else None
    name = f"הצעה {number}, מתוקנת" if number else ((project.name if project else "") or "הצעה מתוקנת")
    quote = m.Quote(
        id=new_id("quo"),
        tenant_id=tenant_id,
        drawing_id=audit.drawing_id,
        project_id=view.drawing.project_id,
        name=name,
    )
    session.add(quote)
    session.flush()
    version = m.QuoteVersion(
        id=new_id("qv"), tenant_id=tenant_id, quote_id=quote.id, version=1, quote_date=datetime.now(UTC).date()
    )
    session.add(version)
    session.flush()

    rows: list[quotes.LineIn] = []
    for ln in view.lines:
        d = by_line.get(ln.line_index)
        qty = ln.qty if ln.qty is not None else Decimal(1)
        description, price = ln.description, ln.unit_price
        if price is None and ln.line_total is not None and ln.qty:
            price = ln.line_total / ln.qty
        if d is not None and d.type in ("qty_over", "possible_double_count") and d.drawing_qty is not None:
            qty = d.drawing_qty
        if d is not None and d.type == "attribute_mismatch" and d.suggested_line:
            description = d.suggested_line["description"]
            found = d.suggested_line.get("unit_price")
            price = Decimal(found) if found is not None else price
        if qty <= 0:
            continue
        rows.append(_manual(f"q{ln.line_index}", description, qty, price, "green" if price is not None else "red"))
    for d in confirmed:
        s = d.suggested_line
        if d.type not in ("missing_in_quote", "qty_short") or not s:
            continue
        price = Decimal(s["unit_price"]) if s.get("unit_price") is not None else None
        rows.append(
            _manual(f"d{d.id}", s["description"], Decimal(s["qty"]), price, "yellow" if price is not None else "red")
        )
    quotes.write_lines(session, version, panel_id, rows)
    quotes.store_totals(session, version)
    audit.corrected_quote_id = quote.id
    session.flush()
    return quote.id, True


def _manual(key: str, description: str, qty: Decimal, price: Decimal | None, status: str) -> quotes.LineIn:
    return quotes.LineIn(
        key=key,
        description=description,
        qty=qty,
        status=status,
        line_type="manual",
        unit_price=price,
        price_status="ok" if price is not None else "missing",
        explanation="מההצעה הקיימת" if key.startswith("q") else "הבדל שאושר בבדיקת ההצעה",
    )
