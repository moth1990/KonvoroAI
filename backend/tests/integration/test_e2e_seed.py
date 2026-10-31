"""The E2E tenants that Playwright logs in as: each one is in the state its tests rely on."""

from datetime import UTC, datetime

from sqlalchemy import Engine

from konboro.db.session import tenant_session
from konboro.devtools import e2e
from konboro.services import auth, flags, home, quota


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


def test_every_e2e_tenant_can_log_in(migrated_db: dict[str, Engine]) -> None:
    e2e.seed_e2e(migrated_db["owner"])
    settings = e2e.e2e_settings(5181)
    assert settings.cors_origins == ["http://localhost:5181", "http://127.0.0.1:5181"]
    for t in e2e.TENANTS:
        user = auth.dev_login(settings, migrated_db["app"], t.email, e2e.PASSWORD)
        assert (user.tenant_id, user.id) == (t.tenant_id, t.user_id)
