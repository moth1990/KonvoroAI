"""Demo data for local development: `make seed` (runs after migrations). Safe to run more than once.

Global rows (plans, flags, VAT, FX rates, the sample master catalog) are upserted. The demo tenant is created once;
if it exists, it is left alone.
Names are made up (decided in S02): the products and prices come from the prototype's price list
(prototype/konboro-app.html, CATALOG), which was built from real quotes, but no real customer or
factory name appears here.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.domain.flags import CATALOG_LINES, LIVE_RUN
from konboro.settings import get_settings

from . import catalog
from .config import migration_dsn
from .ids import new_id

if TYPE_CHECKING:
    from konboro.services.storage import Storage

from .models import (
    Abbreviation,
    AttributeSchema,
    CatalogItem,
    Customer,
    FeatureFlag,
    FxRate,
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
    ValidatorRule,
    VatRate,
)

DEMO_TENANT = "tnt_01JD0DEM000000000000000000"
DEMO_USER = "usr_01JD0DEM000000000000000000"
DEMO_EMAIL = "demo@konboro.local"

PLANS = [
    {"id": "trial", "name_he": "ניסיון", "monthly_quote_limit": 50, "max_pages_per_file": 30},
    {"id": "pro", "name_he": "מקצועי", "monthly_quote_limit": 200, "max_pages_per_file": 60},
]

# S28 decision 4: the build-time flags of accepted screens go at Gate 3 (S32), before the pilot (migration 0026)
GATE_3 = date(2026, 12, 31)

# Spec 13 keys (the prototype's shorter names are not used in code, see CLAUDE.md).
FLAGS: list[dict[str, Any]] = [
    {"key": "unresolved_overlay", "description": "סימון מה לא פוענח על השרטוט (13 §4.4)", "depends_on": []},
    {"key": "export_doc", "description": "הורדת ההצעה כ-PDF ו-Excel (13 §4.1)", "depends_on": []},
    {"key": "chat_quote_builder", "description": "בניית הצעה בצ'אט (13 §4.2)", "depends_on": []},
    {"key": "home_chat", "description": "מסך בית כשיחה (13 §4.3)", "depends_on": []},
    {"key": "voice_input", "description": "הקלטה קולית (13 §4.2)", "depends_on": ["chat_quote_builder"]},
    # S09 decision 2: on while the screen is being built, removed when it is complete (S23).
    # S14 decision 1: an unsure BOM column mapping stops for the user on the confirmation step.
    {
        "key": "bom_column_mapping",
        "description": "אישור מיפוי עמודות בכתב כמויות (01 §5.8)",
        "depends_on": [],
        "remove_by": GATE_3,
    },
    # S15: the quote audit's API (11); its screen is S16's.
    {"key": "quote_audit", "description": "בדיקת הצעה קיימת (11)", "depends_on": [], "remove_by": GATE_3},
    # S24 decision 5: a new factory's entry, the settings screen, and the pilot approval queue.
    {
        "key": "onboarding",
        "description": "שתי שאלות ותנאי השימוש בנתונים לפני השרטוט הראשון (10 §5.1)",
        "depends_on": [],
        "remove_by": GATE_3,
    },
    {"key": "settings_screen", "description": "מסך ההגדרות (10 §9.1)", "depends_on": [], "remove_by": GATE_3},
    {
        "key": "approval_queue",
        "description": "תור אישור לשכבה המשותפת (00 §14.2)",
        "depends_on": [],
        "remove_by": GATE_3,
    },
    # S25 decision 5: spec 13 has no key for the chat; removed once its screen is accepted
    {"key": "chat_layer", "description": "צ'אט על ההצעה במסך הבדיקה (08)", "depends_on": [], "remove_by": GATE_3},
    # S27b: every product line is a product, once per panel; a product not in the catalog waits for a decision
    {
        "key": CATALOG_LINES,
        "description": "שורות מהקטלוג: מוצר אחד בשורה, ומוצר חדש ממתין להחלטה (13 §4.10)",
        "depends_on": [],
    },
    # S28c: the live run step, its time and its cost. The first flag on for every factory (13 §4.11, `scope=global`):
    # a kill switch, not a rollout; with it off the run step is the classic one.
    {
        "key": LIVE_RUN,
        "description": "מסך פענוח חי: מה המערכת רואה, זמן שנותר ועלות בדולרים (13 §4.11)",
        "depends_on": [],
        "default_on": True,
    },
]
S24_FLAGS = ("onboarding", "settings_screen", "approval_queue")
CHAT_FLAG = "chat_layer"
# The demo factory has answered the two questions, and its price list came from two quotes it sent (10288, 10271).
DEMO_TERMS = {"version": "2026-10", "by": DEMO_USER, "at": "2026-10-01T09:00:00+00:00"}

SUPPLIERS = {
    "a": "ספק א׳ · מפיץ ABB",
    "b": "ספק ב׳ · מפיץ ABB",
    "c": "ספק ג׳ · ציוד פיקוד",
    "d": "ספק ד׳ · מדידה",
    "e": "ספק ה׳ · ארונות",
}

# The prototype's family names -> the attribute schemas' families (05 §4.4), which stage 4 writes and margin rules
# and supplier preferences match on. Until S18 these were symbol classes (`mcb`, `mccb`); FAMILY_RENAMES fixes a demo
# tenant seeded before then (BUG-039).
FAMILY = {
    'מא"ז': "circuit_breaker",
    "פחת": "rcd",
    "מפסק": "circuit_breaker",
    "מנתק": "switch_disconnector",
    "מגן מנוע": "circuit_breaker",
    "נורה": "indicator_lamp",
    "ממסר": "relay",
    "מדידה": "measuring_instrument",
    "מגן ברק": "surge_protector",
    "אביזר": "aux_contact",
    "בורר": "selector_switch",
    "ארון": "enclosure",
    "מהדק": "terminal",
}
FAMILY_RENAMES = {
    "mcb": "circuit_breaker",
    "mccb": "circuit_breaker",
    "motor_protection": "circuit_breaker",
    "pilot_light": "indicator_lamp",
    "meter": "measuring_instrument",
    "accessory": "aux_contact",
}

# Fixed local rates, ILS per unit (S18 decision 4), one a week so every date has one within 7 days (`pricing.fx`).
FX_RATES = {"USD": Decimal("3.70"), "EUR": Decimal("4.00")}
FX_FROM, FX_TO = date(2026, 1, 1), date(2027, 12, 31)

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
    ("מפסק מגן מנוע ABB MS116 3P ‏טווח 4–6.3A", "MS116-6.3", "ABB", "מגן מנוע", "260", [("a", "188", 2, True, None)]),
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
        row = insert(FeatureFlag).values(**flag)
        # A flag that says whether it is on for everyone keeps saying it; the others keep what an operator set.
        kept = {"remove_by": row.excluded.remove_by}
        if "default_on" in flag:
            kept["default_on"] = row.excluded.default_on
        session.execute(row.on_conflict_do_update(index_elements=["key"], set_=kept))
    session.execute(
        insert(VatRate)
        .values(id="vat_01JD0DEM000000000000000000", rate=Decimal("0.18"), valid_from=date(2025, 1, 1))
        .on_conflict_do_nothing(index_elements=["valid_from"])
    )
    seed_fx_rates(session)
    catalog.load_sample(session)
    seed_symbol_library(session)
    seed_validator_rules(session)


def seed_validator_rules(session: Session) -> None:
    """06 §6.2, global layer, from `konboro/pipeline/validation/rules.json` (S21). A rule version already there is
    kept: a new wording or threshold is a new version."""
    from konboro.pipeline.validation import pack

    session.execute(
        insert(ValidatorRule).values(pack.rows()).on_conflict_do_nothing(index_elements=["rule_id", "version"])
    )


def seed_fx_rates(session: Session) -> None:
    rows = [
        {"currency": currency, "rate_date": FX_FROM + timedelta(days=week * 7), "rate": rate, "source": "seed"}
        for currency, rate in FX_RATES.items()
        for week in range((FX_TO - FX_FROM).days // 7 + 1)
    ]
    session.execute(insert(FxRate).values(rows).on_conflict_do_nothing(index_elements=["currency", "rate_date"]))


# Stage 5's factory settings (05 §4.3, S20): the prototype's "מותג מועדף למא"זים ולפחת" is ABB; Schneider may stand
# in; a breaker's curve C and 6 kA, an RCD's type A, when the drawing writes none.
DEMO_BRANDS = {"circuit_breaker": "ABB", "rcd": "ABB", "*": "ABB"}
DEMO_MATCHING = {"alternate_brands": {"*": ["Schneider"]}, "tie_break": "frequency"}
DEMO_DEFAULTS = {
    "rcd": {"residual_ma": 30, "rcd_type": "A"},
    "circuit_breaker": {"curve": "C", "breaking_capacity_ka": 6},
}


def demo_matching(session: Session, tenant_id: str) -> None:
    """A demo tenant seeded before S20 gets the matching settings, once: settings someone changed are kept."""
    settings = session.get(TenantSettings, tenant_id)
    if settings is None or settings.matching:
        return
    settings.matching = DEMO_MATCHING
    settings.brand_preferences = settings.brand_preferences or DEMO_BRANDS
    if settings.attribute_defaults == {"rcd": {"residual_ma": 30}}:
        settings.attribute_defaults = DEMO_DEFAULTS


def demo_onboarding(session: Session) -> None:
    """A demo tenant from before S24 answered nothing: it has, and it sent the two quotes its price list came from."""
    settings = session.get(TenantSettings, DEMO_TENANT)
    if settings is None:
        return
    if not settings.data_terms_accepted:
        settings.data_terms_accepted = DEMO_TERMS
    counters = dict(settings.onboarding or {})
    if not counters.get("quotes_sent"):
        settings.onboarding = {**counters, "quotes_sent": 2}
    session.flush()


# S26 decision 1: the customer PDF's template, made up like the rest of the demo factory
DEMO_DOCUMENT: dict[str, Any] = {
    "company": {
        "name": 'לוחות דמו בע"מ',
        "company_id": "510000000",
        "address": "רח' המלאכה 7, חולון",
        "phone": "03-5550123",
    },
    "terms": "ההצעה בתוקף 30 יום מתאריך ההצעה.\nתנאי תשלום: שוטף + 60.\nזמן אספקה: 4–6 שבועות מאישור ההזמנה והשרטוטים.",
    "show_sku": False,
}


def demo_document(session: Session) -> None:
    """The demo factory's template for the customer PDF, unless it wrote its own."""
    settings = session.get(TenantSettings, DEMO_TENANT)
    if settings is not None and not settings.document:
        settings.document = DEMO_DOCUMENT
        session.flush()


def link_demo_catalog(session: Session, tenant_id: str) -> None:
    """The demo products whose manufacturer sku is in the sample catalog point at it and take its family; the rest
    get the family names stage 4 uses (BUG-039). Runs every seed, like the fixtures."""
    for old, new in FAMILY_RENAMES.items():
        session.execute(update(Product).where(Product.tenant_id == tenant_id, Product.family == old).values(family=new))
    items = session.execute(select(CatalogItem.brand, CatalogItem.sku, CatalogItem.id, CatalogItem.family)).all()
    by_sku = {(brand, sku): (id_, family) for brand, sku, id_, family in items}
    for product in session.scalars(select(Product).where(Product.tenant_id == tenant_id)):
        found = by_sku.get((product.brand or "", product.manufacturer_sku or ""))
        if found is not None:
            product.catalog_item_id, product.family = found


def demo_flags(session: Session) -> None:
    """Every flag on for the demo factory, as `seed_demo_tenant` sets them for a new one, so a demo tenant from
    before a flag existed gets it too (BUG-105: `catalog_lines` stayed off for the demo of every seed before S27b).
    A flag already set, on or off, is left as it is."""
    for key in (*S24_FLAGS, CHAT_FLAG, *(f["key"] for f in FLAGS)):
        session.execute(
            insert(TenantFeatureOverride)
            .values(tenant_id=DEMO_TENANT, flag_key=key, enabled=True, reason="demo")
            .on_conflict_do_nothing(index_elements=["tenant_id", "flag_key"])
        )


def demo_common_products(session: Session, tenant_id: str) -> None:
    """`common.csv`'s products (S27b) in the demo factory's price list, pointing at their catalog item, with no
    supplier and no cost, so they show under "בלי עלות" (S28b decision 4). The demo's only: a real factory's price
    list is its own prices, never filled from the shared catalog (07 §7.2). A product already there is kept."""
    from konboro.pipeline.pricing.load import describe

    rows = catalog.parse(catalog.COMMON.read_text(encoding="utf-8"))
    keys = {(r.brand, r.sku) for r in rows}
    items = [i for i in session.scalars(select(CatalogItem)) if (i.brand, i.sku) in keys]
    have = set(session.scalars(select(Product.manufacturer_sku).where(Product.tenant_id == tenant_id)))
    for item in sorted(items, key=lambda i: (i.family, i.brand, i.sku)):
        if item.sku in have:
            continue
        session.add(
            Product(
                id=new_id("prd"),
                tenant_id=tenant_id,
                catalog_item_id=item.id,
                display_name=describe(item),
                manufacturer_sku=item.sku,
                brand=item.brand,
                family=item.family,
                sale_mode="rule",
                source="manual_entry",
            )
        )
    session.flush()


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
    """05 §4.4, global layer, from `konboro.pipeline.association.schemas` (S13), the rows' source. A row the module has
    changed since is replaced, a version up (BUG-108: a database seeded before S27b had no contactor `utilization` and
    no clock `astronomical`, so stage 4 never read them); a row that is the same is kept as it is."""
    from konboro.pipeline.association import schemas

    for family, attributes in schemas.SCHEMAS.items():
        rows = [a.as_row() for a in attributes]
        stmt = insert(AttributeSchema).values(family=family, version=1, attributes=rows)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["family"],
                set_={
                    "attributes": stmt.excluded.attributes,
                    "version": AttributeSchema.version + 1,
                    "updated_at": func.now(),
                },
                where=AttributeSchema.attributes != stmt.excluded.attributes,
            )
        )
    session.flush()


def seed_price_list(session: Session, tenant_id: str) -> None:
    """The prototype's price list (`CATALOG`, `SUP`, lines 484–511) in a tenant: the demo's, and the E2E price-list
    tenants' (S19). Link it to the sample catalog with `link_demo_catalog` once the catalog is loaded."""
    t = tenant_id
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
            attribute_defaults=DEMO_DEFAULTS,
            brand_preferences=DEMO_BRANDS,
            matching=DEMO_MATCHING,
            enclosure_includes_default={"busbar": True, "n": True, "pe": True, "panels": True, "doors": True},
            data_terms_accepted=DEMO_TERMS,
            onboarding={"first_drawing_at": None, "quotes_sent": 2},
            rounding="shekel",  # the prototype's whole-shekel sale prices (S22 decision 2)
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

    seed_price_list(session, t)
    return True


def seed_demo_fixtures(session: Session, storage: "Storage") -> None:
    """The review screen's fixture quote (S09) and its page images (S11), and the 26-993 audit (S16). Runs every
    time, so a demo tenant from before them gets them too, and a bucket that lost the images gets them again."""
    # they read this module's price list
    from konboro.devtools.fixtures import audit_993, nursery
    from konboro.devtools.fixtures.queue import seed_queue

    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": DEMO_TENANT})
    nursery.seed_nursery(session, DEMO_TENANT)
    nursery.seed_nursery_pages(session, storage, DEMO_TENANT)
    nursery.seed_nursery_detections(session, storage, DEMO_TENANT)
    nursery.seed_earlier_quote(session, DEMO_TENANT)
    audit_993.enable_flag(session, DEMO_TENANT)
    audit_993.seed_audit_993(session, DEMO_TENANT, DEMO_USER)
    audit_993.seed_audit_993_pages(session, storage, DEMO_TENANT)
    demo_flags(session)
    demo_onboarding(session)
    demo_document(session)
    seed_queue(session, DEMO_TENANT)
    link_demo_catalog(session, DEMO_TENANT)
    demo_common_products(session, DEMO_TENANT)
    demo_matching(session, DEMO_TENANT)
    from konboro.pipeline.pricing.load import ensure_rules

    ensure_rules(session, DEMO_TENANT)  # 07 §7.4's starter pack; stage 7 copies it for any tenant without one


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
    print(
        "demo tenant created"
        if created
        else "demo tenant already exists: its fixtures, flags and common products brought up to date"
    )
