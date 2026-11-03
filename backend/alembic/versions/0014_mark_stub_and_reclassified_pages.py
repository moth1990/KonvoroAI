"""mark stub pages and pages a person fixed after the stand-in (BUG-042, BUG-043)

0013 marked pages the stand-in classified. Two more kinds of page carry made-up data and were still reusable by a
run on the real model:
- BUG-043: pages from the S05 stage-1 stub, `model = 'stub-s05'`. Their kinds, title block and tag reading were
  never read from the drawing.
- BUG-042: pages a person reclassified after the stand-in read them. Reclassifying cleared `model`, but the title
  block and the tag reading stayed the stand-in's. They are found through their drawing: a page_classification call
  answered by the stand-in, or a sibling page from the stub.

Both get a `stand-in:` model name, and so does every page reused from one of them, down the chain. A model name that
was lost becomes `stand-in:unknown`. Data only and local only in practice, like 0013.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        WITH RECURSIVE made_up AS (
            SELECT p.tenant_id, p.id
            FROM pages p
            WHERE p.model = 'stub-s05'
               OR (p.classified_by = 'user' AND p.model IS NULL AND (
                    EXISTS (
                      SELECT 1 FROM llm_calls c
                      WHERE c.tenant_id = p.tenant_id AND c.drawing_id = p.drawing_id
                        AND c.stage = 'page_classification' AND c.provider = 'fake')
                    OR EXISTS (
                      SELECT 1 FROM pages q
                      WHERE q.tenant_id = p.tenant_id AND q.drawing_id = p.drawing_id
                        AND q.model IN ('stub-s05', 'stand-in:stub-s05'))))
            UNION
            SELECT p.tenant_id, p.id
            FROM pages p JOIN made_up s ON p.tenant_id = s.tenant_id AND p.reused_from = s.id
        )
        UPDATE pages SET model = CASE
            WHEN pages.model IS NULL THEN 'stand-in:unknown'
            ELSE 'stand-in:' || pages.model
          END
        FROM made_up
        WHERE pages.tenant_id = made_up.tenant_id AND pages.id = made_up.id
          AND (pages.model IS NULL OR pages.model NOT LIKE 'stand-in:%')
    """)


def downgrade() -> None:
    # 0014 writes only these two values; 0013's marks stay for 0013's downgrade.
    op.execute("UPDATE pages SET model = 'stub-s05' WHERE model = 'stand-in:stub-s05'")
    op.execute("UPDATE pages SET model = NULL WHERE model = 'stand-in:unknown'")
