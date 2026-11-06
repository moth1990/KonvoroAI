"""05 §5.9.2 (S27b): the products nearest a component nothing matched, for the user to choose from.

A suggestion, never a choice: the match stays `unmatched`, with no SKU and no price (05 §1 principles 2 and 3), and the
review screen shows the products with what differs ("20A במקום 16A"). Only when the candidate query found nothing at
all, and never when the current or the poles are missing: then there is nothing to compare with, and the user picks the
value (09 §6.4).

Ranked in code, with no model:
1. a product with the drawing's poles before any with other poles (the user's decision 2),
2. the attributes that differ, weighted (current, curve, breaking capacity, residual current, RCD type, then the rest),
   an attribute the product doesn't state counting half,
3. the relative distance of the numeric values that differ (16A is nearer 20A than 32A),
4. the factory's brand, then a product it has a cost for.
"""

from dataclasses import dataclass
from typing import Any

from konboro.contracts.matching import ComponentMatch, Nearest
from konboro.contracts.merge import Component

from ..association.schemas import Schemas
from .catalog import PRODUCT, Catalog, Item
from .factory import Factory
from .query import _order, _same
from .text import difference

LIMIT = 3
WEIGHTS = {"current_a": 8.0, "curve": 4.0, "breaking_capacity_ka": 2.0, "residual_ma": 4.0, "rcd_type": 2.0}
UNSTATED = 0.5  # the product doesn't say: maybe the same, maybe not
SKIP = frozenset({"poles", "neutral"})  # poles rank first on their own; a neutral rides with them


@dataclass(frozen=True)
class _Wanted:
    """The component as `text.difference` compares it: its brand and the values stage 5 used."""

    brand: str | None
    series: str | None
    attributes: dict[str, Any]


def _differs(item: Item, name: str, want: Any, mode: str) -> float:
    have = item.attributes.get(name)
    if have is None:
        return UNSTATED
    if mode == "prefer":
        return 0.0
    if mode in ("gte", "lte"):
        a, b = _order(name, have), _order(name, want)
        if a is not None and b is not None:
            return 0.0 if (a >= b if mode == "gte" else a <= b) else 1.0
    return 0.0 if _same(have, want) else 1.0


def _distance(item: Item, name: str, want: Any) -> float:
    a, b = _order(name, item.attributes.get(name)), _order(name, want)
    if a is None or b is None or not b:
        return 0.0
    return abs(a - b) / abs(b)


def nearest(
    component: Component, match: ComponentMatch, catalog: Catalog, factory: Factory, schemas: Schemas
) -> list[Nearest]:
    if match.status != "unmatched" or "missing_required_attribute" in match.warnings:
        return []
    family = component.family
    sig = (match.signature or "").split("|")
    cls = sig[1] if len(sig) > 1 and sig[0] == family and sig[1] else component.symbol_class
    pool = [i for i in catalog.by_family.get(family, []) if i.status == "active"]
    if cls and cls in catalog.classes(family):
        pool = [i for i in pool if i.symbol_class in (cls, None)]
    if not pool:
        return []
    want = {k: u.value for k, u in match.attributes_used.items() if u.value is not None}
    modes = {a.name: a.match_mode for a in schemas.attributes(family)}
    brand = factory.customer_brand(family) or factory.preferred_brand(family)
    names = sorted((n for n in want if n not in SKIP), key=lambda n: (-WEIGHTS.get(n, 1.0), n))

    def key(item: Item) -> tuple[Any, ...]:
        poles = want.get("poles")
        other_poles = 0 if poles is None or _same(item.attributes.get("poles"), poles) else 1
        weighted = sum(WEIGHTS.get(n, 1.0) * _differs(item, n, want[n], modes.get(n, "exact")) for n in names)
        far = sum(_distance(item, n, want[n]) for n in names if _differs(item, n, want[n], modes.get(n, "exact")))
        return (
            other_poles,
            round(weighted, 6),
            round(far, 6),
            0 if brand is None or item.brand == brand else 1,
            0 if factory.has_cost(item) else 1,
            item.brand,
            item.sku,
        )

    ranked = sorted(pool, key=key)[:LIMIT]
    asked = match.brand_decision.brand if match.brand_decision else component.brand_hint
    out: list[Nearest] = []
    for item in ranked:
        wanted = _Wanted(asked or item.brand, item.series, want)  # a brand nobody asked for is no difference
        differ = [n for n in ("poles", *names) if n in want and _differs(item, n, want[n], modes.get(n, "exact"))]
        out.append(
            Nearest(
                sku=item.sku,
                manufacturer=item.brand,
                description=item.description,
                diff=difference(wanted, item, tuple(differ)),
                differs=differ,
                catalog_item_id=None if item.id.startswith(PRODUCT) else item.id,
                product_id=item.id[len(PRODUCT) :] if item.id.startswith(PRODUCT) else None,
                has_cost_price=factory.has_cost(item),
            )
        )
    return out
