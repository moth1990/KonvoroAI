"""the chat layer (S25, 08)

- `chat_conversations.state`: what the conversation has shown the model, kept on the server (08 §5.4): the short
  names it was given for lines, panels, findings and proposals (`L3`, `B1`, `F2`, `CH1`), and every money reference
  (`$T1`) with its amount. The model sees only the names; the screen gets the amounts.
- `chat_proposals`: `warnings`, `affected_line_count`, `alias` (`CH1`), and `undone`, a proposal applied and then
  taken back from the review screen's undo (08 §7.5).
- correction type `discount_set`: the customer discount on the quote (08 §6.7 `set_customer_discount`).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-04 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = (
    "row_confirmed",
    "sku_replaced",
    "attribute_changed",
    "quantity_changed",
    "row_deleted",
    "derived_removed",
    "derived_restored",
    "issue_dismissed",
    "missing_resolved",
    "component_marked",
    "page_reclassified",
    "page_reuploaded",
    "price_entered",
    "brand_discount_set",
    "undo",
    "quote_sent",
    "price_changed",
    "supplier_selected",
    "bom_columns_mapped",
)
STATUSES = ("pending", "applied", "dismissed", "expired")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chat_conversations",
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column(
        "chat_proposals",
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    op.add_column("chat_proposals", sa.Column("affected_line_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("chat_proposals", sa.Column("alias", sa.Text(), nullable=True))
    op.drop_constraint("status", "chat_proposals", type_="check")
    op.create_check_constraint("status", "chat_proposals", _in("status", (*STATUSES, "undone")))
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", (*TYPES, "discount_set")))


def downgrade() -> None:
    """Downgrade schema. Fails while a `discount_set` event exists (correction events are append-only)."""
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", TYPES))
    op.execute("UPDATE chat_proposals SET status = 'applied' WHERE status = 'undone'")
    op.drop_constraint("status", "chat_proposals", type_="check")
    op.create_check_constraint("status", "chat_proposals", _in("status", STATUSES))
    op.drop_column("chat_proposals", "alias")
    op.drop_column("chat_proposals", "affected_line_count")
    op.drop_column("chat_proposals", "warnings")
    op.drop_column("chat_conversations", "state")
