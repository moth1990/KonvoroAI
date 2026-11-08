# ruff: noqa: F811  (pytest fixtures imported from other modules)
"""The review screen's product picker (S23b, 09 §6.4, §6.6, §7.4, §7.8, §7.13) on the NURSERY-1 fixture: the search,
an attribute set by hand and stage 5 again in code, a missing line resolved, a component marked on the drawing with its
detector example, and the brand discount from a row; each with its correction event and its undo. A missing line's
candidates on a quote the pipeline priced: `test_missing_candidates_on_a_pipeline_quote`."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select

from konboro.contracts.merge import AttributeValue, MergeResult, MissingInstance
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import seed_nursery_pages
from konboro.pipeline.context import StageContext
from konboro.pipeline.stages import s7_pricing
from konboro.services import quotes as qs
from konboro.services.storage import Storage

from ..perf import RERUN, within
from .api import Api, add_tenant
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_review_actions import Quote, by_tag, events, quote, seeded  # noqa: F401  (fixtures)
from .test_stage7 import priced_tenant, stages_5_to_7_by_hand, through_the_queue

pytestmark = pytest.mark.integration


def get(q: Quote, path: str, status: int = 200) -> Any:
    r = q.api.client.get(f"/quotes/{q.quote_id}{path}", headers=q.api.as_(q.tenant))
    assert r.status_code == status, r.text
    return r.json()


def timed(q: Quote, path: str, body: dict[str, Any]) -> dict[str, Any]:
    with within(RERUN, path):  # 09 §14: stages 5–7 for the line ≤ 1 s
        done = q.post(path, body)
    return done


# --- the search (09 §6.6 step 3) ------------------------------------------------------------------------------------


def test_the_picker_finds_catalog_items_and_products_priced_first(quote: Quote) -> None:
    found = get(quote, "/products?q=S203M 20")
    assert found and all("S203M" in (c["sku"] or "") or "S203M" in c["description"] for c in found)
    c20 = next(c for c in found if c["sku"] == "S203M-C20")
    assert c20["ref"].startswith("cat:") and c20["unit_price"] is None  # no product for it in the price list
    priced = [c for c in found if c["unit_price"] is not None]
    assert found[: len(priced)] == priced  # S23b decision 2
    assert all(set(c) == {"ref", "description", "sku", "manufacturer", "family", "unit_price"} for c in found)
    by_family = get(quote, "/products?family=circuit_breaker")
    assert by_family and all(c["family"] == "circuit_breaker" for c in by_family)
    assert get(quote, "/products?q=nothing-like-this") == []


def test_another_tenants_product_is_not_offered(quote: Quote, api: Api, seeded: dict[str, Engine]) -> None:
    other = add_tenant(seeded["app"])
    with tenant_session(other.tenant_id, api.engine) as s:
        s.add(
            m.Product(
                id=new_id("prd"),
                tenant_id=other.tenant_id,
                display_name="מוצר של מפעל אחר",
                family="other",
                source="manual_entry",
            )
        )
    assert get(quote, "/products?q=מפעל אחר") == []


# --- an attribute (09 §7.4) -----------------------------------------------------------------------------------------


@pytest.mark.perf
def test_a_current_set_by_hand_matches_the_line_again_and_undo_puts_it_back(quote: Quote) -> None:
    f18 = by_tag(quote.get())["F18"]
    assert f18["attribute_options"]["current_a"][:3] == ["6", "10", "16"]
    assert next(x for x in f18["sources"] if x["attribute"] == "current_a")["value"] == "20A"
    done = timed(quote, f"/lines/{f18['line_id']}/attribute", {"attribute": "current_a", "value": "16"})
    line = by_tag(done)["F18"]
    assert line["sku"] == "S203M-C16" and line["unit_price"] is not None  # the demo price list has the 16A
    src = next(x for x in line["sources"] if x["attribute"] == "current_a")
    assert (src["value"], src["source"]) == ("16", "user")
    [event] = events(quote, "attribute_changed")
    assert event.before["current_a"] == 20 and event.after == {
        "current_a": 16,
        "source": "user",
        "sku": "S203M-C16",
        "description": line["description"],
    }
    back = by_tag(quote.undo(done))["F18"]
    assert back["sku"] == "S203M-C20" and back["unit_price"] is None
    assert next(x for x in back["sources"] if x["attribute"] == "current_a")["source"] == "drawing"


def test_a_value_the_catalog_lacks_turns_the_line_red(quote: Quote) -> None:
    f18 = by_tag(quote.get())["F18"]
    done = quote.post(f"/lines/{f18['line_id']}/attribute", {"attribute": "current_a", "value": "37"})
    line = by_tag(done)["F18"]
    assert done["message"] == "אין בקטלוג מוצר עם הערכים האלה"
    assert line["status"] == "red" and line["sku"] is None
    assert {"source": "match", "value": "not_in_catalog"}.items() <= line["status_reasons"][0].items()


def test_attribute_refusals(quote: Quote) -> None:
    lines = by_tag(quote.get())
    kit = lines["ערכה: מודול פחת למפסק"]
    r = quote.post(f"/lines/{kit['line_id']}/attribute", {"attribute": "current_a", "value": "16"}, status=422)
    assert r["error"]["details"][0]["type"] == "not_editable"
    f18 = lines["F18"]
    for value in ("0", "-3", "9000", "16.25"):
        quote.post(f"/lines/{f18['line_id']}/attribute", {"attribute": "current_a", "value": value}, status=422)
    quote.post(f"/lines/{f18['line_id']}/attribute", {"attribute": "poles", "value": "3"}, status=422)


# --- a missing line (09 §7.8) ---------------------------------------------------------------------------------------


def _missing_line(q: Quote) -> str:
    with q.session() as s:
        version = s.scalar(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == q.quote_id))
        assert version is not None
        page = s.scalar(select(m.Page.id).where(m.Page.page_no == 7, m.Page.tenant_id == q.tenant.tenant_id))
        [line_id] = qs.write_lines(
            s,
            version,
            None,
            [
                qs.LineIn(
                    key="m:ins_x",
                    line_key="m:ins_x",
                    description='רכיב שלא זוהה (נראה כמו מא"ז 3P 20A)',
                    qty=Decimal(1),
                    status="red",
                    line_type="missing",
                    status_reasons=[{"source": "missing", "value": "C20", "status": "red"}],
                    boxes=[{"page_id": page, "bbox": [100.0, 100.0, 130.0, 160.0]}],
                )
            ],
        ).values()
    return line_id


def test_a_missing_line_resolved_by_a_product_is_an_approved_component_line(quote: Quote) -> None:
    line_id = _missing_line(quote)
    assert get(quote, f"/lines/{line_id}/candidates") == []  # no stage outputs: the search only
    body = quote.get()
    missing = next(ln for p in body["panels"] for ln in p["lines"] if ln["line_id"] == line_id)
    assert missing["boxes"][0]["bbox"] == [100.0, 100.0, 130.0, 160.0]
    ref = next(c["ref"] for c in get(quote, "/products?q=S203M-C16") if c["sku"] == "S203M-C16")
    done = quote.post(f"/lines/{line_id}/resolve", {"ref": ref})
    line = next(ln for p in done["quote"]["panels"] for ln in p["lines"] if ln["line_id"] == line_id)
    assert line["line_type"] == "component" and line["approved"] and line["sku"] == "S203M-C16"
    assert line["unit_price"] is not None and line["status"] == "green"
    [event] = events(quote, "missing_resolved")
    assert event.after["positive_example"] and event.after["sku"] == "S203M-C16"
    back = quote.undo(done)
    line = next(ln for p in back["quote"]["panels"] for ln in p["lines"] if ln["line_id"] == line_id)
    assert line["line_type"] == "missing" and not line["approved"]


def test_no_component_here_deletes_the_missing_line_as_a_negative_example(quote: Quote) -> None:
    line_id = _missing_line(quote)
    done = quote.delete(line_id)
    assert done["message"] == "השורה נמחקה: אין כאן רכיב"
    [event] = events(quote, "row_deleted")
    assert event.before["negative_example"] and event.before["line_type"] == "missing"


def test_resolve_refusals(quote: Quote) -> None:
    f18 = by_tag(quote.get())["F18"]
    r = quote.post(f"/lines/{f18['line_id']}/resolve", {"ref": "cat:none"}, status=422)
    assert r["error"]["details"][0]["type"] == "not_missing"
    line_id = _missing_line(quote)
    r = quote.post(f"/lines/{line_id}/resolve", {"ref": "cat:cat_nothing"}, status=422)
    assert r["error"]["details"][0]["type"] == "unknown_product"
    quote.post(f"/lines/{line_id}/resolve", {"ref": "nope"}, status=422)


@pytest.mark.perf
def test_missing_candidates_on_a_pipeline_quote(
    seeded: dict[str, Engine],
    api: Api,
    pipeline: Any,
    storage: Storage,
) -> None:
    """Stage 4 left a breaker it could not place (C20 beside a symbol the detection missed): up to three products by
    what was read, from stage 5's code, the factory's preferred brand first."""
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    drawing_id = through_the_queue(api, pipeline, tenant)
    quote_id = stages_5_to_7_by_hand(engine, storage, tenant, drawing_id).quote_id
    with tenant_session(tenant.tenant_id, engine) as s:
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 4))
        assert key is not None
        merge = MergeResult.model_validate_json(storage.get(tenant.tenant_id, key))
        panel = merge.components[0].panel_id
        page = s.scalar(select(m.Page.id).where(m.Page.drawing_id == drawing_id).order_by(m.Page.page_no))
        assert page is not None
        missing = MissingInstance(
            instance_id=new_id("ins"),
            page_id=page,
            panel_id=panel,
            bbox=(100.0, 100.0, 130.0, 160.0),
            family="circuit_breaker",
            attributes={
                "current_a": AttributeValue(value=20, source="drawing", confidence=0.9),
                "poles": AttributeValue(value=3, source="drawing", confidence=0.9),
                "curve": AttributeValue(value="C", source="drawing", confidence=0.9),
            },
            origin="C20",
            confidence=0.6,
        )
        storage.put(tenant.tenant_id, key, merge.model_copy(update={"missing": [missing]}).model_dump_json().encode())
        drawing = s.get_one(m.Drawing, drawing_id)
        s7_pricing.run(StageContext(s, storage, drawing, 7, None))  # type: ignore[arg-type]  # stage 7 calls no model
    q = Quote(api, tenant, quote_id)
    body = q.get()
    line = next(ln for p in body["panels"] for ln in p["lines"] if ln["line_type"] == "missing")
    assert line["boxes"] == [{"page_id": page, "bbox": [100.0, 100.0, 130.0, 160.0]}]
    with within(RERUN, "a missing line's candidates"):  # 09 §14: stage 5 for the line ≤ 1 s
        found = get(q, f"/lines/{line['line_id']}/candidates")
    assert 1 <= len(found) <= 3 and found[0]["sku"] == "S203M-C20"
    done = q.post(f"/lines/{line['line_id']}/resolve", {"ref": found[0]["ref"]})
    resolved = next(ln for p in done["quote"]["panels"] for ln in p["lines"] if ln["line_id"] == line["line_id"])
    assert resolved["line_type"] == "component" and resolved["approved"] and resolved["sku"] == "S203M-C20"
    # a rerun keeps it (S22 decision 5)
    with tenant_session(tenant.tenant_id, engine) as s:
        s7_pricing.run(StageContext(s, storage, s.get_one(m.Drawing, drawing_id), 7, None))  # type: ignore[arg-type]
    again = next(ln for p in q.get()["panels"] for ln in p["lines"] if ln["line_id"] == line["line_id"])
    assert again["line_type"] == "component" and again["sku"] == "S203M-C20" and again["approved"]


# --- a missed component (09 §6.6) -----------------------------------------------------------------------------------


def _page(q: Quote, storage: Storage, n: int = 7) -> m.Page:
    with q.session() as s:
        seed_nursery_pages(s, storage, q.tenant.tenant_id)
        page = s.scalar(select(m.Page).where(m.Page.page_no == n, m.Page.tenant_id == q.tenant.tenant_id))
        assert page is not None
        s.expunge(page)
    return page


@pytest.mark.perf
def test_a_marked_component_is_a_manual_line_with_its_box_and_a_detector_example(
    quote: Quote, storage: Storage
) -> None:
    page = _page(quote, storage)
    ref = next(c["ref"] for c in get(quote, "/products?q=S203M-C16") if c["sku"] == "S203M-C16")
    box = [200.0, 150.0, 240.0, 210.0]
    done = timed(quote, "/marks", {"page_id": page.id, "bbox": box, "ref": ref})
    manual = [ln for p in done["quote"]["panels"] for ln in p["lines"] if ln["line_type"] == "manual"]
    assert len(manual) == 1
    line = manual[0]
    assert line["boxes"] == [{"page_id": page.id, "bbox": box}] and line["sku"] == "S203M-C16"
    assert line["unit_price"] is not None and line["status"] == "green"
    assert {"source": "user", "value": "manual"}.items() <= line["status_reasons"][0].items()
    [event] = events(quote, "component_marked")
    assert event.after["symbol_class"] == "mcb" and event.after["bbox"] == box
    with quote.session() as s:
        crop = s.get_one(m.TenantReferenceCrop, event.after["crop_id"])
        assert crop.scope == "drawing" and crop.source == "user_correction" and crop.symbol_class == "mcb"
        image_key = crop.image_key
    assert image_key.startswith(f"tenants/{quote.tenant.tenant_id}/")
    assert storage.get(quote.tenant.tenant_id, image_key)[:8] == b"\x89PNG\r\n\x1a\n"
    back = quote.undo(done)
    assert not [ln for p in back["quote"]["panels"] for ln in p["lines"] if ln["line_type"] == "manual"]
    with quote.session() as s:
        assert s.get(m.TenantReferenceCrop, event.after["crop_id"]) is None
    assert not storage.exists(quote.tenant.tenant_id, image_key)


def test_mark_refusals(quote: Quote, storage: Storage) -> None:
    page = _page(quote, storage)
    ref = get(quote, "/products?q=S203M-C16")[0]["ref"]
    small = quote.post("/marks", {"page_id": page.id, "bbox": [10, 10, 15, 40], "ref": ref}, status=422)
    assert small["error"]["details"][0]["type"] == "too_small"
    out = quote.post("/marks", {"page_id": page.id, "bbox": [10, 10, 99999, 40], "ref": ref}, status=422)
    assert out["error"]["details"][0]["type"] == "outside_page"
    skipped = _page(quote, storage, 1)
    if skipped.route != "process":
        r = quote.post("/marks", {"page_id": skipped.id, "bbox": [10, 10, 40, 40], "ref": ref}, status=422)
        assert r["error"]["details"][0]["type"] == "not_parsed"
    quote.post("/marks", {"page_id": "pg_00000000000000000000000000", "bbox": [10, 10, 40, 40], "ref": ref}, 404)


def test_the_panel_is_the_one_whose_area_holds_the_centre() -> None:
    from konboro.services.review_picker import panel_at

    a = m.Panel(id="pnl_a", page_ids=["pg_1"], bboxes={"pg_1": [[0, 0, 100, 100]]})
    b = m.Panel(id="pnl_b", page_ids=["pg_1"], bboxes={"pg_1": [[100, 0, 200, 100]]})
    c = m.Panel(id="pnl_c", page_ids=["pg_2"], bboxes={})
    assert panel_at([a, b, c], "pg_1", [120, 10, 160, 50], None) == "pnl_b"
    assert panel_at([a, b, c], "pg_1", [90, 10, 140, 50], None) == "pnl_b"  # the centre, 115, is in b
    assert panel_at([a, b, c], "pg_2", [10, 10, 40, 40], "pnl_a") == "pnl_a"  # no areas: the active panel
    assert panel_at([a, b, c], "pg_2", [10, 10, 40, 40], None) == "pnl_c"  # the page's only panel


# --- a brand discount from a row (09 §7.13) -------------------------------------------------------------------------


@pytest.mark.perf
def test_a_brand_discount_from_a_row_prices_the_brands_unpriced_lines(quote: Quote) -> None:
    f18 = by_tag(quote.get())["F18"]
    assert f18["list_price_brand"] == "ABB" and f18["unit_price"] is None
    assert by_tag(quote.get())["F1"]["list_price_brand"] is None  # priced already
    done = timed(quote, f"/lines/{f18['line_id']}/brand-discount", {"discount_pct": "0.30"})
    line = by_tag(done)["F18"]
    # 215 × 0.70 = 150.50 cost, the 25% markup: 188.13 (07 §7.2 priority 2, §7.3)
    assert line["price_status"] == "discount_based" and line["status"] == "yellow"
    assert line["unit_cost"] == "150.5000" and line["unit_price"] == "188.1300"
    assert done["message"].endswith("מחירון ABB פחות 30%")
    assert by_tag(done)["F1"]["unit_price"] == by_tag(quote.get())["F1"]["unit_price"]  # its own price stays
    with quote.session() as s:
        assert s.get_one(m.BrandDiscount, (quote.tenant.tenant_id, "ABB")).discount_pct == Decimal("0.3000")
    [event] = events(quote, "brand_discount_set")
    assert event.after["discount_pct"] == "0.30" and f18["line_id"] in event.after["line_ids"]
    back = by_tag(quote.undo(done))["F18"]
    assert back["unit_price"] is None
    with quote.session() as s:
        assert s.get(m.BrandDiscount, (quote.tenant.tenant_id, "ABB")) is None


def test_a_line_with_no_list_price_has_no_bulk_entry(quote: Quote) -> None:
    lines = by_tag(quote.get())
    q0 = next(ln for ln in lines.values() if ln["unit_price"] is None and not ln["list_price_brand"])
    r = quote.post(f"/lines/{q0['line_id']}/brand-discount", {"discount_pct": "0.3"}, status=422)
    assert r["error"]["details"][0]["type"] == "no_list_price"


# --- a sent version, another tenant ---------------------------------------------------------------------------------


def test_a_sent_version_refuses_the_picker_and_another_tenant_sees_nothing(
    quote: Quote,
    api: Api,
    seeded: dict[str, Engine],
    storage: Storage,
) -> None:
    page = _page(quote, storage)
    f18 = by_tag(quote.get())["F18"]
    other = add_tenant(seeded["app"])
    r = api.client.get(f"/quotes/{quote.quote_id}/products?q=S203M", headers=api.as_(other))
    assert r.status_code == 404
    r = api.client.post(
        f"/quotes/{quote.quote_id}/lines/{f18['line_id']}/attribute",
        json={"attribute": "current_a", "value": "16"},
        headers=api.as_(other),
    )
    assert r.status_code == 404
    quote.post("/send")
    assert get(quote, "/products?q=S203M", status=409)["error"]["code"] == "quote_sent"
    quote.post(f"/lines/{f18['line_id']}/attribute", {"attribute": "current_a", "value": "16"}, status=409)
    quote.post(f"/lines/{f18['line_id']}/brand-discount", {"discount_pct": "0.3"}, status=409)
    quote.post("/marks", {"page_id": page.id, "bbox": [10, 10, 40, 40], "ref": "cat:x"}, status=409)
    assert by_tag(quote.get())["F18"]["attribute_options"] == {}  # a sent version offers no edit
