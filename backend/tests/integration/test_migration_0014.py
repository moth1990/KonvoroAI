"""BUG-042, BUG-043: migration 0014 marks stub pages, pages a person fixed after the stand-in, and their reuses."""

from typing import Any

from alembic import command
from sqlalchemy import Connection, create_engine, text

from konboro.db.admin import database_dsn, ensure_app_role, migrating, recreate_database
from konboro.db.ids import new_id

T = new_id("tnt")


def add_drawing(c: Connection, classified_by_provider: str | None = None) -> tuple[str, str]:
    drawing, file = new_id("drw"), new_id("fil")
    c.execute(text("INSERT INTO drawings (id, tenant_id) VALUES (:d, :t)"), {"d": drawing, "t": T})
    c.execute(
        text(
            "INSERT INTO drawing_files (id, tenant_id, drawing_id, original_name, detected_format, sha256,"
            " size_bytes, storage_key) VALUES (:f, :t, :d, 'a.pdf', 'pdf', 'x', 1, 'k')"
        ),
        {"f": file, "t": T, "d": drawing},
    )
    if classified_by_provider:
        c.execute(
            text(
                "INSERT INTO llm_calls (id, tenant_id, stage, provider, model, input_tokens, output_tokens,"
                " latency_ms, attempts, drawing_id) VALUES (:id, :t, 'page_classification', :p,"
                " 'claude-haiku-5-5', 1, 1, 1, 1, :d)"
            ),
            {"id": new_id("llm"), "t": T, "p": classified_by_provider, "d": drawing},
        )
    return drawing, file


def add_page(c: Connection, where: tuple[str, str], no: int, model: str | None, by: str, reused: Any = None) -> str:
    page = new_id("pg")
    c.execute(
        text(
            "INSERT INTO pages (id, tenant_id, drawing_id, file_id, page_no, model, classified_by, reused_from)"
            " VALUES (:id, :t, :d, :f, :no, :m, :by, :r)"
        ),
        {"id": page, "t": T, "d": where[0], "f": where[1], "no": no, "m": model, "by": by, "r": reused},
    )
    return page


def test_marks_made_up_pages_and_leaves_real_ones() -> None:
    name = "konboro_migration_0014"
    recreate_database(name)
    ensure_app_role(database_dsn("postgres"))
    owner = create_engine(database_dsn(name))
    with migrating(database_dsn(name)) as cfg:
        command.upgrade(cfg, "0013")
        with owner.begin() as c:
            c.execute(text("INSERT INTO plans (id, name_he) VALUES ('p', 'p')"))
            c.execute(text("INSERT INTO tenants (id, name, plan_id) VALUES (:t, 'מפעל', 'p')"), {"t": T})
            # The user's case: the stand-in read the drawing, the user fixed every kind, the file came again twice.
            first = add_drawing(c, "fake")
            fixed = add_page(c, first, 1, None, "user")
            second = add_drawing(c)
            reused_once = add_page(c, second, 1, None, "reused", fixed)
            third = add_drawing(c)
            reused_twice = add_page(c, third, 1, None, "reused", reused_once)
            # A golden PDF from the S05 stub, one page fixed by a person, and a later copy of it.
            stub = add_drawing(c)
            stub_page = add_page(c, stub, 1, "stub-s05", "model")
            stub_fixed = add_page(c, stub, 2, None, "user")
            from_stub = add_page(c, add_drawing(c), 1, "stub-s05", "reused", stub_page)
            # Real Claude read it, and a person fixed one page: both stay reusable.
            real = add_drawing(c, "anthropic")
            real_page = add_page(c, real, 1, "claude-haiku-5-5", "model")
            real_fixed = add_page(c, real, 2, None, "user")
            # A template page: classified by code, never by a model.
            template = add_page(c, add_drawing(c), 1, None, "template")

        command.upgrade(cfg, "0014")
        with owner.connect() as c:
            models = dict(c.execute(text("SELECT id, model FROM pages")).tuples().all())
        assert models[fixed] == "stand-in:unknown"
        assert models[reused_once] == "stand-in:unknown"
        assert models[reused_twice] == "stand-in:unknown"
        assert models[stub_page] == "stand-in:stub-s05"
        assert models[stub_fixed] == "stand-in:unknown"
        assert models[from_stub] == "stand-in:stub-s05"
        assert models[real_page] == "claude-haiku-5-5"
        assert models[real_fixed] is None
        assert models[template] is None

        command.downgrade(cfg, "0013")
        with owner.connect() as c:
            back = dict(c.execute(text("SELECT id, model FROM pages")).tuples().all())
        assert back[stub_page] == "stub-s05" and back[fixed] is None and back[real_page] == "claude-haiku-5-5"
    owner.dispose()
