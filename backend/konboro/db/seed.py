"""Demo data for local development: `make seed` (runs after migrations). Safe to run more than once.

Global rows (plans, flags, VAT) are upserted. The demo tenant is created once; if it exists, it is left alone.
Names are made up (decided in S02): the products and prices come from the prototype's price list
(prototype/konboro-app.html, CATALOG), which was built from real quotes, but no real customer or
factory name appears here.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, create_engine, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.settings import get_settings

from .config import migration_dsn
from .ids import new_id

if TYPE_CHECKING:
    from konboro.services.storage import Storage

from .models import (
    Abbreviation,
    AttributeSchema,
    Customer,
    FeatureFlag,
    MarginRule,
    Plan,
    Product,
    ProductSupplier,
    Project,
    QuotaUsage,
    ReferenceCrop,
    Supplier,
    SymbolClass,
    Tenant,
    TenantFeatureOverride,
    TenantSettings,
    User,
    VatRate,
)

DEMO_TENANT = "tnt_01JD0DEM000000000000000000"
DEMO_USER = "usr_01JD0DEM000000000000000000"
DEMO_EMAIL = "demo@konboro.local"

PLANS = [
    {"id": "trial", "name_he": "ניסיון", "monthly_quote_limit": 50, "max_pages_per_file": 30},
    {"id": "pro", "name_he": "מקצועי", "monthly_quote_limit": 200, "max_pages_per_file": 60},
]

# Spec 13 keys (the prototype's shorter names are not used in code, see CLAUDE.md).
FLAGS = [
    {"key": "unresolved_overlay", "description": "סימון מה לא פוענח על השרטוט (13 §4.4)", "depends_on": []},
    {"key": "export_doc", "description": "הורדת ההצעה כ-PDF ו-Excel (13 §4.1)", "depends_on": []},
    {"key": "chat_quote_builder", "description": "בניית הצעה בצ'אט (13 §4.2)", "depends_on": []},
    {"key": "home_chat", "description": "מסך בית כשיחה (13 §4.3)", "depends_on": []},
    {"key": "voice_input", "description": "הקלטה קולית (13 §4.2)", "depends_on": ["chat_quote_builder"]},
    # S09 decision 2: on while the screen is being built, removed when it is complete (S23).
    {"key": "review_screen", "description": "מסך הבדיקה, בבנייה (09). יוסר ב-S23", "depends_on": []},
]

SUPPLIERS = {
    "a": "ספק א׳ · מפיץ ABB",
    "b": "ספק ב׳ · מפיץ ABB",
    "c": "ספק ג׳ · ציוד פיקוד",
    "d": "ספק ד׳ · מדידה",
    "e": "ספק ה׳ · ארונות",
}

FAMILY = {
    'מא"ז': "mcb",
    "פחת": "rcd",
    "מפסק": "mccb",
    "מנתק": "switch_disconnector",
    "מגן מנוע": "motor_protection",
    "נורה": "pilot_light",
    "ממסר": "relay",
    "מדידה": "meter",
    "מגן ברק": "surge_protector",
    "אביזר": "accessory",
    "בורר": "selector_switch",
    "ארון": "enclosure",
    "מהדק": "terminal",
}

# (name, manufacturer sku, brand, family, fixed sale price or None, suppliers [(key, cost, lead, preferred, sku)])
PRODUCTS: list[tuple[str, str | None, str | None, str, str | None, list[tuple[str, str, int, bool, str | None]]]] = [
    ('מא"ז ABB S201M 1P ‏6A', "S201M-C6", "ABB", 'מא"ז', "42", [("a", "31", 2, True, None)]),
    ('מא"ז ABB S201M 1P ‏10A', "S201M-C10", "ABB", 'מא"ז', "42", [("a", "31", 2, True, None)]),
    ('מא"ז ABB S201M 1P ‏16A', "S201M-C16", "ABB", 'מא"ז', "42", [("a", "31.5", 2, True, None)]),
    ('מא"ז ABB SN201M 1P+N ‏10A', "SN201M-C10", "ABB", 'מא"ז', "130", [("a", "96", 2, True, None)]),
    ('מא"ז ABB SN201M 1P+N ‏16A', "SN201M-C16", "ABB", 'מא"ז', "130", [("a", "96", 2, True, None)]),
    ('מא"ז ABB S202M 2P ‏10A', "S202M-C10", "ABB", 'מא"ז', "140", [("a", "104", 2, True, None)]),
    ('מא"ז ABB S203M 3P ‏6A', "S203M-C6", "ABB", 'מא"ז', "185", [("a", "138", 2, True, None)]),
    (
        'מא"ז ABB S203M 3P ‏16A',
        "S203M-C16",
        "ABB",
        'מא"ז',
        "185",
        [("a", "138", 2, True, "A-4471"), ("b", "131", 10, False, "B-20316")],
    ),
    ('מא"ז ABB S203M 3P ‏25A', "S203M-C25", "ABB", 'מא"ז', "195", [("a", "145", 2, True, None)]),
    ('מא"ז ABB S203M 3P ‏40A', "S203M-C40", "ABB", 'מא"ז', "195", [("a", "147", 2, True, None)]),
    (
        "מפסק פחת 4P ‏40A ‏30mA",
        "F204A-40/0.03",
        "ABB",
        "פחת",
        "300",
        [("a", "214", 2, True, None), ("b", "220", 5, False, None)],
    ),
    ("מפסק ABB XT1C 3P ‏80A", "XT1C160 TMD80 3P", "ABB", "מפסק", "750", [("b", "545", 7, True, None)]),
    ("מפסק ABB XT1C 4P ‏125A", "XT1C160 TMD125 4P", "ABB", "מפסק", "1250", [("b", "905", 7, True, None)]),
    ("מנתק SOCOMEC 4P ‏125A", "SIRCO M 4P 125A", "SOCOMEC", "מנתק", "1670", [("c", "1210", 14, True, None)]),
    ("מגן מנוע ABB MS116 ‏4–6.3A", "MS116-6.3", "ABB", "מגן מנוע", "260", [("a", "188", 2, True, None)]),
    ('נורת סימון 22 מ"מ', "AD22-22DS", None, "נורה", None, [("c", "18", 2, True, None)]),  # sale by markup rule
    ("ממסר חוסר מתח", None, None, "ממסר", "340", []),
    ("ממסר מבודד ערוץ אחד", "GIC-1", None, "ממסר", "130", []),
    ("רב מודד SATEC", "PM135E", "SATEC", "מדידה", "1800", [("d", "1350", 5, True, None)]),
    ("מגן מתח יתר", None, None, "מגן ברק", "855", []),
    ("מגע עזר", "S2C-H6R", "ABB", "אביזר", "70", [("a", "48", 2, True, None)]),
    ("בורר 1-0-2", None, None, "בורר", "130", [("c", "62", 2, True, None)]),
    ("ארון 1000/800/300 כולל פסי צבירה, אפס והארקה", None, None, "ארון", "4200", [("e", "3050", 21, True, None)]),
]


def seed_global(session: Session) -> None:
    for plan in PLANS:
        session.execute(insert(Plan).values(**plan).on_conflict_do_nothing(index_elements=["id"]))
    for flag in FLAGS:
        session.execute(insert(FeatureFlag).values(**flag).on_conflict_do_nothing(index_elements=["key"]))
    session.execute(
        insert(VatRate)
        .values(id="vat_01JD0DEM000000000000000000", rate=Decimal("0.18"), valid_from=date(2025, 1, 1))
        .on_conflict_do_nothing(index_elements=["valid_from"])
    )
    seed_symbol_library(session)


def seed_symbol_library(session: Session) -> None:
    """03 §4.3–4.6, global layer, from `konboro.pipeline.detection.library` (S12). Rows already there are kept: a
    curated row may have been approved or edited since."""
    from konboro.pipeline.association import schemas
    from konboro.pipeline.detection import library

    seed_attribute_schemas(session)
    for c in library.CLASSES:
        schema = c.family if c.family in schemas.SCHEMAS else None
        session.execute(
            insert(SymbolClass)
            .values(
                id=c.symbol_class,
                family=c.family,
                display_name_he=c.display_name_he,
                billable=c.billable,
                attribute_schema=schema,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if schema is not None:  # a row seeded before S13 has none yet
            session.execute(
                update(SymbolClass)
                .where(SymbolClass.id == c.symbol_class, SymbolClass.attribute_schema.is_(None))
                .values(attribute_schema=schema)
            )
    session.flush()
    for written, symbol_class in library.ABBREVIATIONS:
        family = next(c.family for c in library.CLASSES if c.symbol_class == symbol_class)
        session.execute(
            insert(Abbreviation)
            .values(id=new_id("abr"), text=written, symbol_class=symbol_class, family=family)
            .on_conflict_do_nothing(index_elements=["text"])
        )
    have = set(session.scalars(select(ReferenceCrop.image_key)))
    for ref in library.curated_references():
        if ref.image_key not in have:
            session.add(
                ReferenceCrop(
                    id=new_id("ref"), symbol_class=ref.symbol_class, image_key=ref.image_key, source="curated"
                )
            )
    session.flush()


def seed_attribute_schemas(session: Session) -> None:
    """05 §4.4, global layer, from `konboro.pipeline.association.schemas` (S13). A row already there is kept."""
    from konboro.pipeline.association import schemas

    for family, attributes in schemas.SCHEMAS.items():
        session.execute(
            insert(AttributeSchema)
            .values(family=family, version=1, attributes=[a.as_row() for a in attributes])
            .on_conflict_do_nothing(index_elements=["family"])
        )
    session.flush()


def seed_demo_tenant(session: Session) -> bool:
    """Creates the demo tenant. Returns False if it already exists."""
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": DEMO_TENANT})
    if session.execute(select(Tenant.id).where(Tenant.id == DEMO_TENANT)).first():
        return False

    t = DEMO_TENANT
    session.add(Tenant(id=t, name='לוחות דמו בע"מ', plan_id="trial"))
    session.flush()
    session.add(User(id=DEMO_USER, tenant_id=t, email=DEMO_EMAIL, display_name="אומדן דמו"))
    # Prototype settings screen: markup 25%, floor 15%, RCD 30mA by default, enclosure includes everything.
    session.add(
        TenantSettings(
            tenant_id=t,
            min_line_margin=Decimal("0.15"),
            min_quote_margin=Decimal("0.15"),
            attribute_defaults={"rcd": {"residual_ma": 30}},
            enclosure_includes_default={"busbar": True, "n": True, "pe": True, "panels": True, "doors": True},
            onboarding={"first_drawing_at": None, "quotes_sent": 0},
        )
    )
    session.add(MarginRule(id=new_id("mr"), tenant_id=t, level="default", kind="markup", value=Decimal("0.25")))
    for flag in FLAGS:  # the prototype shows every v1.0 feature
        session.add(TenantFeatureOverride(tenant_id=t, flag_key=flag["key"], enabled=True, reason="demo"))
    month = datetime.now(ZoneInfo("Asia/Jerusalem")).date().replace(day=1)
    session.add(QuotaUsage(tenant_id=t, month=month, used=12))  # the prototype's "12 of 50"

    customer = Customer(id=new_id("cus"), tenant_id=t, name='קבלן לדוגמה בע"מ')
    session.add(customer)
    session.flush()
    session.add(Project(id=new_id("prj"), tenant_id=t, customer_id=customer.id, name="גן ילדים, לוח ראשי"))

    suppliers = {key: Supplier(id=new_id("sup"), tenant_id=t, name=name) for key, name in SUPPLIERS.items()}
    session.add_all(suppliers.values())
    session.flush()
    for name, sku, brand, family_he, sale, sups in PRODUCTS:
        product = Product(
            id=new_id("prd"),
            tenant_id=t,
            display_name=name,
            manufacturer_sku=sku,
            brand=brand,
            family=FAMILY[family_he],
            sale_mode="fixed" if sale is not None else "rule",
            fixed_price=Decimal(sale) if sale is not None else None,
            source="quote_import" if sale is not None else "supplier_price_list",
        )
        session.add(product)
        session.flush()
        for key, cost, lead, preferred, supplier_sku in sups:
            session.add(
                ProductSupplier(
                    id=new_id("psp"),
                    tenant_id=t,
                    product_id=product.id,
                    supplier_id=suppliers[key].id,
                    supplier_sku=supplier_sku,
                    unit_cost=Decimal(cost),
                    lead_days=lead,
                    price_date=date(2026, 10, 1),
                    preferred=preferred,
                )
            )
    # A consumable: counted but never a separate line (07 §7.4).
    session.add(
        Product(
            id=new_id("prd"),
            tenant_id=t,
            display_name="מהדק בדיקה למשנה זרם",
            family=FAMILY["מהדק"],
            sale_mode="rule",
            consumable=True,
            source="manual_entry",
        )
    )
    return True


def seed_demo_fixtures(session: Session, storage: "Storage") -> None:
    """The review screen's fixture quote (S09) and its page images (S11). Runs every time, so a demo tenant from
    before S09 gets it too, and a bucket that lost the images gets them again."""
    # it reads this module's price list
    from konboro.devtools.fixtures.nursery import enable_flag, seed_nursery, seed_nursery_pages

    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": DEMO_TENANT})
    enable_flag(session, DEMO_TENANT)
    seed_nursery(session, DEMO_TENANT)
    seed_nursery_pages(session, storage, DEMO_TENANT)


def seed(engine: Engine | None = None, storage: "Storage | None" = None) -> bool:
    """Runs as the owner role, inside the demo tenant's context for tenant rows. Needs S3 (`make up`)."""
    from konboro.services.storage import Storage

    engine = engine or create_engine(migration_dsn())
    storage = storage or Storage(get_settings())
    with Session(engine) as session, session.begin():
        seed_global(session)
    with Session(engine) as session, session.begin():
        created = seed_demo_tenant(session)
    with Session(engine) as session, session.begin():
        seed_demo_fixtures(session, storage)
    return created


if __name__ == "__main__":
    created = seed()
    print("demo tenant created" if created else "demo tenant already exists, left unchanged")
