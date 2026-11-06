"""the chat quote builder (S27, 13 §4.2)

- `drawings.origin`: `upload` (files, through the pipeline's queues) or `chat` (no files: the estimator describes the
  panel on `/build`, and each message runs stages 4–7 in the request; S27 design 1–2). A chat drawing is `bom_only`.
- `build_messages` (`bmg_`): the build's conversation, by drawing, since the quote exists only from the first line
  (S27 decision 2). `content` keeps the text, what a recording was heard as, the items and changes the code check
  kept, the rows before the message (for undo) and the reply. A tenant table: RLS, forced, and the app role's
  grants, like every table in 0001.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-06 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
TENANT = "current_setting('app.tenant_id', true)"  # as in 0001


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("drawings", sa.Column("origin", sa.Text(), server_default="upload", nullable=False))
    op.create_check_constraint("origin", "drawings", "origin IN ('upload', 'chat')")

    op.create_table(
        "build_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("drawing_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="applied", nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_build_messages_role")),
        sa.CheckConstraint(
            "status IN ('applied', 'pending', 'dismissed', 'undone')", name=op.f("ck_build_messages_status")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "drawing_id"],
            ["drawings.tenant_id", "drawings.id"],
            name=op.f("fk_build_messages_tenant_id_drawing_id_drawings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_build_messages_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_build_messages")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_build_messages_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_build_messages_tenant_id_drawing_id_created_at"),
        "build_messages",
        ["tenant_id", "drawing_id", "created_at"],
    )
    op.execute("ALTER TABLE build_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE build_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON build_messages "
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON build_messages TO {APP_ROLE}")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_build_messages_tenant_id_drawing_id_created_at"), table_name="build_messages")
    op.drop_table("build_messages")
    op.drop_constraint("origin", "drawings", type_="check")
    op.drop_column("drawings", "origin")
