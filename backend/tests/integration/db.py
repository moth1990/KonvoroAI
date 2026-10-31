"""A fresh, migrated test database (konboro_test), shared by the integration tests that need the schema."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from konboro.db.admin import database_dsn, fresh_database

from .factory import GLOBAL_FLAG, GLOBAL_PLAN, GLOBAL_SYMBOL


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[dict[str, Engine]]:
    name = "konboro_test"
    owner_dsn = fresh_database(name)

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
