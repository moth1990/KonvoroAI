"""the live decoding screen (S28c, 01 §4.6, 13 §4.11)

- `pipeline_events` (`pev_`): what each stage reports while it runs, written from templates in code, never by a
  model: `message` (the live sentence and the log), `counters` and `boxes` (the page view). A tenant table: RLS,
  forced, and the app role's grants, like every table in 0001.
- `llm_calls` keeps every attempt's cost (01 §4.6 "עלות"): the cache tokens, `ok` (false for a call that never gave a
  valid answer, which used to write no row), `cost_usd` priced in code when the row is written (S28c decision 2), and
  `pipeline_stage`, the stage (1–8) of a pipeline call, null for chat. Indexed by drawing, for the run's cost.
- `konboro_stage_medians(interval)`: the median seconds and dollars per page unit of each stage, across every
  factory, for the time left before a factory has its own 20 runs (01 §4.6 "זמן שנותר"). It returns aggregates only.
  The app role reads one tenant at a time, so the function is SECURITY DEFINER, owned by `konboro_stats`: a NOLOGIN
  role with no BYPASSRLS, column-level SELECT on the four tables and a read-only policy on each, like
  `konboro_sweeper` in 0004. `services/run_estimate.MEDIANS_SQL` is the same query for one factory; a test keeps
  the two equal.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-08 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
STATS = "konboro_stats"
TENANT = "current_setting('app.tenant_id', true)"  # as in 0001
FUNCTION = "konboro_stage_medians(interval)"
READS = {
    "drawings": "tenant_id, id, status",
    "stage_runs": "tenant_id, drawing_id, stage, status, started_at, finished_at",
    "pages": "tenant_id, drawing_id, route",
    "llm_calls": "tenant_id, drawing_id, pipeline_stage, cost_usd",
}

# Page units: stage 1 reads every page; the others work on the decoded pages, a context page a quarter of one
# (services/run_estimate.py ROUTE_WEIGHT). Only finished, successful runs count.
MEDIANS = """
  WITH units AS (
    SELECT tenant_id, drawing_id,
           count(*)::float8 AS every_page,
           (count(*) FILTER (WHERE route = 'process') + 0.25 * count(*) FILTER (WHERE route = 'context'))::float8
             AS work
      FROM pages
     GROUP BY tenant_id, drawing_id
  ), cost AS (
    SELECT tenant_id, drawing_id, pipeline_stage AS stage, sum(cost_usd)::float8 AS usd
      FROM llm_calls
     WHERE drawing_id IS NOT NULL AND pipeline_stage IS NOT NULL
     GROUP BY tenant_id, drawing_id, pipeline_stage
  ), runs AS (
    SELECT r.stage,
           CASE WHEN r.stage = 1 THEN u.every_page ELSE u.work END AS n,
           extract(epoch FROM r.finished_at - r.started_at)::float8 AS seconds,
           coalesce(c.usd, 0) AS usd
      FROM stage_runs r
      JOIN drawings d ON d.tenant_id = r.tenant_id AND d.id = r.drawing_id
      JOIN units u ON u.tenant_id = r.tenant_id AND u.drawing_id = r.drawing_id
      LEFT JOIN cost c ON c.tenant_id = r.tenant_id AND c.drawing_id = r.drawing_id AND c.stage = r.stage
     WHERE d.status = 'ready' AND r.status = 'done'
       AND r.started_at IS NOT NULL AND r.finished_at > now() - $1
  )
  SELECT stage::smallint, count(*)::bigint,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds / n),
         percentile_cont(0.5) WITHIN GROUP (ORDER BY usd / n)
    FROM runs
   WHERE n > 0
   GROUP BY stage
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("drawing_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('message', 'counters', 'boxes')", name=op.f("ck_pipeline_events_kind")),
        sa.CheckConstraint("stage BETWEEN 1 AND 8", name=op.f("ck_pipeline_events_stage")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "drawing_id"],
            ["drawings.tenant_id", "drawings.id"],
            name=op.f("fk_pipeline_events_tenant_id_drawing_id_drawings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_pipeline_events_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_events")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_pipeline_events_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_pipeline_events_tenant_id_drawing_id_created_at"),
        "pipeline_events",
        ["tenant_id", "drawing_id", "created_at"],
    )
    op.execute("ALTER TABLE pipeline_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pipeline_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON pipeline_events "
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pipeline_events TO {APP_ROLE}")

    op.add_column("llm_calls", sa.Column("cache_read_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("ok", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("llm_calls", sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False))
    op.add_column("llm_calls", sa.Column("pipeline_stage", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "pipeline_stage", "llm_calls", "pipeline_stage IS NULL OR pipeline_stage BETWEEN 1 AND 8"
    )
    op.create_index(op.f("ix_llm_calls_tenant_id_drawing_id"), "llm_calls", ["tenant_id", "drawing_id"])

    # Roles are cluster-wide: create it once, without login. It can't bypass RLS; its own policies let it read.
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{STATS}') "
        f"THEN CREATE ROLE {STATS} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {STATS}")
    for table, columns in READS.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {STATS}")
        op.execute(f"CREATE POLICY stage_stats ON {table} FOR SELECT TO {STATS} USING (true)")
    op.execute(f"""
        CREATE FUNCTION {FUNCTION}
        RETURNS TABLE (stage smallint, runs bigint, seconds_per_unit float8, usd_per_unit float8)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        {MEDIANS}
        $$""")
    # Handing the function over needs membership in the role (0004).
    op.execute(f"GRANT {STATS} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {STATS}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP FUNCTION {FUNCTION}")
    for table in READS:
        op.execute(f"DROP POLICY stage_stats ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {STATS}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {STATS}")
    # The role stays: other databases in the cluster (test, e2e, eval) may still use it.
    op.drop_index(op.f("ix_llm_calls_tenant_id_drawing_id"), table_name="llm_calls")
    op.drop_constraint("pipeline_stage", "llm_calls", type_="check")
    for column in ("pipeline_stage", "cost_usd", "ok", "cache_write_tokens", "cache_read_tokens"):
        op.drop_column("llm_calls", column)
    op.drop_index(op.f("ix_pipeline_events_tenant_id_drawing_id_created_at"), table_name="pipeline_events")
    op.drop_table("pipeline_events")
