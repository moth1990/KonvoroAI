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
| [S11](sessions/S11-review-drawing.md) | R | Review II: drawing | OpenSeadragon viewer, SVG highlight boxes, page strip, "show on drawing", mobile tabs, toast, undo (5 s, 30 actions) | 09 §5.2, §6.5, §7.11 | 942–1004 | S09, S10 | in review |
| S12 | P | Stage 3 v1: symbols | LLM-vision detection with library examples and the abbreviation dictionary, cross-tile de-duplication and owner tile, orphan text, designator linking | 03 §3.4–3.7, §6, §10 | — | S10 | todo |
| S13 | P | Stage 4: association and merge | Spelling grammar as data, multiplicity, supply scope, geometric association, tile agent with citation check, merge by designator and then signature | 04 (all) | — | S12 | todo |
| S14 | P | BOM-only path | Excel and CSV import, photographed BOM through `table_transcription` (BOM-HW-1) | 01 §5.8 | — | S08 | todo |
| S15 | P | Quote audit backend | Read the existing quote, arithmetic check, matching, 8 difference types, money at risk, API | 11 §4–6, §8 | — | S13, S14 | todo |
| S16 | R | Audit screen | Audit flow and results screen, "create corrected quote" entry point, E2E on 26-993 (replay) | 11 §7–8 | 1066–1096 | S15 | todo |
| S17 | G | **Gate 1** | Live eval, full E2E regression, fix bugs. Tag `phase-1` | dev-strategy §7 | all built screens | S16 | todo |

**Exit:** ≥80% difference accuracy on golden drawings that have actual quotes; audit and review E2E green.

## Phase 2: full quotes (v1.0)

| # | Track | Session | Main contents | Specs | Prototype | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S18 | P | Price list backend | Products with several suppliers, preferred or else cheapest, margin rules, history, consumables, cabinet "includes", bulk brand discount, master-catalog import format | 07 §7.2–7.3; 10 §9.2 | 484–511 | S17 | todo |
| S19 | R | Price list screen | Price list table, filters, search, product editor modal, brand discount | 07 §7.2.1–7.2.3; 10 §8 | 1098–1208 | S18 | todo |
| S20 | P | Stage 5: catalog matching | Signature, explicit SKU and series, match memory, brand, fill-in, circuit inference, candidate query, decision rules, `catalog_disambiguation`, bundles | 05 (all) | — | S18 | todo |
| S21 | P | Stage 6: validation | Panel model, rules stored as data, starter rule pack, BOM cross-check, `validator_review`, re-run after edits in under 1 s | 06 (all) | 460–472 | S20 | todo |
| S22 | P | Stage 7: pricing and versions | Cost lookup, margin priorities, derived items and labor, final color as the worst source with all reasons, totals, versions draft → sent → new with diff, backtest | 07 (all) | 582–619 | S21 | todo |
| S23 | R | Review III: actions | Price edit with "update the price list too?", supplier switch, profitability, findings actions, approve, delete, alternatives, send, lock, new version, correction events | 09 §7, §10; 07 §7.2.3 | 897–941, 1446–1559 | S19, S22 | todo |
| S24 | X | Onboarding, settings, approval queue | Two questions and data terms, settings screen, approval queue and promotion to the shared layer; flags shown read-only (S03 decision) | 10 §5, §9; 00 §9, §14.2 | 1210–1251 | S22 | todo |
| S25 | X | Chat layer | Tool loop in `konboro_llm`, chat tools, `$T` references, history budget and compaction, answer check, chat drawer and proposal cards | 08 (all) | 1007–1064 | S23 | todo |
| S26 | X | Flags: overlay and export | `unresolved_overlay`; `export_doc` (PDF through Playwright Chromium, Excel through openpyxl) | 13 §4.1, §4.4 | 575–580, 1360–1378 | S23 | todo |
| S27 | X | Flags: chat builder, home chat, voice | `chat_quote_builder` and the build screen, `home_chat` wired to real actions, `voice_input` with a fake transcriber | 13 §4.2–4.3 | 1253–1357 | S25 | todo |
| S28 | G | **Gate 2** | Live eval, regression of every prototype flow, fix bugs. Tag `phase-2` | dev-strategy §7 | all | S27 | todo |

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
| B1 | Golden set grown to 10 drawings, from more than one factory | Gate 0 or Gate 1 | User + estimator | 5 of 10 |
| B2 | Electrical expert: attribute schemas, validator rules, inference rules, abbreviation dictionary | S20, S21 | User | open |
| B3 | Master catalog, 3–5 brands (until then, a small sample seed) | S18, S20 | Catalog | open |
| B4 | OCR keys (Google Vision and Azure) | S31 | User | open |
| B5 | Data terms (legal) | Before the pilot | Lawyer | open |
| B6 | Pilot factory and approving engineer | S32 | Business | open |
| B7 | Review-screen usability test with 5 estimators, using the prototype (09 §15.1) | Before S23 | User | open |
| B8 | Bedrock model access and quota in the AWS account | S29 | User | open |

## Backlog

Ideas and out-of-scope findings from sessions. Each one is scheduled into a session, or dropped, at the next gate.

- **Eval each stage on labelled input (00 §10.1)** (from S06). Today `make eval` runs the pipeline end to end, so a stage-1 miss also costs stage 4. Stage 4 can be fed the labelled detections once stage 3 has box labels; due with the stage 2–3 labeling work (S10/S12).
- **Audit metrics read the audit output** (from S06). `eval/predict.py` sets `Prediction.audit = None` until the audit flow exists; S15 maps its differences into `CanonDifference` so `difference_precision` / `difference_recall` stop being n/a.
- **PDFium in a process pool** (from S07, BUG-010). Every PDFium call in a process takes one lock, because PDFium is not thread-safe. Thumbnails are cheap; S10's tiling and deep-zoom renders are not. If rendering becomes the bottleneck, move it to a process pool.
- **Panel count: feed sources are not panels** (from S08). On 26-993 the classifier counts QEN1 and QEN2, the boards that feed MAIN ELECTRICAL BOARD, as panels: panel count accuracy is 60% against a 95% target (01 §10). One prompt rule made no difference in one live run. Candidates: the feed diagram from stage 3 (S12), or a code rule that uses the title block's panel name. Re-record the classification cassettes with whatever lands.
- **Confirmation rate and `page_kind` below target** (from S08). 25% of drawings needed the confirmation screen (target ≤ 15%) and `page_kind` is 95.8% (target ≥ 97%). Calibrate the classifier's confidence, or the 0.85 threshold, against more labelled drawings (01 §12 item 5).

- **Remove `review_screen`** (from S09). The flag gates the review screen while it is built (S09 decision 2); take it out, and its 404 test, when S23 completes the screen.
- **Review row sub line: spec vs prototype** (from S09). 09 §6.3 lists the catalog number, "×2 בשרטוט" and "עמ׳ 4, 5" in a line's sub line; the prototype row shows tags, chips and the circuit's load. S09 follows the prototype; ask the user at S23.
- **Review pricing details** (from S09, for S22). Price hints for unpriced lines ("קרובים במחירון: …"), the "פריטים נלווים: …" footnote, "מחיר חדש במחירון" and "רווח נמוך X%" chips against the tenant's margin floors.
- **Draw mode: mark a missed component** (from S11, 09 §6.6). "סמן רכיב שפוספס": draw a rectangle, pick a product, a manual line with an instance there, the panel by the rectangle's centre, the rectangle kept as a detector example (03 §11). No session has it; S23 at the earliest, since it needs the manual line and the product picker.
- **Reuse stage 2 for a reused page** (from S10). A page stage 1 reused by hash (01 §5.1) still goes through OCR again: about $0.015 a tile with the interim engine. Copy the earlier page's spans, tiles and pyramid instead, within the tenant.
- **Calibrate OCR confidence and the blank threshold** (from S10, for S31). The interim engine's 0.9 / 0.6 confidences are self-rated, and 99.9% white for a blank tile was set on four drawings. Re-check both with the chosen OCR engine; 02 §8's `ocr_low_confidence` depends on the first.
- **Costs by permission** (from S09, 09 §12). A user without cost permission must not receive costs from the server. 1.0 has one owner role, so `GET /quotes/{id}` sends them to everyone; add a cost permission when a second role arrives.

<a id="s00"></a>**S00** is the planning session that produced this roadmap. It has no session file; its PR is the record.
