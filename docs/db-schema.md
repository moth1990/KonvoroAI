# Database schema (v1.0)

The full data model for Konboro v1.0. This document was listed as missing in [00 §2](../specs/00-architecture.md) and README §6.3. It is derived from:
- [00 §6, §8, §9, §14](../specs/00-architecture.md): IDs, the two data layers, shared-layer promotion, single owner.
- [01 §4.3–4.5, §6](../specs/01-intake-page-classification.md): limits, quota, drawing and page fields.
- [05 §4.3–4.4, §11](../specs/05-catalog-matching.md): catalog, attribute schemas, match memory.
- [06 §6.2](../specs/06-validation.md): rules and issues.
- [07 §4, §6, §7.2–7.7](../specs/07-pricing.md): price list, suppliers, margin rules, quote versions and lines.
- [08 §5.2.1, §7](../specs/08-chat-layer.md): conversations and proposals.
- [09 §10](../specs/09-review-screen.md): correction events.
- [10 §9](../specs/10-onboarding.md): tenant settings.
- [11 §6](../specs/11-quote-audit.md): audits.
- [13 §2](../specs/13-feature-flags.md): flags.

**Status:** draft for review (S02). The models in `backend/konboro/db/models/` and the Alembic migrations implement this document. When the two differ, fix the document in the same PR.

## 1. Conventions

| Topic | Rule |
| --- | --- |
| **IDs** | `text` primary key: prefix + ULID, e.g. `quo_01JB8Z…` (00 §6.1). ULIDs sort by creation time. Prefixes are listed in §7 |
| **Money** | `numeric(14,4)` ↔ Python `Decimal` ↔ JSON string. Never float (00 §6.5, 07) |
| **Rates** (markup, margin, discount, VAT) | `numeric(7,4)` as a fraction: `0.28` = 28% (07 §6.1) |
| **Quantities** | `numeric(12,3)`. Most lines are whole units, but the price list has `unit` = meter (07 §7.2.1) |
| **Confidence** | `real` in 0–1 |
| **Time** | `timestamptz`, UTC. Every table has `created_at default now()`; mutable tables also have `updated_at` |
| **Enums** | `text` with a `CHECK` constraint, not Postgres enum types, so a new value is a one-line migration |
| **Unknown values** | `NULL`, never `''` or `0` (00 §6.5) |
| **Trace objects** | `jsonb` for objects that are read as a whole and never filtered on. Examples: `cost_source`, `status_reasons`, `title_block`, `snapshot`, `diff`. Anything the app filters or joins on is a real column |
| **Heavy artifacts** | Rendered pages, tiles, text spans, detections and the wire graph live in S3 under `tenants/<tenant_id>/…`. The DB stores the key (00 §8.2) |
| **Coordinates** | `jsonb` `[x0, y0, x1, y1]` in PDF points, origin top-left after rotation (00 §6.2) |
| **Soft delete** | Only where undo must restore a row: `quote_lines.deleted_at` (09 §7.6, §7.11). Everything else is deleted for real, or never deleted |

## 2. Two layers and tenant isolation

| Layer | Tables | Who writes | App role (`konboro_app`) |
| --- | --- | --- | --- |
| **Global** | §3 | Migrations, the seed, admin import scripts, and the approval-queue promotion job | `SELECT` only |
| **Tenant** | §4–§6 | The app, inside a tenant session | `SELECT, INSERT, UPDATE, DELETE`, filtered by RLS |

**Isolation, in four layers of defense:**

1. **Every tenant table has `tenant_id text not null`.** That includes child tables such as `quote_lines`, so each row's policy is one simple comparison with no joins.
2. **RLS is `ENABLE`d and `FORCE`d on every tenant table**, with one policy:
   ```sql
   CREATE POLICY tenant_isolation ON <table>
     USING (tenant_id = current_setting('app.tenant_id', true))
     WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
   ```
   For `tenants` itself, the column is `id`.

   Without a tenant context, `current_setting(…, true)` is `NULL` and the comparison is never true, so a session with no tenant sees nothing and can write nothing.
3. **Composite foreign keys.**
   - Every tenant table has `UNIQUE (tenant_id, id)`.
   - Child tables reference their parent as `(tenant_id, parent_id) → parent(tenant_id, id)`.

   A row can therefore never point at another tenant's row, even through a bug that sets the wrong ID.
4. **Roles.**
   - `konboro` owns the tables and runs migrations. The app never connects as it.
   - `konboro_app` is the role the API and workers use. It has `LOGIN`, is not a superuser, has no `BYPASSRLS`, and does not own any table.

   - `konboro_sweeper` (migration 0004) has no login and owns one function, `konboro_unsent_stages(interval)`. That function is the only read across tenants. It is `SECURITY DEFINER`, only `konboro_app` may execute it, and it returns `(tenant_id, drawing_id, stage, trace_id)` for stages whose message was sent that long ago and never claimed. The role has no `BYPASSRLS`. It reads through its own `requeue_sweep` policies (`FOR SELECT`) and a column-level `SELECT` on those columns of `stage_runs` and `drawings`. The worker re-checks each row inside `tenant_session` before it sends anything (S07 decision, BUG-006).

   - `konboro_promoter` (migration 0020, S24 decision 4) has no login and owns one function, `konboro_promote(candidate_id, record_id)`. It is the only path from a tenant to the global layer: the pilot approval queue's approval (00 §14.2). It is `SECURITY DEFINER`, only `konboro_app` may execute it, and the role has no `BYPASSRLS`: it reads the candidate through the tenant's own `tenant_isolation` policy (the caller's `app.tenant_id`), promotes only an `approved` one, copies only the fields each kind's global record has (so a price, a cost, a supplier, a customer or a designer cannot travel, even in a payload that carried one), and stamps `source='pilot_engineer'`, `source_tenant_id`, `approved_by` and `approved_at`. Its grants: `SELECT, INSERT` on `catalog_items`, `abbreviations`, `symbol_classes` and `spelling_patterns`; `UPDATE (attributes, attribute_provenance, updated_at)` on `catalog_items`; `SELECT, UPDATE (promoted_id)` on `knowledge_candidates`. The app role keeps `SELECT` only on every global table.

   Postgres superusers and table owners bypass RLS. That is why this split matters.

**Tenant context:**
- `konboro.db.session.tenant_session(tenant_id)` opens a transaction and runs `SET LOCAL app.tenant_id = :tenant_id`.
- Code without a tenant (health check, global reads) uses `global_session()`, which can read global tables only.
- **In the API, nobody calls `tenant_session` by hand.** Every route depends on `require(permission)` (`konboro/api/deps.py`). That runs `current_actor`, which:
  - verifies the bearer token;
  - opens `tenant_session(claims.tenant_id)`, which commits when the route function returns, before the response;
  - loads the user in that tenant, so a token whose user is not in its tenant gets a 401;
  - checks the permission against the DB role. Every permission maps to `owner` in v1.0 (00 §14.1).

  A route audit test fails for any route outside `PUBLIC_ROUTES` that skips it.
- **Dev login** (until Cognito, S29) never reads `users` across tenants. A setting maps each dev email to its tenant, the same job Cognito's `custom:tenant_id` attribute does. The login then looks the user up inside that tenant's session.

**Tests:**
- The cross-tenant suite tries `SELECT`, `UPDATE`, `DELETE` and `INSERT` across tenants on **every** tenant table.
- A guard test reads `pg_class` and `pg_policies` and fails when any table with a `tenant_id` column lacks RLS or the policy.
- The sweeper tests pin the role's flags, its column grants, who may execute the function, and that it returns IDs only.

## 3. Global layer

### 3.1 Plans and flags

**`plans`** stores the commercial packages (01 §4.3).
- `id text pk`: a readable key such as `trial` or `pro`.
- `name_he`.
- `monthly_quote_limit int null`: `null` means unlimited.
- `monthly_audit_limit int null`: `null` means audits count against the quote limit.
- `max_pages_per_file int not null default 30`.
- `active bool`.

System limits (20 MB per file, 20 files, 200 pages per drawing, 2 m² per page) are app config, not data (01 §4.3).

**`feature_flags`** (13 §2):
- `key text pk`, `description`.
- `default_on bool not null default false`. A new flag is always off.
- `depends_on text[]`.
- `owner`, `created_at`, `remove_by date`.
- Seeded keys: spec 13's five. `review_screen` (S09) gated the review screen while it was built; migration 0019 removed it with S23b.

**`plan_feature_flags`** holds the plan-level flag setting: `plan_id → plans`, `flag_key → feature_flags`, `enabled bool`, with PK `(plan_id, flag_key)`.

### 3.2 Catalog and knowledge

**`catalog_items`** is the master catalog (05 §4.3, 07 §4.3).

| Columns | Notes |
| --- | --- |
| `id` (`cat_`) | |
| `sku`, `brand`, `series`, `model_code`, `family` | Unique `(brand, sku)` |
| `symbol_class null` | The class within the family (`mcb`, `mccb`, `motor_protection`): stage 5 narrows by it (05 §5.1; migration 0015) |
| `model_tokens text[]` | The model codes as drawings write them, upper case (`S203M`; `XT1C160`, `XT1C`, `XT1`): an explicit series narrows to the items listing it (05 §5.2.1). Filled from `model_code` for older rows |
| `attributes jsonb` | Normalized attribute values, by the family's schema |
| `module_width numeric(5,2)` | For sizing the enclosure (07 §7.4) |
| `list_price numeric(14,4)`, `list_currency` | The manufacturer's list price, when known |
| `status` | `active` or `discontinued`; `replaced_by → catalog_items` |
| `includes jsonb` | For enclosures and kits (07 §7.4) |
| `source`, `source_tenant_id`, `approved_by`, `approved_at` | Where the record came from. `source` is one of `curated`, `pilot_engineer`, `import` (00 §14.2). The CSV loader writes `import` rows ([catalog-import.md](catalog-import.md), S18) |
| `attribute_provenance jsonb default '{}'` | Per attribute, who set it when it is not the row's own source: `{name: {source, source_tenant_id, approved_by, approved_at}}`. Written by `konboro_promote` for a `catalog_attribute` candidate, which only fills an attribute the item lacks (migration 0020, S24) |

Two global tables hang off the catalog (05 §5.9.1, S20; migration 0015), loaded with it ([catalog-import.md](catalog-import.md)):
- **`catalog_kits`** (`ckt_`): `item_id → catalog_items` (the main item), `part_id → catalog_items`, `quantity` (per unit, at least 1), `when_text` (the phrase in the component's text that calls for the part, "משולב פחת"; empty: always), `reason_he`, plus the source columns. Unique `(item_id, part_id, when_text)`.
- **`catalog_accessories`** (`cac_`): `accessory_id → catalog_items`, `fits_brand`, `fits_series`, plus the source columns. Unique `(accessory_id, fits_brand, fits_series)`. An aux contact, shunt trip or lock is matched among the accessories that fit its device's series.

The remaining global tables:
- **`attribute_schemas`** (05 §4.4): `family text pk`, `version int`, `attributes jsonb`. `attributes` is a list of `{name, required, match_mode, default_allowed}`. For `current_a` and `poles`, `default_allowed` is always false. Seeded by `seed_global` from `konboro/pipeline/association/schemas.py` (S13), one row per billable family; a row already there is kept. Stage 4 reads them back.
- **`symbol_classes`** (03 §4.3): `id text pk` (e.g. `mcb`), `family`, `display_name_he`, `billable bool`, `standard_ref`, `attribute_schema → attribute_schemas.family`, plus the source columns. Seeded by `seed_global` from `konboro/pipeline/detection/library.py` (S12); a row already there is kept, and gets its family's `attribute_schema` when it has none (S13).
- **`reference_crops`** (03 §4.3), global scope only: `id` (`ref_`), `symbol_class → symbol_classes`, `image_key`, `source`, `approved_count`. The `embedding vector` column is added with the similarity index in phase 4. The `vector` extension is enabled now. The curated rows (S12) have `image_key` = `reference/<file>.png`, a file in `konboro/pipeline/detection/reference/`, not an S3 key.
- **`abbreviations`** (03 §4.6), global: `id` (`abr_`), `text`, `symbol_class`, `family`, `display_he`, plus the source columns. Seeded from the same module (S12).
- **`spelling_patterns`** (04 §11), global: `id` (`spl_`), `pattern` (unique, "SAVE", "INC="), `meaning_he`, `family null`, `attribute null`, plus the source columns. Only the approval queue writes it so far (migration 0020, S24); stage 4 still reads its grammar from `association/grammar.json`.
- **`validator_rules`** (06 §6.2): PK `(rule_id, version)`, `category` (A–E), `applies_to text[]`, `requires text null` (`wire_graph`, `bom_table`, `front_view`, `text_layer`; migration 0016), `severity`, `params jsonb`, `title_he` and `message_he` (templates; migration 0016), `enabled bool`, `approval text null` (`pending_expert`: category A until the electrical expert signs it off, S21 decision 7). Seeded by `seed_global` from `konboro/pipeline/validation/rules.json` (S21); a row already there is kept, so a new wording or threshold is a new version.
- **`vat_rates`** (07 §4.3): `id` (`vat_`), `rate numeric(7,4)`, `valid_from date`. The VAT rate is data, never a constant in code.
- **`fx_rates`**: `currency`, `rate_date`, `rate numeric(14,6)`, `source`, with PK `(currency, rate_date)`. The rate is how many ILS one unit costs. A quote uses the latest rate on or before its date, at most 7 days old (S18 decision 4). Locally, `make seed` writes fixed USD and EUR rates, one a week through 2027 (`source` = `seed`).

## 4. Tenant layer: account, quota, settings

**`tenants`** (`tnt_`). Its RLS policy compares `id`, not `tenant_id`.
- `name`.
- `plan_id → plans`.
- `timezone default 'Asia/Jerusalem'`. The quota month is computed in this timezone (01 §4.5).
- `currency default 'ILS'`.
- `status`: `active` or `suspended`.

**`users`** (`usr_`):
- `email`, unique per tenant.
- `auth_subject`: the Cognito `sub` from S29; a dev-issuer ID until then.
- `display_name`.
- `role text default 'owner'`, with `CHECK (role in ('owner'))` in v1.0. Every endpoint still checks permission against it (00 §14.1).

**`tenant_settings`** has `tenant_id` as PK, one row per tenant. It holds 10 §9.1 plus the prototype's settings screen.

| Columns | Notes |
| --- | --- |
| `brand_preferences jsonb` | Family → brand |
| `attribute_defaults jsonb` | E.g. `{"rcd": {"residual_ma": 30}}`. Only for attributes whose schema allows a default |
| `enclosure_includes_default jsonb` | busbar, N, PE, panels, doors (prototype settings) |
| `min_line_margin`, `min_quote_margin numeric(7,4)` | Margin floors (07 §7.3) |
| `stale_days int default 90` | When a supplier price counts as stale |
| `labor jsonb` | Hourly rate and hours per family (07 §4.2) |
| `rounding text default 'agora'` | |
| `data_terms_accepted jsonb` | `{version, by, at}`, written by `POST /onboarding` (S24). While it is null and `onboarding` is on, uploads answer 409 |
| `onboarding jsonb` | 10 §9.1's counters (`first_drawing_at`, `first_quote_sent_at`, `quotes_sent`, `price_coverage_last`, `accelerators_*`), plus the answers: `answered_at`, `markup_source`, `brands` (S24). The markup itself is the `default` margin rule |
| `auxiliary_families text[] default '{terminal}'` | Families the factory counts as auxiliary material: the audit shows them as `not_a_difference` (11 §5.4, S15 decision 4, migration 0011), and stage 5 gives them no SKU (S20 decision 3) |
| `matching jsonb default '{}'` | Stage 5's settings (05 §5.4–5.7, §13 item 1; migration 0015): `series` (family → preferred series), `alternate_brands` (family or `*` → brands allowed instead), `tie_break` (`frequency`, the default, `price` or `ask`), `inference_off` (rule ids of 05 §5.5.1 turned off). `brand_preferences` takes `*` for every family too |
| `document jsonb default '{}'` | The customer PDF's template (13 §4.1, S26 decision 1; migration 0023): `company` (`name`, `company_id`, `address`, `phone`), `terms`, `show_sku`, and `logo` (`key` under `tenants/{tenant_id}/branding/`, `content_type`). Empty: the tenant's name, no SKUs, no logo, no terms |

**`tenant_plan_overrides`** has `tenant_id` as PK. It holds `monthly_quote_limit`, `monthly_audit_limit` and `max_pages_per_file`, all nullable; `null` means use the plan's value.

**`tenant_feature_overrides`**: `tenant_id`, `flag_key → feature_flags`, `enabled`, `reason`, with PK `(tenant_id, flag_key)`.

Flags resolve in the order tenant → plan → global → default (13 §2).

**`quota_usage`** (01 §4.5) has PK `(tenant_id, month date)`, where `month` is the first day of the month in the tenant's timezone.
- It holds `used int`, `reserved int`, and `extra int`. `extra` is a manual one-time addition.
- A check constraint keeps `used` and `reserved` at 0 or more.
- A reservation is one conditional update: `… SET reserved = reserved + 1 WHERE used + reserved < limit + extra`.

**`quota_events`** (`qev_`):
- `month`, `drawing_id null`.
- `kind`: `reserve`, `confirm`, `release`, `refund` or `manual_add`.
- `amount`, `reason`, `created_by`.
- `reservation_id null → quota_events`: a `reserve` event *is* the reservation. Its `confirm` or `release` points back at it. A check makes `reservation_id` required on exactly those two kinds, and the partial unique index `uq_quota_events_one_closing` allows only one closing event per reservation. So a confirm racing the expiry can never decrement `reserved` twice.
- A reservation with no closing event after 24 hours is released with reason `expired`. This runs lazily at the start of every reserve and quota read, so there is no scheduler yet (01 §4.5).
- When an upload counts (S05 decision, 01 §4.5): the reservation is made with the upload and confirmed when stage 1 succeeds. A later system failure, or a cancel, adds a `refund` that points at the same reservation and takes the slot back out of `used`. The partial unique index `uq_quota_events_one_refund` allows one refund per reservation (migration 0003). Before stage 1 succeeds, a failure or cancel is a `release`. A rejected upload rolls back with its reservation, so it leaves no event at all. A new version of a drawing reserves nothing until S08 can check that it really is one.

This table answers the customer's question "why was this counted?".

**`llm_calls`** (`llm_`) holds one row per `konboro_llm` call, for cost per tenant (00 §7.2, 12 §7):
- `stage`, `provider`, `model`;
- `input_tokens`, `output_tokens`, `latency_ms`, `attempts`;
- `drawing_id null`, `quote_id null`.

## 5. Tenant layer: drawings and the pipeline

**`customers`** (`cus_`): `name`, `discount_pct numeric(7,4) null` (07 §4.2), and `brand_preferences jsonb` ("this customer only uses ABB", 05 §4.3).

**`projects`** (`prj_`): `customer_id → customers null`, `name`.

**`drawings`** (`drw_`, 01 §6.2):

| Columns | Notes |
| --- | --- |
| `project_id → projects null`, `revision_of → drawings null` | |
| `purpose` | `quote` or `audit` (11). It decides which quota counter is used |
| `origin` | `upload` (files, through the pipeline's queues) or `chat`: a build on `/build` (13 §4.2, migration 0024, S27). A chat drawing is `bom_only`, has no files and no `pages` rows, one panel or more, and its stages 4–7 run in the request after each message (`pipeline/inline.py`). Its rows are its stage-1 `bom_table` artifact of source `chat`, whose `page_id` stands for the conversation (no `pages` row) |
| `status` | `uploaded`, `processing`, `awaiting_confirmation`, `ready`, `failed`, `cancelled` |
| `input_kind null` | `factory_drawing`, `designer_plan`, `bom_only`, `mixed`. Set by stage 1 |
| `current_stage smallint null`, `progress real` | What the "run" screen shows |
| `needs_confirmation bool` | Stage 1 asks the user to confirm the pages (01 §5.6); the drawing waits in `awaiting_confirmation` |
| `title_block jsonb null` | The drawing's title block, read once by stage 1 (S08): `{project_name, designer, panel_name, drawing_number, revision, date, status}`. The revision check (01 §4.5) compares `drawing_number` |
| `quota jsonb` | `{counted, reason, reservation_id, quota_event_id}`. `reason` is `new_drawing`, `revision` or `reuse` (the same files again, 01 §4.5); `quota_event_id` is the `confirm` |
| `issues jsonb` | Stage-level issues `{code, severity, page_id, message, stage}`. A run that ends in the DLQ adds `pipeline_failed`; stage 1 adds its 01 §8 notices, and `needs_confirmation` with `reasons` |
| `trace_id`, `created_by → users` | |

**`drawing_files`** (`fil_`): `original_name`, `detected_format`, `sha256`, `size_bytes`, `page_count`, `storage_key`, `role` (`drawing`, or `audited_quote` for the quote uploaded with an audit, 11 §4; stage 1 reads only `drawing` files; migration 0011). An index on `(tenant_id, sha256)` supports reuse (01 §5.1). A file inside a ZIP is its own row, named `archive.zip/inner.pdf`.

**S3 keys** (`konboro.services.storage`): everything sits under `tenants/{tenant_id}/`, and every read checks the key is under the caller's tenant. Under it, `drawings/{drawing_id}/` holds `files/{file_id}.{ext}` (never the uploaded name), `pages/{page_id}/thumb.png`, and `stages/s{n}.json` (each stage's contract). Stage 2 adds, per page: `render.png`, `paths.json.gz` (lines and shapes), `wires.json.gz` (the wire graph), `tiles/r{row}c{col}.png` (detection tiles) and the viewer's pyramid (12 §6): `dz/page.dzi`, with every tile packed into `dz/tiles.bin` and their byte ranges in `dz/index.json`. The API serves `GET /pages/{page_id}/dz/page.dzi` and `…/dz/page_files/{level}/{col}_{row}.png` from the pack, inside the tenant check (S11). Stage 2 points `pages.render_key` at `render.png`; the thumbnail stays at `thumb.png`. The NURSERY-1 fixture writes the same keys from the prototype's page images (S11).

**`pages`** (`pg_`, 01 §6.3):

| Columns | Notes |
| --- | --- |
| `file_id → drawing_files`, `page_no`, `sha256`, `reused_from → pages null` | |
| `width_pt`, `height_pt`, `rotation_applied` | Rotation is 0, 90, 180 or 270 |
| `geometry_source`, `text_source`, `quality` | |
| `page_kind`, `page_kind_confidence`, `route` | `route` is `process`, `context` or `skip` |
| `classified_by`, `model` | `classified_by` is `model`, `user`, `reused` or `template` (01 §5.7). `model` is the model that classified the page, prefixed `stand-in:` when the local stand-in answered; a run on the real model never reuses those pages (BUG-041). A person's reclassification clears it, except on a stand-in page, which keeps the mark because its title block and tag reading are still the stand-in's (BUG-042). `stand-in:stub-s05` and `stand-in:unknown` come from migration 0014 (BUG-043) |
| `component_labels` | The classifier's reading of the device tags: `tags_and_models`, `tags_only`, `none` or `not_applicable` (01 §5.4). `input_kind` counts them on the diagram pages (01 §4.4), so a page reused by hash keeps them. Null for a page classified by a template or the user (migration 0006, BUG-015) |
| `title_block jsonb`, `regions jsonb` | `regions`: everything the classifier found, `[{region_kind, bbox, panel_name, confidence}]`, panels included (`panel`) whatever the page's route, so a page-kind change can rebuild the panels (S08) |
| `render_key`, `tiles_prefix` | S3 keys, written by stage 2: the page render, and the prefix of its detection tiles and its viewer pyramid (`dz/`) |
| `tile_count` | The page's tiles that are not blank (02 §2.6), for the run step's stage-2 line. Null until stage 2 runs on the page (migration 0007, S10) |
| `symbol_count`, `symbol_llm_count` | Stage 3's detections on the page, and how many of them the disambiguation call decided (03 §3.4), for the run step's stage-3 line. Null until stage 3 runs on the page (migration 0008, S12) |

**`panels`** (`pnl_`): `drawing_id`, `name`, `page_ids text[]`, `bboxes jsonb` (page → bbox), and `confidence`.

**`context_artifacts`** (`ctx_`): `drawing_id`, `page_id`, `kind` (e.g. `general_notes`, `bom_table`, `legend`), `format`, `content text`. A `bom_table` (S14, 01 §5.8) is JSON (`pipeline/bom/table.py`, `BomTable`): the source (`spreadsheet` or `image`), the sheet, the heading's panel and project, each column with its role and who gave it (`code`, `model`, `user`), the rows' cells, a confidence per cell and a box per row from a picture, `mapping_sure` and `cropped`. A picture's price cells are never kept. The user's column roles rewrite it.

**`page_templates`** (`tpl_`, 01 §5.7): a factory's fixed page, so the next drawing from the same producer classifies it without a model.
- `producer`: the title block's `designer`, normalized; `page_kind` (`factory_template`).
- `fingerprint`: a 64 × 64 ink map as hex (`pipeline/intake/templates.py`); `mask real[]`: the title block, as page fractions, left out of the comparison.
- `source_page_id`: the page it came from, for the audit trail. No foreign key: a template outlives its drawing.
- Index on `(tenant_id, producer)`. Matching never leaves the tenant (RLS) or the producer.

**`stage_runs`** has PK `(tenant_id, drawing_id, stage)`. It records progress, retries and where each stage's output lives.
- `stage`: 1–7, and 8 for the audit step after stage 4 of an audit drawing (11 §5.1, S15 decision 2, migration 0011). An audit drawing has rows 1–8; 5–7 end `skipped`.
- `status`: `queued`, `running`, `done`, `failed` or `skipped`.
- `attempts`, `started_at`, `finished_at`.
- `output_key`: the contract JSON in S3 (00 §5).
- `error jsonb`: `{type, message, attempt}` of the last failure.
- `sent_at`: when the stage's message was last sent. Stage 1's is set by the upload, every other stage's by the stage before it, and the worker's sweep updates it when it sends one again.
- All seven rows are created with the upload, as `queued`. A cancel marks the unfinished ones `skipped`.

**`components`** (`cmp_`, 04 §6.3) is the stage 4 output, kept in the DB because quote lines and audits point at it. Stage 4 writes them (S13), and replaces the drawing's rows when it runs again. The id is the contract's `component_id`, `cmp_<drawing ulid>_<n>`: stable across reruns of the same input.
- `drawing_id`, `panel_id`, `family`.
- `attributes jsonb`: per attribute, `{value, source, confidence, span_ids}`.
- `quantity numeric(12,3)`, `designators text[]`.
- `instances jsonb`: a list of `{instance_id, page_id, bbox, role}`, used for highlighting on the drawing. A BOM row (S14) has role `bom_row`, its `rows` in the table, and `bbox` null when it came from a spreadsheet.
- `confidence`, `brand_hint`, `explicit_texts jsonb`.
- `supply_scope`: `in_panel`, `other_location`, `prepare_only` or `by_others` (04 §5.1.2). The values were `outside_panel`, `prep_only` and `not_in_scope` until migration 0009 (S13): the spec's names won.
- `match_status null`, `catalog_item_id null → catalog_items` (migration 0015): stage 5's result (05 §7), written by stage 5 for the run step and what points at a component; `auxiliary` for a family the factory counts as auxiliary material (S20 decision 3). The full match is stage 5's contract in S3.

## 6. Tenant layer: quotes, price list, learning

### 6.1 Quotes (07 §6, §7.7)

**`quotes`** (`quo_`):
- `drawing_id → drawings null`. A quote built in chat has one too: its drawing of `origin` = `chat` (S27 design 1), so the review screen's actions, picker, overlay and export work on it. `null` is for a quote built by hand.
- `customer_id`, `project_id`, `name`.
- `current_version int`.

**`quote_versions`** (`qv_`) has `UNIQUE (tenant_id, quote_id, version)`.

| Columns | Notes |
| --- | --- |
| `quote_id`, `version int` | |
| `status` | `draft` or `sent`. A sent version never changes; a trigger rejects updates to its lines and to the version row |
| `revision int not null default 0` | Increases on every edit: each run of stage 7 bumps it (`pricing.run`, `pricing.stored`). Used for the optimistic check (09 §11) and proposal expiry (08 §7.5, S25) |
| `quote_date`, `currency` | |
| `discount_pct`, `totals jsonb` | `totals` follows the 07 §6.1 shape, with decimal strings |
| `snapshot jsonb` | What priced this version (07 §7.7, S22): `price_list_ids` (the `product_suppliers` rows its lines used), `products`, `margin_rules_version`, `derived_rules_version`, `fx_rates`, `vat_rate_id`, `rounding`, the panels' `notes` (supply scope `prepare_only` / `by_others`), and `deleted_line_keys` (lines the user deleted, carried into later versions, S22 decision 5) |
| `diff_from_previous jsonb` | Against the sent version this one follows (07 §7.7): `from_version`, `lines[]` (`key`, `change` added / removed / changed, `before`, `after`, `delta`, `why`: sku, qty, cost, margin_rule, price), `net_before`, `net_after`, `delta`. "Open version N+1" writes `{from_version, lines: [], copied: true}` |
| `sent_at`, `sent_by` | |

**`quote_lines`** (`ln_`, 07 §6.2):

| Columns | Notes |
| --- | --- |
| `quote_version_id`, `panel_id null`, `position int`, `line_group` | `line_group` is the review screen's group: feed, outputs, control, enclosure, outside (07 §7.4 "מחוץ ללוח") |
| `line_key null` | Stage 7's stable handle: `c:<component>`, `c:<component>:kit:<n>`, `m:<instance>`, `d:<panel>:<rule>[:<item>]`, `l:<panel>`. A rerun carries what the user did on the line by it (migration 0017, S22 decision 5) |
| `line_type` | `component`, `derived`, `labor`, `manual`, `missing` |
| `component_id null`, `parent_line_id null` | `component_id` is how a line points back to the drawing |
| `signature null`, `brand_context null` | The component's signature (05 §3) and the brand context a match memory for it belongs to (05 §6 `brand_context`: the customer's brand when the customer's preference chose it, else null). Stage 7 writes them from stage 5's match; the fixtures' seed signs its lines the same way. `compare` with another quote pairs lines by signature (08 §6.5), and a proposal remembered for a customer or the factory writes the memory under them (08 §7.4). Null on a kit part, a derived, labor or manual line, and a family with no schema. Migration 0022, S25b |
| `catalog_item_id null`, `product_id null` | |
| `sku`, `description`, `manufacturer`, `qty numeric(12,3)`, `unit` | |
| `unit_cost null`, `cost_source jsonb`, `price_status` | `price_status` is `ok`, `stale`, `discount_based` or `missing` |
| `margin_rule jsonb` | Where the sale price comes from: 07 §6.1's rule `{rule_id, level, kind, value}`, or for a fixed product price `{kind: "fixed", source, quotes}`, e.g. imported from earlier quotes (S09). The review screen shows it as the price's source |
| `unit_price_raw`, `unit_price`, `rounding`, `line_cost`, `line_total`, `margin_pct` | All `null` while the line has no price |
| `derived jsonb`, `alternatives jsonb`, `explanation` | |
| `status`, `status_reasons jsonb`, `issue_ids text[]` | `status` is `green`, `yellow` or `red`, and only stage 7 writes it |
| `override jsonb`, `approved_at`, `deleted_at` | A price set for this quote only; the estimator's approval (09 §7.2); a soft delete, so undo brings the line back |
| `edits jsonb` | The review screen's other edits, carried by `line_key` through a recalculation and a rerun: `qty`, the `supplier_id` chosen for this quote (07 §7.2.2 step 1), and `replaced` (the alternative's `sku`, `manufacturer`, `description`, `catalog_item_id`, 09 §7.3; also a product picked for a missing line, with `product_id`, and `resolved`, 09 §7.8). Since S23b `attrs` (a current or breaking capacity the user set, 09 §7.4) and `match` (stage 5's answer with it: `sku`, `manufacturer`, `description`, `catalog_item_id`, `reasons`, `alternatives`, `explanation`). Migration 0018, S23 |
| `boxes jsonb` | Where a line with no component is on the drawing, `[{page_id, bbox}]` in PDF points: a missing line's instance and a component the estimator marked (09 §6.6). Migration 0019, S23b |

**`findings`** (`iss_`, 06 §6.2) are issues from the validator and from pricing. Stage 6 writes its own on the drawing, replacing them on every run, with `quote_version_id` null; stage 7 attaches them to the version it makes (S21 decision 1). The id is a digest of what the finding says, so a re-run keeps it. `values.title` is the finding's headline; `code` is the rule's id.
- `quote_version_id`, `drawing_id`.
- `source`: `rule`, `bom_crosscheck`, `agent` or `pricing`.
- `rule_id`, `rule_version`, `category`, `severity`, `code`.
- `panel_id`, `component_ids text[]`, `instance_ids text[]`, `line_ids text[]`.
- `page_id`, `bbox jsonb`.
- `message`, `values jsonb`, `confidence`.
- `status`: `open`, `resolved` or `dismissed`.
- `dismissal jsonb null`: why the estimator dismissed it (09 §7.7, 06 §11): `reason` (`intended`, `checker_wrong`, `other`, or `approved` when approving its lines dismissed it), `text`, `by`, `at`, `event_id` (migration 0018, S23). A dismissed finding's reasons leave its lines.

**`correction_events`** (`evt_`, 09 §10) is append-only. The app may update only `undone`, and a trigger enforces this. So an event is written once, whole: a review action keeps what undo needs to put back in `before.restore` (the lines' state, the findings, the price-list product, the match memory, S23).
- `quote_id`, `quote_version`, `user_id`.
- `source`: `review_screen`, `chat`, `price_list`, or `new_quote` (a page kind changed on the new-quote screen, S08).
- `type`: the 09 §10 list, plus `price_changed` and `supplier_selected` from 09 §7.14–7.15, `bom_columns_mapped` (the user set a BOM spreadsheet's column roles, 01 §5.8; migration 0010, S14), `discount_set` (the customer discount on the quote, 08 §6.7, from the chat; migration 0021, S25), and `memory_saved` (the match memory a chat proposal wrote for a customer or the factory, 08 §7.4, with `before.restore.memory`: each row as it was, or `absent` for a row it made; migration 0022, S25b).
- `line_id`, `component_id`, `instance_ids`, `page_id`.
- `before jsonb`, `after jsonb`, `reason`, `undone bool`.

### 6.2 Price list (07 §7.2.1–7.3)

**`products`** (`prd_`) holds one record per product (07 §7.2.1).

| Columns | Notes |
| --- | --- |
| `catalog_item_id null` | Links to the master catalog |
| `display_name`, `manufacturer_sku null`, `brand`, `family`, `unit default 'unit'` | Unique `(tenant_id, manufacturer_sku)` when not null |
| `sale_mode` | `rule` or `fixed`; `fixed_price null` |
| `includes jsonb`, `consumable bool` | |
| `source` | `supplier_price_list`, `manual_entry`, `quote_import`, `brand_discount` |
| `entered_in_quote`, `entered_by`, `entered_at` | |
| `sanity jsonb` | 10 §9.2 |

The rest of the price-list tables:
- **`suppliers`** (`sup_`): the tenant's supplier list, with `name` unique per tenant.
- **`product_suppliers`** (`psp_`, 07 §7.2.2):
  - `product_id`, `supplier_id null`, `supplier_sku`, `unit_cost`, `currency`, `lead_days`, `price_date`, `valid_until`, `preferred bool`, `source`.
  - A partial unique index allows at most one preferred supplier per product.
  - `supplier_id` is null for a cost typed in a quote with no supplier (07 §7.2). A second partial unique index allows at most one such row per product (migration 0012, S18 decision 7).
- **`supplier_preferences`** (`spf_`, 07 §7.2.2 item 3; migration 0012, S18 decision 3): `scope` (`brand` or `family`), `key`, `supplier_id`, unique `(tenant_id, scope, key)`. The family's preference applies before the brand's.
- **`price_history`** (`prh_`): `product_id null`, `subject null`, `field`, `old jsonb`, `new jsonb`, `quote_id null`, `changed_by`, `created_at`.
  - A change to a product sets `product_id`. A change to anything else names it in `subject`, and a check requires one of the two (07 §12; migration 0012). Subjects: `brand_discount:<brand>`, a margin rule's id, `supplier_preference:<scope>:<key>`.
  - `old` and `new` are `{"value": …}` for one field, or a whole supplier row or rule. Amounts are strings.
- **`brand_discounts`**: `brand`, `discount_pct`, with PK `(tenant_id, brand)`.
- **`margin_rules`** (`mr_`, 07 §7.3):
  - `level` is `customer_sku`, `customer`, `sku`, `family`, `brand` or `default`.
  - `target`: the product's id for `sku` and `customer_sku`, the family or the brand for those levels, and null for `customer` and `default`. `customer_id null`: set for the two customer levels.
  - A product's fixed price is not a rule row: it is `products.fixed_price`, which counts as the `sku`-level rule when a rule is picked (S18 decision 6).
  - `kind` is `markup` or `margin`; `value`, `fixed_price null`.
  - `valid_from`, `valid_to`, `version int`.
  - Checks: `margin < 1`, and exactly one of `value` or `fixed_price`.
- **`derived_item_rules`** (`dr_`, 07 §7.4): `rule_key` (the starter rule it copies, unique per tenant), `scope`, `trigger jsonb`, `quantity_formula` (the rule's kind: the function in `pipeline/pricing/derived.py`), `item jsonb` (the catalog query, e.g. `{"family": "enclosure"}`), `params jsonb` (spare share, per output, consumables percentage), `explanation_he`, `enabled`, `version`, `approval` (`pending_expert` until roadmap B2). A tenant with no rows gets a copy of `pipeline/pricing/derived.json` (`pricing.load.ensure_rules`, from stage 7 and `make seed`); one that has rows keeps them as they are. Migration 0017.

### 6.3 Learning, chat and audit

- **`match_memory`** (`mm_`, 05 §11):
  - `customer_id null`, `signature`, `brand_context null`, `sku`, `approved_count`, `last_used_at`.
  - Unique `(tenant_id, coalesce(customer_id,''), signature, coalesce(brand_context,''))`.
- **`tenant_abbreviations`** (`tab_`): the tenant's and designers' abbreviation dictionary (03 §4.6). Columns: `scope` (`tenant` or `designer`), `designer null`, `text`, `symbol_class`, `family`.
- **`tenant_reference_crops`** (`trf_`): reference crops in `tenant`, `designer` or `drawing` scope (03 §4.3). Never visible to another tenant. Since S23b a component marked on the review screen (09 §6.6) writes one, `drawing` scope, `source` = `user_correction`, its class the family's default (S23b decision 5), the crop under `tenants/{tenant_id}/drawings/{drawing_id}/marks/`. Stage 3 does not read them yet.
- **`tenant_rule_overrides`**: `rule_id`, `enabled`, `params jsonb`, with PK `(tenant_id, rule_id)` (06 §6.2).
- **`knowledge_candidates`** (`kc_`) is the pilot approval queue (00 §14.2).
  - `kind`: `symbol`, `abbreviation`, `spelling`, `catalog_item` or `catalog_attribute`.
  - `payload jsonb`: only the fields the kind's global record takes (`services/knowledge.py`'s `FIELDS`), never a price, a supplier, a customer, a project or a designer (10 §11). `evidence jsonb`: the factory's own (its product's name, the quote, `what` and `origin` for the card), never copied.
  - `status`: `pending`, `approved` or `rejected`.
  - `decided_by`, `decided_at`, `reason`.
  - `dedupe_key` (migration 0020): unique `(tenant_id, kind, dedupe_key)`, so the same thing (a brand's SKU, a text, a pattern, a class, an item's attribute) is queued once, pending or decided. `promoted_id`: the global record the approval wrote or found.

  An approval does not write to the global layer directly: `konboro_promote` does, in the same transaction (§2, S24 decision 4). A refused promotion (another value for the same attribute) rolls the approval back and the candidate stays pending. Since S24 a factory product with a SKU and a brand the master catalog lacks is a `catalog_item` candidate (behind `approval_queue`); an approved one links the product to its new catalog item.
- **`chat_conversations`** (`cnv_`, 08 §5.2.1):
  - `quote_id`, `status` (`active` or `closed`; one active conversation per quote), `summary`.
  - The summary never contains money (08 §5.4): `chat.history` strips amounts and references before saving it.
  - `state jsonb` (migration 0021, S25): `names`, the short names the model was given (`L3` → `ln_…`, `B1`, `F2`, `CH1`, and since S25b `QT1` for another quote and `I1` for an instance on the drawing); `money`, each money reference with its amount (`$T1` → `{kind: ils, value}`, `$P1` for a percentage), which only the screen gets; `counters`; and `compacted_through`, the last message the summary covers.
- **`chat_messages`** (`msg_`): `conversation_id`, `role`, `content jsonb`, `tokens`.
  - A user message's `content`: `seq`, `text`, `model_text` (with the screen context, as the model got it), `ui_context`.
  - An assistant message's: `seq`, `blocks` (08 §8.1, line references as ids), `answer_text` (as the model wrote it), `tool_summaries` (one line per call, what later turns get, 08 §5.2.1), `tool_calls` (each tool with its arguments, 08 §10's log), `money_refs`, `instances` (where each instance the answer points at is, page and bbox, S25b), `errors` (`invalid_ref`, `amount_removed`, `tool_failed`).
- **`build_messages`** (`bmg_`, 13 §4.2, migration 0024, S27): a chat build's conversation, by `drawing_id` (cascade), since the quote exists only from the first line (S27 decision 2).
  - `role` (`user` or `assistant`), `status` (`applied`, `pending`: a recording waiting for "הוסף"; `dismissed`: "תקן"; `undone`), `content jsonb`.
  - A user message's `content`: `text`, `heard` (what a recording was heard as; the recording itself is never stored), `items` and `changes` the code check kept (a change with its `line_id`), `dropped` (with why), `question` (the model's, short names replaced by descriptions), and `rows`: the build's rows after it, on a message that changed them. The build's rows are its last applied message's; undo marks that message `undone`.
  - An assistant message's: `text`, the reply written in code.
- **`chat_proposals`** (`prp_`, 08 §7.1):
  - `quote_id`, `conversation_id`, `base_version`, `base_revision`, `summary_he`, `changes jsonb`, `diff jsonb`, `remember_default`.
  - `changes`: each change with the lines it applies to, as ids and line keys, resolved once by code (`chat.proposals.resolve`). `diff`: lines changed, added, removed and derived, totals before and after and new and resolved findings, every amount a money reference of the conversation.
  - `warnings jsonb`, `affected_line_count`, `alias` (`CH1`), migration 0021.
  - `remember_options jsonb` (08 §7.1): `["quote_only"]`, or with `customer` (when the quote has one) and `tenant` for a brand or SKU swap that moves a signed line. `remembered`: the scope chosen on "החל". Migration 0022, S25b.
  - `status`: `pending`, `applied`, `dismissed`, `expired`, or `undone` (applied, then taken back by the review screen's undo).
  - `resolved_at`.
  - Applying writes the review actions' correction events with `source` = `chat` and `after.proposal` = the proposal's id; `review.undo` on any of them undoes them all, newest first.
- **`audits`** (`aud_`, 11 §6): written by `POST /audits` (`processing`) and the audit step (S15).
  - `drawing_id` (the drawing has `purpose` = `audit`), `quote_file_id → drawing_files`, `quote_ref jsonb` (`number`, `date`, `total_before_vat` as a string), `input_kind`, `summary jsonb` (11 §6), `issues jsonb` (reading the quote: `quote_no_lines`, `quote_unreadable`, `quote_mapping_unsure`).
  - `status`: `processing`, `ready` or `failed` (the drawing failed, was cancelled, or its quota ran out).
  - `corrected_quote_id null` (11 §8).
- **`audit_quote_lines`** (`aql_`, S15): the audited quote's lines as read, signed and matched (11 §5.2–5.3). Only the line, its quantity and its prices are kept, never a customer detail (11 §11).
  - `audit_id`, `line_index` (unique per audit, from 1, the `quote_line_index` differences point at).
  - `description`, `qty numeric(12,3) null`, `unit_price`, `line_total numeric(14,4) null`, `confidence`.
  - `page_no null`, `rows int[]`, `bbox jsonb null` (from a picture: where the line is on the quote's page).
  - `signature jsonb` (family, class, values, range, included items), `component_ids text[]`, `matched_qty`.
  - `status`: `matched`, `quantity_differs`, `attribute_differs`, `not_in_drawing` or `arithmetic`.
- **`audit_differences`** (`dif_`):
  - `audit_id`, `type` (11 §5.4's eight and `not_a_difference`), `severity` (`high`, `medium`, `low`, `info`), `confidence`, `family`, `designators text[]`, `component_ids text[]`.
  - `drawing_qty`, `quote_qty`, `quote_line_index`.
  - `evidence jsonb`, `suggested_line jsonb`, `message`, `amount null` (negative for an over-charge).
  - `status`: `open`, `confirmed` or `rejected`; `reject_reason` (`included_elsewhere`, `customer_supplies`, `system_error`, `other`), `reject_note`, `decided_by → users`, `decided_at`.
  - The audit step replaces the rows when it runs again; a decided difference that comes back keeps its decision.

## 7. ID prefixes

The prefixes 00 §6.1 defines: `drw_ fil_ pg_ pnl_ ts_ blk_ tl_ det_ ins_ cmp_ iss_ quo_ ln_ trc_`.

Added here:

| Prefix | Entity | Prefix | Entity |
| --- | --- | --- | --- |
| `tnt_` | tenant | `usr_` | user |
| `cus_` | customer | `prj_` | project |
| `ctx_` | context artifact | `qv_` | quote version |
| `evt_` | correction event | `prd_` | price-list product |
| `sup_` | supplier | `psp_` | product–supplier price |
| `prh_` | price history | `mr_` | margin rule |
| `dr_` | derived-item rule | `mm_` | match memory |
| `qev_` | quota event | `llm_` | LLM call |
| `cnv_` | conversation | `msg_` | chat message |
| `prp_` | chat proposal | `aud_` | audit |
| `dif_` | audit difference | `kc_` | knowledge candidate |
| `aql_` | audited quote line | `bmg_` | chat build message |
| `tpl_` | factory page template | | |
| `cat_` | catalog item | `ref_` | reference crop (global) |
| `trf_` | reference crop (tenant) | `abr_` | abbreviation (global) |
| `tab_` | abbreviation (tenant) | `vat_` | VAT rate |
| `spf_` | supplier preference | `ckt_` | catalog kit part (global) |
| `cac_` | catalog accessory fit (global) | `spl_` | spelling pattern (global) |

## 8. Indexes beyond keys

- `drawings (tenant_id, created_at desc)`: the home screen's recent-work list.
- `drawing_files (tenant_id, sha256)`: reusing a file that was already uploaded.
- `quote_lines (tenant_id, quote_version_id, position)`, plus a partial index `WHERE deleted_at IS NULL`.
- `findings (tenant_id, quote_version_id, status)`.
- `correction_events (tenant_id, quote_id, created_at)`.
- `products (tenant_id, family)` and `(tenant_id, brand)`.
- `match_memory (tenant_id, signature)`.
- `llm_calls (tenant_id, created_at)`: cost reports.
- `knowledge_candidates (tenant_id, status)`.

## 9. What stays out of v1.0

- The `vector` column on reference crops, and the similarity index (phase 4).
- CAD block mapping (v2.0, 02 §2.2).
- Multi-user roles beyond `owner` (00 §14.1). The `role` column and the check constraint are already in place.
- Learning examples from corrections (04 §11). Until then they are read from `correction_events`.
