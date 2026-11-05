"""the chat layer II (S25b, 08 §6.4–6.5, §7.4)

- `quote_lines.signature` and `quote_lines.brand_context`: the component's signature and the brand context stage 5
  matched it in (05 §3, §5.3), kept on the line by stage 7. `compare` with another quote pairs lines by signature
  (08 §6.5), and a proposal remembered for a customer or the factory writes the match memory under the line's
  signature and context (08 §7.4, 05 §11). A quote with no stage outputs (the review fixtures) has them too.
- `chat_proposals.remember_options` (08 §7.1) and `chat_proposals.remembered`, the scope the estimator chose on
  "החל".
- correction type `memory_saved`: the match memory a chat proposal wrote, with what undo puts back.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-05 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
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
    "discount_set",
)
SCOPES = ("quote_only", "customer", "tenant")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("quote_lines", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column("quote_lines", sa.Column("brand_context", sa.Text(), nullable=True))
    op.add_column(
        "chat_proposals",
        sa.Column(
            "remember_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='["quote_only"]',
            nullable=False,
        ),
    )
    op.add_column("chat_proposals", sa.Column("remembered", sa.Text(), nullable=True))
    op.create_check_constraint("remembered", "chat_proposals", "remembered IS NULL OR " + _in("remembered", SCOPES))
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", (*OLD_TYPES, "memory_saved")))


def downgrade() -> None:
    """Downgrade schema. Fails while a `memory_saved` event exists (correction events are append-only)."""
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", OLD_TYPES))
    op.drop_constraint("remembered", "chat_proposals", type_="check")
    op.drop_column("chat_proposals", "remembered")
    op.drop_column("chat_proposals", "remember_options")
    op.drop_column("quote_lines", "brand_context")
    op.drop_column("quote_lines", "signature")
