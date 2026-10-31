from sqlalchemy import Engine, func, select

from konboro.db import models as m
from konboro.db.seed import DEMO_TENANT, PRODUCTS, seed
from konboro.db.session import tenant_session


def test_seed_is_idempotent_and_visible_to_the_app(migrated_db: dict[str, Engine]) -> None:
    assert seed(migrated_db["owner"]) is True
    assert seed(migrated_db["owner"]) is False  # second run changes nothing

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
    assert flags == 5


def test_seeded_prices_are_exact(migrated_db: dict[str, Engine]) -> None:
    seed(migrated_db["owner"])
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
