"""The pricing backtest (07 §10.2, S22 decision 1): each drawing with a real quote, priced again by stage 7's engine
(`konboro.pipeline.pricing.engine`, pure) on this run's own stage 1–6 outputs, with two price lists.

- **Own quote (gated).** The factory's prices from the drawing's own real quote, as `quote_import` fixed prices (11
  §9): the audit matched each quote line to the components it covers, and each one's SKU (stage 5's) gets that
  line's unit price; the quote's cabinet line prices the enclosure, whichever the rule chooses. This measures our
  quantities, derived items and rounding against the factory's total, before VAT, within ±5%, and the derived items
  against the quote's cabinet lines within ±10%.
- **Leave one out (reported).** The prices of the other drawings' quotes, as a new factory would have them: the
  share of component lines that find a price, and the total's gap. Not gated: it measures the golden set's overlap
  more than our code.

The factory's settings are these quotes' factory's (S22 decision 1): its cabinet includes busbars, N, PE, panels
and doors; it quotes no labor, terminals or labels as lines, so only the enclosure rule runs.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from konboro.contracts.audit import AuditedLine
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.validation import ValidationResult
from konboro.domain.pricing.cost import CostContext
from konboro.pipeline.pricing.book import Book, Item, Product, sku_key
from konboro.pipeline.pricing.derived import DerivedRule, Requirement
from konboro.pipeline.pricing.engine import PricedQuote, QuoteInput, amounts, price_quote

ENCLOSURE = "enclosure"
INCLUDES = {"busbar": True, "n": True, "pe": True, "panels": True, "doors": True}
CATALOG_LINES = os.environ.get("EVAL_CATALOG_LINES") == "1"  # S27b: `run.py`'s docstring
RULES = [
    DerivedRule(
        id="dr_eval_enclosure",
        key="enclosure",
        kind="enclosure",
        explanation_he="ארון",
        item={"family": ENCLOSURE},
        params={"spare_pct": "0.20"},
    )
]


@dataclass
class Material:
    """What a drawing's backtest needs from its run."""

    drawing: str
    intake: IntakeResult
    merge: MergeResult
    matching: MatchingResult
    validation: ValidationResult
    items: list[Item]
    requirements: dict[str | None, Requirement]
    lines: list[AuditedLine]  # the real quote as the audit read and matched it
    prices: dict[str, Decimal] = field(default_factory=dict)  # sku → the quote's unit price
    enclosure_price: Decimal | None = None
    quote_derived: Decimal = Decimal(0)  # the quote's cabinet lines

    def __post_init__(self) -> None:
        sku = {x.component_id: x.chosen_sku for x in self.matching.matches if x.chosen_sku}
        for ln in sorted(self.lines, key=lambda x: x.index):
            if ln.unit_price is None:
                continue
            if (ln.signature or {}).get("family") == ENCLOSURE:
                self.quote_derived += ln.total if ln.total is not None else ln.unit_price * (ln.qty or Decimal(1))
                self.enclosure_price = self.enclosure_price if self.enclosure_price is not None else ln.unit_price
                continue
            for cid in ln.component_ids:
                if cid in sku:
                    self.prices.setdefault(sku_key(sku[cid]), ln.unit_price)


@dataclass(frozen=True)
class Result:
    total: Decimal
    derived: Decimal
    component_lines: int
    priced_lines: int
    enclosure_sku: str | None

    @property
    def coverage(self) -> Decimal | None:
        return Decimal(self.priced_lines) / self.component_lines if self.component_lines else None


def book(
    mat: Material, prices: dict[str, Decimal], enclosures: dict[str, Decimal], every_enclosure: Decimal | None, on: date
) -> Book:
    items = {sku_key(i.sku): i for i in mat.items}
    products = [
        Product(
            product_id=f"prd_{n}",
            name=key,
            family=items[key].family if key in items else "device",
            manufacturer_sku=key,
            catalog_item_id=items[key].id if key in items else None,
            sale_mode="fixed",
            fixed_price=price,
        )
        for n, (key, price) in enumerate(sorted(prices.items()))
    ]
    for i in mat.items:
        if i.family != ENCLOSURE:
            continue
        price = every_enclosure if every_enclosure is not None else enclosures.get(sku_key(i.sku))
        if price is not None:
            products.append(
                Product(
                    product_id=f"prd_enc_{i.id}",
                    name=i.description,
                    family=ENCLOSURE,
                    manufacturer_sku=i.sku,
                    catalog_item_id=i.id,
                    sale_mode="fixed",
                    fixed_price=price,
                )
            )
    return Book(cost=CostContext(on_date=on), products=products, items=mat.items)


def price(mat: Material, b: Book, on: date) -> Result:
    q: PricedQuote = price_quote(
        QuoteInput(
            tenant_id="tnt_eval",
            quote_date=on,
            panels=[(p.panel_id, p.name) for p in mat.intake.panels],
            merge=mat.merge,
            matching=mat.matching,
            validation=mat.validation,
            book=b,
            rules=RULES,
            requirements=mat.requirements,
            includes_default=INCLUDES,
            catalog_lines=CATALOG_LINES,
        )
    )
    components = [ln for ln in q.lines if ln.line_type == "component" and not ln.included]
    extras = [ln for ln in q.lines if ln.line_type in ("derived", "labor")]
    derived = sum((amounts(ln).line_total or Decimal(0) for ln in extras), Decimal(0))
    enclosure = next((ln.sku for ln in extras if (ln.derived or {}).get("rule_key") == ENCLOSURE and ln.sku), None)
    priced = sum(ln.priced.unit_price is not None for ln in components)
    return Result(q.totals.net_total, derived, len(components), priced, enclosure)


def run(materials: Sequence[Material], on: date) -> dict[str, dict[str, str | None]]:
    """Per drawing: the own-quote total and derived items (gated), and the leave-one-out total and coverage."""
    own = {m.drawing: price(m, book(m, m.prices, {}, m.enclosure_price, on), on) for m in materials}
    out: dict[str, dict[str, str | None]] = {}
    for mat in materials:
        others = [m for m in materials if m.drawing != mat.drawing]
        prices: dict[str, Decimal] = {}
        enclosures: dict[str, Decimal] = {}
        for m in others:
            for k, v in m.prices.items():
                prices.setdefault(k, v)
            sku = own[m.drawing].enclosure_sku
            if sku and m.enclosure_price is not None:
                enclosures.setdefault(sku_key(sku), m.enclosure_price)
        loo = price(mat, book(mat, prices, enclosures, None, on), on)
        mine = own[mat.drawing]
        out[mat.drawing] = {
            "own_total": str(mine.total),
            "own_derived": str(mine.derived),
            "own_coverage": _ratio(mine.coverage),
            "quote_derived": str(mat.quote_derived),
            "loo_total": str(loo.total),
            "loo_coverage": _ratio(loo.coverage),
        }
    return out


def _ratio(v: Decimal | None) -> str | None:
    return None if v is None else str(v.quantize(Decimal("0.0001")))
