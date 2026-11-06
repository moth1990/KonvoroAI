"""the customer document (S26, 13 §4.1, §6 item 2)

- `tenant_settings.document`: the factory's template for the customer PDF (S26 decision 1): its details (name,
  company number, address, phone), its terms, whether SKUs show (07 §12 "לפי הגדרת המפעל"), and its logo's storage key
  under `tenants/{tenant_id}/branding/`. Empty: the factory's name only, no SKUs, no logo, no terms.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-05 22:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "document")
