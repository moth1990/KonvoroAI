"""component supply scope: the spec's values (S13, 04 §5.1.2)

`components.supply_scope` allowed `in_panel`, `outside_panel`, `prep_only`, `not_in_scope`; 04 §5.1.2, 07 and the
stage-4 contract say `in_panel`, `other_location`, `prepare_only`, `by_others`. The spec wins (S13 decision). No row
has a value other than `in_panel` before stage 4 is real, and any that does is renamed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 23:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = (("outside_panel", "other_location"), ("prep_only", "prepare_only"), ("not_in_scope", "by_others"))


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("supply_scope", "components", type_="check")
    for old, new in RENAMES:
        op.execute(
            sa.text("UPDATE components SET supply_scope = :new WHERE supply_scope = :old").bindparams(new=new, old=old)
        )
    op.create_check_constraint(
        "supply_scope", "components", "supply_scope IN ('in_panel', 'other_location', 'prepare_only', 'by_others')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("supply_scope", "components", type_="check")
    for old, new in RENAMES:
        op.execute(
            sa.text("UPDATE components SET supply_scope = :old WHERE supply_scope = :new").bindparams(new=new, old=old)
        )
    op.create_check_constraint(
        "supply_scope", "components", "supply_scope IN ('in_panel', 'outside_panel', 'prep_only', 'not_in_scope')"
    )
