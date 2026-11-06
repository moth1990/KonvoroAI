"""S28: migration 0026 removes `price_list` with its overrides, and dates the build-time flags for Gate 3 (decision
4)."""

from datetime import date

from alembic import command
from sqlalchemy import create_engine, text

from konboro.db.admin import database_dsn, ensure_app_role, migrating, recreate_database
from konboro.db.ids import new_id

T = new_id("tnt")
BUILD_TIME = ("quote_audit", "bom_column_mapping", "onboarding", "settings_screen", "approval_queue", "chat_layer")
SPEC_13 = ("unresolved_overlay", "export_doc", "chat_quote_builder", "home_chat", "voice_input", "catalog_lines")


def test_price_list_goes_and_the_build_time_flags_get_a_date() -> None:
    name = "konboro_migration_0026"
    recreate_database(name)
    ensure_app_role(database_dsn("postgres"))
    owner = create_engine(database_dsn(name))
    with migrating(database_dsn(name)) as cfg:
        command.upgrade(cfg, "0025")
        with owner.begin() as c:
            c.execute(text("INSERT INTO plans (id, name_he) VALUES ('p', 'p')"))
            c.execute(text("INSERT INTO tenants (id, name, plan_id) VALUES (:t, 'מפעל', 'p')"), {"t": T})
            for key in ("price_list", *BUILD_TIME, *SPEC_13):
                c.execute(text("INSERT INTO feature_flags (key, description) VALUES (:k, :k)"), {"k": key})
            plan_row = "INSERT INTO plan_feature_flags (plan_id, flag_key, enabled) VALUES ('p', 'price_list', true)"
            c.execute(text(plan_row))
            for key in ("price_list", "chat_layer"):
                c.execute(
                    text("INSERT INTO tenant_feature_overrides (tenant_id, flag_key, enabled) VALUES (:t, :k, true)"),
                    {"t": T, "k": key},
                )

        command.upgrade(cfg, "0026")
        with owner.connect() as c:
            dates = {k: d for k, d in c.execute(text("SELECT key, remove_by FROM feature_flags"))}
            overrides = c.execute(text("SELECT flag_key FROM tenant_feature_overrides")).scalars().all()
            plan = c.execute(text("SELECT count(*) FROM plan_feature_flags")).scalar_one()
        assert "price_list" not in dates
        assert {k: dates[k] for k in BUILD_TIME} == dict.fromkeys(BUILD_TIME, date(2026, 12, 31))
        assert all(dates[k] is None for k in SPEC_13)  # removed a month after they are on for everyone (13 §3)
        assert overrides == ["chat_layer"] and plan == 0

        command.downgrade(cfg, "0025")
        with owner.connect() as c:
            back = {k: d for k, d in c.execute(text("SELECT key, remove_by FROM feature_flags"))}
        assert back["price_list"] is None and back["chat_layer"] is None
    owner.dispose()
