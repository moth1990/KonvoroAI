"""stage requeue: find stage messages that were never delivered, across tenants, by IDs only (S07 decision)

A stage's message is sent after its transaction commits: stage 1 by the upload, every other stage by the stage
before it. If that send fails, or the process dies first, the drawing waits forever. `stage_runs.sent_at` records
when the message went out, and `konboro_unsent_stages(older_than)` lists the stages whose message went out that
long ago but that no worker ever claimed.

The worker runs as `konboro_app`, which RLS keeps inside one tenant, so the lookup is a SECURITY DEFINER function
owned by `konboro_sweeper`: a NOLOGIN role with no BYPASSRLS, column-level SELECT on the two tables, and a
read-only policy of its own. The function returns `(tenant_id, drawing_id, stage, trace_id)` and nothing else; the
worker re-checks every row inside that tenant's session before it sends anything (docs/db-schema.md §2).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 22:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
SWEEPER = "konboro_sweeper"
FUNCTION = "konboro_unsent_stages(interval)"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stage_runs", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    # Drawings already waiting on stage 1 count as sent now, so the sweep can pick them up.
    op.execute(
        "UPDATE stage_runs r SET sent_at = now() FROM drawings d "
        "WHERE d.tenant_id = r.tenant_id AND d.id = r.drawing_id AND r.stage = 1 AND d.status = 'uploaded'"
    )

    # Roles are cluster-wide: create it once, without login. It can't bypass RLS; its own policies let it read.
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{SWEEPER}') "
        f"THEN CREATE ROLE {SWEEPER} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {SWEEPER}")
    op.execute(f"GRANT SELECT (tenant_id, drawing_id, stage, status, attempts, sent_at) ON stage_runs TO {SWEEPER}")
    op.execute(f"GRANT SELECT (tenant_id, id, status, trace_id) ON drawings TO {SWEEPER}")
    for table in ("stage_runs", "drawings"):
        op.execute(f"CREATE POLICY requeue_sweep ON {table} FOR SELECT TO {SWEEPER} USING (true)")

    op.execute("""
        CREATE FUNCTION konboro_unsent_stages(interval)
        RETURNS TABLE (tenant_id text, drawing_id text, stage smallint, trace_id text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT r.tenant_id, r.drawing_id, r.stage, d.trace_id
            FROM stage_runs r
            JOIN drawings d ON d.tenant_id = r.tenant_id AND d.id = r.drawing_id
           WHERE d.status IN ('uploaded', 'processing')
             AND r.status = 'queued' AND r.attempts = 0
             AND r.sent_at < now() - $1
           ORDER BY r.sent_at
           LIMIT 100
        $$""")
    # Handing the function over needs membership in the role. A superuser has it already; on RDS the migration
    # user gets it from this grant (PG16 gives a role's creator ADMIN on it, not membership).
    op.execute(f"GRANT {SWEEPER} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {SWEEPER}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP FUNCTION {FUNCTION}")
    for table in ("stage_runs", "drawings"):
        op.execute(f"DROP POLICY requeue_sweep ON {table}")
    op.execute(f"REVOKE ALL ON stage_runs, drawings FROM {SWEEPER}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {SWEEPER}")
    # The role stays: other databases in the cluster (test, e2e, eval) may still use it.
    op.drop_column("stage_runs", "sent_at")
