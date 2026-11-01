"""page templates and the drawing's title block (S08, 01 §5.4 and §5.7)

- `page_templates`: a factory's fixed pages (conductor colours, torques, signs), fingerprinted with the title
  block masked, so the next drawing from the same producer classifies them without a model call. A tenant table:
  RLS, forced, and the app role's grants, like every table in 0001.
- `drawings.title_block`: the title block, read once per drawing from a crop of the region the classifier found.
- `correction_events.source` gains `new_quote`: a page kind changed on the new-quote screen (01 §5.6).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01 00:13:41

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
TENANT = "current_setting('app.tenant_id', true)"  # as in 0001
SOURCES = ("review_screen", "chat", "price_list")


def _sources(values: Sequence[str]) -> str:
    return "source IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "page_templates",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=True),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("mask", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("source_page_id", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_page_templates_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_templates")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_page_templates_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_page_templates_tenant_id_producer"), "page_templates", ["tenant_id", "producer"], unique=False
    )
    op.execute("ALTER TABLE page_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE page_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON page_templates USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON page_templates TO {APP_ROLE}")

    op.add_column("drawings", sa.Column("title_block", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.drop_constraint("source", "correction_events", type_="check")
    op.create_check_constraint("source", "correction_events", _sources((*SOURCES, "new_quote")))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("source", "correction_events", type_="check")
    op.create_check_constraint("source", "correction_events", _sources(SOURCES))
    op.drop_column("drawings", "title_block")
    op.drop_index(op.f("ix_page_templates_tenant_id_producer"), table_name="page_templates")
    op.drop_table("page_templates")
