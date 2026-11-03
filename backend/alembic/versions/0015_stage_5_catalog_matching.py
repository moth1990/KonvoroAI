"""stage 5: catalog matching (S20, 05)

- `catalog_items.symbol_class`: the class within the family (`mcb`, `mccb`, `motor_protection`), which stage 5
  narrows by (05 §5.1 item 2). `catalog_items.model_tokens`: the model codes as drawings write them (05 §5.2.1),
  filled from `model_code` for the rows already there.
- `catalog_kits` and `catalog_accessories`: global, read-only for the app like every global table in 0001. A kit's
  part (the RCD module of a combined breaker) and which accessory fits which series (05 §5.9.1, S20 decision 4).
- `components.match_status`, `components.catalog_item_id`: stage 5's result, for the run step and for what points at
  a component; `auxiliary` for a family the factory counts as auxiliary material (S20 decision 3).
- `tenant_settings.matching`: the factory's series, allowed alternate brands, tie-break (05 §13 item 1) and the
  inference rules it turned off.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-03 09:02:29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
SOURCES = "source IN ('curated', 'pilot_engineer', 'import')"
MATCH_STATUS = "match_status IN ('matched', 'ambiguous', 'unmatched', 'conflict', 'auxiliary')"


def _source_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.Text(), server_default="curated", nullable=False),
        sa.Column("source_tenant_id", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("catalog_items", sa.Column("symbol_class", sa.Text(), nullable=True))
    op.add_column("catalog_items", sa.Column("model_tokens", sa.ARRAY(sa.Text()), server_default="{}", nullable=False))
    op.execute("UPDATE catalog_items SET model_tokens = ARRAY[upper(model_code)] WHERE model_code IS NOT NULL")

    op.create_table(
        "catalog_kits",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("part_id", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("when_text", sa.Text(), server_default="", nullable=False),
        sa.Column("reason_he", sa.Text(), nullable=False),
        *_source_columns(),
        sa.CheckConstraint(SOURCES, name=op.f("ck_catalog_kits_source")),
        sa.CheckConstraint("quantity >= 1", name=op.f("ck_catalog_kits_quantity")),
        sa.ForeignKeyConstraint(
            ["item_id"], ["catalog_items.id"], name=op.f("fk_catalog_kits_item_id_catalog_items"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["part_id"], ["catalog_items.id"], name=op.f("fk_catalog_kits_part_id_catalog_items"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_kits")),
        sa.UniqueConstraint("item_id", "part_id", "when_text", name=op.f("uq_catalog_kits_item_id_part_id_when_text")),
    )
    op.create_table(
        "catalog_accessories",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accessory_id", sa.Text(), nullable=False),
        sa.Column("fits_brand", sa.Text(), nullable=False),
        sa.Column("fits_series", sa.Text(), nullable=False),
        *_source_columns(),
        sa.CheckConstraint(SOURCES, name=op.f("ck_catalog_accessories_source")),
        sa.ForeignKeyConstraint(
            ["accessory_id"],
            ["catalog_items.id"],
            name=op.f("fk_catalog_accessories_accessory_id_catalog_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_accessories")),
        sa.UniqueConstraint(
            "accessory_id",
            "fits_brand",
            "fits_series",
            name=op.f("uq_catalog_accessories_accessory_id_fits_brand_fits_series"),
        ),
    )
    for table in ("catalog_kits", "catalog_accessories"):
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")

    op.add_column("components", sa.Column("match_status", sa.Text(), nullable=True))
    op.add_column("components", sa.Column("catalog_item_id", sa.Text(), nullable=True))
    op.create_check_constraint(op.f("ck_components_match_status"), "components", MATCH_STATUS)
    op.create_foreign_key(
        op.f("fk_components_catalog_item_id_catalog_items"), "components", "catalog_items", ["catalog_item_id"], ["id"]
    )
    op.add_column(
        "tenant_settings",
        sa.Column("matching", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tenant_settings", "matching")
    op.drop_constraint(op.f("fk_components_catalog_item_id_catalog_items"), "components", type_="foreignkey")
    op.drop_constraint(op.f("ck_components_match_status"), "components", type_="check")
    op.drop_column("components", "catalog_item_id")
    op.drop_column("components", "match_status")
    op.drop_table("catalog_accessories")
    op.drop_table("catalog_kits")
    op.drop_column("catalog_items", "model_tokens")
    op.drop_column("catalog_items", "symbol_class")
