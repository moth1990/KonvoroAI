"""Review actions on a quote the pipeline priced (09 §7, S23): stage 7 runs again with its derived items, every line
keeps its id, a line the action did not touch keeps its price (07 §7.2.3), and a rerun keeps the estimator's edits
(S22 decision 5)."""

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.pipeline.coordinator import Pipeline
from konboro.services import quote_versions as qv
from konboro.services.storage import Storage

from ..perf import RERUN, within
from .api import Api, ApiTenant, set_tenant_flag
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage7 import priced_tenant, seeded, stages_5_to_7_by_hand, through_the_queue  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration


def get(api: Api, tenant: ApiTenant, quote_id: str) -> dict[str, Any]:
    r = api.client.get(f"/quotes/{quote_id}", headers=api.as_(tenant))
    assert r.status_code == 200, r.text
    return dict(r.json())


def post(api: Api, tenant: ApiTenant, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    with within(RERUN, path):  # 09 §14: ≤ 500 ms for most, ≤ 1 s with stages 5–7; every action here gets the 1 s
        r = api.client.post(path, json=body, headers=api.as_(tenant))
        assert r.status_code == 200, r.text
    return dict(r.json())


def lines(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [ln for p in body.get("quote", body)["panels"] for ln in p["lines"]]


@pytest.mark.perf
def test_actions_on_a_drawing_the_pipeline_priced(
    seeded: dict[str, Engine],  # noqa: F811
    api: Api,
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    drawing_id = through_the_queue(api, pipeline, tenant)
    quote_id = stages_5_to_7_by_hand(engine, storage, tenant, drawing_id).quote_id
    base = f"/quotes/{quote_id}"
    body = get(api, tenant, quote_id)
    before = {ln["line_id"]: ln for ln in lines(body)}
    priced = next(
        ln for ln in lines(body) if ln["unit_price"] and ln["qty_editable"] and ln["line_type"] == "component"
    )
    derived = next(ln for ln in lines(body) if ln["line_type"] == "derived")

    # approve: green, every line keeps its id and its price
    done = post(api, tenant, f"{base}/lines/{priced['line_id']}/approve")
    after = {ln["line_id"]: ln for ln in lines(done)}
    assert set(after) == set(before)
    assert after[priced["line_id"]]["approved"] and after[priced["line_id"]]["status"] == "green"
    assert all(after[i]["unit_price"] == ln["unit_price"] for i, ln in before.items())

    # a price-list change since: the draft does not follow it by itself (07 §7.2.3); the line shows the new price
    with tenant_session(tenant.tenant_id, engine) as s:
        s.execute(
            update(m.Product).where(m.Product.id == priced["product_id"]).values(fixed_price=999, sale_mode="fixed")
        )
    body = get(api, tenant, quote_id)
    line = next(ln for ln in lines(body) if ln["line_id"] == priced["line_id"])
    assert line["unit_price"] == priced["unit_price"] and line["fresh_price"] == "999.00"

    # quantity: the rules run again, the derived items follow the edit, the other prices stay
    qty = int(float(priced["qty"])) + 1
    done = post(api, tenant, f"{base}/lines/{priced['line_id']}/qty", {"qty": str(qty)})
    line = next(ln for ln in lines(done) if ln["line_id"] == priced["line_id"])
    assert float(line["qty"]) == qty and line["unit_price"] == priced["unit_price"] and line["approved"]
    qty_event = done["event_id"]

    # a derived line removed, then brought back with "החזר"
    r = api.client.delete(f"{base}/lines/{derived['line_id']}", headers=api.as_(tenant))
    assert r.status_code == 200, r.text
    removed = [x for p in r.json()["quote"]["panels"] for x in p["removed"]]
    assert [x["line_id"] for x in removed] == [derived["line_id"]]
    assert derived["line_id"] not in {ln["line_id"] for ln in lines(r.json())}
    with tenant_session(tenant.tenant_id, engine) as s:  # a recalculation does not make it again (07 §7.4)
        qv.recalculate_draft(s, storage, tenant.tenant_id, quote_id, apply=True)
    assert derived["line_id"] not in {ln["line_id"] for ln in lines(get(api, tenant, quote_id))}
    done = post(api, tenant, f"{base}/lines/restore", {"line_ids": [derived["line_id"]]})
    assert derived["line_id"] in {ln["line_id"] for ln in lines(done)}
    assert not [x for p in done["quote"]["panels"] for x in p["removed"]]

    # undo the quantity: back as it was
    done = post(api, tenant, f"{base}/undo/{qty_event}")
    line = next(ln for ln in lines(done) if ln["line_id"] == priced["line_id"])
    assert line["qty"] == priced["qty"]

    # an alternative: on every line with the same signature (F1–F5 and FC1 share S203M-C16), each approved
    f16 = [ln for ln in lines(done) if ln["sku"] == "S203M-C16" and ln["line_type"] == "component"]
    with_alt = next(ln for ln in f16 if any(a.get("sku") for a in ln["alternatives"]))
    index = next(i for i, a in enumerate(with_alt["alternatives"]) if a.get("sku"))
    sku = with_alt["alternatives"][index]["sku"]
    done = post(api, tenant, f"{base}/lines/{with_alt['line_id']}/alternative", {"index": index})
    swapped = [ln for ln in lines(done) if ln["line_id"] in {x["line_id"] for x in f16}]
    assert done["count"] == len(f16) and all(ln["sku"] == sku and ln["approved"] for ln in swapped)
    with tenant_session(tenant.tenant_id, engine) as s:
        events = list(s.scalars(select(m.CorrectionEvent).where(m.CorrectionEvent.type == "sku_replaced")))
        assert len(events) == len(f16)
    done = post(api, tenant, f"{base}/undo/{done['event_id']}")
    assert all(ln["sku"] == "S203M-C16" for ln in lines(done) if ln["line_id"] in {x["line_id"] for x in f16})
    with tenant_session(tenant.tenant_id, engine) as s:
        assert all(
            e.undone for e in s.scalars(select(m.CorrectionEvent).where(m.CorrectionEvent.type == "sku_replaced"))
        )

    # a rerun of stage 7 keeps the approval (S22 decision 5)
    with tenant_session(tenant.tenant_id, engine) as s:
        qv.recalculate(s, storage, tenant.tenant_id, quote_id)
        row = s.get_one(m.QuoteLine, priced["line_id"])
        assert row.approved_at is not None


@pytest.mark.perf
def test_the_unresolved_layer_reads_the_pipelines_outputs(
    seeded: dict[str, Engine],  # noqa: F811
    api: Api,
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    """13 §4.4 (S26) on a drawing the pipeline read with the stand-in model, from stages 3–5's outputs in S3: every
    spot is on one of its pages, a partial one points at a live line, and approving those lines empties that kind."""
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, "unresolved_overlay", True)
    drawing_id = through_the_queue(api, pipeline, tenant)  # all 7 stages on the stand-in model's answers
    with tenant_session(tenant.tenant_id, engine) as s:
        quote_id = s.scalar(select(m.Quote.id).where(m.Quote.drawing_id == drawing_id))
    assert quote_id is not None
    body = get(api, tenant, quote_id)
    pages = {p["page_id"] for p in body["pages"]}
    live = {ln["line_id"] for ln in lines(body)}

    r = api.client.get(f"/quotes/{quote_id}/unresolved", headers=api.as_(tenant))
    assert r.status_code == 200, r.text
    spots = r.json()["spots"]
    assert spots, "the stand-in model leaves lines it can't identify"
    assert {s["page_id"] for s in spots} <= pages
    assert {s["kind"] for s in spots} <= {"unknown_symbol", "orphan_text", "partial", "front_only"}
    partial = {s["line_id"] for s in spots if s["kind"] == "partial"}
    assert partial and partial <= live

    for line_id in partial:
        post(api, tenant, f"/quotes/{quote_id}/lines/{line_id}/approve")
    r = api.client.get(f"/quotes/{quote_id}/unresolved", headers=api.as_(tenant))
    assert not [s for s in r.json()["spots"] if s["kind"] == "partial"]
