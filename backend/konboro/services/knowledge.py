"""The pilot approval queue (00 §14.2, S24): candidates for the shared layer, and their promotion.

A correction changes the factory's own layer at once. What could help every factory is queued here as a candidate,
and only the pilot engineer's explicit approval in the queue promotes it, through `konboro_promote` (migration 0020,
S24 decision 4): the app role never writes a global table itself.

What a candidate may carry is a whitelist per kind (`FIELDS`): the fields of the global record and nothing else, so
a price, a cost, a supplier, a customer, a project or a designer never reaches it (10 §11, 00 §9). The function
copies the same fields again on its side. `evidence` is the factory's own (its product's name, the quote it came
from), shown only in its queue and never copied.

S24 decision 3: real candidates come from the factory's products with a SKU and a brand that the master catalog does
not have (`propose_product`). The other kinds have the queue, the approval and the promotion, and their sources come
later. Runs inside `tenant_session`; the explicit `tenant_id` filters are a second guard.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain.flags import is_enabled
from konboro.services import flags

FLAG = "approval_queue"

KINDS = ("symbol", "abbreviation", "spelling", "catalog_item", "catalog_attribute")

# What each kind's global record takes. Nothing else is ever stored in a payload.
FIELDS: dict[str, tuple[str, ...]] = {
    "catalog_item": ("sku", "brand", "family", "series", "model_code", "symbol_class", "attributes"),
    "abbreviation": ("text", "symbol_class", "family", "display_he"),
    "spelling": ("pattern", "meaning_he", "family", "attribute"),
    "symbol": ("id", "family", "display_name_he", "billable"),
    "catalog_attribute": ("catalog_item_id", "name", "value"),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    "catalog_item": ("sku", "brand", "family"),
    "abbreviation": ("text",),
    "spelling": ("pattern", "meaning_he"),
    "symbol": ("id", "family", "display_name_he"),
    "catalog_attribute": ("catalog_item_id", "name", "value"),
}
# The id prefix of the record a promotion creates (docs/db-schema.md §7). A symbol class keeps its own id; an
# attribute fills an existing item.
PREFIX = {"catalog_item": "cat", "abbreviation": "abr", "spelling": "spl"}

# Never inside an item's attributes either: money and who it came from.
PRIVATE_KEYS = frozenset(
    {
        "price",
        "cost",
        "unit_cost",
        "unit_price",
        "list_price",
        "fixed_price",
        "margin",
        "discount",
        "supplier",
        "supplier_id",
        "supplier_sku",
        "customer",
        "customer_id",
        "project",
        "project_id",
        "designer",
        "tenant",
        "tenant_id",
    }
)

ORIGIN_HE = {
    "manual_entry": "הזנה ידנית",
    "supplier_price_list": "מחירון ספק",
    "quote_import": "ייבוא מהצעה",
    "brand_discount": "הנחת מותג",
}


class KnowledgeError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def clean_payload(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Only the kind's fields, without empty values; an item's attributes lose any private key."""
    if kind not in FIELDS:
        raise KnowledgeError(422, "unknown_kind")
    out: dict[str, Any] = {}
    for name in FIELDS[kind]:
        value = raw.get(name)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            continue
        if name == "attributes":
            if not isinstance(value, dict):
                raise KnowledgeError(422, "invalid_payload")
            value = {k: v for k, v in value.items() if k not in PRIVATE_KEYS}
            if not value:
                continue
        out[name] = value
    missing = [name for name in REQUIRED[kind] if name not in out]
    if missing:
        raise KnowledgeError(422, "invalid_payload")
    return out


def dedupe_key(kind: str, payload: dict[str, Any]) -> str:
    """The same thing proposed twice is one candidate: a SKU per brand, a text, a pattern, a class, an attribute."""
    if kind == "catalog_item":
        return f"{payload['brand'].upper()}|{payload['sku'].upper()}"
    if kind == "catalog_attribute":
        return f"{payload['catalog_item_id']}|{payload['name']}"
    field = {"abbreviation": "text", "spelling": "pattern", "symbol": "id"}[kind]
    return str(payload[field]).strip()


def what_he(kind: str, payload: dict[str, Any], evidence: dict[str, Any]) -> str:
    """The card's title (prototype `vQueue`): the factory's own wording when it gave one."""
    if evidence.get("what"):
        return str(evidence["what"])
    if kind == "catalog_item":
        return f"{payload['brand']} {payload['sku']}"
    if kind == "abbreviation":
        meaning = payload.get("display_he") or payload.get("family") or payload.get("symbol_class") or ""
        return f'"{payload["text"]}" ← {meaning}'.rstrip(" ←")
    if kind == "spelling":
        return f'"{payload["pattern"]}" ← {payload["meaning_he"]}'
    if kind == "symbol":
        return str(payload["display_name_he"])
    return f"{payload['name']} = {payload['value']}"


def propose(session: Session, tenant_id: str, kind: str, raw: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    """Queues a candidate unless the same one exists, pending or decided. Returns the new id, or None."""
    payload = clean_payload(kind, raw)
    cid = new_id("kc")
    inserted = session.execute(
        insert(m.KnowledgeCandidate)
        .values(
            id=cid,
            tenant_id=tenant_id,
            kind=kind,
            payload=payload,
            evidence=evidence,
            dedupe_key=dedupe_key(kind, payload),
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "kind", "dedupe_key"])
        .returning(m.KnowledgeCandidate.id)
    ).scalar()
    return inserted


def propose_product(session: Session, product: m.Product) -> str | None:
    """A factory product with a SKU and a brand that the master catalog lacks is a `catalog_item` candidate (10 §5.4:
    "מועמד לקטלוג המאסטר"). Its SKU, brand and family travel, and what "מוצר חדש" gave it (series, model, class,
    attributes; S27b); its name, price and suppliers stay."""
    if not is_enabled(flags.tenant_flags(session, product.tenant_id), FLAG):
        return None
    sku, brand = (product.manufacturer_sku or "").strip(), (product.brand or "").strip()
    if product.catalog_item_id is not None or not sku or not brand or brand in ("—", "-"):
        return None
    known = session.scalar(select(m.CatalogItem.id).where(m.CatalogItem.brand == brand, m.CatalogItem.sku == sku))
    if known is not None:
        return None
    evidence: dict[str, Any] = {
        "text": product.display_name,
        "origin": ORIGIN_HE.get(product.source, product.source),
        "product_id": product.id,
    }
    if product.entered_in_quote:
        evidence["quote_id"] = product.entered_in_quote
    payload: dict[str, Any] = {"sku": sku, "brand": brand, "family": product.family}
    # a product made in "מוצר חדש" travels with what defines it (S27b, 10 §5.4): never a price or a supplier
    for name in ("series", "model_code", "symbol_class"):
        if getattr(product, name, None):
            payload[name] = getattr(product, name)
    if product.attributes:
        payload["attributes"] = dict(product.attributes)
    return propose(session, product.tenant_id, "catalog_item", payload, evidence)


@dataclass(frozen=True)
class CandidateView:
    id: str
    kind: str
    what: str
    evidence: str
    origin: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    reason: str | None
    promoted: bool


def view(c: m.KnowledgeCandidate) -> CandidateView:
    ev = c.evidence or {}
    return CandidateView(
        id=c.id,
        kind=c.kind,
        what=what_he(c.kind, c.payload, ev),
        evidence=str(ev.get("text") or ""),
        origin=str(ev.get("origin") or ""),
        status=c.status,
        created_at=c.created_at,
        decided_at=c.decided_at,
        reason=c.reason,
        promoted=c.promoted_id is not None,
    )


def list_candidates(session: Session, tenant_id: str) -> list[CandidateView]:
    """Pending first, oldest first (the prototype's order); then the decided ones, newest decision first."""
    rows = session.scalars(select(m.KnowledgeCandidate).where(m.KnowledgeCandidate.tenant_id == tenant_id)).all()
    pending = sorted((r for r in rows if r.status == "pending"), key=lambda r: (r.created_at, r.id))
    decided = sorted(
        (r for r in rows if r.status != "pending"), key=lambda r: (r.decided_at or r.created_at, r.id), reverse=True
    )
    return [view(r) for r in (*pending, *decided)]


def _pending(session: Session, tenant_id: str, candidate_id: str) -> m.KnowledgeCandidate:
    row = session.scalar(
        select(m.KnowledgeCandidate)
        .where(m.KnowledgeCandidate.tenant_id == tenant_id, m.KnowledgeCandidate.id == candidate_id)
        .with_for_update()
    )
    if row is None:
        raise KnowledgeError(404, "not_found")
    if row.status != "pending":
        raise KnowledgeError(409, "already_decided")
    return row


def approve(session: Session, tenant_id: str, user_id: str, candidate_id: str) -> CandidateView:
    """Marks the candidate approved and promotes it in one step: if the global layer refuses it (another value
    for the same attribute), nothing changes and the candidate stays pending."""
    row = _pending(session, tenant_id, candidate_id)
    record_id = new_id(PREFIX[row.kind]) if row.kind in PREFIX else ""
    try:
        with session.begin_nested():
            row.status, row.decided_by, row.decided_at = "approved", user_id, datetime.now(UTC)
            session.flush()
            session.execute(text("SELECT konboro_promote(:c, :r)"), {"c": row.id, "r": record_id})
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) == "23505":
            raise KnowledgeError(409, "global_conflict") from e
        raise
    session.refresh(row)
    if row.kind == "catalog_item" and row.promoted_id:
        _link_product(session, tenant_id, row)
    return view(row)


def _link_product(session: Session, tenant_id: str, row: m.KnowledgeCandidate) -> None:
    """The factory's product now has a catalog item: stage 5 can match it, and the picker lists it once."""
    product_id = (row.evidence or {}).get("product_id")
    if not product_id:
        return
    product = session.scalar(select(m.Product).where(m.Product.tenant_id == tenant_id, m.Product.id == product_id))
    if product is not None and product.catalog_item_id is None:
        product.catalog_item_id = row.promoted_id
        session.flush()


def reject(session: Session, tenant_id: str, user_id: str, candidate_id: str, reason: str | None) -> CandidateView:
    """It stays with the factory ("נדחה · נשאר במפעל"); the shared layer is not touched."""
    row = _pending(session, tenant_id, candidate_id)
    row.status, row.decided_by, row.decided_at = "rejected", user_id, datetime.now(UTC)
    row.reason = (reason or "").strip() or None
    session.flush()
    session.refresh(row)
    return view(row)
