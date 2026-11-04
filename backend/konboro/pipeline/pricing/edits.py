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
| an attribute (09 §7.4, S23b) | stage 5's answer with the user's value (`match`); the line priced anew |
| a missing line resolved (09 §7.8) | a component line with the product picked, approved |

After an action the quote is priced again with every line the action did not touch keeping its price (`Kept`): a draft
never changes by itself when the price list does (07 §7.2.3), only the lines the estimator acted on do. A kept price
counts only for the same product and SKU; a line whose product changed is priced from the list.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from .book import NO_PRODUCT, Book, Priced, own_id, price
from .lines import NO_SKU, Draft

APPROVED: dict[str, Any] = {"source": "user", "value": "approved", "status": "green"}


@dataclass(frozen=True)
class Replaced:
    """The alternative chosen for the line (05 §5.9, 09 §7.3)."""

    sku: str | None
    manufacturer: str | None
    description: str
    catalog_item_id: str | None = None
    product_id: str | None = None  # a price-list product picked with no catalog item (09 §7.8, S23b)

    def as_json(self) -> dict[str, Any]:
        out = {
            "sku": self.sku,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "catalog_item_id": self.catalog_item_id,
        }
        if self.product_id:
            out["product_id"] = self.product_id
        return out

    @classmethod
    def of(cls, r: Mapping[str, Any]) -> "Replaced":
        return cls(r.get("sku"), r.get("manufacturer"), r["description"], r.get("catalog_item_id"), r.get("product_id"))


@dataclass(frozen=True)
class Rematch:
    """Stage 5 again for the line after the user set an attribute (09 §7.4), in code (S23b decision 3): what it
    chose, why, and the reasons it gives the line (07 §7.5)."""

    sku: str | None
    manufacturer: str | None
    description: str
    catalog_item_id: str | None
    reasons: tuple[Mapping[str, Any], ...]
    alternatives: tuple[Mapping[str, Any], ...] = ()
    explanation: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "catalog_item_id": self.catalog_item_id,
            "reasons": [dict(r) for r in self.reasons],
            "alternatives": [dict(a) for a in self.alternatives],
            "explanation": self.explanation,
        }

    @classmethod
    def of(cls, r: Mapping[str, Any]) -> "Rematch":
        return cls(
            r.get("sku"),
            r.get("manufacturer"),
            r["description"],
            r.get("catalog_item_id"),
            tuple(r.get("reasons", ())),
            tuple(r.get("alternatives", ())),
            r.get("explanation"),
        )


@dataclass(frozen=True)
class LineEdits:
    qty: Decimal | None = None
    supplier_id: str | None = None
    replaced: Replaced | None = None
    approved_at: datetime | None = None
    attrs: Mapping[str, Any] | None = None  # attribute → the value the user set (09 §7.4)
    match: Rematch | None = None  # stage 5's answer with those values
    resolved: bool = False  # a missing line the user picked a product for (09 §7.8)

    @classmethod
    def of(cls, edits: Mapping[str, Any] | None, approved_at: datetime | None = None) -> "LineEdits":
        e = edits or {}
        r = e.get("replaced")
        return cls(
            qty=Decimal(str(e["qty"])) if e.get("qty") is not None else None,
            supplier_id=e.get("supplier_id"),
            replaced=Replaced.of(r) if r else None,
            approved_at=approved_at,
            attrs=e.get("attrs") or None,
            match=Rematch.of(e["match"]) if e.get("match") else None,
            resolved=bool(e.get("resolved")),
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
        if self.attrs:
            out["attrs"] = dict(self.attrs)
        if self.match is not None:
            out["match"] = self.match.as_json()
        if self.resolved:
            out["resolved"] = True
        return out

    @property
    def empty(self) -> bool:
        return self == LineEdits()

    @property
    def reprices(self) -> bool:
        """The edit changes the line's product, so its price comes from the list again."""
        return self.replaced is not None or self.supplier_id is not None or self.match is not None


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
    if e.match is not None:
        x = e.match
        product = book.find(None, x.catalog_item_id, x.sku, x.manufacturer) if x.sku else None
        out = replace(
            out,
            sku=x.sku,
            manufacturer=x.manufacturer,
            description=x.description,
            catalog_item_id=x.catalog_item_id,
            product_id=own_id(product),
            unit=product.unit if product else out.unit,
            alternatives=[dict(a) for a in x.alternatives],
            explanation=x.explanation,
            # the match's reasons are stage 5's new answer; the validator's stay until the rules run again
            reasons=[dict(r) for r in x.reasons] + [r for r in out.reasons if r.get("source") == "validator"],
        )
    if e.resolved:
        out = replace(
            out,
            line_type="component",
            reasons=[{"source": "match", "value": "resolved", "status": "green"}],
            explanation=None,
        )
    if e.replaced is not None:
        r = e.replaced
        product = book.find(r.product_id, r.catalog_item_id, r.sku, r.manufacturer) if r.sku or r.product_id else None
        out = replace(
            out,
            sku=r.sku,
            manufacturer=r.manufacturer,
            description=r.description,
            catalog_item_id=r.catalog_item_id,
            product_id=own_id(product),
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
    if not e.reprices:
        return line.priced  # stage 7's own price stands
    return price_line(line, book, e.supplier_id)


def price_line(line: Draft, book: Book, supplier_id: str | None = None) -> Priced:
    """The line's price from the list today: its product (by id, else by catalog item or SKU, else the catalog item at
    the brand discount), from the supplier chosen for the line when there is one."""
    product = book.find(line.product_id, line.catalog_item_id, line.sku, line.manufacturer)
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
