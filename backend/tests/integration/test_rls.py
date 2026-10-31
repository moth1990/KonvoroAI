"""Tenant isolation (00 §8.1, docs/db-schema.md §2): one tenant can never read or write another tenant's rows."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from konboro.db.base import Base
from konboro.db.ids import new_id
from konboro.db.session import TenantContextError, global_session, tenant_session

from .factory import build_tenant_graph

TENANT_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c)
GLOBAL_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if "tenant_id" not in t.c and t.name != "tenants")


@pytest.fixture(scope="module")
def two_tenants(migrated_db: dict[str, Engine]) -> Iterator[tuple[str, str]]:
    a, b = new_id("tnt"), new_id("tnt")
    for tenant in (a, b):
        with tenant_session(tenant, migrated_db["app"]) as s:
            build_tenant_graph(s, tenant)
    yield a, b


def count(engine: Engine, tenant: str, table: str, where: str = "true", **params: str) -> int:
    with tenant_session(tenant, engine) as s:
        return int(s.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one())


# --- every table is covered -------------------------------------------------------------------


def test_every_tenant_table_has_forced_rls_and_the_policy(migrated_db: dict[str, Engine]) -> None:
    """Guard: a future tenant table without RLS fails here, not in production."""
    with migrated_db["owner"].connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM pg_policies p
                               WHERE p.tablename = c.relname AND p.policyname = 'tenant_isolation') AS has_policy
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                  AND (c.relname = 'tenants' OR EXISTS (
                        SELECT 1 FROM information_schema.columns col
                        WHERE col.table_schema = 'public' AND col.table_name = c.relname
                          AND col.column_name = 'tenant_id'))
                """
            )
        ).all()
    found = {r.relname: (r.relrowsecurity, r.relforcerowsecurity, r.has_policy) for r in rows}
    assert set(found) == set(TENANT_TABLES) | {"tenants"}
    unprotected = [name for name, flags in found.items() if flags != (True, True, True)]
    assert unprotected == []


def test_factory_puts_a_row_in_every_tenant_table(migrated_db: dict[str, Engine], two_tenants: tuple[str, str]) -> None:
    a, _ = two_tenants
    empty = [t for t in TENANT_TABLES if count(migrated_db["app"], a, t) == 0]
    assert empty == [], "extend tests/integration/factory.py for these tables"


def test_app_role_cannot_bypass_rls(migrated_db: dict[str, Engine]) -> None:
    with migrated_db["owner"].connect() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'konboro_app'")).one()
        owners = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = 'konboro_app'")
        ).scalar_one()
    assert (row.rolsuper, row.rolbypassrls) == (False, False)
    assert owners == 0


# --- cross-tenant, per table ------------------------------------------------------------------


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_cannot_read_other_tenant(migrated_db: dict[str, Engine], two_tenants: tuple[str, str], table: str) -> None:
    a, b = two_tenants
    assert count(migrated_db["app"], b, table, "tenant_id = :a", a=a) == 0
    assert count(migrated_db["app"], b, table) == count(migrated_db["app"], b, table, "tenant_id = :b", b=b)


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_cannot_update_or_delete_other_tenant(
    migrated_db: dict[str, Engine], two_tenants: tuple[str, str], table: str
) -> None:
    a, b = two_tenants
    with tenant_session(b, migrated_db["app"]) as s:
        updated = s.execute(text(f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :a"), {"a": a})
        deleted = s.execute(text(f"DELETE FROM {table} WHERE tenant_id = :a"), {"a": a})
        assert (updated.rowcount, deleted.rowcount) == (0, 0)
    assert count(migrated_db["app"], a, table) > 0


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_cannot_insert_into_other_tenant(
    migrated_db: dict[str, Engine], two_tenants: tuple[str, str], table: str
) -> None:
    a, b = two_tenants
    with pytest.raises(ProgrammingError, match="row-level security"), tenant_session(b, migrated_db["app"]) as s:
        # Copy one of B's own rows and relabel it as A's: the WITH CHECK clause must refuse it.
        s.execute(text(f"CREATE TEMP TABLE probe ON COMMIT DROP AS SELECT * FROM {table} LIMIT 1"))
        s.execute(text("UPDATE probe SET tenant_id = :a"), {"a": a})
        pk = [c for c in inspect(migrated_db["owner"]).get_pk_constraint(table)["constrained_columns"]]
        if "id" in pk:
            s.execute(text("UPDATE probe SET id = id || 'X'"))
        s.execute(text(f"INSERT INTO {table} SELECT * FROM probe"))


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_cannot_move_own_row_to_other_tenant(
    migrated_db: dict[str, Engine], two_tenants: tuple[str, str], table: str
) -> None:
    a, b = two_tenants
    # Must be RLS that refuses it. A foreign key would also fail for tables with children,
    # which would hide a missing policy. On correction_events the append-only trigger runs
    # first; RLS on that table is still proven by the read, insert and guard tests.
    refused = "row-level security|only undone may change" if table == "correction_events" else "row-level security"
    with pytest.raises(DBAPIError, match=refused), tenant_session(b, migrated_db["app"]) as s:
        s.execute(text(f"UPDATE {table} SET tenant_id = :a"), {"a": a})


def test_tenant_row_itself_is_isolated(migrated_db: dict[str, Engine], two_tenants: tuple[str, str]) -> None:
    a, b = two_tenants
    assert count(migrated_db["app"], b, "tenants") == 1
    assert count(migrated_db["app"], b, "tenants", "id = :a", a=a) == 0


# --- no tenant context ------------------------------------------------------------------------


@pytest.mark.parametrize("table", [*TENANT_TABLES, "tenants"])
def test_without_tenant_context_nothing_is_visible(
    migrated_db: dict[str, Engine], two_tenants: tuple[str, str], table: str
) -> None:
    with global_session(migrated_db["app"]) as s:
        assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_without_tenant_context_nothing_can_be_written(migrated_db: dict[str, Engine]) -> None:
    with pytest.raises(ProgrammingError, match="row-level security"), global_session(migrated_db["app"]) as s:
        s.execute(text("INSERT INTO tenants (id, name, plan_id) VALUES (:t, 'x', 'test_plan')"), {"t": new_id("tnt")})


@pytest.mark.parametrize(
    "bad", ["", "tnt_123", "usr_01JB8Z3K7Q9T2M5X0R4W6Y8C1D", "tnt_01JB8Z3K7Q9T2M5X0R4W6Y8C1D' OR '1'='1"]
)
def test_tenant_session_rejects_invalid_ids(migrated_db: dict[str, Engine], bad: str) -> None:
    with pytest.raises(TenantContextError), tenant_session(bad, migrated_db["app"]):
        pass


# --- global layer -----------------------------------------------------------------------------


@pytest.mark.parametrize("table", GLOBAL_TABLES)
def test_global_tables_are_read_only_for_the_app(migrated_db: dict[str, Engine], table: str) -> None:
    with global_session(migrated_db["app"]) as s:
        s.execute(text(f"SELECT count(*) FROM {table}"))  # readable
    with pytest.raises(ProgrammingError, match="permission denied"), global_session(migrated_db["app"]) as s:
        s.execute(text(f"DELETE FROM {table}"))
