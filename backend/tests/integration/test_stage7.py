"""Stage 7 on the local services (07). NURSERY-1 goes through the queue with the stand-in model, so stage 7 runs as
the last stage, writes its contract under the tenant in S3 and calls no model. Then stages 5–7 run again on a
hand-made stage-4 output with values (a main breaker and six outgoing ones), with the demo price list in the tenant:
the quote has real lines, colours, reasons, an enclosure and totals, and another factory's prices never apply
(07 §12). Then the versions: a rerun keeps what the user did on the draft, a sent version never changes, a
recalculation after it makes version 2 with a diff, and "open version N+1" copies it (07 §7.7, S22 decisions 4–5).
"""

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from konboro.contracts.pricing import QuoteVersionResult
from konboro.db import models as m
from konboro.db.seed import link_demo_catalog, seed_global, seed_price_list
from konboro.db.session import tenant_session
from konboro.devtools import fake_llm
from konboro.pipeline import coordinator
from konboro.pipeline.context import StageContext
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.matching import catalog as matching_catalog
from konboro.pipeline.matching import factory as matching_factory
from konboro.pipeline.pricing import load
from konboro.pipeline.pricing import run as pricing
from konboro.pipeline.stages import s7_pricing
from konboro.pipeline.worker import Worker
from konboro.services import quote_versions as qv
from konboro.services.storage import Storage
from konboro_llm import LLMClient
from konboro_llm.providers import FakeProvider

from .api import Api, ApiTenant, add_tenant, set_tenant_flag
from .test_api_drawings import progress
from .test_api_upload import upload
from .test_pipeline import pipeline  # noqa: F401  (fixture)
from .test_stage1 import NURSERY
from .test_stage6 import rerun as stage_6
from .test_stage6 import stages_4_and_5_by_hand

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(migrated_db: dict[str, Engine]) -> dict[str, Engine]:
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)  # the sample catalog with its enclosures (S22 decision 3), the rule pack
    return migrated_db


def priced_tenant(engine: Engine) -> ApiTenant:
    """A factory with the demo price list (S203M-C16 and the rest) and a 25% default markup."""
    tenant = add_tenant(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        seed_price_list(s, tenant.tenant_id)
        link_demo_catalog(s, tenant.tenant_id)
        s.add(
            m.MarginRule(
                id=f"mr_{tenant.tenant_id[-12:]}",
                tenant_id=tenant.tenant_id,
                level="default",
                kind="markup",
                value=Decimal("0.25"),
            )
        )
    set_tenant_flag(engine, tenant.tenant_id, "review_screen", True)
    return tenant


def through_the_queue(api: Api, pipeline: Pipeline, tenant: ApiTenant) -> str:  # noqa: F811
    response = upload(api, tenant, [("NURSERY-1.pdf", NURSERY.read_bytes())], project="גן ילדים")
    assert response.status_code == 201, response.text
    Worker(pipeline).run_until_idle()
    return str(response.json()["drawing_id"])


def stages_5_to_7_by_hand(engine: Engine, storage: Storage, tenant: ApiTenant, drawing_id: str) -> QuoteVersionResult:
    stages_4_and_5_by_hand(engine, storage, tenant, drawing_id)
    stage_6(engine, storage, tenant, drawing_id, FakeProvider(fake_llm.answer))
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = s.get_one(m.Drawing, drawing_id)
        llm = LLMClient({"anthropic": FakeProvider(fake_llm.answer)})
        out = s7_pricing.run(StageContext(s, storage, drawing, 7, llm))
        key = s.scalar(select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 7))
        assert key is not None
        storage.put(tenant.tenant_id, key, out.model_dump_json().encode())
    return out


def lines_of(s: Session, version_id: str) -> list[m.QuoteLine]:
    return list(s.scalars(select(m.QuoteLine).where(m.QuoteLine.quote_version_id == version_id)))


def version_of(s: Session, quote_id: str, n: int = 1) -> m.QuoteVersion:
    return s.scalars(
        select(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote_id, m.QuoteVersion.version == n)
    ).one()


def test_stage_7_runs_last_in_the_queue(
    seeded: dict[str, Engine],
    api: Api,
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    drawing_id = through_the_queue(api, pipeline, tenant)
    with tenant_session(tenant.tenant_id, engine) as s:
        run7 = s.scalar(select(m.StageRun).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == 7))
        assert run7 is not None and run7.status == "done" and run7.output_key
        assert run7.output_key.startswith(f"tenants/{tenant.tenant_id}/")
        result = QuoteVersionResult.model_validate_json(storage.get(tenant.tenant_id, run7.output_key))
        quote = s.get_one(m.Quote, result.quote_id)
        assert (quote.drawing_id, quote.name, quote.current_version) == (drawing_id, "גן ילדים", 1)
        rows = lines_of(s, version_of(s, quote.id).id)
        assert {ln.id for ln in rows} == {ln.line_id for p in result.panels for ln in p.lines}
        stages = set(s.scalars(select(m.LlmCall.stage).where(m.LlmCall.drawing_id == drawing_id)))
        rules = set(s.scalars(select(m.DerivedItemRule.rule_key)))
    assert not {st for st in stages if "pric" in st}  # 07 §1 principle 1: no model in stage 7
    assert rules == {r["key"] for r in load.starter_pack()[1]}  # the tenant got the starter pack
    assert progress(api, tenant, drawing_id).json()["stages"][6]["status"] == "done"


def test_stage_7_prices_the_quote(
    seeded: dict[str, Engine],
    api: Api,
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    # another factory prices every SKU at 1: none of it may reach this tenant's quote (07 §12)
    other = add_tenant(engine)
    with tenant_session(other.tenant_id, engine) as s:
        seed_price_list(s, other.tenant_id)
        link_demo_catalog(s, other.tenant_id)
        s.execute(update(m.ProductSupplier).values(unit_cost=Decimal("1")))
        s.execute(update(m.Product).values(sale_mode="rule"))
        other_ids = set(s.scalars(select(m.Product.id)))
    drawing_id = through_the_queue(api, pipeline, tenant)
    result = stages_5_to_7_by_hand(engine, storage, tenant, drawing_id)

    with tenant_session(tenant.tenant_id, engine) as s:
        version = version_of(s, result.quote_id)
        lines = lines_of(s, version.id)
        stage6 = list(
            s.scalars(select(m.Finding).where(m.Finding.drawing_id == drawing_id, m.Finding.source != "pricing"))
        )
        found = list(
            s.scalars(select(m.Finding).where(m.Finding.quote_version_id == version.id, m.Finding.source == "pricing"))
        )
        s.expunge_all()  # read below, after the session closes

    assert {ln.line_id for p in result.panels for ln in p.lines} == {ln.id for ln in lines}
    by_sku = {ln.sku: ln for ln in lines if ln.line_type == "component"}
    f16 = by_sku["S203M-C16"]  # F1–F5 and FC1 share the signature
    assert f16.product_id is not None and f16.product_id not in other_ids
    assert f16.unit_price is not None and f16.unit_price > Decimal("10")  # the tenant's own price, never 1.25
    assert f16.cost_source and f16.margin_rule and f16.rounding == "agora"  # a full trace (07 §10.1)
    assert f16.line_total == f16.unit_price * f16.qty and f16.line_key == f"c:{f16.component_id}"
    assert {r["source"] for r in f16.status_reasons} >= {"confidence", "match", "price"}
    enclosure = next(ln for ln in lines if (ln.derived or {}).get("rule_key") == "enclosure")
    assert enclosure.line_type == "derived" and enclosure.line_group == "enclosure"
    assert "מודולים ברכיבים" in (enclosure.derived or {})["explanation"]
    assert not {ln.product_id for ln in lines} & other_ids
    unpriced = [ln for ln in lines if ln.unit_price is None]
    assert all(ln.status == "red" or (ln.derived or {}).get("service") for ln in unpriced)
    total = sum((ln.line_total or Decimal(0) for ln in lines), Decimal(0))
    assert Decimal(version.totals["price_total"]) == result.totals.price_total == total
    assert result.totals.unpriced_count == len(unpriced) and result.totals.vat_rate > 0
    snap = version.snapshot
    assert snap["vat_rate_id"] and snap["derived_rules_version"].startswith(tenant.tenant_id)
    assert snap["price_list_ids"] and set(snap["price_list_ids"]) <= {
        str((ln.cost_source or {}).get("supplier_price_id")) for ln in lines
    }
    # stage 6's findings moved to the version and point at its lines (FC1's load above its rating); pricing's too
    line_ids = {ln.id for ln in lines}
    assert stage6 and all(f.quote_version_id == version.id and set(f.line_ids) <= line_ids for f in stage6)
    assert any(f.line_ids for f in stage6)
    assert all(set(f.line_ids) <= line_ids for f in found)
    if unpriced:
        assert any(f.code == "missing_cost" for f in found)

    # the review screen reads the real lines and totals, and the done step counts the products
    body = api.client.get(f"/quotes/{result.quote_id}", headers=api.as_(tenant)).json()
    assert {ln["line_id"] for p in body["panels"] for ln in p["lines"]} == line_ids
    assert Decimal(body["totals"]["price_total"]) == result.totals.price_total
    run = progress(api, tenant, drawing_id).json()
    products = [
        ln
        for ln in lines
        if ln.line_type in ("component", "missing") and not (ln.parent_line_id and ln.unit_price == 0)
    ]
    assert run["summary"]["products"] == len(products)
    assert run["summary"]["priced"] == sum(1 for ln in products if ln.unit_price is not None)
    assert "מהמחירון" in run["stages"][6]["summary"]


def test_versions_reruns_and_recalculation(
    seeded: dict[str, Engine],
    api: Api,
    pipeline: Pipeline,  # noqa: F811
    storage: Storage,
) -> None:
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    drawing_id = through_the_queue(api, pipeline, tenant)
    quote_id = stages_5_to_7_by_hand(engine, storage, tenant, drawing_id).quote_id
    actor = qv.Actor(tenant.tenant_id, tenant.user_id)

    with tenant_session(tenant.tenant_id, engine) as s:
        v1_id = version_of(s, quote_id).id
        rows = lines_of(s, v1_id)
        derived = next(ln for ln in rows if (ln.derived or {}).get("rule_key") == "labels")
        priced = next(ln for ln in rows if ln.sku == "S203M-C16")
        # the user deletes a derived line and sets a price on another (S23's routes; here as their rows)
        derived.deleted_at = datetime.now(UTC)
        priced.override = {"scope": "quote", "unit_price": "999.00"}
        deleted_key, override_key = derived.line_key, priced.line_key

    # stage 7 again (a rerun): the draft in place, keeping what the user did
    with tenant_session(tenant.tenant_id, engine) as s:
        out = pricing.read_outputs(s, storage, tenant.tenant_id, drawing_id)
        again = pricing.price_drawing(s, tenant.tenant_id, s.get_one(m.Drawing, drawing_id), out, "גן ילדים")
        assert (again.version.id, again.version.version) == (v1_id, 1)
        rows = lines_of(s, v1_id)
        live = {ln.line_key: ln for ln in rows if ln.deleted_at is None}
        assert deleted_key not in live  # a derived line the user deleted is not made again (07 §7)
        assert [ln.line_key for ln in rows if ln.deleted_at is not None] == [deleted_key]  # kept, for undo
        assert live[override_key].unit_price == Decimal("999.00") and live[override_key].override

    # stage 5's frequency tie-break counts what the factory sent, never stage 7's own drafts (BUG-047)
    with tenant_session(tenant.tenant_id, engine) as s:
        catalog = matching_catalog.load(s)
        assert matching_factory.load(s, tenant.tenant_id, catalog, None).usage == {}

    # send locks the version: neither it nor its lines change again
    with tenant_session(tenant.tenant_id, engine) as s:
        sent = qv.send(s, actor, quote_id)
        assert matching_factory.load(s, tenant.tenant_id, matching_catalog.load(s), None).usage
        assert sent.status == "sent" and sent.sent_by == tenant.user_id
        with pytest.raises(qv.VersionError):
            qv.send(s, actor, quote_id)
    with pytest.raises(DBAPIError), tenant_session(tenant.tenant_id, engine) as s:
        s.execute(update(m.QuoteLine).where(m.QuoteLine.quote_version_id == v1_id).values(qty=Decimal("9")))

    # the price list changes; the preview writes nothing, the recalculation makes version 2 with the diff
    with tenant_session(tenant.tenant_id, engine) as s:
        before = {ln.id: (ln.unit_price, ln.line_total) for ln in lines_of(s, v1_id)}
        s.execute(update(m.ProductSupplier).values(unit_cost=m.ProductSupplier.unit_cost * Decimal("1.1")))
        s.execute(update(m.Product).values(sale_mode="rule"))
        preview = qv.preview_recalculation(s, storage, tenant.tenant_id, quote_id)
        assert preview["lines"] and s.get_one(m.Quote, quote_id).current_version == 1
        start = time.perf_counter()
        v2 = qv.recalculate(s, storage, tenant.tenant_id, quote_id)
        assert time.perf_counter() - start < 2.0  # 07 §9: a full recalculation with the diff ≤ 2 s
        assert (v2.version.version, v2.version.status) == (2, "draft")
        diff = v2.version.diff_from_previous or {}
        assert diff["from_version"] == 1 and any(x["change"] == "changed" for x in diff["lines"])
        keys = {ln.key: ln for ln in v2.priced.lines}
        assert keys[override_key].priced.unit_price == Decimal("999.00") and deleted_key not in keys
        assert {ln.id: (ln.unit_price, ln.line_total) for ln in lines_of(s, v1_id)} == before  # v1 as it was sent
        moved = s.scalars(
            select(m.Finding.quote_version_id).where(m.Finding.drawing_id == drawing_id, m.Finding.source != "pricing")
        )
        assert set(moved) == {v2.version.id}
        v2_id, v2_net = v2.version.id, v2.version.totals["net_total"]

    # version 2 sent, then "open version 3": a copy, not priced again
    with tenant_session(tenant.tenant_id, engine) as s:
        qv.send(s, actor, quote_id)
        v3 = qv.open_next(s, actor, quote_id)
        assert (v3.version, v3.status, v3.totals["net_total"]) == (3, "draft", v2_net)
        copied = sorted((ln.line_key or "", str(ln.unit_price)) for ln in lines_of(s, v3.id))
        assert copied == sorted((ln.line_key or "", str(ln.unit_price)) for ln in lines_of(s, v2_id))
        with pytest.raises(qv.VersionError):
            qv.open_next(s, actor, quote_id)  # version 3 is a draft


def test_a_rerun_of_stages_2_to_7_under_the_draft(
    seeded: dict[str, Engine],
    api: Api,
    pipeline: Pipeline,  # noqa: F811
) -> None:
    """A page moved (S08): stage 4 rewrites the components the draft's lines point at, with no foreign-key error
    (the S13 backlog item), and stage 7 writes the draft again."""
    engine = seeded["app"]
    tenant = priced_tenant(engine)
    drawing_id = through_the_queue(api, pipeline, tenant)
    with tenant_session(tenant.tenant_id, engine) as s:
        quote_id = s.scalars(select(m.Quote.id).where(m.Quote.drawing_id == drawing_id)).one()
        assert lines_of(s, version_of(s, quote_id).id)
        message = coordinator.rerun(s, tenant.tenant_id, drawing_id)
    pipeline.queue.send(message)
    Worker(pipeline).run_until_idle()
    with tenant_session(tenant.tenant_id, engine) as s:
        assert s.get_one(m.Drawing, drawing_id).status == "ready"
        assert s.get_one(m.Quote, quote_id).current_version == 1
        rows = lines_of(s, version_of(s, quote_id).id)
        components = set(s.scalars(select(m.Component.id).where(m.Component.drawing_id == drawing_id)))
        assert rows and all(ln.component_id in components for ln in rows if ln.component_id)
        versions = s.scalar(select(func.count()).select_from(m.QuoteVersion).where(m.QuoteVersion.quote_id == quote_id))
        assert versions == 1


def test_derived_rules_are_seeded_once(seeded: dict[str, Engine]) -> None:
    engine = seeded["app"]
    tenant = add_tenant(engine)
    with tenant_session(tenant.tenant_id, engine) as s:
        load.ensure_rules(s, tenant.tenant_id)
        s.execute(update(m.DerivedItemRule).where(m.DerivedItemRule.rule_key == "labels").values(enabled=False))
        load.ensure_rules(s, tenant.tenant_id)  # a tenant that has rules keeps them as they are
        rules = {r.key: r for r in load.derived_rules(s, tenant.tenant_id)}
    assert len(rules) == len(load.starter_pack()[1]) and not rules["labels"].enabled
    other = add_tenant(engine)
    with tenant_session(other.tenant_id, engine) as s:
        assert load.derived_rules(s, other.tenant_id) == []  # RLS: the first tenant's rows are not seen
