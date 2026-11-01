"""page tile count: how many of a page's tiles go on to symbol detection (S10)

- `pages.tile_count`: the page's tiles that are not blank (02 §2.6, §7), written by stage 2. The run step's stage-2
  line counts them ("OCR על 6 עמודים · 58 אריחים", prototype line 762) without reading the stage's output from S3.
  Null until stage 2 has run on the page, and for pages stage 2 doesn't process.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pages", sa.Column("tile_count", sa.Integer(), nullable=True))
    op.create_check_constraint("tile_count", "pages", "tile_count IS NULL OR tile_count >= 0")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("tile_count", "pages", type_="check")
    op.drop_column("pages", "tile_count")
