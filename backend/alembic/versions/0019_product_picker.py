"""product picker (S23b, 09 §6.4, §6.6, §7.8)

- `quote_lines.boxes`: where a line with no component is on the drawing, as `[{page_id, bbox}]` in PDF points (00
  §6.2): a missing line's instance (04 §6.2 `missing[]`) and a component the estimator marked (09 §6.6). A component
  line's boxes stay its component's instances.
- The `review_screen` flag is gone (S23 decision 8): the review screen is complete, and every tenant has it. Its
  overrides and plan rows go with it; a downgrade puts the flag back, on.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-04 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "quote_lines",
        sa.Column("boxes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    op.execute("DELETE FROM tenant_feature_overrides WHERE flag_key = 'review_screen'")
    op.execute("DELETE FROM plan_feature_flags WHERE flag_key = 'review_screen'")
    op.execute("DELETE FROM feature_flags WHERE key = 'review_screen'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "INSERT INTO feature_flags (key, description, depends_on) "
        "VALUES ('review_screen', 'מסך הבדיקה', '{}') ON CONFLICT DO NOTHING"
    )
    op.drop_column("quote_lines", "boxes")
