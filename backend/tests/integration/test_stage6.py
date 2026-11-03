"""Stage 6 on the local services (06): the drawing goes through the queue to stage 7, its findings are rows on the quote
version and reach the review screen; then stages 5 and 6 run again on a hand-made stage-4 output with values. The
rules' overrides are the factory's own (RLS), the agent's calls are logged and it never sees a price, a cost or the
customer; the run step shows the stage-6 line; the rules-only re-run takes under a second. The model is the stand-in.
"""

import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from konboro.contracts.merge import AttributeValue, CircuitContext, Component, MergeResult
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.stages import s5_matching, s6_validation
from konboro.pipeline.validation import pack
from konboro.pipeline.worker import Worker
from konboro.services import validation
from konboro.services.llm import usage_recorder
from konboro.services.storage import Storage
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.validator_review import STAGE as REVIEW

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_api_drawings import progress
from .test_api_upload import upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the rule pack, beside the catalog and the symbol library
    return migrated_db


def _c(drawing_id: str, panel_id: str, tags: list[str], cls: str, load: float | None = None, **v: object) -> Component:
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
        circuit_context=CircuitContext(load_current_a=load) if load is not None else None,
        confidence=0.95,
        status="accepted",
    )


def stages_4_and_5_by_hand(engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str) -> list[Component]:
    """A main breaker and six outgoing ones, one of them (FC1) with a load above its rating; stage 5 matched again
    and stored, as the stage would."""
    with tenant_session(tenant.tenant_id, engine) as s:
        panel_id = s.scalars(select(m.Panel.id).where(m.Panel.drawing_id == drawing_id)).first()
        assert panel_id is not None
        comps = [
            _c(drawing_id, panel_id, ["Q0"], "mccb", current_a=80, poles=3),
            *(_c(drawing_id, panel_id, [f"F{n}"], "mcb", current_a=16, poles=3) for n in range(1, 6)),
            _c(drawing_id, panel_id, ["FC1"], "mcb", load=20, current_a=16, poles=3),
        ]
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
        keys = dict(
            s.execute(select(m.StageRun.stage, m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id)).all()
        )
        storage.put(
            tenant.tenant_id,
            keys[4],
            MergeResult(drawing_id=drawing_id, components=comps, trace_id="trc_example").model_dump_json().encode(),
        )
        drawing = s.get_one(m.Drawing, drawing_id)
        llm = LLMClient({"anthropic": FakeProvider(fake_llm.answer)})
        matched = s5_matching.run(StageContext(s, storage, drawing, 5, llm))
        storage.put(tenant.tenant_id, keys[5], matched.model_dump_json().encode())
    return comps


def rerun(
    engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str, provider: FakeProvider
) -> ValidationResult:
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        llm = LLMClient({"anthropic": provider}, on_call=usage_recorder(engine, tenant.tenant_id, drawing_id))
        out = s6_validation.run(StageContext(s, storage, drawing, 6, llm))
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 6))
        assert key is not None
        storage.put(tenant.tenant_id, key, out.model_dump_json().encode())
        return out


def _cost(engine: Engine, tenant: ApiTenant, sku: str, cost: str) -> None:
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


def test_stage_6_findings_reach_the_review_screen(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    set_tenant_flag(engine, tenant.tenant_id, "review_screen", True)
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], customer="לקוח סודי", project="פרויקט")
    drawing_id = str(response.json()["drawing_id"])
    Worker(pipeline).run_until_idle()

    with tenant_session(tenant.tenant_id, engine) as s:
        run6 = s.scalar(select(m.StageRun).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 6))
        assert run6 is not None and run6.status == "done" and run6.output_key
        assert run6.output_key.startswith(f"tenants/{tenant.tenant_id}/")
        result = ValidationResult.model_validate_json(storage.get(tenant.tenant_id, run6.output_key))
        rows = dict(
            s.execute(
                select(m.Finding.id, m.Finding.quote_version_id).where(
                    m.Finding.drawing_id == drawing_id, m.Finding.source != "pricing"
                )
            ).all()
        )
        priced = s.scalar(select(func.count()).where(m.Finding.drawing_id == drawing_id, m.Finding.source == "pricing"))
        version = s.scalar(select(m.QuoteVersion.id).join(m.Quote).where(m.Quote.drawing_id == drawing_id))
    assert result.rules_version == pack.default().version and result.checks_run
    assert set(rows) == {i.issue_id for i in result.issues}
    assert rows and set(rows.values()) == {version}  # stage 7 attached them (S21 decision 1)

    body = progress(api, tenant, drawing_id).json()
    open_count = sum(1 for i in result.issues if i.status == "open")
    assert body["summary"]["findings"] == open_count + priced  # the done step counts pricing's too (S22)
    stage_6 = body["stages"][5]
    assert stage_6["status"] == "done"
    assert stage_6["summary"] == (
        f"{open_count} ממצאים" if open_count > 1 else "ממצא אחד" if open_count else "אין ממצאים"
    )

    quote = api.client.get(f"/quotes/{body['quote_id']}", headers=api.as_(tenant)).json()
    shown = {f["finding_id"]: f for f in quote["findings"]}
    assert set(shown) >= {i.issue_id for i in result.issues}
    one = result.issues[0]
    assert shown[one.issue_id]["title"] == one.title and shown[one.issue_id]["message"] == one.message


def test_the_agent_and_the_rules_on_a_drawing_with_values(
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
    comps = stages_4_and_5_by_hand(engine, storage, tenant, drawing_id)
    _cost(engine, tenant, "S203M-C16", "138.00")
    provider = FakeProvider(fake_llm.answer)
    out = rerun(engine, storage, tenant, drawing_id, provider)

    fc1 = comps[-1].component_id
    [load] = [i for i in out.issues if i.rule_id == "DATA_LOAD_CURRENT_GT_RATED"]
    assert load.component_ids == [fc1] and load.severity == "warning"
    assert {c.component_id: c.max_status for c in out.row_status_caps}[fc1] == "yellow"
    assert out.panel_summaries[0].main_device_component_id == comps[0].component_id
    assert out.agent_calls == 1
    [agent] = [i for i in out.issues if i.source == "agent"]
    assert agent.severity == "info" and agent.message.startswith("stand-in")  # 0.6: an info, never a colour

    asked = [r for r in provider.requests if r.stage == REVIEW]
    assert len(asked) == 1
    sent = f"{asked[0].system}\n{asked[0].user_text}"
    for word in ("138", "סודי", "₪"):
        assert word not in sent  # 06 §12, non-negotiable 6
    for word in ("price", "cost", "מחיר", "עלות"):
        assert word not in asked[0].user_text.casefold()  # the data sent; the fixed instructions say "price quote"
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.LlmCall).where(m.LlmCall.stage == REVIEW)) == 1
    with tenant_session(other.tenant_id, engine) as s:  # RLS
        assert s.scalar(select(func.count()).select_from(m.LlmCall).where(m.LlmCall.stage == REVIEW)) == 0

    again = rerun(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    assert [i.issue_id for i in again.issues] == [i.issue_id for i in out.issues]

    # the factory's own switch turns a rule off; another factory's does nothing here (RLS)
    with tenant_session(other.tenant_id, engine) as s:
        s.add(m.TenantRuleOverride(tenant_id=other.tenant_id, rule_id="DATA_LOAD_CURRENT_GT_RATED", enabled=False))
    assert load.issue_id in {i.issue_id for i in rerun(engine, storage, tenant, drawing_id, provider).issues}
    with tenant_session(tenant.tenant_id, engine) as s:
        s.add(m.TenantRuleOverride(tenant_id=tenant.tenant_id, rule_id="PANEL_NO_MAIN_DEVICE", enabled=False))
    tuned = rerun(engine, storage, tenant, drawing_id, provider)
    assert tuned.tenant_rules_version and tuned.tenant_rules_version.startswith(tenant.tenant_id)
    assert "PANEL_NO_MAIN_DEVICE" not in tuned.checks_run

    # the user fixes FC1's load: the rules alone run again on its panel, under a second (06 §6.3, §9)
    fixed = [c.model_copy(update={"circuit_context": None}) if c.component_id == fc1 else c for c in comps]
    edited = MergeResult(drawing_id=drawing_id, components=fixed, trace_id="trc_example")
    with tenant_session(tenant.tenant_id, engine) as s:
        start = time.perf_counter()
        fresh = validation.revalidate_panel(s, storage, tenant.tenant_id, drawing_id, comps[0].panel_id, merge=edited)
        took = time.perf_counter() - start
        status = s.scalar(select(m.Finding.status).where(m.Finding.id == load.issue_id))
    assert took < 1.0
    assert next(i for i in fresh.issues if i.issue_id == load.issue_id).status == "resolved"
    assert status == "resolved" and fresh.agent_calls == tuned.agent_calls  # the agent does not run again


def test_the_rule_pack_is_seeded_once(seeded: dict[str, Engine]) -> None:
    with Session(seeded["owner"]) as s, s.begin():
        seed_global(s)  # safe to rerun
    with Session(seeded["owner"]) as s:
        rows = s.scalars(select(m.ValidatorRule)).all()
    assert len(rows) == len(pack.rows())
    assert {r.rule_id for r in rows if r.approval == "pending_expert"} == {
        r.rule_id for r in pack.default().rules.values() if r.category == "A"
    }
    with tenant_session(add_tenant(seeded["app"]).tenant_id, seeded["app"]) as s:
        assert pack.load(s).rules.keys() == pack.default().rules.keys()  # the app reads the global pack
