# ruff: noqa: F811  (pytest fixtures imported from other modules)
"""S27b, `catalog_lines` (07 §7.1, 09 §6.4, §7.12, §7.16, §7.17, 13 §4.10), on a NURSERY-1 drawing through the queue
with stages 4–7 rewritten by hand: Q0, F1–F5 and FC1 (S203M 3P 16A, one product), and F13–F14, a 3P 13A breaker no
product has. One line per product, the waiting line with its finding and nearest products, each decision with its undo,
"מוצר חדש" and stage 5 finding it on the next run, a split by designators, and the send refused while a line waits."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from konboro.contracts.merge import AttributeValue, Component, MergeResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import s5_matching, s7_pricing
from konboro.services import flags
from konboro.services.storage import Storage
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider

from .api import Api, ApiTenant, set_tenant_flag
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_review_actions import Quote, events, seeded  # noqa: F401  (fixtures)
from .test_stage6 import rerun as stage_6
from .test_stage7 import priced_tenant, through_the_queue

pytestmark = pytest.mark.integration


def _c(drawing_id: str, panel_id: str, tags: list[str], cls: str, **v: object) -> Component:
    return Component(
        component_id=new_id("cmp"),
        drawing_id=drawing_id,
        panel_id=panel_id,
        family="circuit_breaker",
        symbol_class=cls,
        attributes={k: AttributeValue(value=x, source="drawing", confidence=0.95) for k, x in v.items()},
        explicit_texts=["S203M"] if cls == "mcb" else ["XT1C"],
        quantity=len(tags),
        designators=tags,
        confidence=0.95,
        status="accepted",
    )


@dataclass
class Drawing:
    quote: Quote
    engine: Engine
    storage: Storage
    tenant: ApiTenant
    drawing_id: str

    def stage(self, n: int) -> None:
        with tenant_session(self.tenant.tenant_id, self.engine) as s:
            drawing = s.get_one(m.Drawing, self.drawing_id)
            llm = LLMClient({"anthropic": FakeProvider(fake_llm.answer)})
            key = s.scalar(
                select(m.StageRun.output_key).where(m.StageRun.drawing_id == self.drawing_id, m.StageRun.stage == n)
            )
            assert key is not None
            run = {5: s5_matching.run, 7: s7_pricing.run}[n]
            out = run(StageContext(s, self.storage, drawing, n, llm))
            self.storage.put(self.tenant.tenant_id, key, out.model_dump_json().encode())

    def again(self) -> None:
        """Stages 5–7 again, as a rerun of the drawing would."""
        self.stage(5)
        stage_6(self.engine, self.storage, self.tenant, self.drawing_id, FakeProvider(fake_llm.answer))
        self.stage(7)


@pytest.fixture
def drawing(seeded: dict[str, Engine], api: Api, pipeline: Pipeline, storage: Storage) -> Drawing:
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, "catalog_lines", True)
    set_tenant_flag(engine, tenant.tenant_id, "approval_queue", True)
    flags.cache.clear()
    drawing_id = through_the_queue(api, pipeline, tenant)
    with tenant_session(tenant.tenant_id, engine) as s:
        panel_id = s.scalars(select(m.Panel.id).where(m.Panel.drawing_id == drawing_id)).first()
        assert panel_id is not None
        comps = [
            _c(drawing_id, panel_id, ["Q0"], "mccb", current_a=80, poles=3),
            *(_c(drawing_id, panel_id, [f"F{n}"], "mcb", current_a=16, poles=3, curve="C") for n in range(1, 6)),
            _c(drawing_id, panel_id, ["FC1"], "mcb", current_a=16, poles=3, curve="C"),
            _c(drawing_id, panel_id, ["F13", "F14"], "mcb", current_a=13, poles=3, curve="C"),
        ]
        mine = select(m.Component.id).where(m.Component.drawing_id == drawing_id)
        s.execute(update(m.QuoteLine).where(m.QuoteLine.component_id.in_(mine)).values(component_id=None))
        s.query(m.Component).filter(m.Component.drawing_id == drawing_id).delete()
        for c in comps:
            s.add(
                m.Component(
                    id=c.component_id,
                    tenant_id=tenant.tenant_id,
                    drawing_id=drawing_id,
                    panel_id=panel_id,
                    family=c.family,
                    quantity=c.quantity,
                    designators=c.designators,
                    explicit_texts=c.explicit_texts,
                )
            )
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 4))
        assert key is not None
        merge = MergeResult(drawing_id=drawing_id, components=comps, trace_id="trc_example")
        storage.put(tenant.tenant_id, key, merge.model_dump_json().encode())
        quote_id = s.scalar(select(m.Quote.id).where(m.Quote.drawing_id == drawing_id))
    d = Drawing(Quote(api, tenant, quote_id or ""), engine, storage, tenant, drawing_id)
    d.again()
    if not quote_id:
        with tenant_session(tenant.tenant_id, engine) as s:
            d.quote.quote_id = s.scalar(select(m.Quote.id).where(m.Quote.drawing_id == drawing_id)) or ""
    return d


def lines(body: dict[str, Any]) -> list[dict[str, Any]]:
    body = body.get("quote", body)
    return [ln for p in body["panels"] for ln in p["lines"] if ln["line_type"] in ("component", "missing")]


def qty(ln: dict[str, Any]) -> int:
    return int(Decimal(ln["qty"]))


def line(body: dict[str, Any], tag: str) -> dict[str, Any]:
    return next(ln for ln in lines(body) if tag in ln["designators"])


def test_one_line_per_product_and_a_waiting_line(drawing: Drawing) -> None:
    body = drawing.quote.get()
    f = line(body, "F1")
    assert sorted(f["designators"]) == sorted(["F1", "F2", "F3", "F4", "F5", "FC1"]) and qty(f) == 6
    assert (f["sku"], f["pending"], len(f["component_ids"])) == ("S203M-C16", False, 6)
    assert [ln for ln in lines(body) if "F2" in ln["designators"]] == [f]  # BUG-084: once
    waiting = line(body, "F13")
    assert (waiting["pending"], waiting["status"], waiting["unit_price"], waiting["sku"]) == (True, "red", None, None)
    near = waiting["alternatives"]
    assert 1 <= len(near) <= 3 and all(a["nearest"] for a in near)
    assert near[0]["sku"] in ("S203M-C10", "S203M-C16") and "במקום 13A" in near[0]["diff"]
    finding = next(x for x in body["findings"] if x["code"] == "PRODUCT_NOT_IN_CATALOG")
    assert waiting["line_id"] in finding["line_ids"]


def test_choosing_a_nearest_product_moves_the_line_and_undo_brings_it_back(drawing: Drawing) -> None:
    q = drawing.quote
    waiting = line(q.get(), "F13")
    index = next(i for i, a in enumerate(waiting["alternatives"]) if a["sku"] == "S203M-C16")
    done = q.post(f"/lines/{waiting['line_id']}/alternative", {"index": index})
    f = line(done, "F13")
    assert sorted(f["designators"]) == sorted(["F1", "F2", "F3", "F4", "F5", "FC1", "F13", "F14"])
    assert (qty(f), f["pending"]) == (8, False)
    assert "PRODUCT_NOT_IN_CATALOG" not in [x["code"] for x in done["quote"]["findings"]]
    [event] = events(q, "sku_replaced")
    assert event.after["sku"] == "S203M-C16" and len(event.after["components"]) == 1
    back = q.undo(done)
    again = line(back, "F13")
    assert again["pending"] and again["designators"] == ["F13", "F14"] and qty(line(back, "F1")) == 6
    # what the user chose survives a rerun of the drawing (kept on the version, by component); the line came back
    # under a new id, its key having been gone while its component sat in the merged line
    q.post(f"/lines/{again['line_id']}/alternative", {"index": index})
    drawing.again()
    assert qty(line(q.get(), "F13")) == 8


def test_a_split_by_designators(drawing: Drawing) -> None:
    """09 §7.17: F3 alone to the 20A; the rest stay. Undo puts it back."""
    q = drawing.quote
    f = line(q.get(), "F3")
    found = q.api.client.get(f"/quotes/{q.quote_id}/products?q=S203M-C20", headers=q.api.as_(q.tenant)).json()
    ref = next(c["ref"] for c in found if c["sku"] == "S203M-C20")
    done = q.post(f"/lines/{f['line_id']}/resolve", {"ref": ref, "designators": ["F3"]})
    moved, rest = line(done, "F3"), line(done, "F1")
    assert (moved["sku"], moved["designators"], moved["approved"]) == ("S203M-C20", ["F3"], True)
    assert (qty(rest), "F3" in rest["designators"]) == (5, False)
    back = q.undo(done)
    assert line(back, "F3")["line_id"] == line(back, "F1")["line_id"] and qty(line(back, "F1")) == 6
    q.post(f"/lines/{f['line_id']}/resolve", {"ref": ref, "designators": ["X9"]}, status=422)


def test_a_new_product_in_the_apps_format_and_stage_5_finds_it_next_time(drawing: Drawing) -> None:
    q = drawing.quote
    waiting = line(q.get(), "F13")
    path = f"/quotes/{q.quote_id}/lines/{waiting['line_id']}/new-product"
    form = q.api.client.get(path, headers=q.api.as_(q.tenant)).json()
    assert form["family"] == "circuit_breaker"
    read = {a["name"]: a for a in form["attributes"]}
    assert read["current_a"]["value"] == "13" and read["current_a"]["required"] and read["poles"]["value"] == "3"
    body = {
        "attributes": {"current_a": "13", "poles": "3", "curve": "C", "breaking_capacity_ka": "10"},
        "brand": "ABB",
        "model_code": "S203M",
        "series": "S200M",
        "sku": "S203M-C13",
    }
    q.post(f"/lines/{waiting['line_id']}/new-product", {**body, "attributes": {"poles": "3"}}, status=422)
    done = q.post(f"/lines/{waiting['line_id']}/new-product", body)
    made = line(done, "F13")
    assert made["description"] == 'מפסק זרם אוטומטי (מא"ז) ABB S203M 3P 13A עקומה C 10kA'
    assert (made["pending"], made["approved"], made["product_id"] is not None) == (False, True, True)
    with q.session() as s:
        product = s.get_one(m.Product, made["product_id"])
        assert product.attributes["current_a"] == 13 and product.model_code == "S203M"
        assert product.display_name == made["description"]
        candidate = s.scalars(select(m.KnowledgeCandidate).where(m.KnowledgeCandidate.kind == "catalog_item")).one()
        assert candidate.payload["attributes"]["current_a"] == 13 and "price" not in str(candidate.payload)
    # undo: the line waits again, and the product goes, no other quote using it
    back = q.undo(done)
    assert line(back, "F13")["pending"]
    with q.session() as s:
        assert s.get(m.Product, made["product_id"]) is None
    # made again; with the choice forgotten, stage 5 alone finds it on the next run (05 §5.6)
    again = q.post(f"/lines/{line(back, 'F13')['line_id']}/new-product", body)
    product_id = line(again, "F13")["product_id"]
    with q.session() as s:
        version = s.scalars(select(m.QuoteVersion).where(m.QuoteVersion.quote_id == q.quote_id)).one()
        version.component_edits = {}
    drawing.again()
    found = line(q.get(), "F13")
    assert (found["pending"], found["product_id"], found["sku"]) == (False, product_id, "S203M-C13")


def test_a_waiting_line_blocks_the_send_and_takes_no_price(drawing: Drawing) -> None:
    q = drawing.quote
    waiting = line(q.get(), "F13")
    q.post(f"/lines/{waiting['line_id']}/price-entry", {"unit_price": "50", "save": False}, status=409)
    q.post(f"/lines/{waiting['line_id']}/approve", status=409)
    r = q.post("/send", status=409)
    assert r["error"]["code"] == "pending_lines"
    q.delete(waiting["line_id"])  # "אין כאן רכיב"
    q.post("/send")


def test_with_the_flag_off_the_lines_are_as_before(drawing: Drawing) -> None:
    set_tenant_flag(drawing.engine, drawing.tenant.tenant_id, "catalog_lines", False)
    flags.cache.clear()
    drawing.again()
    body = drawing.quote.get()
    assert line(body, "F1")["designators"] == ["F1"] and qty(line(body, "F1")) == 1
    assert not any(ln["pending"] for ln in lines(body))
    assert "PRODUCT_NOT_IN_CATALOG" not in [x["code"] for x in body["findings"]]
    r = drawing.quote.api.client.get(
        f"/quotes/{drawing.quote.quote_id}/lines/{line(body, 'F13')['line_id']}/new-product",
        headers=drawing.quote.api.as_(drawing.quote.tenant),
    )
    assert r.status_code == 404
