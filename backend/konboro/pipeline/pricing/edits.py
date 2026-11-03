"""What the estimator did on a line in the review screen (09 §7), applied to stage 7's draft of the line before it is
coloured (07 §7.5). Pure, like the engine.

A line's edits are carried by its key (S22 decision 5), through a recalculation and a rerun:

| Edit | Line |
| --- | --- |
| a quantity (09 §7.5) | `qty`; a kit's parts follow their device (05 §5.9.1) |
| an alternative (09 §7.3) | the SKU, maker and wording; the product is looked up again, the line priced anew |
| a supplier for this quote (07 §7.2.2 step 1) | the cost from that supplier; the sale price too when a rule makes it |
| an approval (09 §7.2) | green, tagged "אושר": every other reason is kept, as green, except the price's |
| a dismissed finding (09 §7.7) | the finding's reason leaves the line |

After an action the quote is priced again with every line the action did not touch keeping its price (`Kept`): a draft
never changes by itself when the price list does (07 §7.2.3), only the lines the estimator acted on do. A kept price
counts only for the same product and SKU; a line whose product changed is priced from the list.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from .book import NO_PRODUCT, Book, Priced, price
from .lines import NO_SKU, Draft

APPROVED: dict[str, Any] = {"source": "user", "value": "approved", "status": "green"}


@dataclass(frozen=True)
class Replaced:
    """The alternative chosen for the line (05 §5.9, 09 §7.3)."""

    sku: str | None
    manufacturer: str | None
    description: str
    catalog_item_id: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "catalog_item_id": self.catalog_item_id,
        }


@dataclass(frozen=True)
class LineEdits:
    qty: Decimal | None = None
    supplier_id: str | None = None
    replaced: Replaced | None = None
    approved_at: datetime | None = None

    @classmethod
    def of(cls, edits: Mapping[str, Any] | None, approved_at: datetime | None = None) -> "LineEdits":
        e = edits or {}
        r = e.get("replaced")
        return cls(
            qty=Decimal(str(e["qty"])) if e.get("qty") is not None else None,
            supplier_id=e.get("supplier_id"),
            replaced=Replaced(r.get("sku"), r.get("manufacturer"), r["description"], r.get("catalog_item_id"))
            if r
            else None,
            approved_at=approved_at,
        )

    def as_json(self) -> dict[str, Any]:
        """`quote_lines.edits`: what is set, and nothing else (the approval has its own column)."""
        out: dict[str, Any] = {}
        if self.qty is not None:
            out["qty"] = format(self.qty.normalize(), "f")
        if self.supplier_id is not None:
            out["supplier_id"] = self.supplier_id
        if self.replaced is not None:
            out["replaced"] = self.replaced.as_json()
        return out

    @property
    def empty(self) -> bool:
        return self == LineEdits()


@dataclass(frozen=True)
class Kept:
    """A line's price as stored, kept while its product and SKU stay the same."""

    product_id: str | None
    sku: str | None
    priced: Priced


def stored_reasons(reasons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A stored line's reasons back as stage 7 had them before colouring: without the price's and the approval's,
    which `status.finalize` adds again, and with the colour an approval had turned green."""
    out = []
    for r in reasons:
        if r.get("source") in ("price", "user"):
            continue
        r = dict(r)
        if "was" in r:
            r["status"] = r.pop("was")
        out.append(r)
    return out


def apply(
    line: Draft,
    edits: LineEdits | None,
    book: Book,
    dismissed: frozenset[str] = frozenset(),
    kept: Kept | None = None,
) -> Draft:
    e = edits or LineEdits()
    out = line
    if e.qty is not None:
        out = replace(out, qty=e.qty)
    if e.replaced is not None:
        r = e.replaced
        product = book.product(r.catalog_item_id, r.sku) if r.sku else None
        out = replace(
            out,
            sku=r.sku,
            manufacturer=r.manufacturer,
            description=r.description,
            catalog_item_id=r.catalog_item_id,
            product_id=product.product_id if product else None,
            unit=product.unit if product else out.unit,
            alternatives=[a for a in out.alternatives if a.get("sku") != r.sku or not r.sku],
        )
    if dismissed:
        out = replace(
            out,
            reasons=[x for x in out.reasons if x.get("issue_id") not in dismissed],
            issue_ids=[i for i in out.issue_ids if i not in dismissed],
        )
    out = replace(out, priced=_priced(out, e, book, kept), edits=e.as_json(), approved_at=e.approved_at)
    return out


def _priced(line: Draft, e: LineEdits, book: Book, kept: Kept | None) -> Priced:
    if line.included and e.replaced is None:
        return line.priced  # "included": the device's product prices it (05 §5.9.1)
    if kept is not None and kept.product_id == line.product_id and kept.sku == line.sku:
        return kept.priced
    if e.replaced is None and e.supplier_id is None:
        return line.priced  # stage 7's own price stands
    return price_line(line, book, e.supplier_id)


def price_line(line: Draft, book: Book, supplier_id: str | None = None) -> Priced:
    """The line's price from the list today: its product (by id, else by catalog item or SKU), from the supplier
    chosen for the line when there is one."""
    product = book.product_by_id(line.product_id) or (
        book.product(line.catalog_item_id, line.sku) if line.sku else None
    )
    if product is None:
        return NO_SKU if not line.sku else NO_PRODUCT
    return price(product, book, supplier_id)


def apply_all(
    lines: Sequence[Draft],
    edits: Mapping[str, LineEdits],
    book: Book,
    dismissed: frozenset[str] = frozenset(),
    kept: Mapping[str, Kept] | None = None,
) -> list[Draft]:
    """Every line's edits; a kit part's quantity follows its device's (05 §5.9.1 "quantity per unit")."""
    kept = kept or {}
    factor: dict[str, Decimal] = {}
    for ln in lines:
        e = edits.get(ln.key)
        if e is not None and e.qty is not None and ln.qty:
            factor[ln.key] = e.qty / ln.qty
    out = []
    for ln in lines:
        e = edits.get(ln.key)
        if ln.parent in factor and (e is None or e.qty is None):
            ln = replace(ln, qty=ln.qty * factor[ln.parent])
        out.append(apply(ln, e, book, dismissed, kept.get(ln.key)))
    return out
