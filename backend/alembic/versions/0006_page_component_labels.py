"""page component labels: keep the classifier's reading of the device tags with the page (S08, BUG-015)

- `pages.component_labels`: `tags_and_models`, `tags_only`, `none` or `not_applicable`, as the classifier answered
  (01 §5.4). `input_kind` counts them on the diagram pages (01 §4.4), so a page reused by hash (01 §5.1) needs
  them too; without them the same factory drawing, uploaded again, became a designer's plan. Null for a page
  classified before this column, by a template, or by the user.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01 06:05:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABELS = ("tags_and_models", "tags_only", "none", "not_applicable")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pages", sa.Column("component_labels", sa.Text(), nullable=True))
    op.create_check_constraint(
        "component_labels",
        "pages",
        "component_labels IS NULL OR component_labels IN (" + ", ".join(f"'{v}'" for v in LABELS) + ")",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("component_labels", "pages", type_="check")
    op.drop_column("pages", "component_labels")
