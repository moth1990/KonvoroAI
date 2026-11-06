"""Stage 7's arithmetic, pure (07 §5): lines (7.1), cost and price (7.2–7.3), derived items and labor (7.4), the final
colour (7.5), rounding and totals (7.6). No database and no model: the same input and book give the same quote to
the agora (07 §10.1), and the eval prices a run again with another book (S22 decision 1).

What the user did on an earlier draft of the same drawing comes in as `Carry` (S22 decision 5): a line they deleted
stays deleted, a derived line they deleted is not made again, a price they set on a line is kept and no rule
overwrites it (07 §7), and their manual lines stay. So do their review-screen edits (S23, `edits.py`): a quantity, an
alternative, a supplier, an approval, a dismissed finding. After a review action, `kept` holds the stored price of every
line the action did not touch, so only those it touched are priced from the list (07 §7.2.3).

Pricing issues (07 §8) are grouped as stage 6's are (S21 decision 14): one finding per cause, naming every line. The
margin floors only tag (07 §7.3), and a pricing finding never changes a line's colour: its price status does.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import Component, MergeResult
from konboro.contracts.validation import Issue, ValidationResult
from konboro.domain import totals as t
from konboro.domain.pricing import margin as pm

from .book import Book
from .derived import DerivedRule, Labor, PanelContext, Requirement, derive
from .edits import Kept, LineEdits, apply_all, price_line
from .lines import Draft, panel_lines, values_of
from .merge import merge, waiting
from .status import finalize

SEVERITY = {
    "missing_cost": "warning",
    "stale_price": "info",
    "fx_rate_missing": "error",
    "no_margin_rule": "error",
    "below_margin_floor": "warning",
    "quote_below_margin_floor": "warning",
    "derived_rule_failed": "warning",
    "enclosure_not_found": "warning",
    "empty_price_list": "info",
}
OVERRIDDEN = ("missing_cost", "no_margin_rule", "below_margin_floor")  # a price the user set answers these
GROUPED = ("missing_cost", "stale_price", "fx_rate_missing", "no_margin_rule")


@dataclass(frozen=True)
class Carry:
    deleted: frozenset[str] = frozenset()  # line keys the user deleted, derived ones included
    overrides: Mapping[str, dict[str, Any]] = field(default_factory=dict)  # line key → `override`
    manual: Sequence[Draft] = ()  # lines the user added, as they were
    edits: Mapping[str, LineEdits] = field(default_factory=dict)  # line key → the review screen's edits
    dismissed: frozenset[str] = frozenset()  # finding ids the user dismissed: their reasons leave the lines
    kept: Mapping[str, Kept] = field(default_factory=dict)  # line key → its stored price, after a review action
    # S27b: the estimator's choice per component, by its line key (`quote_versions.component_edits`)
    components: Mapping[str, LineEdits] = field(default_factory=dict)


@dataclass(frozen=True)
class QuoteInput:
    tenant_id: str
    quote_date: date
    panels: Sequence[tuple[str, str]]  # (panel_id, name), stage 1's order
    merge: MergeResult
    matching: MatchingResult
    validation: ValidationResult
    book: Book
    rules: Sequence[DerivedRule] = ()
    labor: Labor | None = None
    requirements: Mapping[str | None, Requirement] = field(default_factory=dict)  # panel id, None for the drawing
    includes_default: Mapping[str, bool] = field(default_factory=dict)
    discount_pct: Decimal | None = None
    vat_rate: Decimal = Decimal(0)
    carry: Carry = Carry()
    scope: str = ""  # the quote version's id: pricing findings' ids are stable within it
    catalog_lines: bool = False  # S27b (13 §4.10): one line per product in a panel, a product-less line waits


@dataclass(frozen=True)
class PricingFinding:
    code: str
    severity: str
    message: str
    title: str
    panel_id: str | None = None
    line_keys: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    values: Mapping[str, Any] = field(default_factory=dict)

    def finding_id(self, scope: str) -> str:
        """Stable for what it says, within `scope` (the quote version): a rerun keeps the id."""
        key = "|".join([scope, self.code, self.panel_id or "", *sorted(self.line_keys)])
        return "iss_" + hashlib.sha256(key.encode()).hexdigest()[:24]


@dataclass
class PricedPanel:
    panel_id: str
    name: str
    lines: list[Draft]
    notes: list[str]
    sums: t.Sums


@dataclass
class PricedQuote:
    panels: list[PricedPanel]
    totals: t.QuoteSums
    findings: list[PricingFinding]

    @property
    def lines(self) -> list[Draft]:
        return [ln for p in self.panels for ln in p.lines]


def amounts(line: Draft) -> t.LineAmounts:
    return t.line_amounts(line.qty, line.priced.unit_price, line.priced.unit_cost)


def figures(lines: Sequence[Draft]) -> list[t.LineFigures]:
    out = []
    for ln in lines:
        a = amounts(ln)
        out.append(t.LineFigures(ln.status, a.line_total, a.line_cost))
    return out


def override(line: Draft, ov: Mapping[str, Any]) -> Draft:
    """A price the user set on the line (07 §7.2.3 "רק בהצעה הזו"): kept over any rule, the cost still the list's."""
    unit = Decimal(str(ov["unit_price"]))
    priced = replace(
        line.priced,
        unit_price_raw=unit,
        unit_price=unit,
        price_status="ok",
        margin_rule={"kind": "override", "source": "quote", "quotes": [], "value": None},
        issues=tuple(i for i in line.priced.issues if i not in OVERRIDDEN),
        floor=None,
    )
    return replace(line, priced=priced, override=dict(ov))


def main_current(c: Component | None, book: Book, lines: Sequence[Draft]) -> float | None:
    if c is None:
        return None
    line = next((ln for ln in lines if ln.component_id == c.component_id and ln.parent is None), None)
    item = book.item(line.catalog_item_id) if line else None
    v = (item.attributes.get("current_a") if item else None) or values_of(c).get("current_a")
    return float(v) if isinstance(v, int | float) else None


def requirement_for(inp: QuoteInput, panel_id: str) -> Requirement | None:
    """The panel's notes block; else the drawing's data page, when the drawing has one panel (07 §7.4)."""
    if panel_id in inp.requirements:
        return inp.requirements[panel_id]
    return inp.requirements.get(None) if len(inp.panels) == 1 else None


def manual_line(ln: Draft, inp: QuoteInput) -> Draft:
    """A line the user added (09 §6.6) keeps its stored price after a review action that did not touch it, like any
    other line (07 §7.2.3); otherwise it is priced from the list by its product or SKU. One with neither keeps the
    price it was added with. Its edits (a quantity, a supplier) apply as on any line."""
    e = inp.carry.edits.get(ln.key)
    kept = inp.carry.kept.get(ln.key)
    if kept is not None:
        priced = kept.priced
    elif ln.product_id or ln.sku:
        priced = price_line(ln, inp.book, e.supplier_id if e else None)
    else:
        priced = ln.priced
    out = replace(ln, priced=priced, qty=e.qty if e and e.qty is not None else ln.qty)
    return replace(out, edits=e.as_json() if e else {}, approved_at=e.approved_at if e else None)


def per_product(lines: Sequence[Draft], inp: QuoteInput) -> list[Draft]:
    """07 §7.1 (S27b): each component's choices first, so a change of product moves it; then one line per product in
    the panel; then what the estimator did on the merged line itself (a quantity, a supplier, an approval, a kept
    price). A line with no product waits for a decision, unpriced."""
    carry = inp.carry
    own = {k: e for k, e in carry.edits.items() if not k.startswith("p:")}  # a component's row, or a waiting line's
    chosen = apply_all(lines, {**own, **carry.components}, inp.book, carry.dismissed, carry.kept)
    chosen = [ln for ln in chosen if ln.key not in carry.deleted or ln.parent is not None]
    merged = merge(chosen)
    heads = [ln for ln in merged if ln.key.startswith("p:")]
    line_edits = {ln.key: carry.edits.get(ln.key) or LineEdits.of(ln.edits, ln.approved_at) for ln in heads}
    again = apply_all(heads, line_edits, inp.book, carry.dismissed, carry.kept)
    by_key = {ln.key: ln for ln in again}
    out = []
    for ln in merged:
        ln = by_key.get(ln.key, ln)
        if waiting(ln):
            ln = replace(ln, pending=True)
        out.append(ln)
    return out


def price_quote(inp: QuoteInput) -> PricedQuote:
    matches = {m.component_id: m for m in inp.matching.matches}
    auxiliary = set(inp.matching.auxiliary)
    issues_by_component: dict[str, list[Issue]] = {}
    for i in inp.validation.issues:
        if i.status != "open":  # resolved by a re-run of the rules after an edit (06 §6.3), or dismissed
            continue
        for cid in i.component_ids:
            issues_by_component.setdefault(cid, []).append(i)
    main_ids = {s.main_device_component_id for s in inp.validation.panel_summaries if s.main_device_component_id}
    first = inp.panels[0][0] if inp.panels else None
    missing = [x if x.panel_id else x.model_copy(update={"panel_id": first}) for x in inp.merge.missing]
    by_id = {c.component_id: c for c in inp.merge.components}

    panels: list[PricedPanel] = []
    found: list[PricingFinding] = []
    for panel_id, name in inp.panels:
        built = panel_lines(
            panel_id, inp.merge.components, matches, auxiliary, missing, issues_by_component, main_ids, inp.book
        )
        if inp.catalog_lines:
            built.lines = per_product(built.lines, inp)
        else:
            built.lines = apply_all(built.lines, inp.carry.edits, inp.book, inp.carry.dismissed, inp.carry.kept)
        comps = [c for c in inp.merge.components if c.panel_id == panel_id]
        main = next((by_id[i] for i in main_ids if i in by_id and by_id[i].panel_id == panel_id), None)
        ctx = PanelContext(
            panel_id=panel_id,
            name=name,
            lines=built.lines,
            components=comps,
            auxiliary=[c for c in comps if c.component_id in auxiliary],
            busbars=sum(1 for e in inp.merge.context_elements if e.family == "busbar" and e.panel_id == panel_id),
            requirement=requirement_for(inp, panel_id),
            main_current=main_current(main, inp.book, built.lines),
            includes_default=inp.includes_default,
        )
        derived = derive(ctx, inp.rules, inp.labor, inp.book, set(inp.carry.deleted))
        consumable = set(derived.consumable_ids)
        lines = [ln for ln in built.lines if ln.key not in consumable] + derived.lines
        lines += [manual_line(ln, inp) for ln in inp.carry.manual if ln.panel_id == panel_id]
        lines = [ln for ln in lines if ln.key not in inp.carry.deleted]
        kept = {ln.key for ln in lines}
        lines = [ln for ln in lines if ln.parent is None or ln.parent in kept]  # a deleted device takes its children
        overrides = dict(inp.carry.overrides)
        for ln in lines:  # S27b decision 5: a price set on a component's line before the flag, the merged line's
            was = next((overrides[k] for k in ln.members if k in overrides), None)
            if was is not None and ln.key not in overrides:
                overrides[ln.key] = was
        lines = [override(ln, overrides[ln.key]) if ln.key in overrides else ln for ln in lines]
        for ln in lines:
            finalize(ln)
        found += [
            PricingFinding(
                "derived_rule_failed",
                "warning",
                f"לא הצלחנו לחשב {key} ללוח {name}: {why}",
                f"פריט נלווה: {key}",
                panel_id,
                values={"rule_key": key, "why": why},
            )
            for key, why in derived.failed
        ]
        found += [
            PricingFinding(
                "enclosure_not_found",
                "warning",
                ln.description,
                ln.description,
                panel_id,
                (ln.key,),
                values={"explanation": (ln.derived or {}).get("explanation")},
            )
            for ln in lines
            if ln.query_failed and (ln.derived or {}).get("rule_key") == "enclosure"
        ]
        panels.append(PricedPanel(panel_id, name, lines, built.notes, t.sum_lines(figures(lines))))

    sums = t.quote_sums(t.merge(p.sums for p in panels), inp.discount_pct, inp.vat_rate)
    found += line_findings(panels)
    quote_floor = pm.quote_floor(sums.margin_pct, inp.book.min_quote_margin)
    if quote_floor is not None:
        pct, floor = _pct(quote_floor.margin_pct), _pct(quote_floor.floor)
        found.append(
            PricingFinding(
                "quote_below_margin_floor",
                "warning",
                f"הרווח בהצעה {pct}% (רצפה: {floor}%)",
                "רווח נמוך בהצעה",
                values={"margin_pct": str(quote_floor.margin_pct), "floor": str(quote_floor.floor)},
            )
        )
    if not inp.book.products:
        found.append(
            PricingFinding(
                "empty_price_list",
                "info",
                "המחירון שלכם נבנה מההצעות: מחיר שתקלידו בשורה נשמר במחירון לכל ההצעות הבאות",
                "המחירון עדיין ריק",
            )
        )
    attach(panels, found, inp.scope)
    return PricedQuote(panels, sums, found)


def _pct(ratio: Decimal) -> str:
    return format((ratio * 100).quantize(Decimal(1)), "f")


MESSAGES = {
    # the prototype's wording (makeFindings, "price"): its count is the title, so it moves as prices are entered
    "missing_cost": (
        "{n} בלי מחיר",
        "אין מחיר זהה במחירון של המפעל. אפשר להזין בשורה, והמחיר נשמר למחירון להצעות הבאות",
    ),
    "stale_price": ("מחיר ישן", "המחיר ל-{n} ישן מהמוגדר. כדאי לעדכן את המחירון"),
    "fx_rate_missing": ("אין שער מטבע", "אין שער מטבע עדכני ל-{n}, ולכן הן בלי מחיר"),
    "no_margin_rule": ("אין חוק רווח", "אין חוק רווח שחל על {n}, ולכן הן בלי מחיר מכירה"),
}


def _lines_text(n: int) -> str:
    return "שורה אחת" if n == 1 else f"{n} שורות"


def line_findings(panels: Sequence[PricedPanel]) -> list[PricingFinding]:
    lines = [ln for p in panels for ln in p.lines]
    out: list[PricingFinding] = []
    for code in GROUPED:
        hit = [ln for ln in lines if code in ln.priced.issues]
        if not hit:
            continue
        title, text = MESSAGES[code]
        skus = sorted({ln.sku for ln in hit if ln.sku})
        out.append(
            PricingFinding(
                code,
                SEVERITY[code],
                text.format(n=_lines_text(len(hit))),
                title.format(n=_lines_text(len(hit))),
                line_keys=tuple(ln.key for ln in hit),
                component_ids=tuple(sorted({ln.component_id for ln in hit if ln.component_id})),
                values={"count": len(hit), "skus": skus},
            )
        )
    for p in panels:
        for ln in p.lines:
            if "below_margin_floor" not in ln.priced.issues or ln.priced.floor is None:
                continue
            ratio = t.margin_ratio(ln.priced.unit_price, ln.priced.unit_cost) or Decimal(0)
            out.append(
                PricingFinding(
                    "below_margin_floor",
                    "warning",
                    f"הרווח בשורה {_pct(ratio)}% (רצפה: {_pct(ln.priced.floor)}%)",
                    f"רווח נמוך: {ln.description}",
                    p.panel_id,
                    (ln.key,),
                    (ln.component_id,) if ln.component_id else (),
                    {"margin_pct": str(ratio), "floor": str(ln.priced.floor)},
                )
            )
    return out


def attach(panels: Sequence[PricedPanel], found: Sequence[PricingFinding], scope: str) -> None:
    """A pricing finding's id on each of its lines (07 §6.2 `issue_ids`); the colour stays the price status's."""
    by_key = {ln.key: ln for p in panels for ln in p.lines}
    for f in found:
        for key in f.line_keys:
            ln = by_key.get(key)
            if ln is not None:
                ln.issue_ids.append(f.finding_id(scope))
