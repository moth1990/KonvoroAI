"""A quote's versions (07 §7.7): send and lock, recalculate, open the next version. Services only: S23's routes and
buttons call them (S22 decision 4).

| Action | Version |
| --- | --- |
| an edit before sending | the current draft changes (S23) |
| send to the customer | the version is locked (`sent`); the trigger rejects any later change to it or its lines |
| recalculate a draft (after a price-list change) | the draft is priced again in place, keeping the user's |
| | edits; `preview_recalculation` shows the comparison first (07 §7.2.3) |
| recalculate a sent version | version N+1, priced anew, with `diff_from_previous` (07 §7.7) |
| open version N+1 | a draft copy of the sent version, unpriced again ("פתח גרסה N+1", prototype line 961) |

Runs inside `tenant_session`; the explicit `tenant_id` filters are a second guard.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.pipeline.pricing import run as pricing
from konboro.services import quotes as qs
from konboro.services.storage import Storage

COPIED = (
    "panel_id",
    "position",
    "line_key",
    "line_group",
    "line_type",
    "component_id",
    "catalog_item_id",
    "product_id",
    "sku",
    "description",
    "manufacturer",
    "qty",
    "unit",
    "unit_cost",
    "cost_source",
    "price_status",
    "margin_rule",
    "unit_price_raw",
    "unit_price",
    "rounding",
    "line_cost",
    "line_total",
    "margin_pct",
    "derived",
    "alternatives",
    "explanation",
    "status",
    "status_reasons",
    "issue_ids",
    "override",
    "approved_at",
    "deleted_at",
)


class VersionError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    user_id: str


def current(session: Session, tenant_id: str, quote_id: str) -> tuple[m.Quote, m.QuoteVersion]:
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id))
    if quote is None:
        raise VersionError(404, "not_found")
    version = session.scalar(
        select(m.QuoteVersion).where(
            m.QuoteVersion.tenant_id == tenant_id,
            m.QuoteVersion.quote_id == quote_id,
            m.QuoteVersion.version == quote.current_version,
        )
    )
    if version is None:
        raise VersionError(404, "not_found")
    return quote, version


def send(session: Session, actor: Actor, quote_id: str) -> m.QuoteVersion:
    """Locks the current version (07 §7.7). Whether an open `error` blocks sending is S23's (06 §13 item 3)."""
    quote, version = current(session, actor.tenant_id, quote_id)
    if version.status == "sent":
        raise VersionError(409, "quote_sent")
    version.status = "sent"
    version.sent_at = datetime.now(UTC)
    version.sent_by = actor.user_id
    session.add(
        m.CorrectionEvent(
            id=new_id("evt"),
            tenant_id=actor.tenant_id,
            quote_id=quote.id,
            quote_version=version.version,
            user_id=actor.user_id,
            source="review_screen",
            type="quote_sent",
            after={"version": version.version, "net_total": (version.totals or {}).get("net_total")},
        )
    )
    session.flush()
    return version


def _drawing(session: Session, tenant_id: str, quote: m.Quote) -> m.Drawing:
    drawing = session.get(m.Drawing, quote.drawing_id) if quote.drawing_id else None
    if drawing is None or drawing.tenant_id != tenant_id:
        raise VersionError(409, "no_drawing")  # a quote built by hand or in chat has no stage outputs to price from
    return drawing


def recalculate(session: Session, storage: Storage, tenant_id: str, quote_id: str) -> pricing.Priced:
    """Prices the quote again with today's price list and rules: in place for a draft, as N+1 after a sent one."""
    quote, _ = current(session, tenant_id, quote_id)
    drawing = _drawing(session, tenant_id, quote)
    out = pricing.read_outputs(session, storage, tenant_id, drawing.id)
    return pricing.price_drawing(session, tenant_id, drawing, out, quote.name)


def preview_recalculation(session: Session, storage: Storage, tenant_id: str, quote_id: str) -> dict[str, Any]:
    """07 §7.2.3: what a recalculation would change, shown before it is approved. Nothing is written."""
    savepoint = session.begin_nested()
    try:
        return recalculate(session, storage, tenant_id, quote_id).diff
    finally:
        savepoint.rollback()


def open_next(session: Session, actor: Actor, quote_id: str) -> m.QuoteVersion:
    """ "פתח גרסה N+1": the sent version's lines, as they were, in a new draft. Nothing is priced again: the user
    edits from what the customer saw; `recalculate` reprices on request."""
    quote, sent = current(session, actor.tenant_id, quote_id)
    if sent.status != "sent":
        raise VersionError(409, "quote_draft")
    version = m.QuoteVersion(
        id=new_id("qv"),
        tenant_id=actor.tenant_id,
        quote_id=quote.id,
        version=sent.version + 1,
        quote_date=datetime.now(UTC).date(),
        currency=sent.currency,
        discount_pct=sent.discount_pct,
        snapshot=sent.snapshot,
        diff_from_previous={"from_version": sent.version, "lines": [], "copied": True},
    )
    session.add(version)
    session.flush()
    rows = list(
        session.scalars(
            select(m.QuoteLine)
            .where(m.QuoteLine.tenant_id == actor.tenant_id, m.QuoteLine.quote_version_id == sent.id)
            .order_by(m.QuoteLine.position)
        )
    )
    ids = {r.id: new_id("ln") for r in rows}
    findings = list(
        session.scalars(
            select(m.Finding).where(m.Finding.tenant_id == actor.tenant_id, m.Finding.quote_version_id == sent.id)
        )
    )
    # pricing's findings belong to the version: copied under ids of the new one; stage 6's follow the drawing's
    # current version (S21 decision 1), so they move
    renamed = {
        f.id: "iss_" + hashlib.sha256(f"{version.id}|{f.id}".encode()).hexdigest()[:24]
        for f in findings
        if f.source == "pricing"
    }
    for r in sorted(rows, key=lambda r: r.parent_line_id is not None):  # parents first, for the foreign key
        values = {c: getattr(r, c) for c in COPIED}
        values["issue_ids"] = [renamed.get(i, i) for i in r.issue_ids]
        session.add(
            m.QuoteLine(
                id=ids[r.id],
                tenant_id=actor.tenant_id,
                quote_version_id=version.id,
                parent_line_id=ids.get(r.parent_line_id) if r.parent_line_id else None,
                **values,
            )
        )
        session.flush()
    for f in findings:
        line_ids = [ids[i] for i in f.line_ids if i in ids]
        if f.source != "pricing":
            f.quote_version_id, f.line_ids = version.id, line_ids
            continue
        copy = {
            c.key: getattr(f, c.key) for c in m.Finding.__table__.columns if c.key not in ("created_at", "updated_at")
        }
        session.add(m.Finding(**{**copy, "id": renamed[f.id], "quote_version_id": version.id, "line_ids": line_ids}))
    quote.current_version = version.version
    qs.store_totals(session, version)
    session.flush()
    return version
