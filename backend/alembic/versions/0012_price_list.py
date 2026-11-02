"""price list (S18, 07 §7.2–7.3)

- `supplier_preferences`: the factory's preferred supplier for a brand or a family (07 §7.2.2 item 3; S18
  decision 3). A tenant table: RLS, forced, and the app role's grants, like every table in 0001.
- `product_suppliers.supplier_id` nullable: a cost typed in a quote with no supplier (07 §7.2; S18 decision 7). At
  most one supplier-less row per product.
- `price_history.product_id` nullable, and `subject`: a change to a brand discount, a margin rule or a supplier
  preference is logged too (07 §12), with the thing it changed in `subject` (`brand_discount:ABB`, `mr_…`).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02 20:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
TENANT = "current_setting('app.tenant_id', true)"  # as in 0001


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "supplier_preferences",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope IN ('brand', 'family')", name=op.f("ck_supplier_preferences_scope")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name=op.f("fk_supplier_preferences_tenant_id_supplier_id_suppliers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_supplier_preferences_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_preferences")),
        sa.UniqueConstraint("tenant_id", "scope", "key", name=op.f("uq_supplier_preferences_tenant_id_scope_key")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_supplier_preferences_tenant_id_id")),
    )
    op.execute("ALTER TABLE supplier_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE supplier_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON supplier_preferences "
        f"USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON supplier_preferences TO {APP_ROLE}")

    op.alter_column("product_suppliers", "supplier_id", existing_type=sa.Text(), nullable=True)
    op.create_index(
        "uq_product_suppliers_one_manual",
        "product_suppliers",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("supplier_id IS NULL"),
    )

    op.alter_column("price_history", "product_id", existing_type=sa.Text(), nullable=True)
    op.add_column("price_history", sa.Column("subject", sa.Text(), nullable=True))
    op.create_check_constraint("product_or_subject", "price_history", "product_id IS NOT NULL OR subject IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM price_history WHERE product_id IS NULL")
    op.drop_constraint("product_or_subject", "price_history", type_="check")
    op.drop_column("price_history", "subject")
    op.alter_column("price_history", "product_id", existing_type=sa.Text(), nullable=False)

    op.execute("DELETE FROM product_suppliers WHERE supplier_id IS NULL")
    op.drop_index("uq_product_suppliers_one_manual", table_name="product_suppliers")
    op.alter_column("product_suppliers", "supplier_id", existing_type=sa.Text(), nullable=False)

    op.drop_table("supplier_preferences")
