# S02: DB schema and RLS

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s02-db-schema-rls` |
| **Depends on** | S01 |
| **Status** | todo |
| **PR** | |

## Goal

The database schema for v1.0 exists:
- written down in `docs/db-schema.md`, the missing document from 00 §2;
- built as SQLAlchemy models and an Alembic migration;
- every tenant table isolated by RLS, and tests that prove it.

## References

- Specs:
  - 00 §6 (IDs, types), §8 (two data layers, entities), §9 (shared-layer promotion), §14.1 (single `owner` role).
  - 01 §4.5 (`plans`, `tenant_plan_overrides`, `quota_usage`, `quota_events`), §6 (drawing, page fields).
  - 07 §7.2–7.3 and §6 (price list, suppliers, margin rules, quote, line, versions).
  - 09 §10 (correction events).
  - 13 §2 (`feature_flags`, `tenant_feature_overrides`).
  - 10 §9.1 (tenant settings).
- Prototype data shapes: lines 393–580 (`makeLines`, `makeFindings`, `QUOTES`, `CATALOG`, `QUEUE`, `S`).

## Tasks

### Backend
- [ ] Write `docs/db-schema.md`: every table with columns, types, keys and indexes. Mark each table global or tenant, and give its RLS policy. Then get the user's sign-off.
  - **Global:** `plans`, `feature_flags`, `master_catalog_items`, `attribute_schemas`, `symbol_classes`, `validator_rules`, `shared_knowledge_queue`.
  - **Tenant:**
    - `tenants`, `users`, `tenant_settings`, `tenant_plan_overrides`, `tenant_feature_overrides`, `quota_usage`, `quota_events`, `customers`, `projects`.
    - `drawings`, `drawing_files`, `pages`.
    - `quotes`, `quote_versions`, `quote_lines`, `findings`.
    - `price_list_products`, `product_suppliers`, `price_history`, `margin_rules`, `match_memory`, `correction_events`, `llm_calls`.
  - Heavy pipeline artifacts (spans, tiles, detections) are stored as JSON in S3. The DB holds their keys (00 §8).
- [ ] SQLAlchemy 2 models in `konboro/db/models/`. Money columns are `Numeric(14,4)` mapped to `Decimal`. IDs are prefixed text per 00 §6.1 (`quo_…`, `ln_…`).
- [ ] Alembic setup and migration `0001_initial`:
  - RLS `ENABLE` + `FORCE` on every tenant table.
  - Policy `tenant_id = current_setting('app.tenant_id')::text`.
  - An app role without `BYPASSRLS` that does not own the tables. A separate migration role.
- [ ] `konboro/db/session.py`: `tenant_session(tenant_id)` runs `SET LOCAL app.tenant_id`. A request without tenant context is refused.
- [ ] `make seed`: a demo tenant with the NURSERY-1 customer and project, a few catalog products with suppliers (taken from the prototype `CATALOG`), and default flags.

### Integration tests
- [ ] The migration applies cleanly up and down on an empty DB.
- [ ] **Cross-tenant suite:** for every tenant table, tenant B gets nothing from select, update or delete on tenant A's rows, and cannot insert with A's `tenant_id`.
- [ ] A query without tenant context returns nothing, or raises.
- [ ] A money column round-trips `Decimal('1250.10')` exactly.

### Unit tests
- [ ] ID generator: format and prefixes.

### Docs
- [ ] `docs/db-schema.md` is linked from CLAUDE.md and README §6.3, where the schema was listed as missing.

## Acceptance criteria

- [ ] Every tenant table has `tenant_id`, RLS enabled and forced, and a cross-tenant test. A test fails if a new tenant table is added without one: it introspects `pg_class` / `pg_policies`.
- [ ] No money column is float.
- [ ] The user signed off `docs/db-schema.md` before the migration was finalized.

## Out of scope

- Endpoints (S03).
- pgvector columns for the symbol index (phase 4). Do enable the extension now.

## Open questions

- IDs: ULID suffix, or UUIDv7? Default: ULID.
- Soft delete or hard delete for quote lines? The specs imply that deletions are correction events, so the default is soft delete with `deleted_at`.

## Outcome

- **Done:**
- **Decisions made:**
- **Bugs logged:**
- **Follow-ups:**
