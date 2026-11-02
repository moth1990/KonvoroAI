"""correction type `bom_columns_mapped`: the user set a BOM spreadsheet's column roles (01 §5.8, S14 decision 1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02 12:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "bom_columns_mapped"
BEFORE = (
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
)


def _types(types: Sequence[str]) -> str:
    return "type IN (" + ", ".join(f"'{t}'" for t in types) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _types((*BEFORE, NEW)))


def downgrade() -> None:
    """Downgrade schema. Correction events are append-only (a trigger refuses deletes), so this fails while any
    `bom_columns_mapped` event exists."""
    op.drop_constraint("type", "correction_events", type_="check")
    op.create_check_constraint("type", "correction_events", _types(BEFORE))
