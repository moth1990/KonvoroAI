"""gate 2's flags (S28, 13 §2–3)

- The `price_list` flag is gone (S18 decision 5, S19 decision 5): the price list screen was accepted in S19, and every
  factory has it. Its overrides and plan rows go with it; a downgrade puts the flag back, off.
- The build-time flags whose screens are accepted get a `remove_by` (S28 decision 4): they go at Gate 3 (S32), before
  the pilot. The spec-13 features and `catalog_lines` keep none: 13 §3 rule 5 removes them a month after they are on
  for every factory.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-06 18:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GATE_3 = "2026-12-31"
BUILD_TIME = ("quote_audit", "bom_column_mapping", "onboarding", "settings_screen", "approval_queue", "chat_layer")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM tenant_feature_overrides WHERE flag_key = 'price_list'")
    op.execute("DELETE FROM plan_feature_flags WHERE flag_key = 'price_list'")
    op.execute("DELETE FROM feature_flags WHERE key = 'price_list'")
    keys = ", ".join(f"'{k}'" for k in BUILD_TIME)
    op.execute(f"UPDATE feature_flags SET remove_by = DATE '{GATE_3}' WHERE key IN ({keys})")  # noqa: S608 (constants)


def downgrade() -> None:
    """Downgrade schema."""
    keys = ", ".join(f"'{k}'" for k in BUILD_TIME)
    op.execute(f"UPDATE feature_flags SET remove_by = NULL WHERE key IN ({keys})")  # noqa: S608 (constants)
    op.execute(
        "INSERT INTO feature_flags (key, description, depends_on) "
        "VALUES ('price_list', 'מחירון המפעל (07 §7.2)', '{}') ON CONFLICT DO NOTHING"
    )
