"""`uv run python -m konboro.db.catalog <file.csv>`: load a master-catalog file (docs/catalog-import.md)."""

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..config import migration_dsn
from . import CatalogFormatError, load_file

if len(sys.argv) != 2:
    sys.exit("usage: python -m konboro.db.catalog <file.csv>")
try:
    with Session(create_engine(migration_dsn())) as session, session.begin():
        print(f"{load_file(session, Path(sys.argv[1]))} catalog items loaded")
except CatalogFormatError as e:
    sys.exit("\n".join(e.errors))
