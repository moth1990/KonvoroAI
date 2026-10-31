"""Database connection settings (local defaults match docker-compose.yml and .env.example).

Two roles (docs/db-schema.md §2): the owner runs migrations; the app connects as konboro_app,
which is subject to RLS. The app must never connect as the owner or a superuser.
"""

import os

APP_ROLE = "konboro_app"

_LOCAL_OWNER = "postgresql+psycopg://konboro:konboro@localhost:5433/konboro"
_LOCAL_APP = "postgresql+psycopg://konboro_app:konboro_app@localhost:5433/konboro"


def migration_dsn() -> str:
    return os.environ.get("KONBORO_MIGRATION_DSN", _LOCAL_OWNER)


def app_dsn() -> str:
    return os.environ.get("KONBORO_DATABASE_URL", _LOCAL_APP)


def app_role_password() -> str:
    # Local default only. In AWS (S29) the password comes from Secrets Manager.
    return os.environ.get("KONBORO_APP_DB_PASSWORD", "konboro_app")
