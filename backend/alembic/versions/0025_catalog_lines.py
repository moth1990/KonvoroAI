"""quote lines from the catalog, one line per product in a panel (S27b, 07 §7.1, 13 §4.10)

- `products.attributes`, `series`, `model_code`, `symbol_class`: a product made in "מוצר חדש" (09 §7.16) has the
  family's attributes and a model, so stage 5 matches it on the next drawing (05 §5.6) and its name is built the app's
  way (`text.describe`). A product typed in the price list keeps `{}` and nulls.
- `quote_lines.component_ids`: every component of a merged line (07 §6.2); `component_id` stays the first of them.
- `quote_lines.pending`: a line waiting for a decision, with no product (07 §7.1). Sending is refused while one is left
  (09 §7.12).
- `quote_versions.component_edits`: what the estimator chose for a component (a product, an alternative, an attribute,
  a missing line resolved), by the component's line key (`c:…`, `m:…`). Kept on the version, not on a line: the choice
  moves the component to its product's line, whose key changes, and undo puts the map back whole (S27b).
- correction type `product_created`: "מוצר חדש" made a factory product from a waiting line (09 §7.16).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-06 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
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
    "discount_set",
    "memory_saved",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products",
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column("products", sa.Column("series", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("model_code", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("symbol_class", sa.Text(), nullable=True))
    op.add_column(
        "quote_lines",
        sa.Column("component_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    op.add_column("quote_lines", sa.Column("pending", sa.Boolean(), server_default="false", nullable=False))
    op.add_column(
        "quote_versions",
        sa.Column("component_edits", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", (*TYPES, "product_created")))


def downgrade() -> None:
    """Downgrade schema. Fails while a `product_created` event exists (correction events are append-only)."""
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _in("type", TYPES))
    op.drop_column("quote_versions", "component_edits")
    op.drop_column("quote_lines", "pending")
    op.drop_column("quote_lines", "component_ids")
    op.drop_column("products", "symbol_class")
    op.drop_column("products", "model_code")
    op.drop_column("products", "series")
    op.drop_column("products", "attributes")
