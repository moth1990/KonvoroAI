"""quota reservation id: pair each confirm or release with its reserve (01 §4.5, docs/db-schema.md §4)

A reservation is a `reserve` event. Its closing event (`confirm` or `release`) points back at it,
and a partial unique index allows only one closing event per reservation. That makes the 24 h
expiry and a late confirm safe against each other, and lets expiry find open reservations.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31 12:14:27.673917

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSING = sa.text("kind IN ('confirm', 'release')")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("quota_events", sa.Column("reservation_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_quota_events_tenant_id_reservation_id_quota_events"),
        "quota_events",
        "quota_events",
        ["tenant_id", "reservation_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_quota_events_closing_has_reservation"),
        "quota_events",
        "(reservation_id IS NOT NULL) = (kind IN ('confirm', 'release'))",
    )
    op.create_index(
        "uq_quota_events_one_closing",
        "quota_events",
        ["tenant_id", "reservation_id"],
        unique=True,
        postgresql_where=CLOSING,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_quota_events_one_closing", table_name="quota_events", postgresql_where=CLOSING)
    op.drop_constraint(op.f("ck_quota_events_closing_has_reservation"), "quota_events", type_="check")
    op.drop_constraint(
        op.f("fk_quota_events_tenant_id_reservation_id_quota_events"), "quota_events", type_="foreignkey"
    )
    op.drop_column("quota_events", "reservation_id")
