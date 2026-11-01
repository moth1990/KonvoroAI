"""page symbol counts: stage 3's numbers for the run step (S12)

- `pages.symbol_count`: the page's detections, written by stage 3.
- `pages.symbol_llm_count`: of them, the ones the disambiguation call decided (03 §3.4).
The run step's stage-3 line ("61 סימנים · 54 מהספרייה, 7 בהכרעת מודל", prototype line 763) counts them without
reading the stage's output from S3. Null until stage 3 has run on the page.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01 19:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pages", sa.Column("symbol_count", sa.Integer(), nullable=True))
    op.add_column("pages", sa.Column("symbol_llm_count", sa.Integer(), nullable=True))
    op.create_check_constraint("symbol_count", "pages", "symbol_count IS NULL OR symbol_count >= 0")
    op.create_check_constraint(
        "symbol_llm_count", "pages", "symbol_llm_count IS NULL OR symbol_llm_count BETWEEN 0 AND symbol_count"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("symbol_llm_count", "pages", type_="check")
    op.drop_constraint("symbol_count", "pages", type_="check")
    op.drop_column("pages", "symbol_llm_count")
    op.drop_column("pages", "symbol_count")
