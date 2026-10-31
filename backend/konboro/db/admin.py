"""Create and migrate a whole database: the integration tests' `konboro_test` and the E2E run's `konboro_e2e`.

Owner-only operations. The app itself never calls these.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from .bootstrap import ensure_app_role
from .config import APP_ROLE, app_role_password, migration_dsn

BACKEND = Path(__file__).resolve().parents[2]


def database_dsn(name: str, role: str = "owner") -> str:
    """The local server's DSN for database `name`, as the owner or as konboro_app."""
    url = make_url(migration_dsn()).set(database=name)
    if role == "app":
        url = url.set(username=APP_ROLE, password=app_role_password())
    return url.render_as_string(hide_password=False)


def recreate_database(name: str) -> None:
    admin = create_engine(database_dsn("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@contextmanager
def migrating(dsn: str) -> Iterator[Config]:
    """alembic/env.py reads the DSN from the environment: point it at `dsn`, then put the caller's back."""
    previous = os.environ.get("KONBORO_MIGRATION_DSN")
    os.environ["KONBORO_MIGRATION_DSN"] = dsn
    try:
        yield alembic_config()
    finally:
        if previous is None:
            os.environ.pop("KONBORO_MIGRATION_DSN", None)
        else:
            os.environ["KONBORO_MIGRATION_DSN"] = previous


def fresh_database(name: str) -> str:
    """Drop and recreate `name`, make sure konboro_app exists, migrate to head. Returns the owner DSN."""
    recreate_database(name)
    ensure_app_role(database_dsn("postgres"))
    owner_dsn = database_dsn(name)
    with migrating(owner_dsn) as cfg:
        command.upgrade(cfg, "head")
    return owner_dsn
