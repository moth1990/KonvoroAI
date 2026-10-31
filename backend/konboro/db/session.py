"""DB sessions with tenant context (docs/db-schema.md §2).

Every tenant-scoped query runs inside `tenant_session`, which sets `app.tenant_id` for the
transaction only (SET LOCAL semantics). RLS policies compare against it. Without it, a session
sees no tenant rows and can write none.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from .config import app_dsn
from .ids import is_id


class TenantContextError(ValueError):
    """A tenant session was requested without a valid tenant id."""


@lru_cache(maxsize=4)
def app_engine(dsn: str | None = None) -> Engine:
    return create_engine(dsn or app_dsn(), pool_pre_ping=True)


@contextmanager
def tenant_session(tenant_id: str, engine: Engine | None = None) -> Iterator[Session]:
    """One transaction scoped to a tenant. Commits on success, rolls back on error."""
    if not is_id(tenant_id, "tnt"):
        raise TenantContextError(f"not a tenant id: {tenant_id!r}")
    with Session(engine or app_engine()) as session, session.begin():
        # set_config(..., is_local=true) is SET LOCAL with a bind parameter: it ends with the transaction.
        session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
        yield session


@contextmanager
def global_session(engine: Engine | None = None) -> Iterator[Session]:
    """For global-layer reads (plans, flags, catalog). Tenant tables return nothing here."""
    with Session(engine or app_engine()) as session, session.begin():
        yield session
