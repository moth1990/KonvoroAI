"""`uv run python -m konboro.db.catalog <file.csv> [--kits k.csv] [--accessories a.csv]`: load a master-catalog
file and its companion files (docs/catalog-import.md)."""

import argparse
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..config import migration_dsn
from . import CatalogFormatError, load_file

parser = argparse.ArgumentParser(prog="python -m konboro.db.catalog")
parser.add_argument("items", type=Path)
parser.add_argument("--kits", type=Path)
parser.add_argument("--accessories", type=Path)
args = parser.parse_args()
try:
    with Session(create_engine(migration_dsn())) as session, session.begin():
        print(f"{load_file(session, args.items, args.kits, args.accessories)} catalog items loaded")
except CatalogFormatError as e:
    raise SystemExit("\n".join(e.errors)) from None
