"""The match memory's writes (05 §11): approving a line with its SKU unchanged strengthens it (S23), and a chat proposal
approved with "לזכור ללקוח הזה" or "לזכור למפעל" writes it (08 §7.4, S25b; `review.save_memory`). A SKU swapped in a
row is for that quote only (09 §7). Stage 5 reads the memory
(`pipeline/matching/factory.py`); nothing else writes it.

A memory belongs to one factory, and to one of its customers or all of them (`customer_id` null). It never leaves the
tenant (05 §11: only facts about the catalog itself go to the shared layer, through the approval queue).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id


def find(
    session: Session, tenant_id: str, signature: str, customer_id: str | None, brand_context: str | None
) -> m.MatchMemory | None:
    """The memory for this signature in this context, for this customer or all of them (`customer_id` None)."""
    return _row(session, tenant_id, signature, customer_id, brand_context)


def _row(
    session: Session, tenant_id: str, signature: str, customer_id: str | None, brand_context: str | None
) -> m.MatchMemory | None:
    query = select(m.MatchMemory).where(m.MatchMemory.tenant_id == tenant_id, m.MatchMemory.signature == signature)
    query = query.where(
        m.MatchMemory.customer_id.is_(None) if customer_id is None else m.MatchMemory.customer_id == customer_id
    )
    query = query.where(
        m.MatchMemory.brand_context.is_(None) if brand_context is None else m.MatchMemory.brand_context == brand_context
    )
    return session.scalar(query)


def remember(
    session: Session,
    tenant_id: str,
    signature: str,
    sku: str,
    customer_id: str | None = None,
    brand_context: str | None = None,
) -> m.MatchMemory:
    """A swap or a pick: from the next drawing, this signature in this context gets this SKU (05 §11, "מיידי"). A
    different SKU than the one remembered replaces it and starts its count again."""
    now = datetime.now(UTC)
    row = _row(session, tenant_id, signature, customer_id, brand_context)
    if row is None:
        row = m.MatchMemory(
            id=new_id("mm"),
            tenant_id=tenant_id,
            customer_id=customer_id,
            signature=signature,
            brand_context=brand_context,
            sku=sku,
            approved_count=1,
            last_used_at=now,
        )
        session.add(row)
    elif row.sku != sku:
        row.sku, row.approved_count, row.last_used_at = sku, 1, now
    else:
        row.last_used_at = now
    session.flush()
    return row


def approve(
    session: Session,
    tenant_id: str,
    signature: str,
    sku: str,
    customer_id: str | None = None,
    brand_context: str | None = None,
) -> m.MatchMemory | None:
    """A quote approved with the line unchanged strengthens the memory that chose it (`approved_count`); a line the
    memory did not choose leaves it as it is."""
    row = _row(session, tenant_id, signature, customer_id, brand_context)
    if row is None or row.sku != sku:
        return None
    row.approved_count += 1
    row.last_used_at = datetime.now(UTC)
    session.flush()
    return row


def rows_for(
    session: Session, tenant_id: str, signature: str, sku: str, customer_id: str | None = None
) -> list[m.MatchMemory]:
    """The memories that chose `sku` for `signature`: the factory's and this customer's, in any brand context."""
    query = select(m.MatchMemory).where(
        m.MatchMemory.tenant_id == tenant_id, m.MatchMemory.signature == signature, m.MatchMemory.sku == sku
    )
    rows = session.scalars(query)
    return [r for r in rows if r.customer_id is None or r.customer_id == customer_id]


def approve_all(
    session: Session, tenant_id: str, signature: str, sku: str, customer_id: str | None = None
) -> list[m.MatchMemory]:
    """09 §7.2 "אישור שורה" (`row_confirmed`): every memory that chose this line's SKU is strengthened. The review
    screen knows the line's signature, not the brand context stage 5 looked it up in."""
    rows = rows_for(session, tenant_id, signature, sku, customer_id)
    at = datetime.now(UTC)
    for row in rows:
        row.approved_count += 1
        row.last_used_at = at
    session.flush()
    return rows
