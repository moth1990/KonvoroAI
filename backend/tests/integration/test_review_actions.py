"""The review screen's actions (09 §7, S23) on the NURSERY-1 fixture, a quote with no stage outputs: each action, what
it writes for the learning loop (09 §10), its undo (09 §7.11), a sent version refusing them all (07 §7.7), and the
costs a user without the permission never gets (09 §12). A drawing from the pipeline: `test_review_pipeline.py`."""

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.api.deps import Actor
from konboro.api.routes.quotes import quote_out
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global, seed_price_list
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery
from konboro.domain import permissions
from konboro.services import price_list as pl
from konboro.services import quotes as qs

from ..perf import ACTION, RERUN, within
from .api import Api, ApiTenant, add_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    return migrated_db


@dataclass
class Quote:
    api: Api
    tenant: ApiTenant
    quote_id: str

    def get(self) -> dict[str, Any]:
        r = self.api.client.get(f"/quotes/{self.quote_id}", headers=self.api.as_(self.tenant))
        assert r.status_code == 200, r.text
        return dict(r.json())

    def post(self, path: str, body: dict[str, Any] | None = None, status: int = 200) -> dict[str, Any]:
        r = self.api.client.post(f"/quotes/{self.quote_id}{path}", json=body, headers=self.api.as_(self.tenant))
        assert r.status_code == status, r.text
        return dict(r.json())

    def delete(self, line_id: str, status: int = 200) -> dict[str, Any]:
        r = self.api.client.delete(f"/quotes/{self.quote_id}/lines/{line_id}", headers=self.api.as_(self.tenant))
        assert r.status_code == status, r.text
        return dict(r.json())

    def undo(self, done: dict[str, Any], status: int = 200) -> dict[str, Any]:
        return self.post(f"/undo/{done['event_id']}", status=status)

    def session(self) -> Any:
        return tenant_session(self.tenant.tenant_id, self.api.engine)


def by_tag(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    body = body.get("quote", body)
    return {
        ln["designators"][0] if ln["designators"] else ln["description"]: ln
        for p in body["panels"]
        for ln in p["lines"]
    }


def codes(body: dict[str, Any]) -> list[str]:
    return [f["code"] for f in body.get("quote", body)["findings"]]


def missing_title(body: dict[str, Any]) -> str | None:
    return next((f["title"] for f in body.get("quote", body)["findings"] if f["code"] == "missing_cost"), None)


@pytest.fixture
def quote(api: Api, seeded: dict[str, Engine]) -> Iterator[Quote]:
    """A factory with the demo price list, a 25% default markup, a 15% line floor, and the fixture."""
    tenant = add_tenant(seeded["app"])
    with tenant_session(tenant.tenant_id, api.engine) as s:
        seed_price_list(s, tenant.tenant_id)
        s.add(
            m.MarginRule(
                id=new_id("mr"), tenant_id=tenant.tenant_id, level="default", kind="markup", value=Decimal("0.25")
            )
        )
        settings = s.get_one(m.TenantSettings, tenant.tenant_id)
        settings.min_line_margin = Decimal("0.15")
        settings.enclosure_includes_default = {"busbar": True, "n": True, "pe": True}
        s.flush()
        qid = seed_nursery(s, tenant.tenant_id)
    assert qid is not None
    yield Quote(api, tenant, qid)


def events(q: Quote, type_: str) -> list[m.CorrectionEvent]:
    with q.session() as s:
        rows = list(
            s.scalars(
                select(m.CorrectionEvent)
                .where(m.CorrectionEvent.quote_id == q.quote_id, m.CorrectionEvent.type == type_)
                .order_by(m.CorrectionEvent.created_at)
            )
        )
        s.expunge_all()
    return rows


# --- the read model -------------------------------------------------------------------------------------------------


def test_the_screen_reads_suppliers_new_prices_hints_and_the_footnote(quote: Quote) -> None:
    body = quote.get()
    lines = by_tag(body)
    # 07 §7.2.3: the lamp's price came from an earlier quote; the price list's markup rule now says 18 × 1.25
    assert (lines["L1"]["unit_price"], lines["L1"]["fresh_price"]) == ("45.0000", "22.50")
    assert lines["F1"]["fresh_price"] is None  # its product's fixed price is the line's
    f22 = lines["F22"]
    assert [(s["unit_cost"], s["preferred"], s["chosen"]) for s in f22["suppliers"]] == [
        ("131.0000", False, False),
        ("138.0000", True, True),
    ]
    # "קרובים במחירון": the S203M products nearest 20A, for the line with no price
    assert [h["name"] for h in lines["F18"]["price_hints"]] == [
        'מא"ז ABB S203M 3P ‏16A',
        'מא"ז ABB S203M 3P ‏25A',
        'מא"ז ABB S203M 3P ‏6A',
    ]
    assert lines["F18"]["price_hints"][0]["unit_price"] == "185.00"
    assert body["derived_note"] == "פריטים נלווים: פסי צבירה, אפס והארקה כלולים במחיר הארון לפי הגדרות המפעל."
    assert body["line_floor"] == "0.1500" and body["can_see_costs"]
    assert lines["F1"]["qty_editable"] and not lines["ערכה: מודול פחת למפסק"]["qty_editable"]
    assert missing_title(body) == "5 שורות בלי מחיר"


def test_costs_never_reach_a_user_without_the_permission(quote: Quote, monkeypatch: pytest.MonkeyPatch) -> None:
    """09 §12: the server sends no cost at all, not one the screen hides."""
    monkeypatch.setitem(
        permissions.ROLE_PERMISSIONS, "sales", frozenset(permissions.Permission) - {permissions.Permission.COSTS_READ}
    )
    with quote.session() as s:
        actor = Actor(quote.tenant.user_id, quote.tenant.tenant_id, quote.tenant.email, "sales", s)
        body = quote_out(actor, quote.quote_id, quote.api.app.state.storage).model_dump(mode="json")
    assert not body["can_see_costs"]
    for p in body["panels"]:
        assert p["totals"]["cost_total"] is None
        for ln in p["lines"]:
            assert [ln[k] for k in ("unit_cost", "line_cost", "margin_pct", "unit_margin", "cost_source")] == [None] * 5
            assert ln["suppliers"] == []
    assert (body["totals"]["margin_abs"], body["totals"]["margin_pct"], body["totals"]["cost_total"]) == (None,) * 3
    assert body["totals"]["net_total"] == "4674.0000"


# --- line actions ---------------------------------------------------------------------------------------------------


def test_approve_turns_the_line_green_dismisses_its_finding_and_undo_puts_it_back(quote: Quote) -> None:
    c1 = by_tag(quote.get())["C1"]
    done = quote.post(f"/lines/{c1['line_id']}/approve")
    after = by_tag(done)["C1"]
    assert done["message"] == "אושר: מגען 3P ‏16A לפחות (AC-3)" and done["event_id"]
    assert after["approved"] and after["line_id"] == c1["line_id"]
    assert after["status"] == "red"  # approving does not price it (07 §7.5)
    reasons = {(r["source"], r["value"]): r for r in after["status_reasons"] if isinstance(r["value"], str)}
    assert reasons["user", "approved"]["status"] == "green"
    inferred = reasons["match", "inferred_attribute"]
    assert (inferred["status"], inferred["was"]) == ("green", "yellow")  # kept, shown green (09 §9)
    assert "DATA_INFERRED_ATTRIBUTE" not in codes(done)  # dismissed as "אושר ידנית"
    [event] = events(quote, "row_confirmed")
    assert (event.line_id, event.user_id, event.source, event.quote_version) == (
        c1["line_id"],
        quote.tenant.user_id,
        "review_screen",
        1,
    )
    assert event.before and event.before["status"] == "red" and event.before["restore"]["lines"]
    with quote.session() as s:
        finding = s.scalar(select(m.Finding).where(m.Finding.code == "DATA_INFERRED_ATTRIBUTE"))
        assert finding is not None and finding.dismissal and finding.dismissal["reason"] == "approved"

    undone = quote.undo(done)
    assert not by_tag(undone)["C1"]["approved"] and "DATA_INFERRED_ATTRIBUTE" in codes(undone)
    assert by_tag(undone)["C1"]["status_reasons"] == c1["status_reasons"]
    assert events(quote, "row_confirmed")[0].undone and len(events(quote, "undo")) == 1
    assert quote.undo(done, status=409)["error"]["code"] == "already_undone"


def test_a_missing_line_is_not_approved(quote: Quote) -> None:
    with quote.session() as s:
        version = s.scalar(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote.quote_id))
        assert version is not None
        [line_id] = qs.write_lines(
            s,
            version,
            None,
            [
                qs.LineIn(
                    key="x",
                    description='רכיב שלא זוהה (נראה כמו מא"ז 1P 20A)',
                    qty=Decimal(1),
                    status="red",
                    line_type="missing",
                )
            ],
        ).values()
    r = quote.post(f"/lines/{line_id}/approve", status=422)
    assert r["error"]["details"][0]["type"] == "missing_line"


def test_delete_takes_the_line_and_its_kit_part_out_and_undo_brings_them_back(quote: Quote) -> None:
    body = quote.get()
    q0, q0b = by_tag(body)["Q0"], by_tag(body)["ערכה: מודול פחת למפסק"]
    done = quote.delete(q0["line_id"])
    assert done["message"] == "השורה נמחקה"
    left = by_tag(done)
    assert "Q0" not in left and "ערכה: מודול פחת למפסק" not in left
    assert missing_title(done) == "4 שורות בלי מחיר"
    [event] = events(quote, "row_deleted")
    assert set(event.before["restore"]["lines"]) == {q0["line_id"], q0b["line_id"]}
    back = quote.undo(done)
    assert by_tag(back)["Q0"]["line_id"] == q0["line_id"] and missing_title(back) == "5 שורות בלי מחיר"
    assert by_tag(back)["ערכה: מודול פחת למפסק"]["included"]


def test_quantity_changes_the_amounts_and_a_kit_part_follows(quote: Quote) -> None:
    body = quote.get()
    f1 = by_tag(body)["F1"]
    done = quote.post(f"/lines/{f1['line_id']}/qty", {"qty": "18"})
    assert (by_tag(done)["F1"]["qty"], by_tag(done)["F1"]["line_total"]) == ("18.000", "2340.0000")
    assert Decimal(done["quote"]["totals"]["net_total"]) == Decimal(body["totals"]["net_total"]) + 130
    [event] = events(quote, "quantity_changed")
    assert (event.before["qty"], event.after) == ("17.000", {"qty": "18"})
    for bad in ("0", "1.5", "-2"):
        assert quote.post(f"/lines/{f1['line_id']}/qty", {"qty": bad}, status=422)["error"]["code"]
    q0 = by_tag(body)["Q0"]
    assert quote.post(f"/lines/{by_tag(body)['ערכה: מודול פחת למפסק']['line_id']}/qty", {"qty": "2"}, status=422)
    kit = by_tag(quote.post(f"/lines/{q0['line_id']}/qty", {"qty": "2"}))["ערכה: מודול פחת למפסק"]
    assert kit["qty"] == "2.000"
    back = quote.undo(done)
    assert by_tag(back)["F1"]["qty"] == "17.000"


def test_an_alternative_replaces_the_product_and_the_old_one_becomes_an_alternative(quote: Quote) -> None:
    q0 = by_tag(quote.get())["Q0"]
    done = quote.post(f"/lines/{q0['line_id']}/alternative", {"index": 0})
    line = next(ln for p in done["quote"]["panels"] for ln in p["lines"] if ln["line_id"] == q0["line_id"])
    assert line["description"] == "ABB XT2N 4P 160A + RC" and line["approved"]
    assert [a["description"] for a in line["alternatives"]] == [
        "Schneider NSX160 4P + Vigi",
        q0["description"],
    ]
    assert done["message"].startswith("הוחלף: ")
    [event] = events(quote, "sku_replaced")
    assert event.after and event.after["description"] == "ABB XT2N 4P 160A + RC"
    assert quote.post(f"/lines/{q0['line_id']}/alternative", {"index": 7}, status=422)
    back = by_tag(quote.undo(done))["Q0"]
    assert (back["description"], back["approved"], back["alternatives"]) == (
        q0["description"],
        False,
        q0["alternatives"],
    )


def test_dismissing_a_finding_needs_a_reason(quote: Quote) -> None:
    body = quote.get()
    fv = next(f for f in body["findings"] if f["code"] == "FRONT_VIEW_DESIGNATOR_MISSING")
    price = next(f for f in body["findings"] if f["code"] == "missing_cost")
    assert quote.post(f"/findings/{fv['finding_id']}/dismiss", {"reason": "other"}, status=422)
    assert quote.post(f"/findings/{price['finding_id']}/dismiss", {"reason": "intended"}, status=422)
    done = quote.post(f"/findings/{fv['finding_id']}/dismiss", {"reason": "intended"})
    assert "FRONT_VIEW_DESIGNATOR_MISSING" not in codes(done) and done["message"] == "הממצא נדחה"
    [event] = events(quote, "issue_dismissed")
    assert event.after == {"rule_id": "FRONT_VIEW_DESIGNATOR_MISSING", "reason": "intended", "severity": "warning"}
    assert event.reason == "מכוון"
    assert "FRONT_VIEW_DESIGNATOR_MISSING" in codes(quote.undo(done))


# --- prices, costs, suppliers ---------------------------------------------------------------------------------------


def test_a_price_typed_in_the_row_goes_to_the_price_list_and_undo_takes_it_out(quote: Quote) -> None:
    f18 = by_tag(quote.get())["F18"]
    done = quote.post(f"/lines/{f18['line_id']}/price-entry", {"unit_price": "210", "save": True})
    line = by_tag(done)["F18"]
    assert (line["unit_price"], line["status"], line["product_id"] is not None) == ("210.0000", "green", True)
    assert done["message"] == 'נשמר במחירון: מא"ז ABB S203M 3P ‏20A, ₪210'
    assert missing_title(done) == "4 שורות בלי מחיר"
    with quote.session() as s:
        product = s.get_one(m.Product, line["product_id"])
        assert (product.sale_mode, product.fixed_price, product.source) == (
            "fixed",
            Decimal("210.0000"),
            "manual_entry",
        )
        assert product.entered_in_quote == quote.quote_id
    assert quote.post(f"/lines/{f18['line_id']}/price-entry", {"unit_price": "1"}, status=409)

    back = by_tag(quote.undo(done))["F18"]
    assert (back["unit_price"], back["product_id"], back["status"]) == (None, None, "red")
    with quote.session() as s:
        assert s.get(m.Product, line["product_id"]) is None


def test_a_price_for_this_quote_only_is_an_override(quote: Quote) -> None:
    rnv = by_tag(quote.get())["RNV"]
    done = quote.post(f"/lines/{rnv['line_id']}/price-entry", {"unit_price": "88", "save": False})
    line = by_tag(done)["RNV"]
    assert (line["unit_price"], line["override"], line["product_id"]) == ("88.0000", True, None)
    assert done["message"] == "נשמר להצעה הזו בלבד"


def test_a_cost_saved_to_a_product_with_no_supplier_prices_its_margin(quote: Quote) -> None:
    nvr = by_tag(quote.get())["NVR"]
    assert nvr["unit_cost"] is None and nvr["unit_price"] == "340.0000"
    done = quote.post(f"/lines/{nvr['line_id']}/cost", {"unit_cost": "200", "supplier": "ספק חדש"})
    line = by_tag(done)["NVR"]
    assert (line["unit_cost"], line["unit_price"], line["margin_pct"]) == ("200.0000", "340.0000", "0.4118")
    assert [(s["name"], s["preferred"]) for s in line["suppliers"]] == [("ספק חדש", True)]
    [event] = events(quote, "price_entered")
    assert event.after and event.after["supplier"] == "ספק חדש"
    back = by_tag(quote.undo(done))["NVR"]
    assert (back["unit_cost"], back["suppliers"]) == (None, [])


def test_a_cost_on_a_line_with_no_product_makes_one_priced_by_the_rules(quote: Quote) -> None:
    c1 = by_tag(quote.get())["C1"]
    done = quote.post(f"/lines/{c1['line_id']}/cost", {"unit_cost": "100", "supplier": None})
    line = by_tag(done)["C1"]
    assert (line["unit_cost"], line["unit_price"], line["status"]) == ("100.0000", "125.0000", "yellow")
    assert done["sanity"] is not None


def test_a_sale_price_change_in_the_price_list_is_undone_there_too(quote: Quote) -> None:
    f22 = by_tag(quote.get())["F22"]
    done = quote.post(f"/lines/{f22['line_id']}/price", {"unit_price": "190", "scope": "catalog"})
    assert by_tag(done)["F22"]["unit_price"] == "190.0000"
    with quote.session() as s:
        assert s.get_one(m.Product, f22["product_id"]).fixed_price == Decimal("190")
    back = by_tag(quote.undo(done))["F22"]
    assert back["unit_price"] == "185.0000"
    with quote.session() as s:
        product = s.get_one(m.Product, f22["product_id"])
        assert product.fixed_price == Decimal("185")
        fields = [h.field for h in s.scalars(select(m.PriceHistory).where(m.PriceHistory.product_id == product.id))]
        assert fields.count("fixed_price") == 2  # the change and its undo, both in the history (07 §12)


def test_the_price_lists_new_price_is_taken_on_request(quote: Quote) -> None:
    lamp = by_tag(quote.get())["L1"]
    done = quote.post(f"/lines/{lamp['line_id']}/list-price")
    line = by_tag(done)["L1"]
    assert (line["unit_price"], line["fresh_price"]) == ("22.5000", None)
    assert line["below_floor"] is False  # 22.50 over 18: 20%


def test_a_supplier_for_this_quote_then_preferred_in_the_price_list(quote: Quote) -> None:
    f22 = by_tag(quote.get())["F22"]
    cheaper = next(s for s in f22["suppliers"] if not s["preferred"])
    done = quote.post(f"/lines/{f22['line_id']}/supplier", {"supplier_price_id": cheaper["supplier_price_id"]})
    line = by_tag(done)["F22"]
    assert (line["unit_cost"], line["unit_price"], line["supplier_id"]) == (
        "131.0000",
        "185.0000",
        cheaper["supplier_id"],
    )
    assert next(s for s in line["suppliers"] if s["chosen"])["supplier_price_id"] == cheaper["supplier_price_id"]
    assert done["message"] == "הספק הוחלף רק בהצעה הזו"
    preferred = quote.post(f"/lines/{f22['line_id']}/supplier/preferred")
    line = by_tag(preferred)["F22"]
    assert (line["supplier_id"], line["unit_cost"]) == (None, "131.0000")
    assert next(s for s in line["suppliers"] if s["preferred"])["supplier_price_id"] == cheaper["supplier_price_id"]
    back = by_tag(quote.undo(preferred))["F22"]
    assert next(s for s in back["suppliers"] if s["preferred"])["unit_cost"] == "138.0000"
    assert back["supplier_id"] == cheaper["supplier_id"]
    assert quote.post(f"/lines/{f22['line_id']}/supplier", {"supplier_price_id": "psp_x"}, status=422)


# --- versions -------------------------------------------------------------------------------------------------------


def test_recalculation_shows_the_comparison_first(quote: Quote) -> None:
    preview = quote.api.client.get(f"/quotes/{quote.quote_id}/recalculation", headers=quote.api.as_(quote.tenant))
    assert preview.status_code == 200, preview.text
    changed = {x["description"]: x for x in preview.json()["lines"]}
    assert changed['נורת סימון 22 מ"מ']["delta"] == "-90.0000"
    assert by_tag(quote.get())["L1"]["unit_price"] == "45.0000"  # nothing written
    after = quote.post("/recalculation")
    assert by_tag(after)["L1"]["unit_price"] == "22.5000"


def test_send_locks_the_version_and_a_new_one_opens_as_a_draft(quote: Quote) -> None:
    f1 = by_tag(quote.get())["F1"]
    done = quote.post(f"/lines/{f1['line_id']}/approve")
    sent = quote.post("/send")
    assert (sent["status"], sent["version"]) == ("sent", 1)
    assert sent["panels"][0]["lines"][0]["fresh_price"] is None
    for path, body in (
        (f"/lines/{f1['line_id']}/approve", None),
        (f"/lines/{f1['line_id']}/qty", {"qty": "3"}),
        (f"/lines/{f1['line_id']}/price", {"unit_price": "1", "scope": "quote"}),
        ("/recalculation", None),
        (f"/undo/{done['event_id']}", None),
    ):
        assert quote.post(path, body, status=409)["error"]["code"] == "quote_sent", path
    assert quote.delete(f1["line_id"], status=409)
    assert quote.post("/send", status=409)
    v2 = quote.post("/versions")
    assert (v2["status"], v2["version"]) == ("draft", 2)
    assert by_tag(v2)["F1"]["approved"]  # what the customer saw, as it was
    assert quote.undo(done, status=409)["error"]["code"] == "not_undoable"  # before sending: never (09 §7.11)
    assert len(events(quote, "quote_sent")) == 1


def test_another_tenants_quote_is_not_found(quote: Quote) -> None:
    f1 = by_tag(quote.get())["F1"]
    r = quote.api.client.post(
        f"/quotes/{quote.quote_id}/lines/{f1['line_id']}/approve", headers=quote.api.as_(quote.api.b)
    )
    assert r.status_code == 404


@pytest.mark.perf
def test_an_action_on_a_150_line_quote_answers_within_half_a_second(quote: Quote) -> None:
    """09 §14: an action, with the server's recalculation, ≤ 500 ms; an alternative ≤ 1 s."""
    with quote.session() as s:
        version = s.scalar(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote.quote_id))
        assert version is not None
        panel_id = s.scalar(select(m.QuoteLine.panel_id).where(m.QuoteLine.quote_version_id == version.id).limit(1))
        qs.write_lines(
            s,
            version,
            panel_id,
            [
                qs.LineIn(
                    key=f"x{i}",
                    description=f'מא"ז בדיקה {i}',
                    qty=Decimal(2),
                    status="green",
                    unit_price=Decimal("10"),
                    unit_cost=Decimal("7"),
                    price_status="ok",
                    line_key=f"perf:{i}",
                    alternatives=[{"description": "חלופה"}],
                    status_reasons=[{"source": "price", "value": "ok", "status": "green"}],
                )
                for i in range(136)
            ],
        )
    lines = by_tag(quote.get())
    assert sum(1 for _ in lines) >= 150
    line = lines['מא"ז בדיקה 7']
    client, headers = quote.api.client, quote.api.as_(quote.tenant)
    for path, body, target in (
        (f"/lines/{line['line_id']}/approve", None, ACTION),
        (f"/lines/{line['line_id']}/qty", {"qty": "3"}, ACTION),
        (f"/lines/{line['line_id']}/alternative", {"index": 0}, RERUN),
    ):
        with within(target, f"{path} on 150 lines"):
            r = client.post(f"/quotes/{quote.quote_id}{path}", json=body, headers=headers)
            assert r.status_code == 200, r.text


def test_the_editor_counts_the_draft_lines_that_now_show_a_new_price(quote: Quote) -> None:
    """S19's backlog: "בטיוטה הפתוחה N שורות מסומנות 'מחיר חדש'" (prototype `saveEditor`)."""
    f1 = by_tag(quote.get())["F1"]
    with quote.session() as s:
        actor = pl.Actor(quote.tenant.tenant_id, quote.tenant.user_id)
        out = pl.update_product(s, actor, f1["product_id"], {"fixed_price": Decimal("140")})
    assert [(u.quote_id, u.fresh) for u in out.used_in_drafts] == [(quote.quote_id, 1)]
    assert by_tag(quote.get())["F1"]["fresh_price"] == "140.00"
