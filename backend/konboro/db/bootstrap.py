"""Create or update the app's login role. Run before migrations: `python -m konboro.db.bootstrap`.

Roles are cluster-wide and need a password, so they live here and not in a migration.
The migration grants privileges to konboro_app (and creates it as NOLOGIN if bootstrap has not run yet).
"""

from sqlalchemy import create_engine, text

from .config import APP_ROLE, app_role_password, migration_dsn


def ensure_app_role(owner_dsn: str | None = None) -> None:
    engine = create_engine(owner_dsn or migration_dsn())
    password = app_role_password().replace("'", "''")
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}).scalar()
        verb = "ALTER" if exists else "CREATE"
        # Not a superuser, no BYPASSRLS, owns nothing: RLS applies to every query it runs.
        conn.execute(text(f"{verb} ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"))
    engine.dispose()


if __name__ == "__main__":
    ensure_app_role()
    print(f"role {APP_ROLE} ready")
