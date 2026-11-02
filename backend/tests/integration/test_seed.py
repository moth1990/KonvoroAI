from sqlalchemy import Engine, func, select, update

from konboro.db import models as m
from konboro.db.seed import DEMO_TENANT, FLAGS, PRODUCTS, seed
from konboro.db.session import tenant_session
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
        enabled = s.execute(
            select(m.TenantFeatureOverride.enabled).where(m.TenantFeatureOverride.flag_key == "review_screen")
        ).scalar_one()
        # the demo price list links the lines to its products
        linked = s.execute(
            select(func.count()).select_from(m.QuoteLine).where(m.QuoteLine.product_id.is_not(None))
        ).scalar_one()
    assert quotes == 1
    assert enabled is True
    assert linked == 8


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
        flag = s.scalar(select(m.TenantFeatureOverride.enabled).where(m.TenantFeatureOverride.flag_key == "price_list"))
        usd = s.scalar(select(m.FxRate.rate).where(m.FxRate.currency == "USD").limit(1))
    assert rows["S203M-C16"] == ("circuit_breaker", True)
    assert rows["F204A-40/0.03"] == ("rcd", True)
    assert rows["AD22-22DS"] == ("indicator_lamp", False)  # not ABB: no catalog item, the family renamed
    assert rows["SIRCO M 4P 125A"] == ("switch_disconnector", False)
    assert flag is True
    assert str(usd) == "3.700000"
