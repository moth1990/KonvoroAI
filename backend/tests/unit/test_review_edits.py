"""The review screen's edits applied to stage 7's drafts (S23, `pricing/edits.py`), the approved colour (07 §7.5,
09 §7.2), and what a line priced before S23 reports of its price (`load.legacy_issues`)."""

from datetime import UTC, datetime
from decimal import Decimal as D

from konboro.db import models as m
from konboro.pipeline.pricing import load
from konboro.pipeline.pricing.book import NO_PRODUCT, Priced, price
from konboro.pipeline.pricing.edits import Kept, LineEdits, Replaced, apply, apply_all, stored_reasons
from konboro.pipeline.pricing.lines import NO_SKU, Draft
from konboro.pipeline.pricing.status import finalize

from .test_stage7 import book, product, sp

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def draft(key: str = "c:1", sku: str | None = "S203M-C16", qty: str = "2", **kw: object) -> Draft:
    b = book()
    p = b.product(None, sku) if sku else None
    out = Draft(
        key=key,
        panel_id="pnl_1",
        line_type="component",
        description=f"מא״ז {sku}",
        qty=D(qty),
        priced=price(p, b) if p else NO_SKU,
        product_id=p.product_id if p else None,
        sku=sku,
        reasons=[{"source": "confidence", "value": 0.7, "status": "yellow"}],
    )
    for k, v in kw.items():
        setattr(out, k, v)
    return out


def test_no_edit_leaves_stage_7s_price() -> None:
    d = draft()
    out = apply(d, None, book())
    assert (out.qty, out.priced, out.edits, out.approved) == (d.qty, d.priced, {}, False)


def test_a_quantity_and_a_kit_part_that_follows_it() -> None:
    parent = draft()
    part = draft("c:1:kit:0", "S203M-C25", qty="2", parent="c:1")
    own = draft("c:1:kit:1", "S203M-C25", qty="2", parent="c:1")
    edits = {"c:1": LineEdits(qty=D("5")), "c:1:kit:1": LineEdits(qty=D("1"))}
    out = {x.key: x for x in apply_all([parent, part, own], edits, book())}
    assert (out["c:1"].qty, out["c:1:kit:0"].qty, out["c:1:kit:1"].qty) == (D("5"), D("5"), D("1"))
    assert out["c:1"].edits == {"qty": "5"} and out["c:1"].priced == parent.priced  # no new price for a quantity


def test_an_alternative_reprices_the_line_from_its_product() -> None:
    d = draft(alternatives=[{"sku": "S203M-C25", "description": "25A"}, {"sku": "X", "description": "x"}])
    e = LineEdits(replaced=Replaced("S203M-C25", "ABB", 'מא"ז 3P 25A', "ci_s203_25"))
    out = apply(d, e, book())
    assert (out.sku, out.product_id, out.description) == ("S203M-C25", "prd_25", 'מא"ז 3P 25A')
    assert out.priced.unit_price == D("187.50")  # 150 × 1.25
    assert [a["sku"] for a in out.alternatives] == ["X"]
    nothing = apply(d, LineEdits(replaced=Replaced("NOPE", None, "x")), book())
    assert nothing.priced == NO_PRODUCT and nothing.product_id is None


def test_a_supplier_for_this_quote_prices_the_cost_from_it() -> None:
    b = book(products=[product("prd_16", "ci_s203_16", "S203M-C16", sp("psp_a", "138", preferred=True),
                               sp("psp_b", "120", supplier="sup_b"))])  # fmt: skip
    d = draft()
    d.priced = price(b.product_by_id("prd_16"), b)
    assert d.priced.unit_cost == D("138")
    out = apply(d, LineEdits(supplier_id="sup_b"), b)
    assert (out.priced.unit_cost, out.priced.unit_price) == (D("120"), D("150.00"))  # a rule prices from the cost


def test_a_kept_price_counts_for_the_same_product_only() -> None:
    old = Priced(D("100"), None, "ok", {"kind": "fixed"}, D("170"), D("170"), "agora")
    d = draft()
    assert apply(d, None, book(), kept=Kept("prd_16", "S203M-C16", old)).priced == old
    assert apply(d, None, book(), kept=Kept("prd_25", "S203M-C25", old)).priced == d.priced


def test_a_dismissed_finding_leaves_the_line() -> None:
    d = draft(issue_ids=["iss_a", "iss_b"])
    d.reasons = [
        {"source": "validator", "value": None, "issue_id": "iss_a", "status": "red"},
        {"source": "validator", "value": None, "issue_id": "iss_b", "status": "yellow"},
    ]
    out = apply(d, None, book(), frozenset({"iss_a"}))
    finalize(out)
    assert out.issue_ids == ["iss_b"] and out.status == "yellow"


def test_approved_is_green_with_every_reason_kept_but_its_price_still_counts() -> None:
    d = apply(draft(), LineEdits(approved_at=NOW), book())
    finalize(d)
    assert d.status == "green" and d.status_reasons[0] == {"source": "user", "value": "approved", "status": "green"}
    assert {"source": "confidence", "value": 0.7, "status": "green", "was": "yellow"} in d.status_reasons
    unpriced = apply(draft(sku="NOPE"), LineEdits(approved_at=NOW), book())
    finalize(unpriced)
    assert unpriced.status == "red"
    assert stored_reasons(d.status_reasons) == [{"source": "confidence", "value": 0.7, "status": "yellow"}]


def test_the_edits_round_trip_through_their_column() -> None:
    e = LineEdits(qty=D("3"), supplier_id="sup_b", replaced=Replaced("S", "ABB", "x", "ci"), approved_at=NOW)
    assert LineEdits.of(e.as_json(), NOW) == e
    assert LineEdits.of({}, None).empty and not LineEdits.of({}, NOW).empty


def line(**kw: object) -> m.QuoteLine:
    row = m.QuoteLine(line_type="component", status_reasons=[], cost_source=None)
    for k, v in kw.items():
        setattr(row, k, v)
    return row


def test_a_line_priced_before_s23_reports_its_missing_price() -> None:
    """Rows written before the price reason kept its issues: no price is `missing_cost`, unless the match was the
    problem (a red match reason) or the line is a missing one."""
    assert load.legacy_issues(line(), "missing") == ("missing_cost",)
    assert load.legacy_issues(line(cost_source={"type": "missing"}), "missing") == ("missing_cost",)
    assert load.legacy_issues(line(status_reasons=[{"source": "match", "status": "red"}]), "missing") == ()
    assert load.legacy_issues(line(line_type="missing"), "missing") == ()
    assert load.legacy_issues(line(), "stale") == ("stale_price",)
    assert load.legacy_issues(line(), "ok") == ()
    stored = line(price_status="missing", status_reasons=[{"source": "price", "value": "missing", "issues": []}])
    assert load.priced_as_stored(stored).issues == ()  # a row that says it has none
