"""07 §7.4: derived items and labor, from rules stored as data (`derived.json`, a copy per tenant).

Each rule's `kind` names one function here; its `params` and `item` query come from the rule row, so a factory tunes
the numbers without code. "This is where factories lose money": the items that are not drawn as components.

- **enclosure**: by the dimensions and IP written in the drawing (the panel's notes block, else the drawing's data
  page when it has one panel, 01 §5.5–5.5.1), all `gte`, the smallest that fits; else by the modules (Σ
  `module_width` × qty) plus spare, the notes' `spare_space_pct` before the rule's `spare_pct`, the smallest with
  enough modules. None fits → a red row "ארון: לא נמצא מתאים ל-X מודולים" (`enclosure_not_found`). The module count
  still runs beside the dimensions, and a large gap is said in the line's explanation.
- **din_rail**: one per row of the chosen enclosure. **busbar**: the busbars stage 3 saw in the panel
  (`context_elements`), else one per row. Neither is added when the enclosure includes it (`includes`, the product's
  or else the factory's `enclosure_includes_default`).
- **terminals**: stage 5's auxiliary components (S20 decision 3), one line per cross-section; with none drawn,
  `per_output` per output.
- **labels**: `per_output` × outputs + `per_panel`.
- **consumables**: `pct` of the panel's component cost; a product marked `consumable` gets no line of its own and is
  in this percentage (07 §7.4). Priced by the `consumables` family's margin rule, else the default.
- **service**: a required service in the notes ("חישוב חום ע"י יצרן הלוח") → a yellow row with the note, no price.
- **labor** (not a rule row: `tenant_settings.labor`): Σ hours per family × qty at the factory's hourly rate, priced
  by the `labor` family's margin rule. No rate set → no labor line (S22 decision 3).

Every derived line points to its rule and to the components that caused it. A line the user deleted stays deleted:
its `(panel, rule, item)` key is in `suppressed`, and a recalculation never brings it back (07 §7).
"""

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from konboro.contracts.merge import Component
from konboro.domain.pricing import margin as pm
from konboro.domain.pricing import money
from konboro.domain.pricing.rounding import round_price

from .book import Book, Item, Priced, Product, price
from .lines import NO_SKU, Draft

PACK = Path(__file__).with_name("derived.json")
ENCLOSURE_PARTS = ("busbar", "n", "pe", "panels", "doors", "din_rail")
FAMILY_LABOR = "labor"
FAMILY_CONSUMABLES = "consumables"
IP = re.compile(r"IP\s*(\d)(\d)", re.IGNORECASE)
LARGE_GAP = Decimal("0.5")  # the dimensions' enclosure has 50% more or fewer modules than the count asks for


@dataclass(frozen=True)
class DerivedRule:
    id: str
    key: str
    kind: str
    explanation_he: str
    scope: str = "panel"
    item: Mapping[str, Any] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    version: int = 1


def starter_pack() -> tuple[int, list[dict[str, Any]]]:
    pack = json.loads(PACK.read_text())
    return int(pack["version"]), list(pack["rules"])


@dataclass(frozen=True)
class Requirement:
    """What the drawing asks of the panel's enclosure (01 §5.5.1), and where it says so."""

    source: str  # "הערות הלוח", "עמוד הנתונים (עמ׳ 1)"
    height_mm: float | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    ip: str | None = None
    spare_pct: float | None = None
    services: tuple[str, ...] = ()

    @property
    def has_dimensions(self) -> bool:
        return self.height_mm is not None and self.width_mm is not None and self.depth_mm is not None


@dataclass(frozen=True)
class Labor:
    hourly_rate: Decimal
    hours: Mapping[str, Decimal]  # family → hours per unit


@dataclass
class PanelContext:
    panel_id: str
    name: str
    lines: list[Draft]  # the panel's component lines, kit parts and accessories included
    components: Sequence[Component]  # the panel's components, by id
    auxiliary: Sequence[Component]
    busbars: int
    requirement: Requirement | None
    main_current: float | None
    includes_default: Mapping[str, bool]
    enclosure: Item | None = None  # set by the enclosure rule, read by the rails and busbars
    includes: Mapping[str, bool] = field(default_factory=dict)

    @property
    def outputs(self) -> int:
        return int(sum(ln.qty for ln in self.lines if ln.parent is None and ln.line_group == "outputs"))

    @property
    def counted(self) -> list[Draft]:
        """The lines that take room in the enclosure: not outside the panel, not a child line priced in its parent."""
        return [ln for ln in self.lines if ln.line_group != "outside" and not ln.included]


class RuleFailed(Exception):
    """`derived_rule_failed` (07 §8): the rule could not be worked out for this panel."""


def ip_fits(have: str | None, need: str | None) -> bool:
    """Both IP digits at least the asked ones: IP65 is enough for IP55, IP54 isn't."""
    if not need:
        return True
    n, h = IP.search(need), IP.search(have or "")
    if n is None:
        return True
    return h is not None and int(h[1]) >= int(n[1]) and int(h[2]) >= int(n[2])


def num(item: Item, key: str) -> float | None:
    v = item.attributes.get(key)
    return float(v) if isinstance(v, int | float) else None


def modules_of(ctx: PanelContext, book: Book) -> tuple[Decimal, list[str], int]:
    """Σ module_width × qty of the lines whose catalog item has one; the components counted; lines with no width."""
    total, ids, unknown = Decimal(0), [], 0
    for ln in ctx.counted:
        item = book.item(ln.catalog_item_id)
        if item is None or item.module_width is None:
            unknown += ln.line_type == "component"
            continue
        total += item.module_width * ln.qty
        if ln.component_id and ln.component_id not in ids:
            ids.append(ln.component_id)
    return total, ids, unknown


def _fmt(v: Decimal | float) -> str:
    d = Decimal(str(v)).normalize()
    return format(d, "f")


def _item_line(
    ctx: PanelContext, rule: DerivedRule, item: Item | Product | None, qty: Decimal, book: Book, **kw: Any
) -> Draft:
    """A derived line for a catalog item (priced through the factory's product linked to it) or for one of the
    factory's own products."""
    if isinstance(item, Product):
        product: Product | None = item
        catalog = book.item(item.catalog_item_id)
    else:
        catalog = item
        product = book.product(item.id, item.sku) if item else None
    sub = kw.pop("sub", "")
    return Draft(
        key=f"d:{ctx.panel_id}:{rule.key}{sub}",
        panel_id=ctx.panel_id,
        line_type="derived",
        description=kw.pop("description", None)
        or (product.name if product else catalog.description if catalog else rule.key),
        qty=qty,
        priced=price(product, book),
        line_group="enclosure",
        product_id=product.product_id if product else None,
        catalog_item_id=catalog.id if catalog else None,
        sku=catalog.sku if catalog else product.manufacturer_sku if product else None,
        manufacturer=catalog.brand if catalog else product.brand if product else None,
        unit=product.unit if product else "unit",
        derived={
            "rule_id": rule.id,
            "rule_key": rule.key,
            "from_component_ids": kw.pop("from_ids", []),
            "explanation": kw.pop("explanation"),
        },
        **kw,
    )


def _failed_line(ctx: PanelContext, rule: DerivedRule, description: str, explanation: str) -> Draft:
    return Draft(
        key=f"d:{ctx.panel_id}:{rule.key}",
        panel_id=ctx.panel_id,
        line_type="derived",
        description=description,
        qty=Decimal(1),
        priced=NO_SKU,
        line_group="enclosure",
        derived={"rule_id": rule.id, "rule_key": rule.key, "from_component_ids": [], "explanation": explanation},
        query_failed=True,
    )


def smallest(items: Sequence[Item], key: Callable[[Item], tuple[Any, ...]]) -> Item | None:
    return min(items, key=lambda i: (*key(i), i.sku)) if items else None


def enclosure(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    family = str(rule.item.get("family", "enclosure"))
    candidates = book.of_family(family)
    modules, ids, unknown = modules_of(ctx, book)
    req = ctx.requirement
    if req is not None and req.has_dimensions:
        h, w, d = req.height_mm, req.width_mm, req.depth_mm
        fits = [
            i
            for i in candidates
            if (num(i, "height_mm") or 0) >= (h or 0)
            and (num(i, "width_mm") or 0) >= (w or 0)
            and (num(i, "depth_mm") or 0) >= (d or 0)
            and ip_fits(i.attributes.get("ip"), req.ip)
        ]
        size = f"{_fmt(h or 0)}×{_fmt(w or 0)}×{_fmt(d or 0)}" + (f" {req.ip}" if req.ip else "")
        chosen = smallest(
            fits, lambda i: ((num(i, "height_mm") or 0) * (num(i, "width_mm") or 0) * (num(i, "depth_mm") or 0),)
        )
        if chosen is None:
            return [_failed_line(ctx, rule, f"ארון: לא נמצא מתאים ל-{size}", f"מידות מ{req.source}: {size}")]
        explanation = f"מידות מ{req.source}: {size}"
        has = num(chosen, "modules")
        if has and modules and abs(Decimal(str(has)) - modules) / modules > LARGE_GAP:
            explanation += f". לפי המודולים נדרשים {_fmt(modules)}, ובארון {_fmt(has)}"
        reasons = [{"source": "match", "value": "context_page", "status": "green"}]
    else:
        if modules == 0:
            if not ctx.counted:
                return []
            return [_failed_line(ctx, rule, "ארון: לא ידוע כמה מודולים", "לרכיבים בלוח אין רוחב מודולים בקטלוג")]
        spare = (
            Decimal(str(req.spare_pct)) / 100
            if req is not None and req.spare_pct is not None
            else Decimal(str(rule.params.get("spare_pct", "0.20")))
        )
        needed = math.ceil(modules * (1 + spare))
        fits = [i for i in candidates if (num(i, "modules") or 0) >= needed]
        chosen = smallest(fits, lambda i: (num(i, "modules") or 0,))
        spare_from = f" ({req.source})" if req is not None and req.spare_pct is not None else ""
        counted = f"{_fmt(modules)} מודולים ברכיבים + {_fmt(spare * 100)}% רזרבה{spare_from} = {needed}"
        if unknown:
            counted += f". ל-{unknown} שורות אין רוחב מודולים"
        if chosen is None:
            return [_failed_line(ctx, rule, f"ארון: לא נמצא מתאים ל-{needed} מודולים", counted)]
        explanation = f"{counted}. נבחר הארון הקטן ביותר עם {needed} מודולים לפחות"
        reasons = []
    ctx.enclosure = chosen
    product = book.product(chosen.id, chosen.sku)
    ctx.includes = dict(product.includes) if product and product.includes else dict(ctx.includes_default)
    if any(ctx.includes.get(k) for k in ("busbar", "n", "pe")):
        reasons.append({"source": "match", "value": "enclosure_includes", "status": "green"})
    return [_item_line(ctx, rule, chosen, Decimal(1), book, from_ids=ids, explanation=explanation, reasons=reasons)]


def rows_of(ctx: PanelContext) -> int | None:
    if ctx.enclosure is None:
        return None
    rows = num(ctx.enclosure, "rows")
    return int(rows) if rows else None


def din_rail(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    rows = rows_of(ctx)
    if rows is None or ctx.includes.get("din_rail"):
        return []
    width = num(ctx.enclosure, "width_mm") if ctx.enclosure else None
    rails = book.of_family(str(rule.item.get("family", "din_rail")))
    long_enough = [r for r in rails if width is None or (num(r, "length_mm") or 0) >= width]
    chosen = smallest(long_enough or rails, lambda i: (num(i, "length_mm") or 0,))
    if chosen is None:
        raise RuleFailed("אין מסילת DIN בקטלוג")
    return [_item_line(ctx, rule, chosen, Decimal(rows), book, explanation=f"מסילה לכל שורה בארון: {rows} שורות")]


def busbar(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    if ctx.includes.get("busbar"):
        return []
    qty = ctx.busbars or rows_of(ctx)
    if not qty:
        return []
    bars = book.of_family(str(rule.item.get("family", "busbar")))
    need = ctx.main_current or 0
    rated = [b for b in bars if (num(b, "current_a") or 0) >= need]
    chosen = smallest(rated, lambda i: (num(i, "current_a") or 0,))
    if chosen is None:
        raise RuleFailed(f"אין פס צבירה לזרם {_fmt(need)}A בקטלוג")
    why = f"{qty} פסי צבירה בשרטוט" if ctx.busbars else f"פס צבירה לכל שורה בארון: {qty}"
    if need:
        why += f", לזרם של המפסק הראשי ({_fmt(need)}A)"
    return [_item_line(ctx, rule, chosen, Decimal(qty), book, explanation=why)]


def terminals(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    family = str(rule.item.get("family", "terminal"))
    items = book.of_family(family)
    by_size: dict[float | None, list[Component]] = {}
    for c in ctx.auxiliary:
        a = c.attributes.get("cross_section_mm2")
        size = float(a.value) if a is not None and isinstance(a.value, int | float) else None
        by_size.setdefault(size, []).append(c)
    out: list[Draft] = []
    for size, comps in sorted(by_size.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        qty = Decimal(sum(c.quantity for c in comps))
        chosen = smallest(
            [i for i in items if (num(i, "cross_section_mm2") or 0) >= (size or 0)],
            lambda i: (num(i, "cross_section_mm2") or 0,),
        )
        text = f"{_fmt(qty)} מהדקים בשרטוט" + (f", {_fmt(size)} ממ״ר" if size else "")
        out.append(
            _item_line(
                ctx,
                rule,
                chosen,
                qty,
                book,
                sub=f":{_fmt(size) if size else 'x'}",
                description=None if chosen else "מהדקים",
                from_ids=[c.component_id for c in comps],
                explanation=text,
            )
        )
    per_output = Decimal(str(rule.params.get("per_output", "0")))
    if not ctx.auxiliary and per_output and ctx.outputs:
        chosen = smallest(items, lambda i: (num(i, "cross_section_mm2") or 0,))
        qty = per_output * ctx.outputs
        out.append(
            _item_line(
                ctx,
                rule,
                chosen,
                qty,
                book,
                description=None if chosen else "מהדקים",
                explanation=f"{_fmt(per_output)} לכל יציאה: {ctx.outputs} יציאות",
            )
        )
    return out


def labels(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    per_output = Decimal(str(rule.params.get("per_output", "1")))
    per_panel = Decimal(str(rule.params.get("per_panel", "1")))
    qty = per_output * ctx.outputs + per_panel
    if not qty or not ctx.lines:
        return []
    family = str(rule.item.get("family", "label"))
    own = sorted(book.unlinked(family), key=lambda p: p.product_id)
    chosen: Item | Product | None = own[0] if own else smallest(book.of_family(family), lambda i: ())
    return [
        _item_line(
            ctx,
            rule,
            chosen,
            qty,
            book,
            description=None if chosen else "שילוט",
            explanation=f"שלט לכל יציאה ({ctx.outputs}) ושלט ללוח",
        )
    ]


def service_price(family: str, unit_cost: Decimal | None, book: Book) -> Priced:
    """Labor and consumables: a cost of the factory's own, priced by its family's margin rule, else the default."""
    subject = pm.Subject(family, family, None, "rule", None, book.customer_id)
    sale = pm.sale_price(unit_cost, book.rules, subject, book.cost.on_date)
    if sale.unit_price_raw is None:
        return Priced(
            unit_cost,
            {"type": "factory_setting"},
            "missing",
            sale.rule,
            None,
            None,
            None,
            (sale.issue or "missing_cost",),
        )
    return Priced(
        unit_cost,
        {"type": "factory_setting"},
        "ok",
        sale.rule,
        sale.unit_price_raw,
        round_price(sale.unit_price_raw, book.rounding),
        book.rounding,
    )


def consumables(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    pct = Decimal(str(rule.params.get("pct", "0")))
    base = sum((ln.priced.unit_cost * ln.qty for ln in ctx.counted if ln.priced.unit_cost is not None), Decimal(0))
    if not pct or not base:
        return []
    cost = money(base * pct)
    return [
        Draft(
            key=f"d:{ctx.panel_id}:{rule.key}",
            panel_id=ctx.panel_id,
            line_type="derived",
            description="חומרי עזר",
            qty=Decimal(1),
            priced=service_price(FAMILY_CONSUMABLES, cost, book),
            line_group="enclosure",
            derived={
                "rule_id": rule.id,
                "rule_key": rule.key,
                "from_component_ids": [],
                "explanation": f"{_fmt(pct * 100)}% מעלות הרכיבים בלוח ({_fmt(money(base))} ₪)",
            },
        )
    ]


def service(ctx: PanelContext, rule: DerivedRule, book: Book) -> list[Draft]:
    word = str(rule.params.get("contains", ""))
    asked = [s for s in (ctx.requirement.services if ctx.requirement else ()) if word and word in s]
    where = ctx.requirement.source if ctx.requirement else "השרטוט"
    return [
        Draft(
            key=f"d:{ctx.panel_id}:{rule.key}:{n}",
            panel_id=ctx.panel_id,
            line_type="derived",
            description=note,
            qty=Decimal(1),
            priced=NO_SKU,
            line_group="enclosure",
            derived={
                "rule_id": rule.id,
                "rule_key": rule.key,
                "from_component_ids": [],
                "explanation": f"דרישה מ{where}. המפעל מחליט אם לתמחר",
                "service": True,
            },
        )
        for n, note in enumerate(asked)
    ]


KINDS: dict[str, Callable[[PanelContext, DerivedRule, Book], list[Draft]]] = {
    "enclosure": enclosure,
    "din_rail": din_rail,
    "busbar": busbar,
    "terminals": terminals,
    "labels": labels,
    "consumables": consumables,
    "service": service,
}
ORDER = tuple(KINDS)  # the enclosure first: the rails and busbars read what it chose; consumables after the items


def labor_line(ctx: PanelContext, labor: Labor, derived: Sequence[Draft], book: Book) -> Draft | None:
    hours: dict[str, Decimal] = {}
    for ln in [*ctx.counted, *derived]:
        item = book.item(ln.catalog_item_id)
        component = next((c for c in ctx.components if c.component_id == ln.component_id), None)
        family = item.family if item else component.family if component else None
        if family and family in labor.hours and not ln.included:
            hours[family] = hours.get(family, Decimal(0)) + labor.hours[family] * ln.qty
    total = sum(hours.values(), Decimal(0))
    if not total:
        return None
    breakdown = " · ".join(f"{fam}: {_fmt(h)}" for fam, h in sorted(hours.items()))
    return Draft(
        key=f"l:{ctx.panel_id}",
        panel_id=ctx.panel_id,
        line_type="labor",
        description=f"עבודה, {ctx.name}",
        qty=total.quantize(Decimal("0.001")),
        priced=service_price(FAMILY_LABOR, labor.hourly_rate, book),
        unit="hour",
        derived={
            "rule_id": "labor",
            "rule_key": "labor",
            "from_component_ids": [],
            "explanation": f"{_fmt(total)} שעות לפי משפחה ({breakdown}), {_fmt(labor.hourly_rate)} ₪ לשעה",
            "hours": {k: str(v) for k, v in sorted(hours.items())},
        },
    )


@dataclass
class Derived:
    lines: list[Draft]
    failed: list[tuple[str, str]]  # (rule key, why): `derived_rule_failed`
    consumable_ids: list[str] = field(default_factory=list)


def derive(
    ctx: PanelContext,
    rules: Sequence[DerivedRule],
    labor: Labor | None,
    book: Book,
    suppressed: set[str],
) -> Derived:
    """The panel's derived lines, in `ORDER`, then labor. `suppressed` holds the keys of lines the user deleted."""
    out: list[Draft] = []
    failed: list[tuple[str, str]] = []
    by_kind = {r.kind: r for r in rules if r.enabled and r.scope == "panel"}
    for kind in ORDER:
        rule = by_kind.get(kind)
        if rule is None:
            continue
        try:
            made = KINDS[kind](ctx, rule, book)
        except RuleFailed as e:
            failed.append((rule.key, str(e)))
            continue
        out += [ln for ln in made if ln.key not in suppressed]
    consumable = {p.product_id for p in book.products if p.consumable}
    consumable_ids = [ln.key for ln in ctx.lines if ln.product_id in consumable]
    if labor is not None:
        line = labor_line(ctx, labor, out, book)
        if line is not None and line.key not in suppressed:
            out.append(line)
    return Derived(out, failed, consumable_ids)
