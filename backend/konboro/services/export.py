"""The quote's two documents (13 §4.1, behind `export_doc`; S26): the customer PDF and the internal Excel, for any
version (S26 decision 2), from what the review screen reads (`quotes.read_quote`), so a document never says
something the screen doesn't.

- The customer document (07 §12): description, SKU by the factory's setting, quantity, unit price, line total, the
  discount, VAT and the total. Never a cost, a margin, a supplier, a price source or a row's colour: `Row` has no
  field for them, and `tests/unit/test_export.py` checks the HTML for them. A kit part included in its parent's price
  ("כלול") is not a row of its own. An unpriced line is a row with no amount (13 §4.1), and the totals are the stored
  ones (07 §7.6), which leave it out. A draft is marked "טיוטה" (S26 decision 3).
- The internal Excel has every live line with all of it, the findings and the totals (`export_xlsx.py`).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.domain.totals import QuoteSums
from konboro.services import document_template as dt
from konboro.services import quotes as qs

AGORA = Decimal("0.01")


@dataclass(frozen=True)
class Row:
    description: str
    sku: str | None
    qty: Decimal
    unit: str
    unit_price: Decimal | None
    line_total: Decimal | None


@dataclass(frozen=True)
class Section:
    """One panel's rows; a quote with one panel has one section and no panel headings."""

    name: str
    rows: list[Row]
    total: Decimal  # the panel's price before the quote's discount and VAT


@dataclass(frozen=True)
class Document:
    quote_id: str
    name: str
    drawing_number: str | None
    customer: str | None
    version: int
    draft: bool
    quote_date: date | None
    currency: str
    sections: list[Section]
    totals: QuoteSums
    template: dt.Template
    view: qs.QuoteView  # everything, for the internal Excel

    @property
    def unpriced(self) -> int:
        return sum(1 for s in self.sections for r in s.rows if r.line_total is None)


def build(session: Session, tenant_id: str, quote_id: str, version_no: int) -> Document | None:
    """Version `version_no` of the quote as its documents print it, or None when the tenant has no such version."""
    view = qs.read_quote(session, tenant_id, quote_id, version_no)
    if view is None:
        return None
    quote = session.get_one(m.Quote, quote_id)
    customer = session.get(m.Customer, quote.customer_id) if quote.customer_id else None
    if customer is None and quote.project_id:
        project = session.get(m.Project, quote.project_id)
        customer = session.get(m.Customer, project.customer_id) if project and project.customer_id else None
    sections = [
        Section(
            name=p.name,
            rows=[
                Row(ln.description, ln.sku, ln.qty, ln.unit, ln.unit_price, ln.line_total)
                for ln in p.lines
                if not ln.included
            ],
            total=p.sums.price_total,
        )
        for p in view.panels
    ]
    return Document(
        quote_id=view.quote_id,
        name=view.name,
        drawing_number=view.drawing_number,
        customer=customer.name if customer else None,
        version=view.version,
        draft=view.status == "draft",
        quote_date=view.quote_date,
        currency=view.currency,
        sections=[s for s in sections if s.rows],
        totals=view.totals,
        template=dt.read(session, tenant_id),
        view=view,
    )


def versions(session: Session, tenant_id: str, quote_id: str) -> list[m.QuoteVersion] | None:
    """The quote's versions, newest first; None when the tenant has no such quote."""
    if session.scalar(select(m.Quote.id).where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id)) is None:
        return None
    return list(
        session.scalars(
            select(m.QuoteVersion)
            .where(m.QuoteVersion.tenant_id == tenant_id, m.QuoteVersion.quote_id == quote_id)
            .order_by(m.QuoteVersion.version.desc())
        )
    )


# --- formatting, as the review screen's `shekels` and the prototype's `ils` -----------------------------------------


def shekels(amount: Decimal | None) -> str:
    """4674 → "₪4,674", 24.575 → "₪24.58" (half up), None → "" (an unpriced row has no amount, 13 §4.1)."""
    if amount is None:
        return ""
    cents = amount.quantize(AGORA, ROUND_HALF_UP)
    sign = "-" if cents < 0 else ""
    whole, frac = f"{abs(cents):.2f}".split(".")
    return f"{sign}₪{int(whole):,}{'' if frac == '00' else '.' + frac}"


def quantity(qty: Decimal) -> str:
    """17.000 → "17", 2.500 → "2.5"."""
    text = format(qty.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def percent(rate: Decimal | None) -> str:
    """0.18 → "18%", 0.075 → "7.5%"."""
    if rate is None:
        return ""
    return quantity((rate * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)) + "%"


def file_name(doc: Document, ext: str) -> str:
    """ "הצעת מחיר NURSERY גרסה 2.pdf"; the Excel says it is internal."""
    kind = "הצעת מחיר" if ext == "pdf" else "הצעה פנימית"
    safe = "".join(c for c in doc.name if c not in '\\/:*?"<>|').strip() or "הצעה"
    return f"{kind} {safe} גרסה {doc.version}.{ext}"
