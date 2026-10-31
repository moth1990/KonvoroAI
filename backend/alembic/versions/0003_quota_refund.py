"""quota refund: give back a counted upload after a later system failure or a cancel (01 §4.5, S05 decision)

An upload counts when stage 1 succeeds (`confirm`). If a later stage fails for a technical reason, or the user
cancels, a `refund` event points at the same reservation and takes the slot back out of `used`. A partial unique
index allows one refund per reservation, so a retry can't refund twice.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31 19:40:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFUND = sa.text("kind = 'refund'")


def _kinds(*kinds: str) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("ck_quota_events_kind"), "quota_events", type_="check")
    op.create_check_constraint(
        op.f("ck_quota_events_kind"), "quota_events", _kinds("reserve", "confirm", "release", "refund", "manual_add")
    )
    op.drop_constraint(op.f("ck_quota_events_closing_has_reservation"), "quota_events", type_="check")
    op.create_check_constraint(
        op.f("ck_quota_events_closing_has_reservation"),
        "quota_events",
        f"(reservation_id IS NOT NULL) = ({_kinds('confirm', 'release', 'refund')})",
    )
    op.create_index(
        "uq_quota_events_one_refund",
        "quota_events",
        ["tenant_id", "reservation_id"],
        unique=True,
        postgresql_where=REFUND,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM quota_events WHERE kind = 'refund'")
    op.drop_index("uq_quota_events_one_refund", table_name="quota_events", postgresql_where=REFUND)
    op.drop_constraint(op.f("ck_quota_events_closing_has_reservation"), "quota_events", type_="check")
    op.create_check_constraint(
        op.f("ck_quota_events_closing_has_reservation"),
        "quota_events",
        f"(reservation_id IS NOT NULL) = ({_kinds('confirm', 'release')})",
    )
    op.drop_constraint(op.f("ck_quota_events_kind"), "quota_events", type_="check")
    op.create_check_constraint(
        op.f("ck_quota_events_kind"), "quota_events", _kinds("reserve", "confirm", "release", "manual_add")
    )
