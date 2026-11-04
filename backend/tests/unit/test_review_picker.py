"""The product picker's pure parts (S23b): the crop of a marked rectangle, the detector example's class, the fixture's
values as the schema's, and the edits a rematch and a resolved missing line carry through a rerun."""

import io
from datetime import date
from decimal import Decimal

from PIL import Image

from konboro.domain.pricing import cost as pc
from konboro.domain.pricing.margin import Rule
from konboro.pipeline.pricing.book import Book, Item, Product
from konboro.pipeline.pricing.edits import LineEdits, Rematch, Replaced, apply
from konboro.pipeline.pricing.lines import NO_SKU, Draft
from konboro.services.review_picker import (
    _fixture_value,
    crop_png,
    default_class,
    panel_at,
)


def test_the_crop_is_the_rectangle_at_the_renders_scale() -> None:
    page = Image.new("RGB", (1684, 1190), "white")  # 842 × 595 pt at 2 px per point
    buf = io.BytesIO()
    page.save(buf, "PNG")
    out = Image.open(io.BytesIO(crop_png(buf.getvalue(), 842, [100, 100, 140, 160])))
    assert out.size == (2 * (40 + 8) + 1, 2 * (60 + 8) + 1)  # a 4 pt margin each side


def test_a_marks_class_is_its_familys_default() -> None:
    assert default_class("circuit_breaker") == "mcb"
    assert default_class("no_such_family") is None
    assert default_class(None) is None


def test_the_fixtures_texts_are_read_as_numbers() -> None:
    assert _fixture_value("current_a", "160A") == 160
    assert _fixture_value("breaking_capacity_ka", "4.5kA") == 4.5
    assert _fixture_value("poles", "3") == 3
    assert _fixture_value("curve", "C") == "C"
    assert _fixture_value("current_a", "—") is None


def test_fixture_poles_with_a_neutral() -> None:
    """BUG-064: "1P+N" is one pole and a neutral; stage 5 and `describe` take poles as a number."""
    assert _fixture_value("poles", "1P+N") == 1
    assert _fixture_value("poles", "—") is None


def test_the_panel_falls_back_to_none_with_no_panels() -> None:
    assert panel_at([], "pg_1", [0, 0, 20, 20], None) is None


def _book(*items: Item, discount: str | None = None) -> Book:
    ctx = pc.CostContext(on_date=date(2026, 11, 4), currency="ILS")
    if discount:
        ctx = pc.CostContext(on_date=ctx.on_date, currency="ILS", brand_discounts={"ABB": Decimal(discount)})
    return Book(
        cost=ctx, items=items, rules=(Rule(id="mr_default", level="default", kind="markup", value=Decimal("0.25")),)
    )


C20 = Item(
    id="cat_c20",
    sku="S203M-C20",
    brand="ABB",
    family="circuit_breaker",
    description='מא"ז ABB S203M 3P 20A',
    list_price=Decimal("215.00"),
)


def test_a_catalog_item_with_no_product_is_priced_at_the_brand_discount() -> None:
    """BUG-058: 07 §7.2 priority 2 is by SKU."""
    book = _book(C20, discount="0.30")
    found = book.find(None, "cat_c20", "S203M-C20", "ABB")
    assert isinstance(found, Product) and found.listed and found.list_price == Decimal("215.00")
    assert _book(C20).find(None, "cat_c20", "S203M-C20", "ABB") is None  # no discount: no price


def test_a_rematch_and_a_resolution_survive_the_round_trip_and_apply() -> None:
    rem = Rematch(
        "S203M-C16",
        "ABB",
        'מא"ז ABB S203M 3P 16A',
        None,
        ({"source": "match", "value": "matched", "status": "green"},),
    )
    edits = LineEdits(attrs={"current_a": 16}, match=rem)
    assert LineEdits.of(edits.as_json()) == edits
    line = Draft(key="c:cmp_1", panel_id="pnl_1", line_type="component", description="x", qty=Decimal(4), priced=NO_SKU)
    out = apply(line, edits, _book())
    assert (out.sku, out.description) == ("S203M-C16", rem.description)
    assert out.reasons == [{"source": "match", "value": "matched", "status": "green"}]
    resolved = LineEdits(replaced=Replaced("S203M-C20", "ABB", 'מא"ז 20A', "cat_c20"), resolved=True)
    assert LineEdits.of(resolved.as_json()) == resolved
    missing = Draft(
        key="m:ins_1", panel_id="pnl_1", line_type="missing", description="?", qty=Decimal(1), priced=NO_SKU
    )
    out = apply(missing, resolved, _book(C20, discount="0.30"))
    assert out.line_type == "component" and out.sku == "S203M-C20" and out.product_id is None
    # 215 × 0.70 = 150.50, the 25% markup: 188.13 (07 §7.2 priority 2, §7.3)
    assert (out.priced.price_status, out.priced.unit_price) == ("discount_based", Decimal("188.13"))
