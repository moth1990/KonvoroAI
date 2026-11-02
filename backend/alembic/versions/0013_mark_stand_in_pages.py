"""mark pages the stand-in model classified (BUG-041)

Since this fix stage 1 stores "stand-in:<model>" when the stand-in answered, and a run on the real model never
reuses such a page. Pages classified before the fix carry the plain model name. This marks them: a page whose
drawing's page_classification calls were answered by the stand-in (llm_calls.provider = 'fake'), and every page
reused from one, down the chain.

Data only, and local only in practice: the stand-in runs only where env=local and there is no key. In AWS the owner
role is subject to FORCE ROW LEVEL SECURITY, sees no tenant rows here, and the update does nothing (as it should).

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The prefix is konboro.services.llm.STAND_IN_PREFIX, written out: a migration must not change with the code.


def upgrade() -> None:
    op.execute("""
        WITH RECURSIVE stand_in AS (
            SELECT p.tenant_id, p.id
            FROM pages p
            WHERE p.classified_by = 'model' AND p.model IS NOT NULL AND p.model NOT LIKE 'stand-in:%'
              AND EXISTS (
                SELECT 1 FROM llm_calls c
                WHERE c.tenant_id = p.tenant_id AND c.drawing_id = p.drawing_id
                  AND c.stage = 'page_classification' AND c.provider = 'fake')
            UNION
            SELECT p.tenant_id, p.id
            FROM pages p JOIN stand_in s ON p.tenant_id = s.tenant_id AND p.reused_from = s.id
        )
        UPDATE pages SET model = 'stand-in:' || pages.model
        FROM stand_in
        WHERE pages.tenant_id = stand_in.tenant_id AND pages.id = stand_in.id
          AND pages.model IS NOT NULL AND pages.model NOT LIKE 'stand-in:%'
    """)


def downgrade() -> None:
    # 10 = len("stand-in:") + 1
    op.execute("UPDATE pages SET model = substr(model, 10) WHERE model LIKE 'stand-in:%'")
