"""quote audit (S15, 11)

- `audit_quote_lines`: the audited quote's lines as read, signed and matched (11 §5.2–5.3). A tenant table: RLS,
  forced, and the app role's grants, like every table in 0001.
- `audit_differences`: the nine types (11 §5.4 and `not_a_difference`, S15 decision 4), severity `info`, the user's
  decision (who, when, a reason from 11 §7's list and a note), and the components a difference points at.
- `audits.issues`: what reading the quote reported.
- `drawing_files.role`: `audited_quote` for the quote uploaded with the drawing; stage 1 skips it.
- `stage_runs.stage` and `drawings.current_stage` reach 8: the audit step (S15 decision 2).
- `tenant_settings.auxiliary_families`: the factory's auxiliary material, seeded with terminals (S15 decision 4).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-02 12:48:36

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
TENANT = "current_setting('app.tenant_id', true)"  # as in 0001
TYPES = (
    "missing_in_quote",
    "qty_short",
    "qty_over",
    "possible_double_count",
    "attribute_mismatch",
    "extra_in_quote",
    "arithmetic",
    "drawing_conflict",
    "not_a_difference",
)
REASONS = ("included_elsewhere", "customer_supplies", "system_error", "other")
LINE_STATUS = ("matched", "quantity_differs", "attribute_differs", "not_in_drawing", "arithmetic")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_quote_lines",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("audit_id", sa.Text(), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("confidence", sa.Double(), server_default="1", nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("rows", sa.ARRAY(sa.Integer()), server_default="{}", nullable=False),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("signature", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("component_ids", sa.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("matched_qty", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("status", LINE_STATUS), name=op.f("ck_audit_quote_lines_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "audit_id"],
            ["audits.tenant_id", "audits.id"],
            name=op.f("fk_audit_quote_lines_tenant_id_audit_id_audits"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_audit_quote_lines_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_quote_lines")),
        sa.UniqueConstraint(
            "tenant_id", "audit_id", "line_index", name=op.f("uq_audit_quote_lines_tenant_id_audit_id_line_index")
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_audit_quote_lines_tenant_id_id")),
    )
    op.execute("ALTER TABLE audit_quote_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_quote_lines FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_quote_lines "
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON audit_quote_lines TO {APP_ROLE}")

    op.add_column("audit_differences", sa.Column("reject_note", sa.Text(), nullable=True))
    op.add_column(
        "audit_differences", sa.Column("component_ids", sa.ARRAY(sa.Text()), server_default="{}", nullable=False)
    )
    op.add_column("audit_differences", sa.Column("decided_by", sa.Text(), nullable=True))
    op.add_column("audit_differences", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_audit_differences_tenant_id_decided_by_users"),
        "audit_differences",
        "users",
        ["tenant_id", "decided_by"],
        ["tenant_id", "id"],
    )
    op.drop_constraint("severity", "audit_differences", type_="check")
    op.create_check_constraint("severity", "audit_differences", _in("severity", ("high", "medium", "low", "info")))
    op.create_check_constraint("type", "audit_differences", _in("type", TYPES))
    op.create_check_constraint(
        "reject_reason", "audit_differences", "reject_reason IS NULL OR " + _in("reject_reason", REASONS)
    )

    op.add_column(
        "audits", sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False)
    )
    op.add_column("drawing_files", sa.Column("role", sa.Text(), server_default="drawing", nullable=False))
    op.create_check_constraint("role", "drawing_files", _in("role", ("drawing", "audited_quote")))
    op.add_column(
        "tenant_settings",
        sa.Column("auxiliary_families", sa.ARRAY(sa.Text()), server_default="{terminal}", nullable=False),
    )

    op.drop_constraint("stage", "stage_runs", type_="check")
    op.create_check_constraint("stage", "stage_runs", "stage BETWEEN 1 AND 8")
    op.drop_constraint("current_stage", "drawings", type_="check")
    op.create_check_constraint("current_stage", "drawings", "current_stage IS NULL OR current_stage BETWEEN 1 AND 8")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM stage_runs WHERE stage = 8")
    op.execute("UPDATE drawings SET current_stage = 7 WHERE current_stage = 8")
    op.drop_constraint("current_stage", "drawings", type_="check")
    op.create_check_constraint("current_stage", "drawings", "current_stage IS NULL OR current_stage BETWEEN 1 AND 7")
    op.drop_constraint("stage", "stage_runs", type_="check")
    op.create_check_constraint("stage", "stage_runs", "stage BETWEEN 1 AND 7")

    op.drop_column("tenant_settings", "auxiliary_families")
    op.drop_constraint("role", "drawing_files", type_="check")
    op.drop_column("drawing_files", "role")
    op.drop_column("audits", "issues")

    op.execute("DELETE FROM audit_differences WHERE severity = 'info'")
    op.drop_constraint("reject_reason", "audit_differences", type_="check")
    op.drop_constraint("type", "audit_differences", type_="check")
    op.drop_constraint("severity", "audit_differences", type_="check")
    op.create_check_constraint("severity", "audit_differences", _in("severity", ("high", "medium", "low")))
    op.drop_constraint(op.f("fk_audit_differences_tenant_id_decided_by_users"), "audit_differences", type_="foreignkey")
    op.drop_column("audit_differences", "decided_at")
    op.drop_column("audit_differences", "decided_by")
    op.drop_column("audit_differences", "component_ids")
    op.drop_column("audit_differences", "reject_note")
    op.drop_table("audit_quote_lines")
