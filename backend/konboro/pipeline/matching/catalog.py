"""The master catalog as stage 5 reads it (05 §4.3): items with their attributes, model tokens and status, the kits
and which accessory fits which series (05 §5.9.1). Global and read-only; no price is kept here (05 §12): a price is
the factory's, and only `factory.py` turns it into a yes or no.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.contracts.matching import CatalogItemSnapshot
from konboro.db import models as m

from . import text

_SKU_NOISE = re.compile(r"[\s\-./_]+")
PRODUCT = "prd:"  # a factory product made in "מוצר חדש", as stage 5 sees it (05 §5.6, S27b)


def norm_sku(value: str) -> str:
    """05 §5.2 item 2: spaces, hyphens and dots removed, upper case."""
    return _SKU_NOISE.sub("", value).upper()


def norm_token(value: str, brands: frozenset[str] = frozenset()) -> str:
    """A model code as the catalog keeps it (`model_tokens`): upper case, no spaces, a leading brand dropped
    ("ABB-XT1C" → "XT1C")."""
    t = "".join(value.split()).upper()
    for brand in sorted(brands, key=len, reverse=True):
        b = brand.upper()
        if t.startswith(b) and len(t) > len(b):
            return t[len(b) :].lstrip("-_.")
    return t


@dataclass(frozen=True)
class Item:
    id: str
    sku: str
    brand: str
    series: str | None
    model_code: str | None
    model_tokens: tuple[str, ...]
    family: str
    symbol_class: str | None
    attributes: dict[str, Any]
    status: str
    replaced_by: str | None

    @property
    def description(self) -> str:
        return text.describe(self.family, self.symbol_class, self.brand, self.model_code, self.attributes)

    def snapshot(self) -> CatalogItemSnapshot:
        """05 §12: kept in the match as it was, so a later catalog change never moves a sent quote."""
        return CatalogItemSnapshot(
            sku=self.sku,
            manufacturer=self.brand,
            series=self.series,
            description=self.description,
            attributes=dict(self.attributes),
        )


@dataclass(frozen=True)
class Kit:
    part: Item
    quantity: int
    when_text: str  # empty: always
    reason: str


@dataclass
class Catalog:
    items: dict[str, Item]
    kits: dict[str, list[Kit]] = field(default_factory=dict)  # main item id → its parts
    fits: dict[str, set[tuple[str, str]]] = field(default_factory=dict)  # accessory id → {(brand, series)}
    by_family: dict[str, list[Item]] = field(default_factory=dict)
    by_sku: dict[str, list[Item]] = field(default_factory=dict)  # normalized sku → items
    by_token: dict[str, list[Item]] = field(default_factory=dict)  # model token → items

    def __post_init__(self) -> None:
        fam: dict[str, list[Item]] = defaultdict(list)
        skus: dict[str, list[Item]] = defaultdict(list)
        tokens: dict[str, list[Item]] = defaultdict(list)
        for item in sorted(self.items.values(), key=lambda i: (i.brand, i.sku)):
            fam[item.family].append(item)
            skus[norm_sku(item.sku)].append(item)
            for t in item.model_tokens:
                tokens[t].append(item)
        self.by_family, self.by_sku, self.by_token = dict(fam), dict(skus), dict(tokens)

    @property
    def brands(self) -> frozenset[str]:
        return frozenset(i.brand for i in self.items.values())

    def classes(self, family: str) -> set[str]:
        return {i.symbol_class for i in self.by_family.get(family, []) if i.symbol_class}

    def top_current(self, family: str, symbol_class: str) -> float | None:
        """The largest rated current the catalog has for a class (BUG-070: where its MCBs stop)."""
        currents = [
            float(v)
            for i in self.by_family.get(family, [])
            if i.symbol_class == symbol_class and i.status == "active"
            for v in [i.attributes.get("current_a")]
            if isinstance(v, int | float) and not isinstance(v, bool)
        ]
        return max(currents) if currents else None

    def active(self, item: Item) -> Item | None:
        """An active item, or what replaced a discontinued one (05 §5.6), or None."""
        seen: set[str] = set()
        while item.status != "active":
            if item.replaced_by is None or item.replaced_by in seen or item.replaced_by not in self.items:
                return None
            seen.add(item.id)
            item = self.items[item.replaced_by]
        return item


def from_rows(
    rows: list[m.CatalogItem],
    kits: list[m.CatalogKit] | None = None,
    accessories: list[m.CatalogAccessory] | None = None,
) -> Catalog:
    items = {
        r.id: Item(
            id=r.id,
            sku=r.sku,
            brand=r.brand,
            series=r.series,
            model_code=r.model_code,
            model_tokens=tuple(r.model_tokens or ()),
            family=r.family,
            symbol_class=r.symbol_class,
            attributes=dict(r.attributes or {}),
            status=r.status,
            replaced_by=r.replaced_by,
        )
        for r in rows
    }
    by_item: dict[str, list[Kit]] = defaultdict(list)
    for k in sorted(kits or [], key=lambda k: (k.item_id, k.part_id)):
        if k.item_id in items and k.part_id in items:
            by_item[k.item_id].append(Kit(items[k.part_id], k.quantity, k.when_text or "", k.reason_he))
    fits: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for a in accessories or []:
        fits[a.accessory_id].add((a.fits_brand, a.fits_series))
    return Catalog(items, dict(by_item), dict(fits))


def product_item(p: m.Product) -> Item | None:
    """A factory product as a candidate (05 §5.6, S27b): one made in "מוצר חדש", with its family's attributes, a brand
    and a model. Its SKU is the maker's when it has one, else its model. A product typed in the price list has no
    attributes and stays out; one linked to a catalog item is that item already."""
    if p.catalog_item_id or not p.attributes or not p.brand or not p.model_code:
        return None
    token = norm_token(p.model_code)
    return Item(
        id=PRODUCT + p.id,
        sku=p.manufacturer_sku or p.model_code,
        brand=p.brand,
        series=p.series,
        model_code=p.model_code,
        model_tokens=(token,) if token else (),
        family=p.family,
        symbol_class=p.symbol_class,
        attributes=dict(p.attributes),
        status="active",
        replaced_by=None,
    )


def with_products(catalog: Catalog, products: list[m.Product]) -> Catalog:
    """The catalog and the factory's own products (05 §5.6, S27b). Kits and fits are the catalog's only."""
    items = dict(catalog.items)
    for p in products:
        item = product_item(p)
        if item is not None:
            items[item.id] = item
    return Catalog(items, catalog.kits, catalog.fits)


def factory_products(session: Session, tenant_id: str) -> list[m.Product]:
    return list(
        session.scalars(
            select(m.Product).where(
                m.Product.tenant_id == tenant_id,
                m.Product.catalog_item_id.is_(None),
                m.Product.model_code.is_not(None),
            )
        )
    )


def load(session: Session) -> Catalog:
    """The whole catalog: a few thousand rows at most in v1.0 (roadmap B3), read once per drawing."""
    return from_rows(
        list(session.scalars(select(m.CatalogItem))),
        list(session.scalars(select(m.CatalogKit))),
        list(session.scalars(select(m.CatalogAccessory))),
    )
