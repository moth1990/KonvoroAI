"""Write the OpenAPI spec for `make gen-client`: `python -m konboro.api.openapi <path>`.

Builds the app without touching the DB, with fixed settings, so the output depends only on the code.
"""

import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from konboro.settings import Settings

from .app import create_app


def spec() -> dict[str, Any]:
    # A lazy engine that is never connected: building the spec must not need Postgres.
    engine = create_engine("postgresql+psycopg://unused@localhost/unused")
    return create_app(Settings(_env_file=None, env="local"), engine=engine).openapi()  # type: ignore[call-arg]


def main(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(spec(), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
