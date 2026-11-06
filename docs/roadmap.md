# Roadmap

Every session is one branch `sNN-slug` and one PR, and every session includes its own tests. Each session has a file in [sessions/](sessions/), created at kickoff from [the template](sessions/_template.md). Phases and gates are explained in [dev-strategy.md §7–8](dev-strategy.md#7-definition-of-done-bugs-gates).

**Tracks:**
- **P**: pipeline and backend.
- **R**: review and UI.
- **X**: cross-cutting.
- **G**: gate.

**Status:** `todo`, `in progress`, `in review` (PR open), `done`, `blocked`.

Prototype references are line ranges in [prototype/konboro-app.html](../prototype/konboro-app.html).

## Phase 0: foundations and thin end-to-end skeleton

| # | Track | Session | Main contents | Specs | Prototype | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [S00](#s00) | X | Development plan | CLAUDE.md, dev strategy, roadmap, session files, bug log, session commands | README, HANDOFF | — | — | done |
| [S01](sessions/S01-tooling.md) | X | Tooling and repo layout | Monorepo, `konboro_llm` moved into `backend/`, uv/ruff/mypy/pytest, Vite+React+TS+MUI with RTL and the prototype tokens, Playwright smoke, docker-compose, Makefile, CI | 12 §3, §6, §8 | 9–32 | S00 | done |
| [S02](sessions/S02-db-schema-rls.md) | P | DB schema and RLS | `docs/db-schema.md`, SQLAlchemy models, first migration, RLS policies, cross-tenant tests, demo seed | 00 §6, §8; 01 §4.5; 07 §7.2; 13 §2 | 393–580 (data shapes) | S01 | done |
| [S03](sessions/S03-api-auth-flags.md) | P | API, auth, flags, quota | FastAPI app, dev JWT, `owner` permission check, `/me`, flags and quota endpoints, OpenAPI → TS client | 00 §14.1; 01 §4.5; 13 §2–3 | 384–388, 560–572 | S02 | done |
| [S04](sessions/S04-app-shell.md) | R | App shell, login, home | Shell, rail and tab bar, login, classic home and `home_chat` home, quota meter, first fidelity report | 09 §5, §13; 13 §4.3 | 660–751, 1253–1284 | S03 | done |
| [S05](sessions/S05-upload-pipeline-skeleton.md) | X | Upload and pipeline skeleton | Upload checks, atomic quota, S3 (S3Mock), ElasticMQ, coordinator with 7 stub stages emitting the contracts, progress and cancel, new-quote screen wired end to end | 00 §4–5; 01 §4.3–4.6; 12 §3 | 754–869 | S04 | done |
| [S06](sessions/S06-golden-eval.md) | P | Golden eval harness | Normalizers for 5 formats, per-stage metrics, reports, `make eval`, cassette record and replay, CI job | 00 §10; 01 §10; 04 §10; 11 §10 | — | S05 | done |
| [S07](sessions/S07-gate-0.md) | G | **Gate 0** | Full suite, fix bugs, docs. Tag `phase-0` | dev-strategy §7 | all built screens | S06 | done |

**Exit:** eval runs automatically on the golden set, the skeleton E2E is green, and the RLS tests are green.

## Phase 1: parsing + quote audit (P), alongside the review screen on fixtures (R)

P and R sessions alternate. R sessions use a fixture quote seeded through the real quote API (NURSERY-1, priced from its actual quote), so they never wait for the pipeline.

| # | Track | Session | Main contents | Specs | Prototype | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [S08](sessions/S08-stage1-intake.md) | P | Stage 1: intake and page classification | pypdfium2 rendering, rotation and quality, geometry and text source, sha256 reuse, `page_classification`, `input_kind`, context extraction, page confirmation and page-kind change, visibility heartbeat for long stages (BUG-009) | 01 (all) | 840–855 | S07 | done |
| [S09](sessions/S09-review-lines.md) | R | Review I: lines | Quote read API and fixture seed, split layout, virtualized grouped lines table, colors and filters, line detail (raw text, sources, why), keyboard | 09 §5–6.4, §8–9 | 872–941, 942–995 | S07 | done |
| [S10](sessions/S10-extraction-tiling.md) | P | Stage 2: extraction and tiling | pdfplumber vector text, `OcrEngine` interface + `ClaudeVisionOcr`, normalization with `raw_text`, low-confidence re-read, 1024/256 tiles, deep-zoom tiles in S3 | 02 (all); 12 §5 | — | S08 | done |
| [S11](sessions/S11-review-drawing.md) | R | Review II: drawing | OpenSeadragon viewer, SVG highlight boxes, page strip, "show on drawing", mobile tabs, toast, undo (5 s, 30 actions) | 09 §5.2, §6.5, §7.11 | 942–1004 | S09, S10 | done |
| [S12](sessions/S12-stage3-symbols.md) | P | Stage 3 v1: symbols | LLM-vision detection with library examples and the abbreviation dictionary, cross-tile de-duplication and owner tile, orphan text, designator linking | 03 §3.4–3.7, §6, §10 | — | S10 | done |
| [S13](sessions/S13-stage4-association.md) | P | Stage 4: association and merge | Spelling grammar as data, multiplicity, supply scope, geometric association, tile agent with citation check, merge by designator and then signature | 04 (all) | — | S12 | done |
| [S14](sessions/S14-bom-only.md) | P | BOM-only path | Excel and CSV import, photographed BOM through `table_transcription` (BOM-HW-1) | 01 §5.8 | — | S08 | done |
| [S15](sessions/S15-quote-audit.md) | P | Quote audit backend | Read the existing quote, arithmetic check, matching, 8 difference types, money at risk, API | 11 §4–6, §8 | — | S13, S14 | done |
| [S16](sessions/S16-audit-screen.md) | R | Audit screen | Audit flow and results screen, "create corrected quote" entry point, E2E on 26-993 (replay) | 11 §7–8 | 1066–1096 | S15 | done |
| [S17](sessions/S17-gate-1.md) | G | **Gate 1** | Live eval, full E2E regression, fix bugs. Tag `phase-1` | dev-strategy §7 | all built screens | S16 | done |

**Exit:** ≥80% difference accuracy on golden drawings that have actual quotes; audit and review E2E green.

## Phase 2: full quotes (v1.0)

| # | Track | Session | Main contents | Specs | Prototype | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [S18](sessions/S18-price-list-backend.md) | P | Price list backend | Products with several suppliers, preferred or else cheapest, margin rules, history, consumables, cabinet "includes", bulk brand discount, master-catalog import format | 07 §7.2–7.3; 10 §9.2 | 484–511 | S17 | done |
| [S19](sessions/S19-price-list-screen.md) | R | Price list screen | Price list table, filters, search, product editor modal, brand discount | 07 §7.2.1–7.2.3; 10 §8 | 1098–1208 | S18 | done |
| [S20](sessions/S20-catalog-matching.md) | P | Stage 5: catalog matching | Signature, explicit SKU and series, match memory, brand, fill-in, circuit inference, candidate query, decision rules, `catalog_disambiguation`, bundles | 05 (all) | — | S18 | done |
| [S21](sessions/S21-validation.md) | P | Stage 6: validation | Panel model, rules stored as data, starter rule pack, BOM cross-check, `validator_review`, re-run after edits in under 1 s | 06 (all) | 460–472 | S20 | done |
| [S22](sessions/S22-pricing-versions.md) | P | Stage 7: pricing and versions | Cost lookup, margin priorities, derived items and labor, final color as the worst source with all reasons, totals, versions draft → sent → new with diff, backtest | 07 (all) | 582–619 | S21 | done |
| [S23](sessions/S23-review-actions.md) | R | Review III: actions | Price edit with "update the price list too?", supplier switch, profitability, findings actions, approve, delete, alternatives, send, lock, new version, correction events | 09 §7, §10; 07 §7.2.3 | 897–941, 1446–1559 | S19, S22 | done |
| [S23b](sessions/S23b-product-picker.md) | R | Review IV: product picker | Edit an attribute with a stage-5 rerun for the line, resolve a missing line (up to 3 products, "מוצר אחר…" catalog search, "אין כאן רכיב"), draw mode for a missed component, the bulk brand discount from a row; then remove `review_screen` | 09 §6.4, §6.6, §7.4, §7.8, §7.13 | 942–1004 | S23 | done |
| [S24](sessions/S24-onboarding-settings-queue.md) | X | Onboarding, settings, approval queue | Two questions and data terms, settings screen, approval queue and promotion to the shared layer; flags shown read-only (S03 decision) | 10 §5, §9; 00 §9, §14.2 | 1210–1251 | S22 | done |
| [S24b](sessions/S24b-designer-plan-reading.md) | P | Reading a designer's plan | 25.26.100's main panel (BUG-066–072): a tag merges one family, `xN` beside a breaker is a count, tag ranges, a designator-prefix table as data, a breaker's end circles, the cable along the line, one description format | 03 §3.5–3.7, §4.6; 04 §5.1.1, §5.8; 05 §5.5.1; 07 §7.4 | — | S22 | done |
| [S25](sessions/S25-chat-layer.md) | X | Chat layer | Tool loop in `konboro_llm`, chat tools, `$T` references, history budget and compaction, answer check, chat drawer and proposal cards | 08 (all) | 1007–1064 | S23 | done |
| [S25b](sessions/S25b-chat-layer-2.md) | X | Chat layer II | `explain_line` sub-agent with the drawing crop, `compare` with another quote by signatures, remember scopes `customer` and `tenant` on the proposal card | 08 §6.4–6.5, §7.4; 05 §11 | 1007–1064 | S25 | done |
| [S26](sessions/S26-overlay-export.md) | X | Flags: overlay and export | `unresolved_overlay`; `export_doc` (PDF through Playwright Chromium, Excel through openpyxl) | 13 §4.1, §4.4 | 575–580, 1360–1378 | S23 | done |
| [S27](sessions/S27-chat-builder-voice.md) | X | Flags: chat builder, home chat, voice | `chat_quote_builder` and the build screen, `home_chat` wired to real actions, `voice_input` with a fake transcriber | 13 §4.2–4.3 | 1253–1357 | S25 | done |
| [S27b](sessions/S27b-catalog-lines.md) | X | Quote lines from the catalog | One line per product in a panel, a waiting line for a product not in the catalog (an alert, up to 3 nearest products, no price, send refused), "מוצר חדש" in the app's format for the factory and the approval queue, behind `catalog_lines`; the user's 15 common products (`common.csv`); the clocks' names, a contactor's AC-1, "LS/I", U+200F | 05 §5.6–5.9; 07 §7.1, §6.2; 09 §6.4, §7.8, §7.12; 10 §5.4; 13 | 409–460, 872–1004 | S27 | done |
| [S28](sessions/S28-gate-2.md) | G | **Gate 2** | Live eval, regression of every prototype flow, fix bugs. Tag `phase-2` | dev-strategy §7 | all | S27b | in progress |

**Exit:** a new tenant produces a quote on day one; ≥85% of golden rows need no edit; every prototype flow is covered by E2E.

## Phase 3: cloud and pilot readiness

| # | Track | Session | Main contents | Specs | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- |
| S29 | X | Infrastructure as code | Terraform or CDK (decide at kickoff): VPC, RDS, S3 + KMS, SQS + DLQ, ECS API and workers, ALB, CloudFront, Secrets Manager, Cognito replacing dev auth, Bedrock provider, Transcribe, per-tenant pipeline concurrency limit (00 §4.3, BUG-008) | 12 §2, §4, §7 | S28 | todo |
| S30 | X | Deploy and observability | GitHub Actions deploy to staging, Sentry, OpenTelemetry `trace_id`, CloudWatch, per-tenant cost table | 12 §7 | S29 | todo |
| S31 | P | **Floating:** OCR engine choice | Google Vision vs Azure on the golden set by electrical-token accuracy, plug in the winner, live eval. **Runs whenever OCR keys exist** | 02 §10; 12 §5 | S10 | blocked (keys) |
| S32 | G | **Gate 3: pilot readiness** | Security review, RLS checks on staging, backups and restore test, staging E2E, live eval. Tag `phase-3` | 00 §11, §14.2 | S30, S31 | todo |

After S32: one triage session per batch of pilot feedback (P0 and P1 first). Phase 4 (dedicated detector, embedding index, learning service, ERP export, DWG/DXF) is planned after the pilot.

## External blockers

These items are owned outside the code. They do not stop sessions from starting, but they limit what a gate can prove.

| # | What | Needed by | Owner | Status |
| --- | --- | --- | --- | --- |
| B1 | Golden set grown to 10 drawings, from more than one factory | Gate 0 or Gate 1 | User + estimator | 7 of 10 (MINHAROT-1 not verified with the factory yet; 25.26.100's main panel only, S24b) |
| B2 | Electrical expert: attribute schemas, validator rules, inference rules (`pipeline/matching/inference.json`, S20), abbreviation dictionary | S20, S21 | User | open |
| B3 | Master catalog, 3–5 brands (until then, a small sample seed) | S18, S20 | Catalog | open |
| B4 | OCR keys (Google Vision and Azure) | S31 | User | open |
| B5 | Data terms (legal) | Before the pilot | Lawyer | open |
| B6 | Pilot factory and approving engineer | S32 | Business | open |
| B7 | Review-screen usability test with 5 estimators, using the prototype (09 §15.1) | Before S23 | User | open |
| B8 | Bedrock model access and quota in the AWS account | S29 | User | open |

## Backlog

Ideas and out-of-scope findings from sessions. Each one is scheduled into a session, or dropped, at the next gate.

- **A manual line joins its product's line** (from S27b, 07 §7.1). With `catalog_lines` on, a line the user adds (the picker, draw mode, the chat's `add_line`) of a product the panel already has a line for should add to that line's quantity, its box with it; today it is a line of its own. Due with the flag's removal at the latest.
- **Eval each stage on labelled input (00 §10.1)** (from S06). Today `make eval` runs the pipeline end to end, so a stage-1 miss also costs stage 4. Stage 4 can be fed the labelled detections once stage 3 has box labels; due with the stage 2–3 labeling work (S10/S12).
- **PDFium in a process pool** (from S07, BUG-010). Every PDFium call in a process takes one lock, because PDFium is not thread-safe. Thumbnails are cheap; S10's tiling and deep-zoom renders are not. If rendering becomes the bottleneck, move it to a process pool.
- **Panel count: feed sources are not panels** (from S08). On 26-993 the classifier counts QEN1 and QEN2, the boards that feed MAIN ELECTRICAL BOARD, as panels: panel count accuracy is 60% against a 95% target (01 §10). One prompt rule made no difference in one live run. Candidates: the feed diagram from stage 3 (S12), or a code rule that uses the title block's panel name. Re-record the classification cassettes with whatever lands.
- **Confirmation rate and `page_kind` below target** (from S08). 25% of drawings needed the confirmation screen (target ≤ 15%) and `page_kind` is 95.8% (target ≥ 97%). Calibrate the classifier's confidence, or the 0.85 threshold, against more labelled drawings (01 §12 item 5).

- ~~**Remove `review_screen`**~~ Done in S23b: migration 0019, the routes, the client's guard and the 404 tests.
- **Remove `price_list`** (from S18 decision 5, S19 decision 5). The price list screen was accepted in S19; take out the flag, its 404 tests (`test_api_price_list*.py`) and the `prices-off` E2E tenant. Due at Gate 2 (S28) at the latest.
- ~~**Review row sub line: spec vs prototype**~~ Resolved in S23 (decision 4): the prototype's sub line; 09 §6.3 fixed.
- ~~**Review pricing details**~~ Done in S23: the quote API's `fresh_price`, `below_floor`, `price_hints` and `derived_note`, and their chips.
- ~~**Draw mode: mark a missed component**~~ Done in S23b (09 §6.6): a manual line with the rectangle as its box, and the crop as a `tenant_reference_crops` row.
- **Reuse stage 2 for a reused page** (from S10). A page stage 1 reused by hash (01 §5.1) still goes through OCR again: about $0.015 a tile with the interim engine. Copy the earlier page's spans, tiles and pyramid instead, within the tenant.
- **Calibrate OCR confidence and the blank threshold** (from S10, for S31). The interim engine's 0.9 / 0.6 confidences are self-rated, and 99.9% white for a blank tile was set on four drawings. Re-check both with the chosen OCR engine; 02 §8's `ocr_low_confidence` depends on the first.
- **Symbol-box labels for the golden set** (from S12). Stage 3 is scored by designators and family counts (S12 decision); precision, true recall, tile coverage against real boxes (02 §10) and the 1% calibration of `accepted` (03 §6.3) need a box per symbol. Draft the boxes from a stage-3 run, have them checked on a report page, and save them as new golden files (with the user: golden/ changes).
- **Time switches and impulse relays missed** (from S12). On 6199-2-50 the first look finds 0 of 5 time switches ("שעון 2 תכניות") and 0 of 3 impulse relays: the designer draws them as boxes with an axis or a step that our reference drawings don't resemble, so they come back as contactor coils or unknown. Redraw those two references after that style (drawn by us, not cut from the golden file) and re-record the `symbol_detection` cassettes (about $3.60).
- **Disambiguation share above target** (from S12). 19.7% of detections reach the disambiguation call, against 03 §10's 10%: the interim model rates many symbols unsure. Candidates: a second look with neighbouring context only for the billable unsure ones, or the phase-4 index. Measure with the eval's `llm_share`.
- **An auxiliary contact's device** (from S12, 03 §3.7 item 4). `linked_designator` needs the dashed mechanical line, which needs line styles in the wire graph. The front view's ranges ("R1-R7") are read since S21: stage 6 spreads stage 1's front-view tags and compares them with the plan (`FRONT_VIEW_*`).
- **Legend crops as drawing-scope examples** (from S12, 03 §4.2). Stage 1's legend artifact is text, so stage 3 gives the legend to the disambiguation call as text only. Crops need a box per legend entry from stage 1. No golden drawing has a legend page.
- ~~**Output terminals as derived material**~~ Done in S22: stage 7's `terminals` rule counts stage 5's auxiliary components, one line per cross-section (07 §7.4).
- **Dashed frames for supply scope** (from S13, 04 §5.1.2). Stage 4 reads the scope from the phrases only: stage 2's paths keep no line style, so a device in a dashed frame with no phrase near it stays `in_panel`. Keep the dash pattern in `paths.json` (pdfplumber's `dash`), then find closed dashed frames around symbols.
- **An auxiliary contact drawn twice** (from S13). NEVIS-1 draws F1–F7's aux contacts on page 5 and again, untagged, in the fault-lamp circuit on page 7; stage 4 counts both drawings. Needs the aux contact's device (the dashed mechanical link, S21) to merge them by parent.
- ~~**Re-running stage 4 under existing quote lines**~~ Done in S22: stage 4 lets a draft's lines go of the components first and keeps the ones a sent version points at; stage 7 writes the draft again, keeping the user's edits by `line_key` (S22 decision 5).
- **A tenant's own BOM words** (from S14). The BOM terms (`pipeline/bom/terms.py`) are global and in code. A factory writes its own ("מאמ"ת", a supplier's product names): keep them per tenant like the abbreviations, and learn them from the user's choice of family on an `unknown` row.
- **A misread BOM word** (from S14). On BOM-HW-1 Opus read "מגן מתח יתר" as "מגן מתח ותדר", so the row stayed `unknown` (red, the user picks). A word one letter off a known term, at a lower confidence, would catch it; measure the false matches on more BOMs first.
- **BOM tables in a vector PDF** (from S14). A `bom_table` page in a PDF is transcribed from its picture, like a photo. Its text layer could be read in code (pdfplumber's tables), with the model only for scans.
- ~~**The done step's product count**~~ Done in S22: `ProgressSummaryOut.products` and `priced` count stage 7's lines, and the run step's stage-7 line says "8 מחירים מהמחירון · 5 חסרים".
- ~~**Undo a line's price change**~~ Done in S23: every action's event keeps what undo puts back, the price list included (S23 decision 11).
- **A product's delete or archive** (from S18; S19 decision 3). Quote lines point at products, and the prototype has no control for it. An archive (`archived_at`, hidden from the list and from new quotes, kept by existing lines) is the likely shape.
- **Similar-products check without the catalog** (from S18, 10 §8). The 3-times check compares products of the same family, brand and current, and the current comes only from a linked catalog item. A product the factory typed with no catalog link gets no comparison. The editor's check before saving (S19) has the same limit, and a new product has no link at all, so only the previous-cost check can fire on it. Linking a product to the catalog by exact brand and manufacturer sku when it is saved would give it the list-price check too.
- ~~**The editor's toast after a price change**~~ Done in S23: `used_in_drafts[].fresh`, and the prototype's wording.
- ~~**The price list's sale price before rounding**~~ Done in S23: `ProductOut.unit_price` is after 07 §7.6's rounding.
- **Exchange rates in production** (from S18, S18 decision 4). Locally they are fixed seeded rates. Before the pilot, a daily feed (07 §4.3 "ממקור מוגדר") writes `fx_rates`, and `fx_rate_missing` alerts the operations team (07 §8).
- **A model for quote lines code can't sign** (from S15, decision 3). A line no BOM word names has no family and matches nothing; it caps every missing item's confidence at 0.55. A closed-list `table_transcription`-style call (pick a family and values, no price in the request) would sign it; measure how many real lines need it first.
- **The price list in the audit's money** (from S15, 11 §5.5 priority 3). A missing item with no similar line in the quote is "ללא מחיר" even when the factory's price list has it. Stage 5's matching exists since S20 (`pipeline/matching/match.py`): the audit can match the missing component and look up its product.
- **The audit's learning loop** (from S15, 11 §9). S15 stores the verdicts and reject reasons only: the quote's prices into the price list ("מחיר מהצעה קיימת"), confirmed differences as golden labels (with the factory's consent), "טעות של המערכת" as negative examples for stages 3–4.
- **"הורד דוח" for an audit** (from S16, 11 §7). The audit's differences and value at risk as a PDF or Excel report, next to `export_doc`. S26's `services/export_pdf.py` (escaped HTML, embedded fonts, Chromium offline) and `export_xlsx.py` are the parts to reuse.
- **Audits in home's recent work** (from S16, prototype line 476). `GET /quotes` lists quotes only; an audit reaches home through the omissions card. A recent-work row per audit needs the list to carry audits.
- **The audit's summary counts the ones to check** (from S16). 11 §6's `missing_items` and `missing_items_without_price` include differences below 0.6, while `value_at_risk` doesn't; the screen counts from the shown differences. Make the summary say shown only, or add both.
- **Costs by permission** (from S09, 09 §12). A user without cost permission must not receive costs from the server. 1.0 has one owner role, so `GET /quotes/{id}` sends them to everyone; add a cost permission when a second role arrives.

<a id="s00"></a>**S00** is the planning session that produced this roadmap. It has no session file; its PR is the record.
- **Matching settings on the settings screen** (from S20). `tenant_settings.matching` (series, alternate brands, tie-break, rules turned off) and per-family `brand_preferences` and defaults have no screen; the prototype shows one brand for breakers and RCDs and the 30 mA toggle (lines 1239–1243). With the settings screen (S24). S24 built the prototype's rows (the two brands, the 30 mA default) and left series, alternate brands and tie-break out.
- **A drawing's BOM SKUs and a CT's count** (from S20, 05 §5.2 item 1, §5.5.1). Since S21, stage 6 compares a designer's BOM with the quote and flags a different SKU (`BOM_SKU_DIFF`, info), but the BOM's SKUs still don't reach stage 5 on a drawing, and a meter's one drawn CT is still counted as 1 (the BOM cross-check shows the difference when the BOM lists 3). Both are stage 4–5 work: link BOM rows to components before matching.
- **The factory tunes an inference rule** (from S20, 05 §5.5.1 last bullet). When the estimator keeps choosing one size above the rule's contactor, propose a tenant override; it takes effect on approval (06 §11). With the approval queue (S24). Not in S24 (decision 3): a tenant-level proposal, not the shared-layer queue; it needs a card design of its own.
- **Findings actions and the dismissal loop** (from S21, 06 §6.3, §11). Stage 6 gives every finding a stable id and `services/validation.revalidate_panel` re-runs the rules after an edit; the review screen's "ignore with a reason", the dismissal stats per rule and the proposal to turn off a rule dismissed 5 times in a row are S23's and S24's. S24 left the proposal to turn off a rule out (decision 3), like the inference and pricing proposals.
- **`QTY_RANGE_MISMATCH` reads stage 4's own flag** (from S21). The rule uses the instance's `range_mismatch` issue, since a merged component no longer says which instance had which range. An independent count would need each instance's range in the contract (04 §6.2).
- **The agent's catch rate on injected errors** (from S21, 06 §10.2: measured, no target). The labelled quote has no picture, so the agent is measured end to end only; a labelled run with the drawing's panel crops would measure it.
- **The backtest's unpriced lines** (from S22, 07 §10.2; checked again at Gate 2, S28). Priced from its own quote, NURSERY-1 is 6.2% under the factory's total and NEVIS-1 8.2% (target ±5%): 30–40% of the component lines have no SKU from stage 5, so no price can find them. 26-993 is 46% over because BUG-035's three panels each get an enclosure. Stage 4–5 work, and BUG-035.
- ~~**Version routes and buttons**~~ Done in S23: `/quotes/{id}/send`, `/versions`, `/recalculation`, and their buttons and dialogs.
- ~~**What a rerun keeps, beyond prices and deletions**~~ Done in S23: `quote_lines.edits` and `approved_at` by `line_key` (07, S23 decision 2).
- **Pricing's learning loop** (from S22, 07 §11). Proposals from repeated manual price changes in a family, repeated additions or deletions of a derived item; with the approval queue (S24). Not in S24 (decision 3).
- **Labor and derived-rule settings on the settings screen** (from S22). `tenant_settings.labor` (hourly rate, hours per family) and `derived_item_rules` (on or off, params) have no screen; with the settings screen (S24). Not in S24: the prototype's settings screen has no rows for them.

- **One editor at a time** (from S23, 09 §11). Every action carries the quote's `revision` and a stale one is refused; a second user sees the quote read-only. Not needed while a tenant has one user (00 §14.1).
- **The review screen's usability test** (from S23 decision 1, roadmap B7). Five estimators with the prototype (09 §15.1); what comes out of it is scheduled at the next gate.
- **Paste rows from a supplier quote** (from S23b decision 7, 09 §7.13, not in the prototype). "מק"ט, מחיר" rows pasted from an email or a spreadsheet, matched by SKU, with what was found and what was not.
- **Stage 3 reads the tenant's crops** (from S23b, 03 §4.3, §11). Draw mode keeps each marked rectangle as a `drawing`-scope crop, and `missing_resolved` / `row_deleted` mark positive and negative examples; nothing reads them yet. With the similarity index (phase 4).
- **A rematch and the kit** (from S23b). An attribute set by hand matches the line again, but the line's kit parts stay those of the product it had (05 §5.9.1). Rare (a kit is on a few MCCBs); make the parts follow the new product when it happens.
- **The rules on a resolved missing line** (from S23b). A missing line resolved to a product is a component line for stage 7, but stage 6 still reads stage 4's components, which don't have it: a rule that counts breakers misses it until the drawing is decoded again.
- **The picker at catalog scale** (from S23b). The search reads the active catalog items of the family, or all of them, in code; fine for the sample's 190 and a few thousand (roadmap B3). With a real catalog, a trigram index on the description and SKU.
- **The picker's price for a catalog item at a brand discount** (from S23b). A catalog item with no product shows "אין מחיר" in the picker even when the factory's brand discount would price it on the line (BUG-058).
- **A test database per checkout** (from S23b's merge). Two checkouts on one machine (a worktree for another branch) share `konboro_test`: one run drops and creates it under the other, which fails with "column does not exist" or "database does not exist". Name the integration database after the checkout or an env var (`tests/integration/db.py`), like the E2E and eval databases.
- **Show an action before the server answers** (from S23 decision 10, 09 §14). The screen waits for the server, which answers within 500 ms; measure the wait in the pilot before guessing amounts on the client.
- ~~**Reading fixes found on MINHAROT-1**~~ (from fix-minharot-golden). Done in `fix-minharot-reading` (PR #29), merged into `main` in S28: BUG-051, 053, 054, 055 and 057, with the cassettes and the baseline they move. Left: stage 3 detecting a selector drawn as two contact points (BUG-036), and the dashed link from an aux contact to its breaker (03 §3.7 item 4).
- **Tenant-level proposals** (from S24 decision 3). The proposals the factory approves for itself (turn off a rule dismissed 5 times, 06 §11; a margin rule from repeated price changes, 07 §11; an inference override, 05 §5.5.1) are not the shared-layer queue. They need a place on screen (a section of the queue, or the settings) and a card design; the prototype has neither.
- **More sources for the approval queue** (from S24 decision 3). Only factory products feed it. A new abbreviation needs the review screen's "classify a rectangle with an abbreviation" (03 §4.6), a spelling pattern stage 4's spelling corrections (04 §11), a symbol a new class in draw mode (03 §11), an attribute a catalog item's value corrected in review. Each writes its candidate through `knowledge.propose`.
- **Stage 4 reads `spelling_patterns`** (from S24). An approved spelling pattern is in the global table, and stage 4 still reads only `association/grammar.json`. Load the approved patterns on top of the grammar, with a golden-set run.
- **Re-review of `pilot_engineer` records** (from S24, 00 §14.2). When a second factory joins, a `pilot_engineer` record it corrects goes back to the queue instead of being overwritten. Needs a second tenant and a correction that points at a global record.
- **The data terms' wording** (from S24). `/welcome` shows a three-point summary of 00 §11 and 10 §5.1, version `2026-10`. The real terms are a contract: link the full text once it exists, and bump `TERMS_VERSION` when it changes, which asks every factory again.
- **An audit scoped to the quoted panel** (from S24b decision 18). Quote 10298 is for 25.26.100's main panel ("לוח ראשי"), but the audit and the backtest take every panel on the drawing: the sub-panel's components come out as missing from the quote, and the backtest prices two enclosures. A quote that names a panel, or a user's choice at upload, should limit the audit to that panel's components.
- **25.26.100's sub-panel** (from S24b decision 11). `golden/25.26.100/` labels the main panel only; the sub-panel (לוח משנה-מקווה) is listed with `verified: false` and is not scored in stage 4. Label it once the user checks it. The main panel's labels are all user-verified (S24b decision 14).
- **End circles before the disambiguation call** (from S24b decision 5). A breaker's end circles are absorbed after the call, so on 25.26.100 a few circles read as current transformers at 0.42 still cost a call each. Move the absorption before the call and re-record the `symbol_disambiguation` cassettes it moves.
- **A terminal with a device's tag** (from S24b, BUG-051, BUG-036). MINHAROT-1's SW2–SW5 and 26-993's SG are detected only as terminals, tagged SW and SG. A terminal whose tag's letters name another class (SW, Q, F, K in `prefixes.json`) is suspect: a second look, or the disambiguation call with that class among its candidates.
- **Cassettes that replay the same on every platform** (from S24b decision 15, BUG-073). pdfium rasterises a page a few pixels differently on macOS arm64 and on CI's Linux amd64, stage 3's ink-shrunk boxes can move by one pixel, and a tile's prompt then misses its cassette; the tile agent falls back without an error. Record cassettes in the CI image (or replay every new cassette there before it is committed), and make a tile agent's cassette miss in replay fail the eval instead of falling back.
- **The prefix table and S24b's thresholds to the electrical expert** (roadmap B2). `detection/prefixes.json` and the end-circle, peer and count thresholds (S24b decision 6) are starting values.
- **Grow the chat's test set to about 200** (from S25 decision 4, 08 §13.1). `eval/chat_set.json` has 62 requests written by Claude on NURSERY-1. An estimator's own phrasing, a second quote with several panels (where "תחליף לשניידר" is ambiguous, 08 §9), and multi-turn requests ("ועכשיו גם בלוח 2"). Before Gate 2.
- **The chat streams its answer** (from S25 decision 9, 08 §12's 2 s to the first output). A turn answers whole, with a typing indicator. Stream the text block over SSE if the pilot finds the wait long.
- **The chat's `set_attribute` for any value** (from S25 decision 7). Only current and breaking capacity, the row's editable values; poles, curve and the rest need the row's editor first (09 §6.4).
- **A chat proposal's "ליצור מחדש"** (from S25). An expired card sends its title again as a new message; carry the original changes instead, re-resolved on the current quote.
- **A usage table for every flag** (from S26 decision 6, 13 §3 rule 4: how many users, how many times, and the model's cost per factory). S26 logs each export download; no flag is counted where a report can read it. A `flag_usage` row per use, written by the routes' `require_flag`, or a daily roll-up of the logs.
- **Grow the chat builder's test set** (from S27). `eval/build_set.json` has 51 turns written by Claude, typed, spoken and multi-turn, and `eval/home_set.json` 30 requests. Estimators' own messages and recordings at the pilot, several panels in one message, and corrections by panel ("בלוח 2 תוריד…"). Before the pilot's first month ends.
- **A value changed by message in the chat builder** (from S27 decision 4). A message changes a line's quantity or removes it; "תחליף את ה-16 ל-20 אמפר" is answered with a question. A `set_value` change, checked like the rest, through the rows.
- **An enclosure said in the chat builder** (from S27). "ארון 1200X800" is no product word on the BOM path: stage 7 derives the enclosure from the modules, yellow with its reason (01 §5.8). Read a said enclosure's dimensions as the panel's requirement (07 §7.4), as the drawing's notes are.
- **`validator_review` on a chat build** (from S27 design 2). A build runs stage 6's rules only, on every message. Run the agent once when the draft opens in review, if the pilot finds the rules miss things on chat builds.
- **The customer PDF's template, further** (from S26 decision 1). A second logo position, colours or a footer per factory are a template editor, which 13 §6 item 2 left out. Ask the pilot factory first.
- **A product deleted after it was queued** (from S24). Its pending `catalog_item` candidate stays; approving it still promotes the SKU and has no product to link. Remove a pending candidate with its product.
