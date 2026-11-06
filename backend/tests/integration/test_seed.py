from sqlalchemy import Engine, func, select, update

from konboro.db import models as m
from konboro.db.seed import DEMO_TENANT, FLAGS, GATE_3, PRODUCTS, seed
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import EARLIER_NAME
from konboro.services.storage import Storage


def test_seed_is_idempotent_and_visible_to_the_app(migrated_db: dict[str, Engine], storage: Storage) -> None:
    assert seed(migrated_db["owner"], storage) is True
    assert seed(migrated_db["owner"], storage) is False  # second run changes nothing

    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        products = s.execute(select(func.count()).select_from(m.Product)).scalar_one()
        preferred = s.execute(
            select(func.count()).select_from(m.ProductSupplier).where(m.ProductSupplier.preferred)
        ).scalar_one()
        tenants = s.execute(select(m.Tenant.name)).scalars().all()
        flags = s.execute(select(func.count()).select_from(m.TenantFeatureOverride)).scalar_one()

    assert products == len(PRODUCTS) + 1  # plus the consumable
    assert preferred == sum(1 for *_, sups in PRODUCTS if sups)
    assert tenants == ['לוחות דמו בע"מ']
    assert flags == len(FLAGS)


def test_the_flags_and_their_removal_dates(migrated_db: dict[str, Engine], storage: Storage) -> None:
    """S28 decision 4: no `price_list`; the build-time flags go at Gate 3, the spec-13 ones have no date (13 §3)."""
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        dates = {k: d for k, d in s.execute(select(m.FeatureFlag.key, m.FeatureFlag.remove_by))}
    assert "price_list" not in dates
    build_time = {"quote_audit", "bom_column_mapping", "onboarding", "settings_screen", "approval_queue", "chat_layer"}
    assert {k for k, d in dates.items() if d is not None} == build_time
    assert {d for d in dates.values() if d is not None} == {GATE_3}


def test_seeded_prices_are_exact(migrated_db: dict[str, Engine], storage: Storage) -> None:
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        price = s.execute(select(m.Product.fixed_price).where(m.Product.manufacturer_sku == "S203M-C16")).scalar_one()
        costs = sorted(
            s.execute(
                select(m.ProductSupplier.unit_cost)
                .join(m.Product, m.Product.id == m.ProductSupplier.product_id)
                .where(m.Product.manufacturer_sku == "S203M-C16")
            ).scalars()
        )
    assert str(price) == "185.0000"
    assert [str(c) for c in costs] == ["131.0000", "138.0000"]


def test_the_demo_tenant_gets_the_review_fixture_once(migrated_db: dict[str, Engine], storage: Storage) -> None:
    seed(migrated_db["owner"], storage)
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        quotes = s.execute(select(func.count()).select_from(m.Quote).where(m.Quote.name == "NURSERY")).scalar_one()
        # the demo price list links the lines to its products
        linked = s.execute(
            select(func.count())
            .select_from(m.QuoteLine)
            .join(m.QuoteVersion, m.QuoteVersion.id == m.QuoteLine.quote_version_id)
            .join(m.Quote, m.Quote.id == m.QuoteVersion.quote_id)
            .where(m.Quote.name == "NURSERY", m.QuoteLine.product_id.is_not(None))
        ).scalar_one()
        earlier = s.execute(select(func.count()).select_from(m.Quote).where(m.Quote.name == EARLIER_NAME)).scalar_one()
    assert quotes == 1
    assert linked == 8
    assert earlier == 1  # the sent quote compare reads (S25b), once


def test_seed_links_the_demo_price_list(migrated_db: dict[str, Engine], storage: Storage) -> None:
    """BUG-039: demo products take the catalog's family; a tenant seeded before S18 has its families renamed."""
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["owner"]) as s:
        s.execute(update(m.Product).where(m.Product.manufacturer_sku == "AD22-22DS").values(family="pilot_light"))
        s.execute(
            update(m.Product)
            .where(m.Product.manufacturer_sku == "S203M-C16")
            .values(family="mcb", catalog_item_id=None)
        )
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        rows = {
            p.manufacturer_sku: (p.family, p.catalog_item_id is not None)
            for p in s.scalars(select(m.Product).where(m.Product.manufacturer_sku.is_not(None)))
        }
        flag = s.get(m.FeatureFlag, "price_list")  # S28: the flag is gone
        usd = s.scalar(select(m.FxRate.rate).where(m.FxRate.currency == "USD").limit(1))
    assert rows["S203M-C16"] == ("circuit_breaker", True)
    assert rows["F204A-40/0.03"] == ("rcd", True)
    assert rows["AD22-22DS"] == ("indicator_lamp", False)  # not ABB: no catalog item, the family renamed
    assert rows["SIRCO M 4P 125A"] == ("switch_disconnector", False)
    assert flag is None
    assert str(usd) == "3.700000"
