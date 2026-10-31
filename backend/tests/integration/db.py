"""A fresh, migrated test database (konboro_test), shared by the integration tests that need the schema."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from konboro.db.bootstrap import ensure_app_role
from konboro.db.config import APP_ROLE, app_role_password, migration_dsn

from .factory import GLOBAL_FLAG, GLOBAL_PLAN, GLOBAL_SYMBOL

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def database_dsn(name: str, role: str = "owner") -> str:
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


def alembic(dsn: str) -> Config:
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    os.environ["KONBORO_MIGRATION_DSN"] = dsn
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[dict[str, Engine]]:
    name = "konboro_test"
    recreate_database(name)
    ensure_app_role(database_dsn("postgres"))
    previous = os.environ.get("KONBORO_MIGRATION_DSN")
    owner_dsn = database_dsn(name)
    command.upgrade(alembic(owner_dsn), "head")
    if previous is None:
        os.environ.pop("KONBORO_MIGRATION_DSN", None)
    else:
        os.environ["KONBORO_MIGRATION_DSN"] = previous

    owner = create_engine(owner_dsn)
    app = create_engine(database_dsn(name, role="app"))
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO plans (id, name_he) VALUES (:p, 'בדיקה')"), {"p": GLOBAL_PLAN})
        conn.execute(text("INSERT INTO feature_flags (key, description) VALUES (:f, 'test')"), {"f": GLOBAL_FLAG})
        conn.execute(
            text(
                "INSERT INTO symbol_classes (id, family, display_name_he, billable) VALUES (:s, 'mcb', 'מא\"ז', true)"
            ),
            {"s": GLOBAL_SYMBOL},
        )
    yield {"owner": owner, "app": app}
    owner.dispose()
    app.dispose()
