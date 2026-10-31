"""Alembic environment. Migrations run as the owner role (KONBORO_MIGRATION_DSN), never as konboro_app."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from konboro.db import models  # noqa: F401  (registers every table on Base.metadata)
from konboro.db.base import Base
from konboro.db.config import migration_dsn

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=migration_dsn(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # A connection passed in (tests) wins over the configured DSN.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(migration_dsn(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
