"""The NURSERY-1 draft as a seeded quote, so the review screen (S09) never waits for the pipeline.

It is what stage 7 would draft today (golden/NURSERY-1/README.md, S09 decision 1): 13 products and Q0's kit add-on,
42 units, 8 priced at ₪4,674 before VAT, and 5 with no price. Sale prices are the ones the factory's earlier quotes
used (10288, 10271); costs come from the demo price list (`konboro.db.seed.PRODUCTS`). Colors and reasons follow
from that data (S09 decision 8): five red for no price, the rest green.

Written through `konboro.services.quotes`, the same path stage 7 will use. Safe to rerun: a tenant that already has
the fixture drawing is left alone. No customer, factory or person name from the real drawing is stored.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import PRODUCTS, SUPPLIERS
from konboro.pipeline.extraction import deepzoom
from konboro.pipeline.extraction.config import DEFAULT as EXTRACTION
from konboro.pipeline.intake.pages import png
from konboro.pipeline.stages.s1_intake import THUMB_PX, thumbnail_key
from konboro.services.quotes import LineIn, store_totals, write_lines
from konboro.services.storage import Storage, drawing_key

MARKER = "fixture:NURSERY-1"  # drawings.trace_id of the fixture drawing
FLAG = "review_screen"
QUOTE_DATE = date(2026, 10, 13)
PRICE_DATE = "2026-10-01"

# The drawing pane's pages (S11 decision 2): the prototype's own page images, 1400 × 989, title block blanked. The
# golden PDF's title block names the real customer, so it is never rendered into a tenant.
PAGE_IMAGES = Path(__file__).with_name("nursery_pages")

# The prototype's page boxes are in 1755 × 1240 page pixels; the PDF's pages are 842 × 595 points (00 §6.2).
PX_TO_PT = 842 / 1755
PAGE_KINDS = [
    ("technical_data", "context"),
    ("factory_template", "skip"),
    ("factory_template", "skip"),
    ("panel_front_view", "context"),
    *[("single_line_diagram", "process")] * 5,
]


@dataclass(frozen=True)
class Item:
    key: str
    description: str
    qty: int
    group: str
    designators: list[str] = field(default_factory=list)
    raw: str = ""
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)
    product: str | None = None  # a name in seed.PRODUCTS: the line's sku, cost and supplier
    price: str | None = None
    quotes: list[str] = field(default_factory=list)  # the earlier quotes the sale price comes from
    reasons: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    why: str | None = None
    parent: str | None = None
    finding: str | None = None


def a(value: str, source: str = "drawing", detail: str | None = None, confidence: float = 0.95) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "source": source, "confidence": confidence}
    if detail:
        out["detail"] = detail
    return out


def col(
    page: int, xs: list[int], y0: int, y1: int, w: int = 95, off: int = -15
) -> list[tuple[int, float, float, float, float]]:
    """The prototype's `col()`: a row of equal boxes."""
    return [(page, x + off, y0, x + off + w, y1) for x in xs]


EXPLICIT = {"source": "match", "value": "explicit_model", "status": "green"}
NO_PRICE = {"source": "price", "value": "missing", "status": "red"}
PRICE_OK = {"source": "price", "value": "ok", "status": "green"}

# prototype makeLines() (konboro-app.html 410–470), in its order
ITEMS = [
    Item(
        "q0",
        "מפסק בתיבה יצוקה ABB XT1C 4P ‏160A משולב פחת",
        1,
        "feed",
        ["Q0"],
        "Q0\n4X160A\nABB-XT1C\nINC=125A\nמשולב פחת",
        {"current": a("160A"), "poles": a("4"), "series": a("XT1C"), "load_current": a("125A")},
        [(5, 1030, 90, 1265, 345)],
        reasons=[EXPLICIT, {"source": "match", "value": "kit", "status": "green"}, NO_PRICE],
        alternatives=["ABB XT2N 4P 160A + RC", "Schneider NSX160 4P + Vigi"],
    ),
    Item(
        "q0b",
        "ערכה: מודול פחת למפסק",
        1,
        "feed",
        parent="q0",
        price="0",
        reasons=[PRICE_OK],
        why='כלול במחיר שורת האב (ערכה). נקרא מ"משולב פחת" ליד Q0',
    ),
    Item(
        "q01",
        "מפסק בתיבה יצוקה ABB XT1C 3P ‏80A",
        1,
        "outputs",
        ["Q01"],
        "Q01\n3X80A\nABB-XT1C\nINC=63A",
        {"current": a("80A"), "poles": a("3"), "load_current": a("63A"), "load": a("מאווררי סחרור")},
        [(9, 285, 225, 435, 335)],
        "מפסק ABB XT1C 3P ‏80A",
        "750",
        ["10271"],
        [EXPLICIT, PRICE_OK],
    ),
    Item(
        "f1",
        'מא"ז ABB SN201M 1P+N ‏10A',
        17,
        "outputs",
        [f"F{n}" for n in range(1, 18)],
        "F1 … F17\n10+N\nINC=8A\nSN201M",
        {"current": a("10A"), "poles": a("1P+N"), "load": a("BOM 1–17")},
        [
            *col(5, [222, 420, 605, 828, 1025, 1212, 1422], 470, 548),
            *col(6, [185, 382, 565, 785, 980, 1165, 1373], 258, 336),
            *col(7, [268, 453, 660], 252, 330),
        ],
        'מא"ז ABB SN201M 1P+N ‏10A',
        "130",
        ["10288"],
        [EXPLICIT, PRICE_OK],
    ),
    Item(
        "f18",
        'מא"ז ABB S203M 3P ‏20A',
        4,
        "outputs",
        ["F18", "F19", "F20", "F21"],
        "F18 … F21\n3X20A\nINC=16A\nS203M ABB",
        {"current": a("20A"), "poles": a("3"), "load": a("שקעי שירות")},
        col(7, [800, 928, 1078, 1190], 252, 360),
        reasons=[EXPLICIT, NO_PRICE],
    ),
    Item(
        "f22",
        'מא"ז ABB S203M 3P ‏16A',
        5,
        "outputs",
        ["F22", "F23", "F24", "F25", "F30"],
        "F22 … F25, F30\n3X16A\nINC=12.8A\nS203M ABB",
        {"current": a("16A"), "poles": a("3"), "load": a("מנועי מסכים, ושמור")},
        [*col(8, [185, 390, 563, 727], 262, 365), (9, 590, 262, 695, 362)],
        'מא"ז ABB S203M 3P ‏16A',
        "185",
        ["10288", "10271"],
        [EXPLICIT, PRICE_OK],
    ),
    Item(
        "f31",
        'מא"ז ABB S201M 1P ‏16A',
        1,
        "outputs",
        ["F31"],
        "F31\n1X16A\nINC=12.8A\nS201M ABB",
        {"current": a("16A"), "poles": a("1"), "load": a('שמור ("SAVE")')},
        [(9, 800, 262, 895, 362)],
        'מא"ז ABB S201M 1P ‏16A',
        "42",
        ["10288", "10271"],
        [EXPLICIT, PRICE_OK],
    ),
    Item(
        "fnv",
        'מא"ז ABB S203M 3P ‏6A',
        1,
        "control",
        ["FNV"],
        "FNV\n3X6A\nINC=4A\nS204M\nABB",
        {"current": a("6A"), "poles": a("3", detail='"3X6A"'), "series": a("S203M", "memory", "הצעה 10288", 0.9)},
        [(5, 640, 262, 735, 360)],
        'מא"ז ABB S203M 3P ‏6A',
        "185",
        ["10288"],
        [{"source": "match", "value": "memory", "status": "green"}, PRICE_OK],
        why='בשרטוט כתוב S204M (דגם 4 קטבים) ליד "3X6A". אותו צירוף היה ב-NEVIS-1, וההצעה 10288 אישרה 3P. '
        "נבחר 3P לפי זיכרון ההתאמות.",
        finding="fnvf",
    ),
    Item(
        "nvr",
        "ממסר חוסר מתח",
        1,
        "control",
        ["NVR"],
        "NVR",
        {"type": a("ממסר מתח", "graphic")},
        [(5, 620, 170, 700, 212)],
        "ממסר חוסר מתח",
        "340",
        ["10288"],
        [PRICE_OK],
    ),
    Item(
        "rnv",
        "ממסר עזר",
        1,
        "control",
        ["RNV"],
        "RNV\n10 / 6 · 9 / 5",
        {"type": a("ממסר עזר", "graphic"), "contacts": a("2"), "load": a("מפעיל את המגענים C1–C4")},
        [(5, 450, 250, 530, 295), (8, 1210, 380, 1290, 448)],
        reasons=[{"source": "match", "value": "model_not_written", "status": "green"}, NO_PRICE],
        alternatives=["Finder 40.52 230VAC + בסיס", "ABB CR-M 230VAC 2C/O + בסיס"],
    ),
    Item(
        "c1",
        "מגען 3P ‏16A לפחות (AC-3)",
        4,
        "control",
        ["C1", "C2", "C3", "C4"],
        "C1 … C4\n(אין זרם כתוב)",
        {
            "ac3_current": a("16A לפחות", "circuit", "F22–F25 (3X16A)", 0.7),
            "poles": a("3", "graphic", "מגעי כוח שצוירו"),
            "coil_voltage": a("230V AC", "notes", "עמוד נתונים טכניים"),
        },
        [
            *col(8, [185, 390, 563, 727], 440, 485, 125),
            (8, 990, 572, 1036, 612),
            (8, 1138, 572, 1184, 612),
            (8, 1265, 572, 1311, 612),
            (8, 1408, 572, 1454, 612),
        ],
        reasons=[{"source": "match", "value": "inferred_attribute", "status": "yellow"}, NO_PRICE],
        alternatives=["מגען 3P ‏18A", "מגען 3P ‏25A"],
        why='הזרם לא כתוב בשרטוט. כלל ההסקה בוחר את הקטן ביותר שגדול או שווה למא"ז שמעל כל מגען (F22–F25, ‏16A).',
        finding="inc",
    ),
    Item(
        "fp1",
        'מא"ז ABB S201M 1P ‏6A',
        1,
        "control",
        ["FP1"],
        "FP1\n1X6A\nINC=4A\nS201M",
        {"current": a("6A"), "poles": a("1"), "load": a("פיקוד")},
        [(8, 1135, 225, 1230, 330)],
        'מא"ז ABB S201M 1P ‏6A',
        "42",
        ["10288"],
        [EXPLICIT, PRICE_OK],
    ),
    Item(
        "lamp",
        'נורת סימון 22 מ"מ',
        4,
        "control",
        ["L1", "L2", "L3", "HNV"],
        "L1 L2 L3 (ירוק)\nHNV (אדום)",
        {"colors": a("3 ירוקות, אדומה אחת")},
        [(5, 745, 100, 845, 160), (5, 280, 200, 355, 245), (4, 880, 370, 1050, 440)],
        'נורת סימון 22 מ"מ',
        "45",
        ["10288", "10271"],
        [PRICE_OK],
    ),
    Item(
        "enc",
        "ארון פח IP55 ‏1200×800×300, ‏RAL7035, עמידה על הרצפה",
        1,
        "enclosure",
        [],
        "1200/800/300 · IP-55 · IK=10 · RAL-7035\nהעמדה על הרצפה · חיצוני · 160A",
        {
            "dimensions": a("1200×800×300", "notes", "עמוד 1"),
            "ip": a("55", "notes", "עמוד 1"),
            "ik": a("10", "notes", "עמוד 1"),
        },
        [(1, 150, 128, 812, 556), (4, 780, 300, 1150, 860)],
        reasons=[
            {"source": "match", "value": "context_page", "status": "green"},
            {"source": "match", "value": "enclosure_includes", "status": "green"},
            NO_PRICE,
        ],
    ),
]

# prototype makeFindings() (konboro-app.html 474–490)
FINDINGS: list[dict[str, Any]] = [
    {
        "key": "fv",
        "source": "rule",
        "severity": "warning",
        "code": "FRONT_VIEW_DESIGNATOR_MISSING",
        "page": 4,
        "box": (497, 663, 632, 733),
        "title": "F26–F29 מופיעים בחזית ולא בתוכנית",
        "message": 'ארבעה מא"זים תלת-קוטביים מצוירים בחזית הלוח (עמוד 4), ולא מופיעים באף עמוד של התוכנית. '
        "הם לא נספרו.",
    },
    {
        "key": "price",
        "source": "pricing",
        "severity": "error",
        "code": "MISSING_PRICE",
        "title": "5 שורות בלי מחיר",
        "message": "אין מחיר זהה במחירון של המפעל. אפשר להזין בשורה, והמחיר נשמר למחירון להצעות הבאות.",
        "lines": [i.key for i in ITEMS if i.price is None],
    },
    {
        "key": "inc",
        "source": "rule",
        "severity": "info",
        "code": "DATA_INFERRED_ATTRIBUTE",
        "title": "מגענים C1–C4: הזרם הוסק",
        "message": 'הזרם לא כתוב בשרטוט. נבחר 16A לפחות לפי המא"זים F22–F25.',
        "lines": ["c1"],
    },
    {
        "key": "fnvf",
        "source": "rule",
        "severity": "info",
        "code": "DATA_MODEL_TEXT_CONFLICT",
        "title": 'FNV: הדגם S204M סותר את "3X6A"',
        "message": "נפתר לפי זיכרון ההתאמות: 3P, כמו בהצעה 10288.",
        "lines": ["fnv"],
    },
]

_PRODUCTS = {name: (sku, sups) for name, sku, _brand, _family, _sale, sups in PRODUCTS}


def _bbox(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [round(v * PX_TO_PT, 1) for v in (x0, y0, x1, y1)]


def enable_flag(session: Session, tenant_id: str) -> None:
    """Turns the review screen on for a tenant that existed before the flag (S09 decision 2)."""
    session.execute(
        insert(m.TenantFeatureOverride)
        .values(tenant_id=tenant_id, flag_key=FLAG, enabled=True, reason="fixture")
        .on_conflict_do_nothing(index_elements=["tenant_id", "flag_key"])
    )


def seed_nursery(session: Session, tenant_id: str) -> str | None:
    """Writes the fixture into the tenant (the session already set `app.tenant_id`). Returns the new quote's id,
    or None if the tenant has it already."""
    if session.scalar(select(m.Drawing.id).where(m.Drawing.tenant_id == tenant_id, m.Drawing.trace_id == MARKER)):
        return None

    def add(obj: Any) -> Any:
        session.add(obj)
        session.flush()
        return obj

    drawing = add(
        m.Drawing(
            id=new_id("drw"),
            tenant_id=tenant_id,
            status="ready",
            input_kind="factory_drawing",
            current_stage=7,
            progress=1.0,
            title_block={"panel_name": "NURSERY", "drawing_number": "26/952", "date": "2026-10-05"},
            trace_id=MARKER,
        )
    )
    file = add(
        m.DrawingFile(
            id=new_id("fil"),
            tenant_id=tenant_id,
            drawing_id=drawing.id,
            original_name="NURSERY-1.pdf",
            detected_format="pdf",
            sha256="0" * 64,  # no PDF is stored for the fixture, only its page images (seed_nursery_pages)
            size_bytes=0,
            page_count=len(PAGE_KINDS),
            storage_key=f"tenants/{tenant_id}/drawings/{drawing.id}/files/fixture.pdf",
        )
    )
    pages: dict[int, str] = {}
    for no, (kind, route) in enumerate(PAGE_KINDS, start=1):
        page = add(
            m.Page(
                id=new_id("pg"),
                tenant_id=tenant_id,
                drawing_id=drawing.id,
                file_id=file.id,
                page_no=no,
                width_pt=842.0,
                height_pt=595.0,
                geometry_source="vector",
                text_source="pdf_text",
                quality="ok",
                page_kind=kind,
                page_kind_confidence=0.95,
                route=route,
                classified_by="model",
            )
        )
        pages[no] = page.id
    panel = add(
        m.Panel(
            id=new_id("pnl"),
            tenant_id=tenant_id,
            drawing_id=drawing.id,
            name="NURSERY",
            page_ids=[pages[n] for n in range(5, 10)],
            confidence=0.95,
        )
    )

    finding_ids = {f["key"]: new_id("iss") for f in FINDINGS}
    products = {
        p.display_name: p.id for p in session.scalars(select(m.Product).where(m.Product.tenant_id == tenant_id))
    }
    lines: list[LineIn] = []
    for item in ITEMS:
        component_id = None
        if item.designators or item.raw:
            component_id = add(
                m.Component(
                    id=new_id("cmp"),
                    tenant_id=tenant_id,
                    drawing_id=drawing.id,
                    panel_id=panel.id,
                    family="enclosure" if item.group == "enclosure" else "device",
                    attributes=item.attributes,
                    quantity=Decimal(item.qty),
                    designators=item.designators,
                    instances=[
                        {"instance_id": new_id("ins"), "page_id": pages[p], "bbox": _bbox(*box), "role": "symbol"}
                        for p, *box in item.boxes
                    ],
                    confidence=0.95,
                    explicit_texts=item.raw.split("\n") if item.raw else [],
                )
            ).id
        sku, cost, supplier = None, None, None
        if item.product:
            sku, sups = _PRODUCTS[item.product]
            preferred = next((s for s in sups if s[3]), None)
            if preferred:
                cost, supplier = Decimal(preferred[1]), SUPPLIERS[preferred[0]]
        priced = item.price is not None
        lines.append(
            LineIn(
                key=item.key,
                description=item.description,
                qty=Decimal(item.qty),
                status=_worst(item.reasons),
                line_group=item.group,
                parent=item.parent,
                component_id=component_id,
                product_id=products.get(item.product or ""),
                sku=sku,
                manufacturer="ABB" if "ABB" in item.description else None,
                unit_cost=cost,
                cost_source=(
                    {"type": "supplier_price_list", "supplier": supplier, "price_date": PRICE_DATE}
                    if supplier
                    else None
                ),
                unit_price=Decimal(item.price) if item.price is not None else None,
                price_status="ok" if priced else "missing",
                margin_rule=(
                    {"kind": "fixed", "source": "quote_import", "quotes": item.quotes} if item.quotes else None
                ),
                rounding="agora" if priced else None,
                status_reasons=item.reasons,
                issue_ids=[finding_ids[item.finding]] if item.finding else [],
                alternatives=[{"description": alt} for alt in item.alternatives],
                explanation=item.why,
            )
        )

    quote = add(m.Quote(id=new_id("quo"), tenant_id=tenant_id, drawing_id=drawing.id, name="NURSERY"))
    version = add(
        m.QuoteVersion(id=new_id("qv"), tenant_id=tenant_id, quote_id=quote.id, version=1, quote_date=QUOTE_DATE)
    )
    line_ids = write_lines(session, version, panel.id, lines)
    for f in FINDINGS:
        page = f.get("page")
        session.add(
            m.Finding(
                id=finding_ids[f["key"]],
                tenant_id=tenant_id,
                quote_version_id=version.id,
                drawing_id=drawing.id,
                source=f["source"],
                severity=f["severity"],
                code=f["code"],
                panel_id=panel.id,
                line_ids=[line_ids[k] for k in f.get("lines", [])],
                page_id=pages[page] if page else None,
                bbox=_bbox(*f["box"]) if "box" in f else None,
                message=f["message"],
                values={"title": f["title"]},
            )
        )
    session.flush()
    store_totals(session, version)
    return str(quote.id)


def _worst(reasons: list[dict[str, Any]]) -> str:
    """07 §7.5: the line's color is the worst of its reasons. The fixture plays stage 7 here."""
    statuses = {r["status"] for r in reasons}
    return "red" if "red" in statuses else "yellow" if "yellow" in statuses else "green"


def seed_nursery_pages(session: Session, storage: Storage, tenant_id: str) -> int:
    """Puts each fixture page's render, thumbnail and viewer pyramid in S3, where stage 2 would (S11 decision 2),
    and sets the page's keys. Safe to rerun: a page whose pyramid is in S3 is left alone, and one whose objects are
    gone (a bucket emptied by a test run) is written again. Returns the number of pages written."""
    drawing_id = session.scalar(
        select(m.Drawing.id).where(m.Drawing.tenant_id == tenant_id, m.Drawing.trace_id == MARKER)
    )
    if drawing_id is None:
        return 0
    written = 0
    pages = session.scalars(select(m.Page).where(m.Page.tenant_id == tenant_id, m.Page.drawing_id == drawing_id))
    tile, overlap = EXTRACTION.dzi_tile_px, EXTRACTION.dzi_overlap_px
    for page in pages:
        base = drawing_key(tenant_id, drawing_id, "pages", page.id) + "/"
        if page.tiles_prefix is not None and storage.exists(tenant_id, base + "dz/index.json"):
            continue
        image = Image.open(PAGE_IMAGES / f"p{page.page_no}.jpg").convert("RGB")
        thumb = image.copy()
        thumb.thumbnail((THUMB_PX, THUMB_PX))
        storage.put(tenant_id, thumbnail_key(tenant_id, drawing_id, page.id), png(thumb), "image/png")
        storage.put(tenant_id, base + "render.png", png(image), "image/png")
        dzi = deepzoom.descriptor(image.width, image.height, tile, overlap)
        storage.put(tenant_id, base + "dz/page.dzi", dzi, "application/xml")
        packed, index = deepzoom.pack(image, tile, overlap)
        storage.put(tenant_id, base + "dz/tiles.bin", packed)
        storage.put(tenant_id, base + "dz/index.json", index, "application/json")
        page.render_key, page.tiles_prefix = base + "render.png", base + "tiles/"
        written += 1
    session.flush()
    return written
