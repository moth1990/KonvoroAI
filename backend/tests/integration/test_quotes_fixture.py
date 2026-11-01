"""The NURSERY-1 fixture quote, read back through the review screen's read model (S09).

The numbers are the golden draft's (golden/NURSERY-1/README.md, S09 decision 1), and the prices it shares with the
quote the factory sent must match that quote exactly.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery
from konboro.services import quotes
from konboro.services.quotes import QuoteView

from .api import add_tenant

GOLDEN = Path(__file__).parents[3] / "golden" / "NURSERY-1" / "actual_quote.json"


@dataclass(frozen=True)
class Nursery:
    engine: Engine
    tenant_id: str
    quote_id: str

    def view(self) -> QuoteView:
        with tenant_session(self.tenant_id, self.engine) as s:
            view = quotes.read_quote(s, self.tenant_id, self.quote_id)
        assert view is not None
        return view


@pytest.fixture(scope="module")
def nursery(migrated_db: dict[str, Engine]) -> Iterator[Nursery]:
    """A tenant of its own (no price list: costs come from the demo list's constants), as the app role."""
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the VAT rate and the review_screen flag
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        quote_id = seed_nursery(s, tenant.tenant_id)
    assert quote_id is not None
    yield Nursery(engine, tenant.tenant_id, quote_id)


def test_the_fixture_is_the_golden_draft(nursery: Nursery) -> None:
    view = nursery.view()
    assert view is not None
    (panel,) = view.panels
    lines = panel.lines
    products = [ln for ln in lines if ln.parent_line_id is None]

    assert (view.name, view.drawing_number, view.input_kind, view.version, view.status) == (
        "NURSERY",
        "26/952",
        "factory_drawing",
        1,
        "draft",
    )
    assert len(products) == 13
    assert sum(ln.qty for ln in products) == 42
    assert [ln.description for ln in lines if ln.parent_line_id] == ["ערכה: מודול פחת למפסק"]
    assert all(isinstance(ln.qty, Decimal) for ln in lines)

    q = view.totals
    assert q.net_total == Decimal("4674.0000")
    assert panel.sums.price_total == q.net_total
    assert q.sums.unpriced_count == 5
    assert q.sums.line_counts == {"green": 9, "yellow": 0, "red": 5}
    assert q.vat == Decimal("841.32") and q.gross_total == Decimal("5515.32")
    # NVR has no cost in the price list: its 340 is left out of the margin (09 §6.3)
    assert q.sums.uncosted_count == 1
    assert q.sums.cost_total == Decimal("3139.5000")
    assert q.margin_abs == Decimal("1194.5000") and q.margin_pct == Decimal("0.2756")
    assert view.coverage_pct == 62  # 8 of 13 products; the kit add-on is priced in Q0


def test_shared_prices_match_the_sent_quote(nursery: Nursery) -> None:
    golden = json.loads(GOLDEN.read_text())
    sent = {d: Decimal(line["unit_price"]) for line in golden["lines"] for d in line["drawing_designators"]}
    view = nursery.view()
    shared = 0
    for ln in view.panels[0].lines:
        key = "F1–F17" if ln.designators[:1] == ["F1"] else (ln.designators[:1] or [""])[0]
        if ln.unit_price is not None and key in sent:
            assert ln.unit_price == sent[key], ln.description
            shared += 1
    assert shared == 7  # FNV's 185 (quote 10288) is the eighth; the sent quote left FNV out


def test_lines_follow_the_review_order_and_every_non_green_line_says_why(nursery: Nursery) -> None:
    view = nursery.view()
    lines = view.panels[0].lines
    assert [ln.line_group for ln in lines] == ["feed"] * 2 + ["outputs"] * 5 + ["control"] * 6 + ["enclosure"]
    assert lines[1].parent_line_id == lines[0].line_id and lines[1].included
    for ln in lines:
        if ln.status != "green":
            assert any(r["status"] == ln.status for r in ln.status_reasons), ln.description
    c1 = next(ln for ln in lines if ln.designators[:1] == ["C1"])
    assert c1.explanation and c1.alternatives and c1.issue_ids
    assert {src.source for src in c1.sources} == {"circuit", "graphic", "notes"}
    assert c1.raw_text == ["C1 … C4", "(אין זרם כתוב)"]

    codes = [(f.severity, f.code) for f in view.findings]
    assert codes[0] == ("error", "MISSING_PRICE")
    assert ("warning", "FRONT_VIEW_DESIGNATOR_MISSING") in codes and len(codes) == 4
    front = next(f for f in view.findings if f.code == "FRONT_VIEW_DESIGNATOR_MISSING")
    assert front.page_no == 4
    priced = next(f for f in view.findings if f.code == "MISSING_PRICE")
    assert len(priced.line_ids) == 5


def test_stored_totals_equal_the_sums_of_the_live_lines(nursery: Nursery) -> None:
    with tenant_session(nursery.tenant_id, nursery.engine) as s:
        version = s.scalar(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == nursery.quote_id))
        assert version is not None
        totals = version.totals
    assert totals == quotes.totals_contract(nursery.view().totals).model_dump(mode="json")
    assert totals["net_total"] == "4674.0000"


def test_a_deleted_line_leaves_the_sums(nursery: Nursery) -> None:
    """Soft delete (09 §7.6): the read model sums the live lines, not the stored totals."""
    with tenant_session(nursery.tenant_id, nursery.engine) as s:
        q01 = s.scalar(select(m.QuoteLine).where(m.QuoteLine.description.startswith("מפסק בתיבה יצוקה ABB XT1C 3P")))
        assert q01 is not None
        q01.deleted_at = q01.created_at
        q01_id = q01.id
    try:
        view = nursery.view()
        assert view.totals.net_total == Decimal("3924.0000")
        assert len(view.panels[0].lines) == 13
    finally:
        with tenant_session(nursery.tenant_id, nursery.engine) as s:
            line = s.get(m.QuoteLine, q01_id)
            assert line is not None
            line.deleted_at = None


def test_seeding_twice_adds_nothing(nursery: Nursery) -> None:
    with tenant_session(nursery.tenant_id, nursery.engine) as s:
        assert seed_nursery(s, nursery.tenant_id) is None
        assert s.scalar(select(func.count()).select_from(m.Quote)) == 1


def test_an_unknown_quote_reads_as_none(nursery: Nursery) -> None:
    with tenant_session(nursery.tenant_id, nursery.engine) as s:
        assert quotes.read_quote(s, nursery.tenant_id, "quo_01JD0000000000000000000000") is None
