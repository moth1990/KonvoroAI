"""07 §7.1: lines from stage 5's matches and stage 4's missing rows, grouped by panel.

| From | Line |
| --- | --- |
| a match with a SKU | `component`, priced from the factory's price list |
| a match without one (`unmatched`, `ambiguous`, `conflict`) | `component`, no price, red |
| a row in `missing[]` | `missing`, no price, red |
| a kit's part (05 §5.9.1) | a child line under its device: priced on its own, or "included" (0.00) when the |
| | device's product lists the part's SKU in `includes` |
| an accessory with `parent_designators` | a child line under its device's line, priced on its own |

`supply_scope` (04 §5.1.2, 07 §7.4): `other_location` is priced in its own "מחוץ ללוח" group and stays out of the
enclosure's module count; `prepare_only` and `by_others` are not priced and become a note on the panel.

Stage 5's auxiliary families (terminals) get no line of their own here; the derived rules count them (S20 decision 3).
Every line keeps the reasons for its colour that are not about price (`reasons`); `status.py` adds the price's and
decides the colour (07 §7.5).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from konboro.contracts.matching import Alternative, ComponentMatch
from konboro.contracts.merge import Component, MissingInstance
from konboro.contracts.validation import Issue
from konboro.pipeline.audit.differences import describe
from konboro.pipeline.matching.match import ACCESSORY_FAMILIES

from .book import INCLUDED, Book, Priced, Product, price

# 09 §6.3's groups (db-schema `line_group`). A panel's main device is "feed" whatever its family (06 §6.1).
FEED = frozenset({"changeover_switch", "ats", "energy_meter", "current_transformer", "measuring_instrument"})
OUTPUTS = frozenset(
    {"circuit_breaker", "rcd", "rcbo", "fuse", "socket_outlet", "switch_disconnector", "surge_protector"}
)
OUTSIDE = "outside"  # 07 §7.4 "מחוץ ללוח"
SEVERITY_STATUS = {"error": "red", "warning": "yellow", "info": "green"}
NO_SKU = Priced(None, None, "missing", None, None, None, None)  # a match problem, not a price-list one: no issue

# how a value filled in by default reads in its chip ("פחת 30mA: ברירת מחדל")
DEFAULT_WORDING = {
    "residual_ma": "פחת {}mA",
    "curve": "עקומה {}",
    "breaking_capacity_ka": "{}kA",
    "current_a": "{}A",
    "poles": "{}P",
    "rcd_type": "סוג {}",
}


@dataclass
class Draft:
    """One line on its way to the quote (07 §6.2). `key` is stable for the same input, so a rerun can carry what the
    user did on the line (S22 decision 5)."""

    key: str
    panel_id: str | None
    line_type: str
    description: str
    qty: Decimal
    priced: Priced
    line_group: str | None = None
    component_id: str | None = None
    parent: str | None = None
    product_id: str | None = None
    catalog_item_id: str | None = None
    sku: str | None = None
    manufacturer: str | None = None
    unit: str = "unit"
    derived: dict[str, Any] | None = None
    explanation: str | None = None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[dict[str, Any]] = field(default_factory=list)
    issue_ids: list[str] = field(default_factory=list)
    override: dict[str, Any] | None = None
    edits: dict[str, Any] = field(default_factory=dict)  # the review screen's, as stored (`edits.LineEdits`)
    approved_at: datetime | None = None  # the estimator approved the line (09 §7.2)
    query_failed: bool = False  # a derived line whose catalog query found nothing (07 §7.5, `enclosure_not_found`)
    status: str = "red"
    status_reasons: list[dict[str, Any]] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.approved_at is not None

    @property
    def included(self) -> bool:
        return self.parent is not None and self.priced.unit_price is not None and self.priced.unit_price == 0


@dataclass
class PanelLines:
    lines: list[Draft]
    notes: list[str]  # 07 §7.4: `prepare_only` / `by_others`, shown on the quote, not priced


def group_of(c: Component, main_ids: set[str]) -> str:
    if c.supply_scope == "other_location":
        return OUTSIDE
    if c.component_id in main_ids or c.family in FEED:
        return "feed"
    return "outputs" if c.family in OUTPUTS else "control"


def values_of(c: Component | MissingInstance) -> dict[str, Any]:
    return {k: a.value for k, a in c.attributes.items() if a.value is not None}


def match_reasons(m: ComponentMatch) -> list[dict[str, Any]]:
    """07 §7.5 "סטטוס ההתאמה": matched is green, ambiguous yellow, unmatched and conflict red. The chips the review
    screen shows (09 §6.3) ride along as green reasons: they explain, they don't colour."""
    if m.status == "ambiguous":
        return [{"source": "match", "value": "ambiguous", "status": "yellow"}]
    if m.status in ("unmatched", "conflict"):
        return [{"source": "match", "value": m.status, "status": "red"}]
    code = {"explicit_sku": "explicit_model", "explicit_series": "explicit_model", "memory": "memory"}.get(
        m.method or "", "matched"
    )
    out: list[dict[str, Any]] = [{"source": "match", "value": code, "status": "green"}]
    for name in m.defaulted_attributes:
        used = m.attributes_used.get(name)
        value = DEFAULT_WORDING.get(name, name + " {}").format(used.value if used else "")
        out.append({"source": "match", "value": {"code": "defaulted_attribute", "value": value}, "status": "green"})
    if any(u.source == "inferred" for u in m.attributes_used.values()):
        out.append({"source": "match", "value": "inferred_attribute", "status": "green"})
    if m.substitution is not None:
        out.append(
            {
                "source": "match",
                "value": {
                    "code": "brand_substituted",
                    "drawing": m.substitution.requested_brand,
                    "chosen": m.substitution.chosen_brand,
                },
                "status": "green",
            }
        )
    if m.bundle_lines:
        out.append({"source": "match", "value": "kit", "status": "green"})
    return out


def confidence_reason(value: float) -> dict[str, Any]:
    """00 §6.4: ≥ 0.85 green, 0.5–0.85 yellow, < 0.5 red."""
    status = "green" if value >= 0.85 else "yellow" if value >= 0.5 else "red"
    return {"source": "confidence", "value": round(value, 2), "status": status}


def validator_reasons(issues: Sequence[Issue]) -> list[dict[str, Any]]:
    return [
        {"source": "validator", "value": None, "issue_id": i.issue_id, "status": SEVERITY_STATUS[i.severity]}
        for i in issues
    ]


def alternative(a: Alternative) -> dict[str, Any]:
    """05 §5.9 for the review screen's "חלופות" (09 §6.4), which shows `description` (the S09 fixture's shape)."""
    head = " ".join(x for x in (a.manufacturer, a.sku) if x)
    return {"description": f"{head} · {a.diff}" if a.diff else head, **a.model_dump(mode="json")}


def component_line(
    c: Component, m: ComponentMatch | None, book: Book, group: str, issues: Sequence[Issue]
) -> tuple[Draft, Product | None]:
    item = m.catalog_item if m else None
    catalog = book.item_by_sku(item.manufacturer, item.sku) if item else None
    product = book.product(catalog.id if catalog else None, m.chosen_sku) if m and m.chosen_sku else None
    priced = price(product, book) if m and m.chosen_sku else NO_SKU
    reasons = [confidence_reason(m.confidence if m else c.confidence)]
    reasons += match_reasons(m) if m else [{"source": "match", "value": "unmatched", "status": "red"}]
    reasons += validator_reasons(issues)
    return (
        Draft(
            key=f"c:{c.component_id}",
            panel_id=c.panel_id,
            line_type="component",
            description=item.description if item else describe(c.family, c.symbol_class, values_of(c)),
            qty=Decimal(c.quantity),
            priced=priced,
            line_group=group,
            component_id=c.component_id,
            product_id=product.product_id if product else None,
            catalog_item_id=catalog.id if catalog else None,
            sku=m.chosen_sku if m else None,
            manufacturer=item.manufacturer if item else None,
            unit=product.unit if product else "unit",
            explanation=m.reason or None if m else None,
            alternatives=[alternative(a) for a in m.alternatives] if m else [],
            reasons=reasons,
            issue_ids=[i.issue_id for i in issues],
        ),
        product,
    )


def kit_lines(parent: Draft, m: ComponentMatch, product: Product | None, book: Book) -> list[Draft]:
    """05 §5.9.1: a kit's parts under the device's line, `quantity` per unit of the device."""
    out: list[Draft] = []
    for n, part in enumerate(m.bundle_lines):
        included = product is not None and bool(product.includes.get(part.sku))
        catalog = book.item_by_sku(part.manufacturer, part.sku)
        own = book.product(catalog.id if catalog else None, part.sku)
        out.append(
            Draft(
                key=f"{parent.key}:kit:{n}",
                panel_id=parent.panel_id,
                line_type="component",
                description=part.description,
                qty=parent.qty * part.quantity,
                priced=INCLUDED if included else price(own, book),
                line_group=parent.line_group,
                component_id=parent.component_id,
                parent=parent.key,
                product_id=None if included or own is None else own.product_id,
                catalog_item_id=catalog.id if catalog else None,
                sku=part.sku,
                manufacturer=part.manufacturer,
                explanation=part.reason,
                reasons=[{"source": "match", "value": "kit", "status": "green"}],
            )
        )
    return out


def missing_line(x: MissingInstance) -> Draft:
    return Draft(
        key=f"m:{x.instance_id}",
        panel_id=x.panel_id,
        line_type="missing",
        description=describe(x.family, x.family, values_of(x)),
        qty=Decimal(1),
        priced=NO_SKU,
        line_group=None,
        explanation=x.origin or None,
        reasons=[confidence_reason(x.confidence), {"source": "missing", "value": x.origin, "status": "red"}],
    )


def panel_lines(
    panel_id: str,
    components: Sequence[Component],
    matches: Mapping[str, ComponentMatch],
    auxiliary: set[str],
    missing: Sequence[MissingInstance],
    issues_by_component: Mapping[str, list[Issue]],
    main_ids: set[str],
    book: Book,
) -> PanelLines:
    lines: list[Draft] = []
    notes: list[str] = []
    by_designator: dict[str, Draft] = {}
    accessories: list[tuple[Component, Draft]] = []
    for c in components:
        if c.panel_id != panel_id or c.component_id in auxiliary:
            continue
        m = matches.get(c.component_id)
        if c.supply_scope in ("prepare_only", "by_others"):
            what = "הכנה בלבד" if c.supply_scope == "prepare_only" else "באחריות אחרים"
            name = m.catalog_item.description if m and m.catalog_item else describe(c.family, c.symbol_class, {})
            notes.append(f"{what}: {name} ({', '.join(c.designators)})" if c.designators else f"{what}: {name}")
            continue
        line, product = component_line(c, m, book, group_of(c, main_ids), issues_by_component.get(c.component_id, []))
        if c.family in ACCESSORY_FAMILIES and c.parent_designators:
            accessories.append((c, line))
            continue
        lines.append(line)
        if m is not None:
            lines += kit_lines(line, m, product, book)
        for d in c.designators:
            by_designator.setdefault(d, line)
    for c, line in accessories:
        parent = next((by_designator[d] for d in c.parent_designators if d in by_designator), None)
        if parent is not None:
            line.parent, line.line_group = parent.key, parent.line_group
        lines.append(line)
    lines += [missing_line(x) for x in missing if x.panel_id == panel_id]
    return PanelLines(lines, notes)
