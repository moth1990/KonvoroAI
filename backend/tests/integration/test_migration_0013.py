"""BUG-041: migration 0013 marks the pages the stand-in classified before the fix, and only those."""

from alembic import command
from sqlalchemy import create_engine, text

from konboro.db.admin import database_dsn, ensure_app_role, migrating, recreate_database
from konboro.db.ids import new_id

T = new_id("tnt")


def page(drawing: str, file: str, no: int, model: str | None, by: str, reused_from: str | None = None) -> dict:
    return {"id": new_id("pg"), "t": T, "d": drawing, "f": file, "no": no, "m": model, "by": by, "r": reused_from}


def test_marks_stand_in_pages_and_their_reuses_only() -> None:
    name = "konboro_migration_0013"
    recreate_database(name)
    ensure_app_role(database_dsn("postgres"))
    owner = create_engine(database_dsn(name))
    with migrating(database_dsn(name)) as cfg:
        command.upgrade(cfg, "0012")

        fake_drw, real_drw, reuse_drw = new_id("drw"), new_id("drw"), new_id("drw")
        files = {d: new_id("fil") for d in (fake_drw, real_drw, reuse_drw)}
        fake_page = page(fake_drw, files[fake_drw], 1, "claude-haiku-5-5", "model")
        user_page = page(fake_drw, files[fake_drw], 2, None, "user")
        real_page = page(real_drw, files[real_drw], 1, "claude-haiku-5-5", "model")
        reused = page(reuse_drw, files[reuse_drw], 1, "claude-haiku-5-5", "reused", reused_from=fake_page["id"])
        with owner.begin() as c:
            c.execute(text("INSERT INTO plans (id, name_he) VALUES ('p', 'p')"))
            c.execute(text("INSERT INTO tenants (id, name, plan_id) VALUES (:t, 'מפעל', 'p')"), {"t": T})
            for d in files:
                c.execute(text("INSERT INTO drawings (id, tenant_id) VALUES (:d, :t)"), {"d": d, "t": T})
                c.execute(
                    text(
                        "INSERT INTO drawing_files (id, tenant_id, drawing_id, original_name, detected_format,"
                        " sha256, size_bytes, storage_key) VALUES (:f, :t, :d, 'a.pdf', 'pdf', 'x', 1, 'k')"
                    ),
                    {"f": files[d], "t": T, "d": d},
                )
            for p in (fake_page, user_page, real_page, reused):
                c.execute(
                    text(
                        "INSERT INTO pages (id, tenant_id, drawing_id, file_id, page_no, model, classified_by,"
                        " reused_from) VALUES (:id, :t, :d, :f, :no, :m, :by, :r)"
                    ),
                    p,
                )
            for d, provider in ((fake_drw, "fake"), (real_drw, "anthropic")):
                c.execute(
                    text(
                        "INSERT INTO llm_calls (id, tenant_id, stage, provider, model, input_tokens, output_tokens,"
                        " latency_ms, attempts, drawing_id) VALUES (:id, :t, 'page_classification', :p,"
                        " 'claude-haiku-5-5', 1, 1, 1, 1, :d)"
                    ),
                    {"id": new_id("llm"), "t": T, "p": provider, "d": d},
                )

        command.upgrade(cfg, "0013")
        command.upgrade(cfg, "0013")  # already at head: nothing runs twice
        with owner.connect() as c:
            models = dict(c.execute(text("SELECT id, model FROM pages")).all())  # type: ignore[arg-type]
        assert models[fake_page["id"]] == "stand-in:claude-haiku-5-5"
        assert models[reused["id"]] == "stand-in:claude-haiku-5-5"  # reused from a stand-in page
        assert models[real_page["id"]] == "claude-haiku-5-5"  # Claude classified it: untouched
        assert models[user_page["id"]] is None  # a person classified it

        command.downgrade(cfg, "0012")
        with owner.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pages WHERE model LIKE 'stand-in:%'")).scalar_one() == 0
    owner.dispose()
