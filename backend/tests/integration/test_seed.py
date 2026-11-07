from sqlalchemy import Engine, delete, func, select, update

from konboro.db import catalog
from konboro.db import models as m
from konboro.db.seed import DEMO_TENANT, FLAGS, GATE_3, PRODUCTS, seed
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import EARLIER_NAME
from konboro.domain.flags import CATALOG_LINES
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

    common = catalog.parse(catalog.COMMON.read_text(encoding="utf-8"))
    assert products == len(PRODUCTS) + 1 + len(common)  # plus the consumable and common.csv's (S28b)
    assert preferred == sum(1 for *_, sups in PRODUCTS if sups)
    assert tenants == ['לוחות דמו בע"מ']
    assert flags == len(FLAGS)


def test_the_common_shunt_trip_fits_the_xt5_and_xt6(migrated_db: dict[str, Engine], storage: Storage) -> None:
    """BUG-109: `common_accessories.csv` loads with `common.csv`, so stage 5 can put YO-C XT5-XT6 on an XT5."""
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        fits = s.execute(
            select(m.CatalogAccessory.fits_brand, m.CatalogAccessory.fits_series)
            .join(m.CatalogItem, m.CatalogItem.id == m.CatalogAccessory.accessory_id)
            .where(m.CatalogItem.sku == "YO-C XT5-XT6 F/P 110-240VAC")
        ).all()
    assert sorted(fits) == [("ABB", "XT5"), ("ABB", "XT6")]


def test_an_attribute_schema_changed_in_code_reaches_a_seeded_database(
    migrated_db: dict[str, Engine], storage: Storage
) -> None:
    """BUG-108: a database seeded before S27b kept a contactor row with no `utilization`, so stage 4 never read the
    "AC-1" written under 25/886's C3. Seeding again replaces a changed row, a version up, and keeps one that is the
    same."""
    from konboro.pipeline.association import schemas

    seed(migrated_db["owner"], storage)
    stale = [a.as_row() for a in schemas.SCHEMAS["contactor"] if a.name != "utilization"]
    with migrated_db["owner"].begin() as conn:
        conn.execute(
            update(m.AttributeSchema).where(m.AttributeSchema.family == "contactor").values(attributes=stale, version=1)
        )
    seed(migrated_db["owner"], storage)
    seed(migrated_db["owner"], storage)
    with migrated_db["owner"].begin() as conn:
        rows = dict(conn.execute(select(m.AttributeSchema.family, m.AttributeSchema.version)).all())
        attrs = conn.execute(
            select(m.AttributeSchema.attributes).where(m.AttributeSchema.family == "contactor")
        ).scalar_one()
    assert "utilization" in {a["name"] for a in attrs}
    assert rows["contactor"] == 2
    assert rows["circuit_breaker"] == 1  # the same as the code: kept


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


def test_a_demo_tenant_from_before_a_flag_gets_it_and_keeps_one_turned_off(
    migrated_db: dict[str, Engine], storage: Storage
) -> None:
    """BUG-105: the demo tenant got every flag only when it was made, so `catalog_lines` (S27b) stayed off on a
    database seeded before it. A flag the user turned off stays off."""
    seed(migrated_db["owner"], storage)
    with tenant_session(DEMO_TENANT, migrated_db["owner"]) as s:
        s.execute(delete(m.TenantFeatureOverride).where(m.TenantFeatureOverride.flag_key == CATALOG_LINES))
        s.execute(
            update(m.TenantFeatureOverride).where(m.TenantFeatureOverride.flag_key == "home_chat").values(enabled=False)
        )
    assert seed(migrated_db["owner"], storage) is False
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        on = dict(s.execute(select(m.TenantFeatureOverride.flag_key, m.TenantFeatureOverride.enabled)).all())
    assert on[CATALOG_LINES] is True
    assert on["home_chat"] is False
    assert set(on) == {f["key"] for f in FLAGS}


def test_the_common_products_are_in_the_demo_price_list_without_a_cost(
    migrated_db: dict[str, Engine], storage: Storage
) -> None:
    """S28b decision 4: common.csv's 15 products show in the demo's price list, linked to the catalog, under
    "בלי עלות"; a rerun adds none twice."""
    seed(migrated_db["owner"], storage)
    seed(migrated_db["owner"], storage)
    common = {(r.brand, r.sku) for r in catalog.parse(catalog.COMMON.read_text(encoding="utf-8"))}
    with tenant_session(DEMO_TENANT, migrated_db["app"]) as s:
        rows = [
            (p.manufacturer_sku, p.display_name, p.family, p.fixed_price, p.sale_mode, p.id, item.sku, item.family)
            for p in s.scalars(select(m.Product))
            if (p.brand, p.manufacturer_sku) in common
            for item in [s.get_one(m.CatalogItem, p.catalog_item_id or "")]
        ]
        costs = s.scalar(
            select(func.count())
            .select_from(m.ProductSupplier)
            .where(m.ProductSupplier.product_id.in_([r[5] for r in rows]))
        )
    assert len(rows) == len(common) == 15
    assert all(sku == item_sku and family == item_family for sku, _, family, _, _, _, item_sku, item_family in rows)
    assert {(price, mode) for _, _, _, price, mode, *_ in rows} == {(None, "rule")}
    assert costs == 0
    names = {r[0]: r[1] for r in rows}
    assert names["DWA1"] == "שעון אסטרונומי ABB DWA1 סליל 230V"
    assert names["AM530D"] == "מחליף אוטומטי AMDAR AM530D"
