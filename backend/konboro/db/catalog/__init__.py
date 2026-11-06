"""The master catalog's import format and its loader (07 §4.3, 05 §4.3; S18 decision 1). The layout is documented
in docs/catalog-import.md.

The catalog is the shared layer (docs/db-schema.md §3.2): global, with no prices of any factory. The loader writes
it as the owner role, like the seed, since the app role may only read global tables:

    uv run python -m konboro.db.catalog path/to/catalog.csv [--kits kits.csv] [--accessories accessories.csv]

The items file may come with two companion files (05 §5.9.1, S20 decision 4): a kit's parts, and which accessory fits
which series. Their rows name items by brand and sku, of this file or already in the catalog.

`sample.csv` (with `sample_kits.csv` and `sample_accessories.csv`) is the sample `make seed` loads until the real
catalog arrives (roadmap B3): ABB and Schneider items covering the golden drawings' families, with made-up list
prices (S20 decision 1). `common.csv` follows it: the common products the user listed from three factory drawings
(25/886, 2240-P-001, 25/823; S27b), real ones with no price, kept apart so the sample stays the sample.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import CatalogAccessory, CatalogItem, CatalogKit

SAMPLE = Path(__file__).with_name("sample.csv")
SAMPLE_KITS = Path(__file__).with_name("sample_kits.csv")
SAMPLE_ACCESSORIES = Path(__file__).with_name("sample_accessories.csv")
COMMON = Path(__file__).with_name("common.csv")
REQUIRED = ("brand", "sku", "family")
OPTIONAL = (
    "series",
    "model_code",
    "model_tokens",
    "symbol_class",
    "module_width",
    "list_price",
    "list_currency",
    "status",
    "replaced_by_sku",
)
COLUMNS = REQUIRED + OPTIONAL
KIT_COLUMNS = ("brand", "item_sku", "part_sku", "quantity", "when_text", "reason_he")
ACCESSORY_COLUMNS = ("brand", "accessory_sku", "fits_brand", "fits_series")
ATTR = "attr."
STATUSES = ("active", "discontinued")
CURRENCY = re.compile(r"^[A-Z]{3}$")
INTEGER = re.compile(r"^-?\d+$")
NUMBER = re.compile(r"^-?\d+\.\d+$")


@dataclass(frozen=True)
class CatalogRow:
    brand: str
    sku: str
    family: str
    series: str | None = None
    model_code: str | None = None
    model_tokens: tuple[str, ...] = ()
    symbol_class: str | None = None
    module_width: Decimal | None = None
    list_price: Decimal | None = None
    list_currency: str | None = None
    status: str = "active"
    replaced_by_sku: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KitRow:
    brand: str
    item_sku: str
    part_sku: str
    quantity: int
    when_text: str  # empty: the part always comes with the item
    reason_he: str


@dataclass(frozen=True)
class AccessoryRow:
    brand: str
    accessory_sku: str
    fits_brand: str
    fits_series: str


class CatalogFormatError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def attribute(text: str) -> Any:
    """An attribute value as stage 4 writes it (04 §6): a JSON boolean or number, else the text. A measurement, never
    money, so a fraction is a JSON number like stage 4's (6.3)."""
    if text in ("true", "false"):
        return text == "true"
    if INTEGER.match(text):
        return int(text)
    if NUMBER.match(text):
        return float(text)
    return text


def decimal(text: str, column: str, line: int, errors: list[str]) -> Decimal | None:
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        errors.append(f"line {line}: {column} {text!r} is not a number")
        return None
    if not value.is_finite() or value < 0:
        errors.append(f"line {line}: {column} {text!r} must be zero or more")
        return None
    return value


def tokens(cell: dict[str, str]) -> tuple[str, ...]:
    """`model_tokens` is `|`-separated ("XT1C160|XT1C|XT1"); without it, the model code alone. Upper case, with no
    spaces, as stage 5 compares them (05 §5.2.1)."""
    raw = cell.get("model_tokens") or cell.get("model_code") or ""
    out: list[str] = []
    for t in raw.split("|"):
        t = "".join(t.split()).upper()
        if t and t not in out:
            out.append(t)
    return tuple(out)


def parse(text: str) -> list[CatalogRow]:
    """Every problem in the file at once, with its line number; nothing is loaded from a file with any."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = reader.fieldnames or []
    errors = [f"missing column {c!r}" for c in REQUIRED if c not in header]
    errors += [f"unknown column {c!r}" for c in header if c not in COLUMNS and not c.startswith(ATTR)]
    if errors:
        raise CatalogFormatError(errors)
    rows: list[CatalogRow] = []
    seen: set[tuple[str, str]] = set()
    for line, raw in enumerate(reader, start=2):
        cell = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        missing = [c for c in REQUIRED if not cell[c]]
        if missing:
            errors.append(f"line {line}: empty {', '.join(missing)}")
            continue
        key = (cell["brand"], cell["sku"])
        if key in seen:
            errors.append(f"line {line}: {key[0]} {key[1]} appears twice")
            continue
        seen.add(key)
        status = cell.get("status") or "active"
        if status not in STATUSES:
            errors.append(f"line {line}: status {status!r} is not one of {', '.join(STATUSES)}")
        currency = cell.get("list_currency") or None
        if currency is not None and not CURRENCY.match(currency):
            errors.append(f"line {line}: list_currency {currency!r} is not a 3-letter code")
        price = decimal(cell.get("list_price", ""), "list_price", line, errors)
        if price is not None and currency is None:
            errors.append(f"line {line}: list_price needs list_currency")
        rows.append(
            CatalogRow(
                brand=cell["brand"],
                sku=cell["sku"],
                family=cell["family"],
                series=cell.get("series") or None,
                model_code=cell.get("model_code") or None,
                model_tokens=tokens(cell),
                symbol_class=cell.get("symbol_class") or None,
                module_width=decimal(cell.get("module_width", ""), "module_width", line, errors),
                list_price=price,
                list_currency=currency,
                status=status,
                replaced_by_sku=cell.get("replaced_by_sku") or None,
                attributes={k[len(ATTR) :]: attribute(v) for k, v in cell.items() if k.startswith(ATTR) and v},
            )
        )
    for row in rows:
        if row.replaced_by_sku is not None and (row.brand, row.replaced_by_sku) not in seen:
            errors.append(f"{row.brand} {row.sku}: replaced_by_sku {row.replaced_by_sku!r} is not in the file")
    if errors:
        raise CatalogFormatError(errors)
    return rows


def _table(text: str, columns: tuple[str, ...], required: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = reader.fieldnames or []
    errors = [f"missing column {c!r}" for c in required if c not in header]
    errors += [f"unknown column {c!r}" for c in header if c not in columns]
    if errors:
        raise CatalogFormatError(errors)
    out: list[tuple[int, dict[str, str]]] = []
    for line, raw in enumerate(reader, start=2):
        cell = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        missing = [c for c in required if not cell.get(c)]
        if missing:
            errors.append(f"line {line}: empty {', '.join(missing)}")
        out.append((line, cell))
    if errors:
        raise CatalogFormatError(errors)
    return out


def parse_kits(text: str) -> list[KitRow]:
    rows: list[KitRow] = []
    errors: list[str] = []
    for line, cell in _table(text, KIT_COLUMNS, ("brand", "item_sku", "part_sku", "reason_he")):
        quantity = cell.get("quantity") or "1"
        if not INTEGER.match(quantity) or int(quantity) < 1:
            errors.append(f"line {line}: quantity {quantity!r} must be a whole number, 1 or more")
            continue
        rows.append(
            KitRow(
                cell["brand"],
                cell["item_sku"],
                cell["part_sku"],
                int(quantity),
                cell.get("when_text", ""),
                cell["reason_he"],
            )
        )
    if errors:
        raise CatalogFormatError(errors)
    return rows


def parse_accessories(text: str) -> list[AccessoryRow]:
    return [
        AccessoryRow(c["brand"], c["accessory_sku"], c["fits_brand"], c["fits_series"])
        for _, c in _table(text, ACCESSORY_COLUMNS, ACCESSORY_COLUMNS)
    ]


def load(
    session: Session,
    rows: list[CatalogRow],
    kits: list[KitRow] | None = None,
    accessories: list[AccessoryRow] | None = None,
) -> int:
    """Upserts on (brand, sku): a rerun updates the rows in place and keeps their ids. Returns the rows written."""
    for row in rows:
        values = {
            "sku": row.sku,
            "brand": row.brand,
            "family": row.family,
            "series": row.series,
            "model_code": row.model_code,
            "model_tokens": list(row.model_tokens),
            "symbol_class": row.symbol_class,
            "module_width": row.module_width,
            "list_price": row.list_price,
            "list_currency": row.list_currency,
            "status": row.status,
            "attributes": row.attributes,
        }
        session.execute(
            insert(CatalogItem)
            .values(id=new_id("cat"), source="import", **values)
            .on_conflict_do_update(index_elements=["brand", "sku"], set_=values)
        )
    brands = {row.brand for row in rows}
    items = {(i.brand, i.sku): i for i in session.scalars(select(CatalogItem).where(CatalogItem.brand.in_(brands)))}
    for row in rows:
        replaced_by = items[(row.brand, row.replaced_by_sku)].id if row.replaced_by_sku else None
        items[(row.brand, row.sku)].replaced_by = replaced_by
    session.flush()
    _links(session, kits or [], accessories or [])
    return len(rows)


def _links(session: Session, kits: list[KitRow], accessories: list[AccessoryRow]) -> None:
    """Kits and accessories name items by brand and sku; any that is not in the catalog fails the whole load. A
    rerun with the same rows changes nothing (upsert on the natural key)."""
    wanted = {(k.brand, s) for k in kits for s in (k.item_sku, k.part_sku)}
    wanted |= {(a.brand, a.accessory_sku) for a in accessories}
    brands = {b for b, _ in wanted}
    ids = {
        (i.brand, i.sku): i.id
        for i in session.scalars(select(CatalogItem).where(CatalogItem.brand.in_(brands)))
        if (i.brand, i.sku) in wanted
    }
    errors = [f"{b} {s} is not in the catalog" for b, s in sorted(wanted - set(ids))]
    if errors:
        raise CatalogFormatError(errors)
    for k in kits:
        item, part = ids[(k.brand, k.item_sku)], ids[(k.brand, k.part_sku)]
        session.execute(
            insert(CatalogKit)
            .values(
                id=new_id("ckt"),
                item_id=item,
                part_id=part,
                quantity=k.quantity,
                when_text=k.when_text,
                reason_he=k.reason_he,
                source="import",
            )
            .on_conflict_do_update(
                index_elements=["item_id", "part_id", "when_text"],
                set_={"quantity": k.quantity, "reason_he": k.reason_he},
            )
        )
    for a in accessories:
        session.execute(
            insert(CatalogAccessory)
            .values(
                id=new_id("cac"),
                accessory_id=ids[(a.brand, a.accessory_sku)],
                fits_brand=a.fits_brand,
                fits_series=a.fits_series,
                source="import",
            )
            .on_conflict_do_nothing(index_elements=["accessory_id", "fits_brand", "fits_series"])
        )
    session.flush()


def load_file(session: Session, path: Path, kits: Path | None = None, accessories: Path | None = None) -> int:
    return load(
        session,
        parse(path.read_text(encoding="utf-8")),
        parse_kits(kits.read_text(encoding="utf-8")) if kits else None,
        parse_accessories(accessories.read_text(encoding="utf-8")) if accessories else None,
    )


def load_sample(session: Session) -> int:
    return load_file(session, SAMPLE, SAMPLE_KITS, SAMPLE_ACCESSORIES) + load_file(session, COMMON)
