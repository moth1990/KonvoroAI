"""Rules the database enforces on its own: immutable sent versions, append-only events, money as Decimal."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from konboro.db import models as m
from konboro.db.admin import database_dsn, migrating, recreate_database
from konboro.db.ids import new_id
from konboro.db.session import tenant_session

from .factory import build_tenant_graph


@pytest.fixture
def tenant(migrated_db: dict[str, Engine]) -> tuple[str, dict[str, str]]:
    tid = new_id("tnt")
    with tenant_session(tid, migrated_db["app"]) as s:
        ids = build_tenant_graph(s, tid)
    return tid, ids


def test_money_round_trips_exactly(migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]) -> None:
    tid, ids = tenant
    with tenant_session(tid, migrated_db["app"]) as s:
        price = s.execute(select(m.QuoteLine.unit_price).where(m.QuoteLine.id == ids["quote_lines"])).scalar_one()
    assert isinstance(price, Decimal)
    assert price == Decimal("1250.10")


def test_money_columns_are_never_float(migrated_db: dict[str, Engine]) -> None:
    with migrated_db["owner"].connect() as conn:
        floats = (
            conn.execute(
                text(
                    "SELECT table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND data_type IN ('real', 'double precision') "
                    "AND (column_name LIKE '%price%' OR column_name LIKE '%cost%' OR column_name LIKE '%total%' "
                    "     OR column_name LIKE '%amount%' OR column_name LIKE '%pct%' OR column_name = 'rate')"
                )
            )
            .scalars()
            .all()
        )
    assert floats == []


def test_sent_version_cannot_change(migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]) -> None:
    tid, ids = tenant
    with tenant_session(tid, migrated_db["app"]) as s:
        s.execute(
            update(m.QuoteVersion)
            .where(m.QuoteVersion.id == ids["quote_versions"])
            .values(status="sent", sent_at=datetime.now(UTC))
        )

    with pytest.raises(DBAPIError, match="is sent and cannot change"), tenant_session(tid, migrated_db["app"]) as s:
        s.execute(update(m.QuoteVersion).where(m.QuoteVersion.id == ids["quote_versions"]).values(revision=5))

    with (
        pytest.raises(DBAPIError, match="sent quote version cannot change"),
        tenant_session(tid, migrated_db["app"]) as s,
    ):
        s.execute(update(m.QuoteLine).where(m.QuoteLine.id == ids["quote_lines"]).values(qty=Decimal(5)))

    with (
        pytest.raises(DBAPIError, match="sent quote version cannot change"),
        tenant_session(tid, migrated_db["app"]) as s,
    ):
        s.add(
            m.QuoteLine(
                id=new_id("ln"),
                tenant_id=tid,
                quote_version_id=ids["quote_versions"],
                position=2,
                description="שורה חדשה",
                qty=Decimal(1),
            )
        )
        s.flush()


def test_draft_version_can_change(migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]) -> None:
    tid, ids = tenant
    with tenant_session(tid, migrated_db["app"]) as s:
        s.execute(update(m.QuoteLine).where(m.QuoteLine.id == ids["quote_lines"]).values(qty=Decimal("2.5")))
        assert s.get(m.QuoteLine, ids["quote_lines"]).qty == Decimal("2.5")  # type: ignore[union-attr]


def test_correction_events_are_append_only(migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]) -> None:
    tid, _ = tenant
    with tenant_session(tid, migrated_db["app"]) as s:
        event_id = s.execute(select(m.CorrectionEvent.id)).scalar_one()
        s.execute(update(m.CorrectionEvent).where(m.CorrectionEvent.id == event_id).values(undone=True))  # allowed

    with pytest.raises(DBAPIError, match="only undone may change"), tenant_session(tid, migrated_db["app"]) as s:
        s.execute(update(m.CorrectionEvent).where(m.CorrectionEvent.id == event_id).values(reason="rewritten"))

    with pytest.raises(DBAPIError, match="append-only"), tenant_session(tid, migrated_db["app"]) as s:
        s.execute(text("DELETE FROM correction_events WHERE id = :id"), {"id": event_id})


def test_only_one_preferred_supplier_per_product(
    migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]
) -> None:
    tid, _ = tenant
    with pytest.raises(IntegrityError), tenant_session(tid, migrated_db["app"]) as s:
        product_id = s.execute(select(m.Product.id)).scalar_one()
        supplier = m.Supplier(id=new_id("sup"), tenant_id=tid, name="ספק ב׳")
        s.add(supplier)
        s.flush()
        s.add(
            m.ProductSupplier(
                id=new_id("psp"),
                tenant_id=tid,
                product_id=product_id,
                supplier_id=supplier.id,
                unit_cost=Decimal("131"),
                price_date=datetime.now(UTC).date(),
                preferred=True,
            )
        )
        s.flush()


def test_margin_must_be_below_100_percent(migrated_db: dict[str, Engine], tenant: tuple[str, dict[str, str]]) -> None:
    tid, _ = tenant
    with pytest.raises(IntegrityError, match="margin_below_one"), tenant_session(tid, migrated_db["app"]) as s:
        s.add(m.MarginRule(id=new_id("mr"), tenant_id=tid, level="default", kind="margin", value=Decimal("1.0")))
        s.flush()


def test_cannot_reference_another_tenants_row(migrated_db: dict[str, Engine]) -> None:
    """Composite foreign keys: even a correct-looking id of another tenant is rejected."""
    a, b = new_id("tnt"), new_id("tnt")
    with tenant_session(a, migrated_db["app"]) as s:
        ids_a = build_tenant_graph(s, a)
    with tenant_session(b, migrated_db["app"]) as s:
        build_tenant_graph(s, b)
    with pytest.raises(IntegrityError), tenant_session(b, migrated_db["app"]) as s:
        s.add(m.Quote(id=new_id("quo"), tenant_id=b, drawing_id=ids_a["drawings"], name="גניבה"))
        s.flush()


def test_migration_downgrades_and_upgrades_cleanly() -> None:
    name = "konboro_migration_test"
    recreate_database(name)
    with migrating(database_dsn(name)) as cfg:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
