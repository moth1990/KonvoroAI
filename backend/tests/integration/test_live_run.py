"""The live run step (01 §4.6, 13 §4.11 `live_run`; S28c): the progress endpoint's times, cost and events, the start
bar's check, every attempt's cost, and the medians across factories that give aggregates only."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.worker import Worker
from konboro.services import run_cost, run_estimate
from konboro.services.llm import usage_recorder
from konboro_llm import LLMClient, LLMError, LLMRequest, LLMResult
from konboro_llm.config import StageRoute
from konboro_llm.providers import FakeProvider
from konboro_llm.types import Usage

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_pipeline import NURSERY, pipeline, start  # noqa: F401  (fixture and helpers)

CAD = b"AC1032" + b"\0" * 64  # a DWG header: refused by format (01 §4.3)


@pytest.fixture(scope="module")
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    run_estimate.clear_cache()
    return migrated_db


class Kind(BaseModel):
    page_kind: str


def bill(engine: Engine, tenant: ApiTenant, drawing_id: str | None, stage: int | None, usage: Usage) -> None:
    """One priced call, as the pipeline's recorder writes it (Sonnet 5.5: $2 in, $10 out a million)."""
    request = LLMRequest(stage="symbol_detection", system="s", user_text="u", output_schema=Kind, tenant_id="t")
    result: LLMResult[Any] = LLMResult(
        data=None, provider="anthropic", model="claude-sonnet-5-5", usage=usage, latency_ms=1, attempts=1
    )
    usage_recorder(engine, tenant.tenant_id, drawing_id, stage)(request, result)


def progress(api: Api, tenant: ApiTenant, drawing_id: str, **query: Any) -> dict[str, Any]:
    response = api.client.get(f"/drawings/{drawing_id}/progress", headers=api.as_(tenant), params=query)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_a_new_factory_has_the_live_run_on(api: Api, seeded: dict[str, Engine]) -> None:
    tenant = add_tenant(seeded["app"])
    assert api.client.get("/me", headers=api.as_(tenant)).json()["flags"]["live_run"] is True


def test_the_live_run_reports_times_cost_and_what_each_stage_did(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)

    live = progress(api, tenant, drawing_id)["live"]
    assert live["cost_usd"] == "0"
    assert live["seconds_left"] > 0  # nothing ran yet: the seed's time for 9 pages
    assert (live["messages"], live["view"]) == ([], None)

    Worker(pipeline).run_until_idle()
    bill(engine, tenant, drawing_id, 3, Usage(1_000, 10_000))  # $0.102 in stage 3
    bill(engine, tenant, drawing_id, None, Usage(1_000_000, 0))  # a chat call on the drawing: not the run's
    bill(engine, tenant, None, None, Usage(1_000_000, 0))  # a chat call: not the run's

    body = progress(api, tenant, drawing_id)
    live = body["live"]
    assert body["status"] == "ready"
    assert Decimal(live["cost_usd"]) == Decimal("0.102")
    assert Decimal(live["cost_per_page_usd"]) == Decimal("0.102") / 9
    assert live["seconds_left"] is None and live["fraction"] == 1
    assert [s["stage"] for s in live["stages"]] == list(range(1, 8))
    assert all(s["seconds"] is not None for s in live["stages"])
    stage_3 = live["stages"][2]
    assert Decimal(stage_3["cost_usd"]) == Decimal("0.102")  # the stand-in's own calls cost nothing
    assert stage_3["calls"] == sum(x["calls"] for x in stage_3["models"]) > 1
    assert "Sonnet" in [x["label"] for x in stage_3["models"]]
    assert (live["counters"]["pages"], live["counters"]["pages_read"]) == (9, 9)
    assert {"tiles", "components", "findings"} <= set(live["counters"])
    texts = [msg["text"] for msg in live["messages"]]
    assert len(texts) <= 6
    assert texts[-1].endswith("שורות בהצעה")  # stage 7's last sentence
    assert live["view"] is None  # a finished run shows no page

    with tenant_session(tenant.tenant_id, engine) as s:
        kinds = dict(
            s.execute(
                select(m.PipelineEvent.stage, func.count())
                .where(m.PipelineEvent.drawing_id == drawing_id)
                .group_by(m.PipelineEvent.stage)
            ).all()
        )
        boxes = s.scalars(
            select(m.PipelineEvent.payload).where(
                m.PipelineEvent.drawing_id == drawing_id, m.PipelineEvent.kind == "boxes"
            )
        ).all()
    assert set(kinds) == set(range(1, 8))  # every stage reported
    assert boxes and all(len(b) == 4 for payload in boxes for b in payload["boxes"])


def test_the_live_run_is_off_with_its_flag(api: Api, seeded: dict[str, Engine]) -> None:
    tenant = add_tenant(seeded["app"])
    set_tenant_flag(seeded["app"], tenant.tenant_id, "live_run", False)
    drawing_id = start(api, tenant)
    assert progress(api, tenant, drawing_id)["live"] is None
    files = [("files", ("NURSERY-1.pdf", NURSERY.read_bytes(), "application/pdf"))]
    response = api.client.post("/drawings/check", headers=api.as_(tenant), files=files)
    assert response.status_code == 404


def test_the_check_counts_pages_and_stores_nothing(
    api: Api, seeded: dict[str, Engine], monkeypatch: pytest.MonkeyPatch
) -> None:
    # the seed's rates: other tests' runs would otherwise give every factory's medians (20 runs in all)
    monkeypatch.setattr(run_estimate, "rates", lambda s, tenant_id: run_estimate.SEED)
    engine = seeded["app"]
    tenant = add_tenant(engine, used=4)
    files = [("files", ("NURSERY-1.pdf", NURSERY.read_bytes(), "application/pdf"))]
    body = api.client.post("/drawings/check", headers=api.as_(tenant), files=files).json()
    assert [(f["name"], f["page_count"], f["error"]) for f in body["files"]] == [("NURSERY-1.pdf", 9, None)]
    assert body["estimate"]["pages"] == 9
    assert 60 < body["estimate"]["seconds"] < 600
    assert Decimal(body["estimate"]["cost_usd"]) > 0
    audit = api.client.post("/drawings/check", headers=api.as_(tenant), files=files, data={"purpose": "audit"}).json()
    assert audit["estimate"]["seconds"] < body["estimate"]["seconds"]  # an audit stops after stage 4 and the step

    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.scalar(select(func.count()).select_from(m.Drawing)) == 0
        assert s.scalar(select(func.count()).select_from(m.QuotaEvent)) == 0
    assert api.client.get("/quota", headers=api.as_(tenant)).json()["counters"][0]["used"] == 4

    cad = [*files, ("files", ("panel.dwg", CAD, "application/octet-stream"))]
    rejected = api.client.post("/drawings/check", headers=api.as_(tenant), files=cad).json()
    assert [f["error"] for f in rejected["files"]] == [None, "cad_not_supported"]
    assert rejected["estimate"] is None


def test_a_cancelled_run_says_what_it_cost_so_far(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    drawing_id = start(api, tenant)
    bill(engine, tenant, drawing_id, 1, Usage(10_000, 1_000))  # stage 1 was under way: $0.03
    response = api.client.post(f"/drawings/{drawing_id}/cancel", headers=api.as_(tenant))
    assert response.status_code == 200
    assert Decimal(response.json()["live"]["cost_usd"]) == Decimal("0.03")
    Worker(pipeline).run_until_idle()


def test_a_call_that_never_answers_is_still_billed(seeded: dict[str, Engine]) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        s.add(m.Drawing(id="drw_01JD0LIVE0000000000000000A", tenant_id=tenant.tenant_id))
    llm = LLMClient(
        {"fake": FakeProvider([{"nope": 1}, {"nope": 2}])},
        {"page_classification": StageRoute("fake", "claude-haiku-5-5")},
        on_call=usage_recorder(engine, tenant.tenant_id, "drw_01JD0LIVE0000000000000000A", 1),
    )
    request = LLMRequest(stage="page_classification", system="s", user_text="u", output_schema=Kind, tenant_id="t")
    with pytest.raises(LLMError):
        llm.run(request)
    with tenant_session(tenant.tenant_id, engine) as s:
        row = s.scalars(select(m.LlmCall).where(m.LlmCall.drawing_id == "drw_01JD0LIVE0000000000000000A")).one()
        assert (row.ok, row.attempts, row.pipeline_stage) == (False, 2, 1)
        assert run_cost.drawing_cost(s, "drw_01JD0LIVE0000000000000000A").stages[1].calls == 1


def test_the_medians_across_factories_are_aggregates_only(
    api: Api,
    seeded: dict[str, Engine],
    pipeline: Pipeline,  # noqa: F811
) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    start(api, tenant)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        own = run_estimate.own_medians(s)
        every = run_estimate.all_medians(s)
        medians = s.execute(text("SELECT * FROM konboro_stage_medians(:w)"), {"w": timedelta(days=30)})
        columns = list(medians.keys())
    assert columns == ["stage", "runs", "seconds_per_unit", "usd_per_unit"]  # no tenant, no drawing
    assert set(own) == set(range(1, 8)) and all(runs == 1 for runs, _, _ in own.values())
    for stage, (runs, _, _) in own.items():
        assert every[stage][0] >= runs  # every factory's include this one's
