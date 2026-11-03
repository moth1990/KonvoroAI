"""stage 6: validation (S21, 06)

- `validator_rules.title_he`: a finding's headline, beside its message (S21 decision 11). `approval`: who still has
  to sign a rule off; `pending_expert` for category A until the electrical expert does (06 §13 item 2, S21 decision 7).
- `validator_rules.requires` also takes `front_view` (a front view's designators, S21 decision 2) and `text_layer`
  (the stage-2 spans the coverage check counts).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-03 14:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "requires IS NULL OR requires IN ('wire_graph', 'bom_table')"
NEW = "requires IS NULL OR requires IN ('wire_graph', 'bom_table', 'front_view', 'text_layer')"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("validator_rules", sa.Column("title_he", sa.Text(), server_default="", nullable=False))
    op.add_column("validator_rules", sa.Column("approval", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_validator_rules_requires"), "validator_rules", type_="check")
    op.create_check_constraint(op.f("ck_validator_rules_requires"), "validator_rules", NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM validator_rules WHERE requires IN ('front_view', 'text_layer')")
    op.drop_constraint(op.f("ck_validator_rules_requires"), "validator_rules", type_="check")
    op.create_check_constraint(op.f("ck_validator_rules_requires"), "validator_rules", OLD)
    op.drop_column("validator_rules", "approval")
    op.drop_column("validator_rules", "title_he")
