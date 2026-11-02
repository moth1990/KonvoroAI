"""The master catalog's import format and its loader (07 §4.3, 05 §4.3; S18 decision 1). The layout is documented
in docs/catalog-import.md.

The catalog is the shared layer (docs/db-schema.md §3.2): global, with no prices of any factory. The loader writes
it as the owner role, like the seed, since the app role may only read global tables:

    uv run python -m konboro.db.catalog path/to/catalog.csv

`abb_sample.csv` is the sample `make seed` loads until the real catalog arrives (roadmap B3): 20 ABB items, the
demo price list's ABB products and a few more, with made-up list prices.
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
from ..models import CatalogItem

SAMPLE = Path(__file__).with_name("abb_sample.csv")
REQUIRED = ("brand", "sku", "family")
OPTIONAL = ("series", "model_code", "module_width", "list_price", "list_currency", "status", "replaced_by_sku")
COLUMNS = REQUIRED + OPTIONAL
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
    module_width: Decimal | None = None
    list_price: Decimal | None = None
    list_currency: str | None = None
    status: str = "active"
    replaced_by_sku: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


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


def load(session: Session, rows: list[CatalogRow]) -> int:
    """Upserts on (brand, sku): a rerun updates the rows in place and keeps their ids. Returns the rows written."""
    for row in rows:
        values = {
            "sku": row.sku,
            "brand": row.brand,
            "family": row.family,
            "series": row.series,
            "model_code": row.model_code,
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
    return len(rows)


def load_file(session: Session, path: Path) -> int:
    return load(session, parse(path.read_text(encoding="utf-8")))
