"""review actions (S23, 09 §7)

- `quote_lines.edits`: what the estimator changed on a line, besides its price, approval and deletion: `qty`, the
  `supplier_id` chosen for this quote only (07 §7.2.2 step 1), and an alternative `replaced` the SKU with (09 §7.3).
  Carried by `line_key` through a recalculation and a rerun, like `override` (S22 decision 5).
- `findings.dismissal`: why the estimator dismissed a finding (09 §7.7, 06 §11): `reason` (`intended`,
  `checker_wrong`, `other` or `approved`), its `text`, who and when, and the event.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-03 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "quote_lines",
        sa.Column("edits", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column("findings", sa.Column("dismissal", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("findings", "dismissal")
    op.drop_column("quote_lines", "edits")
