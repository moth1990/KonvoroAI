"""/quotes and /home/summary: the home screen's data, tenant-scoped (prototype vHome; 00 §8)."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, update

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.session import tenant_session

from .api import Api, ApiTenant, add_tenant


def add_quote(
    engine: Engine,
    tenant: ApiTenant,
    name: str,
    prices: list[Decimal | None],
    *,
    status: str = "draft",
    deleted: int = 0,
) -> str:
    """A quote whose current version has one line per price (None = no price yet) plus `deleted` unpriced lines."""
    with tenant_session(tenant.tenant_id, engine) as s:
        quote = m.Quote(id=new_id("quo"), tenant_id=tenant.tenant_id, name=name)
        s.add(quote)
        s.flush()
        version = m.QuoteVersion(id=new_id("qv"), tenant_id=tenant.tenant_id, quote_id=quote.id, version=1)
        s.add(version)
        s.flush()
        for position, price in enumerate([*prices, *[None] * deleted], start=1):
            s.add(
                m.QuoteLine(
                    id=new_id("ln"),
                    tenant_id=tenant.tenant_id,
                    quote_version_id=version.id,
                    position=position,
                    description="שורה",
                    qty=Decimal(1),
                    unit_price=price,
                )
            )
        s.flush()
        if deleted:
            s.execute(
                update(m.QuoteLine)
                .where(m.QuoteLine.quote_version_id == version.id, m.QuoteLine.position > len(prices))
                .values(deleted_at=m.QuoteLine.created_at)
            )
        if status == "sent":  # lines go in while it is a draft: a sent version is frozen (07 §7.7)
            version.status, version.sent_at = "sent", datetime.now(UTC)
        return quote.id


def add_audit(
    engine: Engine, tenant: ApiTenant, number: str, amounts: list[Decimal | None], *, status: str = "ready"
) -> str:
    """An audit with one `missing_in_quote` difference per amount, plus one rejected and one other-type difference."""
    with tenant_session(tenant.tenant_id, engine) as s:
        drawing = m.Drawing(id=new_id("drw"), tenant_id=tenant.tenant_id, created_by=tenant.user_id)
        s.add(drawing)
        s.flush()
        audit = m.Audit(
            id=new_id("aud"),
            tenant_id=tenant.tenant_id,
            drawing_id=drawing.id,
            quote_ref={"number": number},
            status=status,
        )
        s.add(audit)
        s.flush()
        rows = [("missing_in_quote", "open", a) for a in amounts]
        rows += [("missing_in_quote", "rejected", Decimal("999")), ("qty_short", "open", Decimal("999"))]
        for kind, state, amount in rows:
            s.add(
                m.AuditDifference(
                    id=new_id("dif"),
                    tenant_id=tenant.tenant_id,
                    audit_id=audit.id,
                    type=kind,
                    severity="high",
                    confidence=0.9,
                    message="חסר",
                    amount=amount,
                    status=state,
                )
            )
        return audit.id


def add_candidates(engine: Engine, tenant: ApiTenant, statuses: list[str]) -> None:
    with tenant_session(tenant.tenant_id, engine) as s:
        for status in statuses:
            s.add(
                m.KnowledgeCandidate(
                    id=new_id("kc"), tenant_id=tenant.tenant_id, kind="abbreviation", payload={}, status=status
                )
            )


def test_a_new_tenant_has_nothing_waiting(api: Api, migrated_db: dict[str, Engine]) -> None:
    tenant = add_tenant(migrated_db["app"])
    assert api.client.get("/quotes", headers=api.as_(tenant)).json() == {"items": []}
    assert api.client.get("/home/summary", headers=api.as_(tenant)).json() == {
        "queue_pending": 0,
        "missing_prices": [],
        "audit_omissions": [],
    }


def test_quotes_list_newest_first_with_missing_prices(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    older = add_quote(engine, tenant, "NURSERY", [Decimal("10.00"), None, None], deleted=2)
    newer = add_quote(engine, tenant, "KARWANI", [Decimal("5.00")], status="sent")

    body = api.client.get("/quotes", headers=api.as_(tenant)).json()
    assert [(q["id"], q["name"], q["version_status"], q["missing_prices"]) for q in body["items"]] == [
        (newer, "KARWANI", "sent", 0),
        (older, "NURSERY", "draft", 2),  # deleted lines don't count
    ]
    assert body["items"][0]["version"] == 1
    assert [q["id"] for q in api.client.get("/quotes?limit=1", headers=api.as_(tenant)).json()["items"]] == [newer]


def test_quotes_limit_is_bounded(api: Api) -> None:
    for bad in ("0", "51", "x"):
        response = api.client.get(f"/quotes?limit={bad}", headers=api.as_(api.a))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_summary_counts(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    draft = add_quote(engine, tenant, "NURSERY", [None, None, None, Decimal("1.00")])
    add_quote(engine, tenant, "SENT", [None], status="sent")  # sent versions are final: not waiting
    add_quote(engine, tenant, "PRICED", [Decimal("1.00")])
    audit = add_audit(engine, tenant, "10271", [Decimal("1250.00"), None, Decimal("40.50")])
    add_audit(engine, tenant, "10272", [None], status="processing")  # not finished: not waiting
    add_candidates(engine, tenant, ["pending", "pending", "approved", "rejected"])

    body = api.client.get("/home/summary", headers=api.as_(tenant)).json()
    (omission,) = body.pop("audit_omissions")
    assert body == {"queue_pending": 2, "missing_prices": [{"quote_id": draft, "quote_name": "NURSERY", "count": 3}]}
    assert omission == {
        "audit_id": audit,
        "quote_number": "10271",
        "count": 3,
        "amount_at_risk": omission["amount_at_risk"],
    }
    assert Decimal(omission["amount_at_risk"]) == Decimal("1290.50")  # a string in JSON, at the column's scale


def test_unpriced_omissions_have_no_amount(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    tenant = add_tenant(engine)
    add_audit(engine, tenant, "77", [None, None])
    (item,) = api.client.get("/home/summary", headers=api.as_(tenant)).json()["audit_omissions"]
    assert (item["count"], item["amount_at_risk"]) == (2, None)


def test_home_data_is_tenant_scoped(api: Api, migrated_db: dict[str, Engine]) -> None:
    engine = migrated_db["app"]
    a, b = add_tenant(engine), add_tenant(engine)
    add_quote(engine, a, "של A", [None])
    add_audit(engine, a, "1", [Decimal("1.00")])
    add_candidates(engine, a, ["pending"])

    assert len(api.client.get("/quotes", headers=api.as_(a)).json()["items"]) == 1
    assert api.client.get("/quotes", headers=api.as_(b)).json() == {"items": []}
    assert api.client.get("/home/summary", headers=api.as_(b)).json() == {
        "queue_pending": 0,
        "missing_prices": [],
        "audit_omissions": [],
    }


def test_home_routes_need_a_token(api: Api) -> None:
    for path in ("/quotes", "/home/summary"):
        assert api.client.get(path).status_code == 401
