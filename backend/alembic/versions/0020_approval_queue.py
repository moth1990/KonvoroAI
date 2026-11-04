"""approval queue and promotion to the shared layer (S24, 00 §9, §14.2, 10 §11)

- `knowledge_candidates.dedupe_key`: one candidate per thing, so a product proposed again, or after a rejection, is
  not queued twice; `promoted_id`: the global record an approval wrote or found.
- `spelling_patterns`: a global table for the queue's `spelling` kind (04 §11). Stage 4 does not read it yet.
- `catalog_items.attribute_provenance`: who set an attribute the row's own source did not (a `catalog_attribute`).
- `konboro_promote(candidate_id, new_id)`: the only way a tenant's approval reaches the global layer (S24 decision 4).
  The app role keeps SELECT only on global tables, so the function is SECURITY DEFINER, owned by `konboro_promoter`:
  a NOLOGIN role with no BYPASSRLS, INSERT on the four global tables it writes, and UPDATE on two columns of
  `catalog_items` and one of `knowledge_candidates`. It reads the candidate through the tenant's own RLS policy (the
  caller's `app.tenant_id`), promotes only an approved one, copies only the payload fields each kind's record has (so
  no price, cost, supplier, customer, project or designer can travel, even if a payload carried one), and stamps
  `source='pilot_engineer'`, the tenant, the user and the time. Only `konboro_app` may execute it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-04 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "konboro_app"
PROMOTER = "konboro_promoter"
FUNCTION = "konboro_promote(text, text)"
WRITTEN = ("catalog_items", "abbreviations", "symbol_classes", "spelling_patterns")

PROMOTE = r"""
CREATE FUNCTION konboro_promote(candidate text, record_id text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  tenant text := current_setting('app.tenant_id', true);
  c knowledge_candidates%ROWTYPE;
  p jsonb;
  rid text;
  prov jsonb;
BEGIN
  SELECT * INTO c FROM knowledge_candidates WHERE id = candidate AND tenant_id = tenant FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'knowledge candidate % not found', candidate USING ERRCODE = 'no_data_found';
  END IF;
  IF c.status <> 'approved' THEN
    RAISE EXCEPTION 'knowledge candidate % is %, not approved', candidate, c.status USING ERRCODE = 'check_violation';
  END IF;
  IF c.promoted_id IS NOT NULL THEN
    RETURN c.promoted_id;
  END IF;
  p := c.payload;

  IF c.kind = 'catalog_item' THEN
    IF coalesce(p->>'sku', '') = '' OR coalesce(p->>'brand', '') = '' OR coalesce(p->>'family', '') = '' THEN
      RAISE EXCEPTION 'a catalog item needs sku, brand and family' USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO catalog_items (id, sku, brand, series, model_code, family, symbol_class, attributes,
                               source, source_tenant_id, approved_by, approved_at)
    VALUES (record_id, p->>'sku', p->>'brand', p->>'series', p->>'model_code', p->>'family', p->>'symbol_class',
            coalesce(p->'attributes', '{}'::jsonb), 'pilot_engineer', tenant, c.decided_by, c.decided_at)
    ON CONFLICT (brand, sku) DO NOTHING RETURNING id INTO rid;
    IF rid IS NULL THEN
      SELECT id INTO rid FROM catalog_items WHERE brand = p->>'brand' AND sku = p->>'sku';
    END IF;

  ELSIF c.kind = 'abbreviation' THEN
    INSERT INTO abbreviations (id, text, symbol_class, family, display_he,
                               source, source_tenant_id, approved_by, approved_at)
    VALUES (record_id, p->>'text', p->>'symbol_class', p->>'family', p->>'display_he',
            'pilot_engineer', tenant, c.decided_by, c.decided_at)
    ON CONFLICT (text) DO NOTHING RETURNING id INTO rid;
    IF rid IS NULL THEN
      SELECT id INTO rid FROM abbreviations WHERE text = p->>'text';
    END IF;

  ELSIF c.kind = 'spelling' THEN
    INSERT INTO spelling_patterns (id, pattern, meaning_he, family, attribute,
                                   source, source_tenant_id, approved_by, approved_at)
    VALUES (record_id, p->>'pattern', p->>'meaning_he', p->>'family', p->>'attribute',
            'pilot_engineer', tenant, c.decided_by, c.decided_at)
    ON CONFLICT (pattern) DO NOTHING RETURNING id INTO rid;
    IF rid IS NULL THEN
      SELECT id INTO rid FROM spelling_patterns WHERE pattern = p->>'pattern';
    END IF;

  ELSIF c.kind = 'symbol' THEN
    INSERT INTO symbol_classes (id, family, display_name_he, billable,
                                source, source_tenant_id, approved_by, approved_at)
    VALUES (p->>'id', p->>'family', p->>'display_name_he', coalesce((p->>'billable')::boolean, true),
            'pilot_engineer', tenant, c.decided_by, c.decided_at)
    ON CONFLICT (id) DO NOTHING;
    rid := p->>'id';

  ELSIF c.kind = 'catalog_attribute' THEN
    -- Fills an attribute the item does not have. A different value already there is a conflict: the candidate
    -- stays pending, and nothing is overwritten silently (00 §14.2).
    prov := jsonb_build_object('source', 'pilot_engineer', 'source_tenant_id', tenant,
                               'approved_by', c.decided_by, 'approved_at', c.decided_at);
    UPDATE catalog_items
       SET attributes = attributes || jsonb_build_object(p->>'name', p->'value'),
           attribute_provenance = attribute_provenance || jsonb_build_object(p->>'name', prov),
           updated_at = now()
     WHERE id = p->>'catalog_item_id' AND NOT attributes ? (p->>'name')
    RETURNING id INTO rid;
    IF rid IS NULL THEN
      SELECT id INTO rid FROM catalog_items
       WHERE id = p->>'catalog_item_id' AND attributes->(p->>'name') = p->'value';
      IF rid IS NULL THEN
        RAISE EXCEPTION 'catalog item % has another value for %', p->>'catalog_item_id', p->>'name'
          USING ERRCODE = 'unique_violation';
      END IF;
    END IF;

  ELSE
    RAISE EXCEPTION 'unknown kind %', c.kind USING ERRCODE = 'check_violation';
  END IF;

  UPDATE knowledge_candidates SET promoted_id = rid WHERE id = candidate AND tenant_id = tenant;
  RETURN rid;
END $$"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("knowledge_candidates", sa.Column("dedupe_key", sa.Text(), nullable=True))
    op.execute("UPDATE knowledge_candidates SET dedupe_key = id")
    op.alter_column("knowledge_candidates", "dedupe_key", nullable=False)
    op.add_column("knowledge_candidates", sa.Column("promoted_id", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_knowledge_candidates_tenant_id_kind_dedupe_key", "knowledge_candidates", ["tenant_id", "kind", "dedupe_key"]
    )
    op.add_column(
        "catalog_items",
        sa.Column("attribute_provenance", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.create_table(
        "spelling_patterns",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("meaning_he", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=True),
        sa.Column("attribute", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), server_default="curated", nullable=False),
        sa.Column("source_tenant_id", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('curated', 'pilot_engineer', 'import')", name=op.f("ck_spelling_patterns_source")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spelling_patterns")),
        sa.UniqueConstraint("pattern", name=op.f("uq_spelling_patterns_pattern")),
    )
    op.execute(f"GRANT SELECT ON spelling_patterns TO {APP_ROLE}")

    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PROMOTER}') "
        f"THEN CREATE ROLE {PROMOTER} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PROMOTER}")
    # Reads the candidate through the tenant_isolation policy (it applies to every role), marks it promoted.
    op.execute(f"GRANT SELECT, UPDATE (promoted_id) ON knowledge_candidates TO {PROMOTER}")
    for table in WRITTEN:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {PROMOTER}")
    op.execute(f"GRANT UPDATE (attributes, attribute_provenance, updated_at) ON catalog_items TO {PROMOTER}")

    op.execute(PROMOTE)
    op.execute(f"GRANT {PROMOTER} TO CURRENT_USER")  # as in 0004: handing the function over needs membership
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {PROMOTER}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP FUNCTION {FUNCTION}")
    op.execute(f"REVOKE ALL ON knowledge_candidates FROM {PROMOTER}")
    for table in WRITTEN:
        if table != "spelling_patterns":
            op.execute(f"REVOKE ALL ON {table} FROM {PROMOTER}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PROMOTER}")
    # The role stays: other databases in the cluster (test, e2e, eval) may still use it.
    op.drop_table("spelling_patterns")
    op.drop_column("catalog_items", "attribute_provenance")
    op.drop_constraint("uq_knowledge_candidates_tenant_id_kind_dedupe_key", "knowledge_candidates", type_="unique")
    op.drop_column("knowledge_candidates", "promoted_id")
    op.drop_column("knowledge_candidates", "dedupe_key")
