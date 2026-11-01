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
- Seeded keys: spec 13's five, plus `review_screen` (S09), which gates the review screen while it is built and goes away in S23.

**`plan_feature_flags`** holds the plan-level flag setting: `plan_id → plans`, `flag_key → feature_flags`, `enabled bool`, with PK `(plan_id, flag_key)`.

### 3.2 Catalog and knowledge

**`catalog_items`** is the master catalog (05 §4.3, 07 §4.3).

| Columns | Notes |
| --- | --- |
| `id` (`cat_`) | |
| `sku`, `brand`, `series`, `model_code`, `family` | Unique `(brand, sku)` |
| `attributes jsonb` | Normalized attribute values, by the family's schema |
| `module_width numeric(5,2)` | For sizing the enclosure (07 §7.4) |
| `list_price numeric(14,4)`, `list_currency` | The manufacturer's list price, when known |
| `status` | `active` or `discontinued`; `replaced_by → catalog_items` |
| `includes jsonb` | For enclosures and kits (07 §7.4) |
| `source`, `source_tenant_id`, `approved_by`, `approved_at` | Where the record came from. `source` is one of `curated`, `pilot_engineer`, `import` (00 §14.2) |

The remaining global tables:
- **`attribute_schemas`** (05 §4.4): `family text pk`, `version int`, `attributes jsonb`. `attributes` is a list of `{name, required, match_mode, default_allowed}`. For `current_a` and `poles`, `default_allowed` is always false.
- **`symbol_classes`** (03 §4.3): `id text pk` (e.g. `mcb`), `family`, `display_name_he`, `billable bool`, `standard_ref`, `attribute_schema → attribute_schemas.family`, plus the source columns.
- **`reference_crops`** (03 §4.3), global scope only: `id` (`ref_`), `symbol_class → symbol_classes`, `image_key`, `source`, `approved_count`. The `embedding vector` column is added with the similarity index in phase 4. The `vector` extension is enabled now.
- **`abbreviations`** (03 §4.6), global: `id` (`abr_`), `text`, `symbol_class`, `family`, `display_he`, plus the source columns.
- **`validator_rules`** (06 §6.2): PK `(rule_id, version)`, `category` (A–E), `applies_to text[]`, `requires text null`, `severity`, `params jsonb`, `message_he`, `enabled bool`.
- **`vat_rates`** (07 §4.3): `id` (`vat_`), `rate numeric(7,4)`, `valid_from date`. The VAT rate is data, never a constant in code.
- **`fx_rates`**: `currency`, `rate_date`, `rate numeric(14,6)`, `source`, with PK `(currency, rate_date)`.

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
| `data_terms_accepted jsonb` | `{version, by, at}` |
| `onboarding jsonb` | 10 §9.1 |

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
| `status` | `uploaded`, `processing`, `awaiting_confirmation`, `ready`, `failed`, `cancelled` |
| `input_kind null` | `factory_drawing`, `designer_plan`, `bom_only`, `mixed`. Set by stage 1 |
| `current_stage smallint null`, `progress real` | What the "run" screen shows |
| `needs_confirmation bool` | Stage 1 asks the user to confirm the pages (01 §5.6); the drawing waits in `awaiting_confirmation` |
| `title_block jsonb null` | The drawing's title block, read once by stage 1 (S08): `{project_name, designer, panel_name, drawing_number, revision, date, status}`. The revision check (01 §4.5) compares `drawing_number` |
| `quota jsonb` | `{counted, reason, reservation_id, quota_event_id}`. `reason` is `new_drawing`, `revision` or `reuse` (the same files again, 01 §4.5); `quota_event_id` is the `confirm` |
| `issues jsonb` | Stage-level issues `{code, severity, page_id, message, stage}`. A run that ends in the DLQ adds `pipeline_failed`; stage 1 adds its 01 §8 notices, and `needs_confirmation` with `reasons` |
| `trace_id`, `created_by → users` | |

**`drawing_files`** (`fil_`): `original_name`, `detected_format`, `sha256`, `size_bytes`, `page_count`, `storage_key`. An index on `(tenant_id, sha256)` supports reuse (01 §5.1). A file inside a ZIP is its own row, named `archive.zip/inner.pdf`.

**S3 keys** (`konboro.services.storage`): everything sits under `tenants/{tenant_id}/`, and every read checks the key is under the caller's tenant. Under it, `drawings/{drawing_id}/` holds `files/{file_id}.{ext}` (never the uploaded name), `pages/{page_id}/thumb.png`, and `stages/s{n}.json` (each stage's contract). Stage 2 adds, per page: `render.png`, `paths.json.gz` (lines and shapes), `wires.json.gz` (the wire graph), `tiles/r{row}c{col}.png` (detection tiles) and the viewer's pyramid (12 §6): `dz/page.dzi`, with every tile packed into `dz/tiles.bin` and their byte ranges in `dz/index.json`. The API serves `GET /pages/{page_id}/dz/page.dzi` and `…/dz/page_files/{level}/{col}_{row}.png` from the pack, inside the tenant check (S11). Stage 2 points `pages.render_key` at `render.png`; the thumbnail stays at `thumb.png`. The NURSERY-1 fixture writes the same keys from the prototype's page images (S11).

**`pages`** (`pg_`, 01 §6.3):

| Columns | Notes |
| --- | --- |
| `file_id → drawing_files`, `page_no`, `sha256`, `reused_from → pages null` | |
| `width_pt`, `height_pt`, `rotation_applied` | Rotation is 0, 90, 180 or 270 |
| `geometry_source`, `text_source`, `quality` | |
| `page_kind`, `page_kind_confidence`, `route` | `route` is `process`, `context` or `skip` |
| `classified_by`, `model` | `classified_by` is `model`, `user`, `reused` or `template` (01 §5.7) |
| `component_labels` | The classifier's reading of the device tags: `tags_and_models`, `tags_only`, `none` or `not_applicable` (01 §5.4). `input_kind` counts them on the diagram pages (01 §4.4), so a page reused by hash keeps them. Null for a page classified by a template or the user (migration 0006, BUG-015) |
| `title_block jsonb`, `regions jsonb` | `regions`: everything the classifier found, `[{region_kind, bbox, panel_name, confidence}]`, panels included (`panel`) whatever the page's route, so a page-kind change can rebuild the panels (S08) |
| `render_key`, `tiles_prefix` | S3 keys, written by stage 2: the page render, and the prefix of its detection tiles and its viewer pyramid (`dz/`) |
| `tile_count` | The page's tiles that are not blank (02 §2.6), for the run step's stage-2 line. Null until stage 2 runs on the page (migration 0007, S10) |

**`panels`** (`pnl_`): `drawing_id`, `name`, `page_ids text[]`, `bboxes jsonb` (page → bbox), and `confidence`.

**`context_artifacts`** (`ctx_`): `drawing_id`, `page_id`, `kind` (e.g. `general_notes`, `bom_table`, `legend`), `format`, `content text`.

**`page_templates`** (`tpl_`, 01 §5.7): a factory's fixed page, so the next drawing from the same producer classifies it without a model.
- `producer`: the title block's `designer`, normalized; `page_kind` (`factory_template`).
- `fingerprint`: a 64 × 64 ink map as hex (`pipeline/intake/templates.py`); `mask real[]`: the title block, as page fractions, left out of the comparison.
- `source_page_id`: the page it came from, for the audit trail. No foreign key: a template outlives its drawing.
- Index on `(tenant_id, producer)`. Matching never leaves the tenant (RLS) or the producer.

**`stage_runs`** has PK `(tenant_id, drawing_id, stage)`. It records progress, retries and where each stage's output lives.
- `stage`: 1–7.
- `status`: `queued`, `running`, `done`, `failed` or `skipped`.
- `attempts`, `started_at`, `finished_at`.
- `output_key`: the contract JSON in S3 (00 §5).
- `error jsonb`: `{type, message, attempt}` of the last failure.
- `sent_at`: when the stage's message was last sent. Stage 1's is set by the upload, every other stage's by the stage before it, and the worker's sweep updates it when it sends one again.
- All seven rows are created with the upload, as `queued`. A cancel marks the unfinished ones `skipped`.

**`components`** (`cmp_`, 04 §6.3) is the stage 4 output, kept in the DB because quote lines and audits point at it.
- `drawing_id`, `panel_id`, `family`.
- `attributes jsonb`: per attribute, `{value, source, confidence, span_ids}`.
- `quantity numeric(12,3)`, `designators text[]`.
- `instances jsonb`: a list of `{instance_id, page_id, bbox, role}`, used for highlighting on the drawing.
- `confidence`, `brand_hint`, `explicit_texts jsonb`.
- `supply_scope`: `in_panel`, `outside_panel`, `prep_only` or `not_in_scope` (04 §5.1.2).

## 6. Tenant layer: quotes, price list, learning

### 6.1 Quotes (07 §6, §7.7)

**`quotes`** (`quo_`):
- `drawing_id → drawings null`. It is `null` for a quote built in chat or by hand.
- `customer_id`, `project_id`, `name`.
- `current_version int`.

**`quote_versions`** (`qv_`) has `UNIQUE (tenant_id, quote_id, version)`.

| Columns | Notes |
| --- | --- |
| `quote_id`, `version int` | |
| `status` | `draft` or `sent`. A sent version never changes; a trigger rejects updates to its lines and to the version row |
| `revision int not null default 0` | Increases on every edit. Used for the optimistic check (09 §11) and proposal expiry (08 §7.5) |
| `quote_date`, `currency` | |
| `discount_pct`, `totals jsonb` | `totals` follows the 07 §6.1 shape, with decimal strings |
| `snapshot jsonb` | Price lists, rule versions, FX and VAT used for this version |
| `diff_from_previous jsonb` | |
| `sent_at`, `sent_by` | |

**`quote_lines`** (`ln_`, 07 §6.2):

| Columns | Notes |
| --- | --- |
| `quote_version_id`, `panel_id null`, `position int`, `line_group` | `line_group` is the review screen's group: feed, outputs, control, enclosure |
| `line_type` | `component`, `derived`, `labor`, `manual`, `missing` |
| `component_id null`, `parent_line_id null` | `component_id` is how a line points back to the drawing |
| `catalog_item_id null`, `product_id null` | |
| `sku`, `description`, `manufacturer`, `qty numeric(12,3)`, `unit` | |
| `unit_cost null`, `cost_source jsonb`, `price_status` | `price_status` is `ok`, `stale`, `discount_based` or `missing` |
| `margin_rule jsonb` | Where the sale price comes from: 07 §6.1's rule `{rule_id, level, kind, value}`, or for a fixed product price `{kind: "fixed", source, quotes}`, e.g. imported from earlier quotes (S09). The review screen shows it as the price's source |
| `unit_price_raw`, `unit_price`, `rounding`, `line_cost`, `line_total`, `margin_pct` | All `null` while the line has no price |
| `derived jsonb`, `alternatives jsonb`, `explanation` | |
| `status`, `status_reasons jsonb`, `issue_ids text[]` | `status` is `green`, `yellow` or `red`, and only stage 7 writes it |
| `override jsonb`, `approved_at`, `deleted_at` | |

**`findings`** (`iss_`, 06 §6.2) are issues from the validator and from pricing.
- `quote_version_id`, `drawing_id`.
- `source`: `rule`, `bom_crosscheck`, `agent` or `pricing`.
- `rule_id`, `rule_version`, `category`, `severity`, `code`.
- `panel_id`, `component_ids text[]`, `instance_ids text[]`, `line_ids text[]`.
- `page_id`, `bbox jsonb`.
- `message`, `values jsonb`, `confidence`.
- `status`: `open`, `resolved` or `dismissed`.

**`correction_events`** (`evt_`, 09 §10) is append-only. The app may update only `undone`, and a trigger enforces this.
- `quote_id`, `quote_version`, `user_id`.
- `source`: `review_screen`, `chat`, `price_list`, or `new_quote` (a page kind changed on the new-quote screen, S08).
- `type`: the 09 §10 list, plus `price_changed` and `supplier_selected` from 09 §7.14–7.15.
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
  - `product_id`, `supplier_id`, `supplier_sku`, `unit_cost`, `currency`, `lead_days`, `price_date`, `valid_until`, `preferred bool`, `source`.
  - A partial unique index allows at most one preferred supplier per product.
- **`price_history`** (`prh_`): `product_id`, `field`, `old jsonb`, `new jsonb`, `quote_id null`, `changed_by`.
- **`brand_discounts`**: `brand`, `discount_pct`, with PK `(tenant_id, brand)`.
- **`margin_rules`** (`mr_`, 07 §7.3):
  - `level` is `customer_sku`, `customer`, `sku`, `family`, `brand` or `default`.
  - `target`, `customer_id null`.
  - `kind` is `markup` or `margin`; `value`, `fixed_price null`.
  - `valid_from`, `valid_to`, `version int`.
  - Checks: `margin < 1`, and exactly one of `value` or `fixed_price`.
- **`derived_item_rules`** (`dr_`, 07 §7.4): `scope`, `trigger jsonb`, `quantity_formula`, `item jsonb`, `explanation_he`, `enabled`, `version`. A new tenant gets a copy of the starter rules.

### 6.3 Learning, chat and audit

- **`match_memory`** (`mm_`, 05 §11):
  - `customer_id null`, `signature`, `brand_context null`, `sku`, `approved_count`, `last_used_at`.
  - Unique `(tenant_id, coalesce(customer_id,''), signature, coalesce(brand_context,''))`.
- **`tenant_abbreviations`** (`tab_`): the tenant's and designers' abbreviation dictionary (03 §4.6). Columns: `scope` (`tenant` or `designer`), `designer null`, `text`, `symbol_class`, `family`.
- **`tenant_reference_crops`** (`trf_`): reference crops in `tenant`, `designer` or `drawing` scope (03 §4.3). Never visible to another tenant.
- **`tenant_rule_overrides`**: `rule_id`, `enabled`, `params jsonb`, with PK `(tenant_id, rule_id)` (06 §6.2).
- **`knowledge_candidates`** (`kc_`) is the pilot approval queue (00 §14.2).
  - `kind`: `symbol`, `abbreviation`, `spelling`, `catalog_item` or `catalog_attribute`.
  - `payload jsonb`, `evidence jsonb`.
  - `status`: `pending`, `approved` or `rejected`.
  - `decided_by`, `decided_at`, `reason`.

  An approval does not write to the global layer directly. A promotion job running as the owner role copies the record and stamps `source='pilot_engineer'`.
- **`chat_conversations`** (`cnv_`, 08 §5.2.1):
  - `quote_id`, `status` (`active` or `closed`; one active conversation per quote), `summary`.
  - The summary never contains money (08 §5.4).
- **`chat_messages`** (`msg_`): `conversation_id`, `role`, `content jsonb`, `tokens`.
- **`chat_proposals`** (`prp_`, 08 §7.1):
  - `quote_id`, `conversation_id`, `base_version`, `base_revision`, `summary_he`, `changes jsonb`, `diff jsonb`, `remember_default`.
  - `status`: `pending`, `applied`, `dismissed` or `expired`.
  - `resolved_at`.
- **`audits`** (`aud_`, 11 §6):
  - `drawing_id`, `quote_file_id → drawing_files`, `quote_ref jsonb`, `input_kind`, `summary jsonb`.
  - `status`: `processing`, `ready` or `failed`.
  - `corrected_quote_id null` (11 §8).
- **`audit_differences`** (`dif_`):
  - `audit_id`, `type`, `severity`, `confidence`, `family`, `designators text[]`.
  - `drawing_qty`, `quote_qty`, `quote_line_index`.
  - `evidence jsonb`, `suggested_line jsonb`, `message`, `amount null`.
  - `status`: `open`, `confirmed` or `rejected`; `reject_reason`.

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
| `tpl_` | factory page template | | |
| `cat_` | catalog item | `ref_` | reference crop (global) |
| `trf_` | reference crop (tenant) | `abr_` | abbreviation (global) |
| `tab_` | abbreviation (tenant) | `vat_` | VAT rate |

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
