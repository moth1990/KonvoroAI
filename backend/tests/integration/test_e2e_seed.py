"""The E2E tenants that Playwright logs in as: each one is in the state its tests rely on."""

from datetime import UTC, datetime

from sqlalchemy import Engine

from konboro.db.session import tenant_session
from konboro.devtools import e2e
from konboro.services import auth, flags, home, onboarding, price_list, quota


def test_e2e_tenants_have_their_states(migrated_db: dict[str, Engine]) -> None:
    e2e.seed_e2e(migrated_db["owner"])
    e2e.seed_e2e(migrated_db["owner"])  # a second run changes nothing

    states = {}
    for t in e2e.TENANTS:
        with tenant_session(t.tenant_id, migrated_db["app"]) as s:
            (counter,) = quota.summary(s, t.tenant_id, now=datetime.now(UTC)).counters
            states[t.email] = (
                flags.tenant_flags(s, t.tenant_id)["home_chat"],
                counter.usage.used,
                counter.state.value,
                home.summary(s, t.tenant_id),
                len(home.recent_quotes(s, t.tenant_id, 10)),
            )

    assert {email: state[:3] for email, state in states.items()} == {
        "chat@e2e.konboro.local": (True, 12, "ok"),
        "classic@e2e.konboro.local": (False, 12, "ok"),
        "near@e2e.konboro.local": (False, 43, "quota_near"),
        "full@e2e.konboro.local": (False, 50, "quota_reached"),
        "upload-desktop@e2e.konboro.local": (False, 12, "ok"),
        "upload-mobile@e2e.konboro.local": (False, 12, "ok"),
        "done-light-desktop@e2e.konboro.local": (False, 12, "ok"),
        "done-dark-desktop@e2e.konboro.local": (False, 12, "ok"),
        "done-light-mobile@e2e.konboro.local": (False, 12, "ok"),
        "done-dark-mobile@e2e.konboro.local": (False, 12, "ok"),
        "review@e2e.konboro.local": (False, 12, "ok"),
        "bom-desktop@e2e.konboro.local": (False, 12, "ok"),
        "bom-mobile@e2e.konboro.local": (False, 12, "ok"),
        "audit-desktop@e2e.konboro.local": (False, 12, "ok"),
        "audit-mobile@e2e.konboro.local": (False, 12, "ok"),
        "audit-shots@e2e.konboro.local": (False, 12, "ok"),
        "prices-desktop@e2e.konboro.local": (False, 12, "ok"),
        "prices-mobile@e2e.konboro.local": (False, 12, "ok"),
        "prices-shots@e2e.konboro.local": (False, 12, "ok"),
        "prices-off@e2e.konboro.local": (False, 12, "ok"),
        "review-desktop@e2e.konboro.local": (False, 12, "ok"),
        "review-mobile@e2e.konboro.local": (False, 12, "ok"),
        "picker-desktop@e2e.konboro.local": (False, 12, "ok"),
        "picker-mobile@e2e.konboro.local": (False, 12, "ok"),
        "welcome-desktop@e2e.konboro.local": (False, 0, "ok"),
        "welcome-mobile@e2e.konboro.local": (False, 0, "ok"),
        "prefs-desktop@e2e.konboro.local": (False, 12, "ok"),
        "prefs-mobile@e2e.konboro.local": (False, 12, "ok"),
        "queue-desktop@e2e.konboro.local": (False, 12, "ok"),
        "queue-mobile@e2e.konboro.local": (False, 12, "ok"),
        "s24-shots@e2e.konboro.local": (False, 12, "ok"),
        "s24-off@e2e.konboro.local": (False, 12, "ok"),
    }
    sample = states["classic@e2e.konboro.local"][3]
    assert sample.queue_pending == 3
    assert [(m.quote_name, m.count) for m in sample.missing_prices] == [("גן ילדים, לוח ראשי", 5)]
    assert [(a.quote_number, a.count, str(a.amount_at_risk)) for a in sample.audit_omissions] == [
        ("10271", 3, "1250.0000")
    ]
    assert states["classic@e2e.konboro.local"][4] == 3
    assert states["near@e2e.konboro.local"][3].queue_pending == 0
    assert states["near@e2e.konboro.local"][4] == 0
    # the review screen's fixture (S09), once, however often the seed runs
    review = next(t for t in e2e.TENANTS if t.nursery)
    with tenant_session(review.tenant_id, migrated_db["app"]) as s:
        assert [q.name for q in home.recent_quotes(s, review.tenant_id, 10)] == ["NURSERY"]
    # S24: the prototype's six queue candidates, once; a new factory must answer first, an established one has
    for t in e2e.TENANTS:
        expected = 6 if t.queue else 3 if t.sample_data else 0
        assert states[t.email][3].queue_pending == expected, t.email
        with tenant_session(t.tenant_id, migrated_db["app"]) as s:
            assert onboarding.required(s, t.tenant_id) is (not t.terms and "onboarding" not in t.off), t.email
    # the 26-993 audit (S16), once per audit tenant, under the id the Playwright tests open
    for t in (t for t in e2e.TENANTS if t.audit):
        omissions = states[t.email][3].audit_omissions
        assert [(a.audit_id, a.quote_number, a.count, str(a.amount_at_risk)) for a in omissions] == [
            (t.audit_id, "10271", 3, "1250.0000")  # QG2 short, TC-G1/TC-G2 and MS1–MS3 (S17, BUG-031)
        ]


def test_every_e2e_tenant_can_log_in(migrated_db: dict[str, Engine]) -> None:
    e2e.seed_e2e(migrated_db["owner"])
    settings = e2e.e2e_settings(5181)
    assert settings.cors_origins == ["http://localhost:5181", "http://127.0.0.1:5181"]
    for t in e2e.TENANTS:
        user = auth.dev_login(settings, migrated_db["app"], t.email, e2e.PASSWORD)
        assert (user.tenant_id, user.id) == (t.tenant_id, t.user_id)
    # the price list (S19): the demo's products, linked to the sample catalog, used by the NURSERY draft
    for t in (t for t in e2e.TENANTS if t.prices and t.nursery):
        with tenant_session(t.tenant_id, migrated_db["app"]) as s:
            products = price_list.list_products(s, t.tenant_id)
            assert len(products) == 24
            assert sum(p.catalog_item_id is not None for p in products) >= 15
            f1 = next(p for p in products if p.manufacturer_sku == "SN201M-C10")
            assert [u.quote_name for u in price_list.drafts_using(s, t.tenant_id, f1.id)] == ["NURSERY"]
            assert flags.tenant_flags(s, t.tenant_id)["price_list"] is True
    off = next(t for t in e2e.TENANTS if t.off)
    with tenant_session(off.tenant_id, migrated_db["app"]) as s:
        assert flags.tenant_flags(s, off.tenant_id)["price_list"] is False
