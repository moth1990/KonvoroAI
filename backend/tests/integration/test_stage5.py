"""Stage 5 on the local services (05): the drawing goes through the queue to stage 7; then stage 5 runs again on a
hand-made stage-4 output (the stand-in model's breakers carry no values) against the sample catalog. The matches go to
S3 and each component row keeps its status and item; the factory's price list, memory and customer are its own (RLS);
the agent's calls are logged, and it never sees a price, a cost or the customer. The model is the stand-in."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import AttributeValue, Component, MergeResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import s5_matching
from konboro.pipeline.worker import Worker
from konboro.services.llm import usage_recorder
from konboro.services.storage import Storage
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.catalog_disambiguation import STAGE as CATALOG

from .api import Api, ApiTenant, add_tenant
from .test_api_drawings import progress
from .test_api_upload import upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the symbol library, the attribute schemas and the sample catalog (S20 decision 1)
    return migrated_db


def _value(v: object) -> AttributeValue:
    return AttributeValue(value=v, source="drawing", confidence=0.95)


def components(drawing_id: str, panel_id: str) -> list[Component]:
    def c(cid: str, family: str, cls: str, attrs: dict[str, object], texts: list[str], des: list[str]) -> Component:
        return Component(
            component_id=cid,
            drawing_id=drawing_id,
            panel_id=panel_id,
            family=family,
            symbol_class=cls,
            attributes={k: _value(v) for k, v in attrs.items()},
            explicit_texts=texts,
            quantity=len(des) or 1,
            designators=des,
            confidence=0.95,
            status="accepted",
        )

    return [
        c(new_id("cmp"), "circuit_breaker", "mcb", {"current_a": 16, "poles": 3}, ["S203M", "3×16A"], ["F1"]),
        c(new_id("cmp"), "circuit_breaker", "mcb", {"current_a": 16, "poles": 3}, ["S203M", "3×16A"], ["F2"]),
        c(new_id("cmp"), "circuit_breaker", "mcb", {"current_a": 6, "poles": 3}, ["S204M", "3×6A"], ["FNV"]),
        c(new_id("cmp"), "push_button", "push_button", {}, ["EMS"], ["EMS"]),
        c(new_id("cmp"), "terminal", "terminal", {}, [], ["X1"]),
    ]


def stage_4_by_hand(engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str) -> list[Component]:
    """Replaces the stand-in's stage-4 output and its rows with components that carry values. The factory's default
    curve is C (05 §5.5), as most factories' is."""
    with tenant_session(tenant.tenant_id, engine) as s:
        settings = s.get_one(m.TenantSettings, tenant.tenant_id)
        settings.attribute_defaults = {"circuit_breaker": {"curve": "C"}}
        panel_id = s.scalars(select(m.Panel.id).where(m.Panel.drawing_id == drawing_id)).first()
        assert panel_id is not None
        comps = components(drawing_id, panel_id)
        mine = select(m.Component.id).where(m.Component.drawing_id == drawing_id)
        # stage 7's draft lines point at the components; they let go first, as stage 4's rewrite does (S22)
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
        out = MergeResult(drawing_id=drawing_id, components=comps, trace_id="trc_example")
        storage.put(tenant.tenant_id, key, out.model_dump_json().encode())
    return comps


def price(engine: Engine, tenant: ApiTenant, sku: str, cost: str) -> None:
    """A product of the tenant's price list linked to the catalog item, with a supplier cost (07 §7.2.2)."""
    with tenant_session(tenant.tenant_id, engine) as s:
        item = s.scalar(select(m.CatalogItem.id).where(m.CatalogItem.sku == sku))
        prd = m.Product(
            id=new_id("prd"),
            tenant_id=tenant.tenant_id,
            catalog_item_id=item,
            display_name=sku,
            manufacturer_sku=sku,
            brand="ABB",
            family="circuit_breaker",
            sale_mode="rule",
            source="manual_entry",
        )
        s.add(prd)
        s.flush()
        s.add(
            m.ProductSupplier(
                id=new_id("psp"),
                tenant_id=tenant.tenant_id,
                product_id=prd.id,
                unit_cost=Decimal(cost),
                price_date=date(2026, 10, 1),
            )
        )


def rerun(
    engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str, provider: FakeProvider
) -> MatchingResult:
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        llm = LLMClient({"anthropic": provider}, on_call=usage_recorder(engine, tenant.tenant_id, drawing_id))
        return s5_matching.run(StageContext(s, storage, drawing, 5, llm))


def test_stage_5_matches_against_the_catalog_under_the_tenant(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], customer="לקוח סודי", project="פרויקט")
    drawing_id = str(response.json()["drawing_id"])
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:  # the stand-in's breakers: no values, red, but no failure
        run5 = s.scalar(select(m.StageRun).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 5))
        assert run5 is not None and run5.status == "done"
        assert (
            s.scalar(select(m.StageRun.status).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 7))
            == "done"
        )
        assert set(s.scalars(select(m.Component.match_status).where(m.Component.drawing_id == drawing_id))) == {
            "unmatched"
        }

    comps = stage_4_by_hand(engine, storage, tenant, drawing_id)
    price(engine, tenant, "S203M-C16", "138.00")
    provider = FakeProvider(fake_llm.answer)
    out = rerun(engine, storage, tenant, drawing_id, provider)

    by_id = {mm.component_id: mm for mm in out.matches}
    f1, f2, fnv, ems = (by_id[c.component_id] for c in comps[:4])
    assert (f1.method, f1.chosen_sku, f1.has_cost_price) == ("explicit_series", "S203M-C16", True)
    assert f2.chosen_sku == f1.chosen_sku  # 100% consistency (05 §10)
    assert (fnv.status, fnv.chosen_sku) == ("conflict", None)
    assert ems.method == "llm" and ems.chosen_sku is not None  # the stand-in picks the first candidate
    assert out.auxiliary == [comps[4].component_id] and out.stats.llm_signatures == 1
    assert out.stats.signatures == 3  # F1 and F2 once
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = {r.id: r for r in s.scalars(select(m.Component).where(m.Component.drawing_id == drawing_id))}
        assert rows[comps[0].component_id].match_status == "matched"
        item = s.get_one(m.CatalogItem, rows[comps[0].component_id].catalog_item_id)
        assert item.sku == "S203M-C16"
        assert rows[comps[2].component_id].match_status == "conflict"
        assert rows[comps[4].component_id].match_status == "auxiliary"
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == CATALOG).limit(1)) is not None
    with tenant_session(other.tenant_id, engine) as s:  # RLS
        assert s.scalar(select(m.LlmCall.id).where(m.LlmCall.stage == CATALOG)) is None

    # the agent saw no price, no cost and no customer (05 §12, non-negotiable 6)
    asked = [r for r in provider.requests if r.stage == CATALOG]
    assert len(asked) == 1
    sent = f"{asked[0].system}\n{asked[0].user_text}"
    assert "138" not in sent and "210" not in sent and "סודי" not in sent and "₪" not in sent
    assert "price" not in asked[0].user_text.casefold()

    # a rerun gives the same SKUs
    again = rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    assert [x.chosen_sku for x in again.matches] == [x.chosen_sku for x in out.matches]


def test_the_memory_is_the_tenants_own(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    """05 §11–12: FNV's conflict is settled by this factory's memory, never by another's."""
    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())])
    drawing_id = str(response.json()["drawing_id"])
    Worker(pipeline).run_until_idle()
    comps = stage_4_by_hand(engine, storage, tenant, drawing_id)
    first = rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    fnv = next(x for x in first.matches if x.component_id == comps[2].component_id)
    assert fnv.status == "conflict" and fnv.signature

    with tenant_session(other.tenant_id, engine) as s:
        s.add(m.MatchMemory(id=new_id("mm"), tenant_id=other.tenant_id, signature=fnv.signature, sku="S203M-C6"))
    still = rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    assert next(x for x in still.matches if x.component_id == fnv.component_id).status == "conflict"

    with tenant_session(tenant.tenant_id, engine) as s:
        s.add(m.MatchMemory(id=new_id("mm"), tenant_id=tenant.tenant_id, signature=fnv.signature, sku="S203M-C6"))
    settled = rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    match = next(x for x in settled.matches if x.component_id == fnv.component_id)
    assert (match.status, match.method, match.chosen_sku) == ("matched", "memory", "S203M-C6")


def test_the_run_step_shows_the_stage_5_line(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())])
    drawing_id = str(response.json()["drawing_id"])
    Worker(pipeline).run_until_idle()
    stage_5 = progress(api, tenant, drawing_id).json()["stages"][4]
    assert stage_5["status"] == "done"
    assert stage_5["summary"].startswith("0 מותאמים · ")  # the stand-in's breakers carry no values
    assert stage_5["summary"].endswith("בלי דגם")
    stage_4_by_hand(engine, storage, tenant, drawing_id)
    rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    stage_5 = progress(api, tenant, drawing_id).json()["stages"][4]
    assert stage_5["summary"] == "3 מותאמים · אחד בסתירה"  # the terminal is auxiliary material, not counted


def test_remember_and_approve_write_the_tenants_memory(seeded: dict[str, Engine]) -> None:
    """05 §11: a swap is remembered at once, a different SKU replaces it, an approval strengthens it; RLS keeps it."""
    from konboro.services import match_memory

    engine = seeded["app"]
    tenant, other = add_tenant(engine), add_tenant(engine)
    sig = "circuit_breaker|mcb|current_a=16|poles=3|curve=C|bc_ka>=6"
    with tenant_session(tenant.tenant_id, engine) as s:
        match_memory.remember(s, tenant.tenant_id, sig, "S203M-C16")
        match_memory.remember(s, tenant.tenant_id, sig, "S203M-C16")
        assert match_memory.approve(s, tenant.tenant_id, sig, "S203M-C16") is not None
        assert match_memory.approve(s, tenant.tenant_id, sig, "A9F74316") is None  # not the memory's choice
        row = match_memory.remember(s, tenant.tenant_id, sig, "A9F74316", brand_context="Schneider")
        assert (row.sku, row.approved_count) == ("A9F74316", 1)
    with tenant_session(tenant.tenant_id, engine) as s:
        rows = sorted((r.brand_context or "", r.sku, r.approved_count) for r in s.scalars(select(m.MatchMemory)))
        assert rows == [("", "S203M-C16", 2), ("Schneider", "A9F74316", 1)]
        match_memory.remember(s, tenant.tenant_id, sig, "S203M-C20")
    with tenant_session(tenant.tenant_id, engine) as s:
        plain = s.scalar(select(m.MatchMemory).where(m.MatchMemory.brand_context.is_(None)))
        assert plain is not None and (plain.sku, plain.approved_count) == ("S203M-C20", 1)
    with tenant_session(other.tenant_id, engine) as s:
        assert s.scalars(select(m.MatchMemory)).all() == []
