"""stage 7: pricing and versions (S22, 07)

- `derived_item_rules.rule_key`: the starter rule a tenant's row is a copy of (`enclosure`, `din_rail`…), unique per
  tenant, so a deleted derived line names its rule across reruns (07 §7). `params`: the rule's numbers (spare share,
  per output, consumables percentage). `approval`: `pending_expert` until the electrical expert signs the starter
  pack off (roadmap B2, S22 decision 3). `quantity_formula` holds the rule's kind, the function that works it out.
- `quote_lines.line_key`: stage 7's handle for a line, stable for the same input (`c:<component>`,
  `d:<panel>:<rule>`), so a rerun carries what the user did on the line (S22 decision 5).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("derived_item_rules", sa.Column("rule_key", sa.Text(), nullable=True))
    op.execute("UPDATE derived_item_rules SET rule_key = id WHERE rule_key IS NULL")
    op.alter_column("derived_item_rules", "rule_key", nullable=False)
    op.add_column(
        "derived_item_rules",
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column("derived_item_rules", sa.Column("approval", sa.Text(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_derived_item_rules_tenant_id_rule_key"), "derived_item_rules", ["tenant_id", "rule_key"]
    )
    op.add_column("quote_lines", sa.Column("line_key", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("quote_lines", "line_key")
    op.drop_constraint(op.f("uq_derived_item_rules_tenant_id_rule_key"), "derived_item_rules", type_="unique")
    op.drop_column("derived_item_rules", "approval")
    op.drop_column("derived_item_rules", "params")
    op.drop_column("derived_item_rules", "rule_key")
