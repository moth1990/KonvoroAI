# CLAUDE.md: Konboro

Konboro turns electrical-panel drawings into price quotes that are ready for review, for panel-building factories. It is a 7-stage pipeline where the coordinator is code and LLMs only handle ambiguous cases. Next to it are a split review screen, a chat command layer, and onboarding that happens through use.

- Product summary and decisions: [README.md](README.md). Conversation history: [HANDOFF.md](HANDOFF.md).
- Data model, tables and isolation: [docs/db-schema.md](docs/db-schema.md).
- Architecture, stage contracts and glossary: [specs/00-architecture.md](specs/00-architecture.md).
- How we build, test and ship: [docs/dev-strategy.md](docs/dev-strategy.md).
- What to build next: [docs/roadmap.md](docs/roadmap.md). Bug log: [docs/bugs.md](docs/bugs.md).

The specs are in Hebrew. Code, identifiers, comments, commit messages and these docs are in English. Text the user sees is Hebrew.

## Sources of truth

| Question | Source | Notes |
| --- | --- | --- |
| Logic, contracts, thresholds, data model | `specs/00`–`13` | Cite `NN §x.y` in code comments and PRs when a rule comes from a spec |
| Screens, flows, copy, layout, colors, interactions | [prototype/konboro-app.html](prototype/konboro-app.html) | The app must look and behave like the prototype. `prototype/review-screen.html` is superseded and is reference only, for its matching model |
| Expected pipeline output | `golden/*/labels.json`, `golden/*/actual_quote.json` | Verified with the factory. Never edit them to make a test pass |

**When a spec and the prototype disagree, stop and ask the user.** Do not pick one silently. Record the answer in the session file.

### Prototype map

The prototype is a single file with no framework. The main pieces:
- `render()` (line 1380) redraws `#app` from the global state `S` (533–557).
- Routes are hashes (`#home`, `#review`…).
- Every click goes through a `data-act` handler (1446–1559).

To view it, serve the folder (`python -m http.server -d prototype`) and set `localStorage['konboro:authed']='1'`.

**Porting a screen:** the prototype's CSS moves to `frontend/src/theme/app.css` with the same class names, and the
React screens render those classes; MUI is for behaviour, not looks. The app routes are paths (`/home`, `/review/:quoteId`…),
not hashes. The phone layout starts at **860px** everywhere (09 §5.2; the prototype uses 820px), kept in `MOBILE_MAX_PX`.
Built so far: login, shell, classic and chat home (S04); new quote: pick, run, done (S05); confirm pages and page-kind change (S08); review lines, filters and line detail on the NURSERY-1 fixture (S09); the review drawing pane (OpenSeadragon, boxes, page strip, "הצג בשרטוט"), toast and undo stack (S11); a BOM spreadsheet's column mapping on the confirm step, behind `bom_column_mapping` (S14, no prototype screen). the audit's upload, results, decisions, "הצג בשרטוט" and corrected quote on the 26-993 fixture, behind `quote_audit` (S15 API, S16 screen; the upload has no prototype screen); the price list, its product editor and the bulk brand discount (S19; its flag `price_list` removed in S28); the run step's stage-6 line and the done step's findings count (S21); the review actions: approve and move on, delete and "החזר", quantity, alternatives, a finding dismissed with a reason, a price typed in the row, "לעדכן גם במחירון?", "עדכן בהצעה", a cost, a supplier, profitability, send and lock, version N+1, the recalculation's comparison, each with its undo and correction event (S23); the product picker: a current or breaking capacity from a list with stage 5 again for the line, a missing line resolved (its products, "מוצר אחר…", "אין כאן רכיב"), draw mode for a missed component, the bulk brand discount from a row (S23b, no prototype screen; `review_screen` removed); the onboarding page (`/welcome`, two questions and the data terms, no prototype screen) and the first-quote banner, behind `onboarding`; the settings screen, behind `settings_screen`; the approval queue, behind `approval_queue` (S24); the chat drawer (prototype `vChat`, `propCard`): its messages, line chips, amounts, suggestions, "שיחה חדשה", the proposal card with "החל" / "בטל" and undo, behind `chat_layer` (S25); the "why" answer with its "בשרטוט" chip, another quote by its name, and the card's memory chips (S25b); the drawing's "לא פוענח" layer (its boxes and tabs, the toolbar's count, the strip's dots), behind `unresolved_overlay`, and "הורדה": the export modal with its version selector, the customer PDF and the internal Excel, and the settings screen's "המסמך ללקוח" (no prototype screen), behind `export_doc` (S26); the chat quote builder (prototype `vBuild`: the conversation, the draft's table with its price field and "לעדכן גם במחירון?", "פתח במסך הבדיקה", undo), behind `chat_quote_builder`; the chat home routed by the server (its question with choices has no prototype screen), behind `home_chat`; the mic on both and the recording's card ("שמעתי", "הוסף", "תקן"), behind `voice_input` (S27); one line per product in a panel, a waiting line's nearest products, "מוצר חדש" and a merged line's designators picked for a change of product, behind `catalog_lines` (S27b, no prototype screen).

| Screen | Route | Function | Lines |
| --- | --- | --- | --- |
| Design tokens (light and dark) | — | `:root` | 9–32 |
| Login | (not authed) | `vLogin` | 660–688 |
| Shell: rail, mobile tab bar, quota meter | — | `shell`, `navItems` | 690–714 |
| Home, classic and chat (`home_chat` flag; routed by `POST /home/route`, S27) | `#home` | `vHome`, `vHomeChat` | 716–751, 1253–1284 |
| New quote: pick, run, done | `#new` | `vNew`, `validateFile`, `runPipeline` | 754–869 |
| Review: lines, line detail, drawing (the "לא פוענח" layer, built: `UNRESOLVED`, `boxesFor`) | `#review` | `vReview` | 872–1004, 575–580 |
| Chat drawer and proposal cards (built: `screens/review/Chat.tsx`) | `#review` | `vChat`, `applyProp` | 1007–1064 |
| Audit of an existing quote | `#audit` | `vAudit` | 1066–1096 |
| Price list and product editor (built: `screens/prices/`) | `#prices` | `vPrices`, `openEditor` | 1098–1208 |
| Approval queue (built: `screens/queue/`) | `#queue` | `vQueue` | 1210–1226 |
| Settings and flags (built: `screens/prefs/`) | `#prefs` | `vPrefs` | 1228–1251 |
| Chat quote builder (`chat_quote_builder` flag; built: `screens/build/`) | `#build` | `parseBom`, `vBuild` | 1287–1357 |
| Export modal (`export_doc` flag; built: `screens/review/ExportModal.tsx`) | — | `exportModal` | 1360–1378 |

Mock data in the prototype (lines 393–580) suggests field names for the API: `makeLines`, `makeFindings`, `QUOTES`, `CATALOG`, `QUEUE`, `AUDIT`, `UNRESOLVED`. The specs still win on the data model.

## Non-negotiables

1. **The coordinator is code.** An LLM only decides inside one stage, picks from a closed list, and code checks its answer afterwards (00 §3, §7.2). The chat coordinator (08) is the one exception.
2. **Every LLM call goes through `konboro_llm`**, with one route per stage key in `config.py`. Never call a provider SDK directly. Changing a model requires a golden-set run.
3. **Every value has evidence.** If it is not written in the drawing, it is `null`. Stage 4 reads, stage 5 fills in, and each value keeps its source (00 §5.3, 04 §5.5).
4. **Current and poles never get a default.** Changing an electrical value requires user approval (05 §4.4).
5. **Money is `Decimal` in code, `numeric` in the database, and a string in JSON. Never float.** Pricing is code only (07).
6. **Prices, costs and customer details are never sent to any model.** In chat, amounts reach the model only as references such as `$T1` (08). A test enforces this. The one exception is the audited quote's own page (11 §5.2, S15 decision 1): `table_transcription.transcribe_quote` copies that quote's selling prices from a picture or a scan, code checks every amount arithmetically, and no other request carries them. Costs, margins and the price list never go.
7. **Tenant isolation** ([docs/db-schema.md §2](docs/db-schema.md#2-two-layers-and-tenant-isolation)):
   - Every tenant table has `tenant_id`, forced RLS, and composite foreign keys `(tenant_id, id)`.
   - The app connects only as `konboro_app`, never as the owner, and runs tenant queries inside `tenant_session(tenant_id)`.
   - Every endpoint checks permission against the single `owner` role (00 §8, §14.1). In code, every route depends on `require(Permission.X)` from `konboro/api/deps.py`. That runs `current_actor`, which verifies the token, opens `tenant_session` for the token's tenant, and loads the user (the DB role counts, not the token's). Public routes are listed in `PUBLIC_ROUTES`, and `tests/integration/test_api_routes.py` fails for any other route without an actor.
   - Flag-gated routes add `Depends(require_flag(key))`. A flag that is off answers 404, as if the route did not exist (13 §3).
   - A new tenant table needs a row in `tests/integration/factory.py`; the RLS suite fails until it has one.
8. **Every new feature sits behind a flag**, evaluated on the server (13).
9. **No AGPL or GPL dependencies.** That rules out PyMuPDF and Ultralytics YOLO (12 §8). LGPL is allowed (psycopg). `make licenses` and CI check this.
10. **RTL from day one.** Use `dir="rtl"`, logical CSS properties, and wrap numbers and designators in `dir="ltr"` (the prototype's `.mono` and `.des` classes).
11. **IDs, coordinates, confidence and colors** follow 00 §6:
    - ID prefixes: `drw_`, `pg_`, `ln_`…
    - Coordinates are PDF points with the origin at the top left.
    - Confidence maps to colors: ≥0.85 green, 0.5–0.85 yellow, <0.5 red.
    - Stage 7 alone sets a row's final color.

## Repository layout

```
backend/        Python 3.12 (uv): konboro/ (api, db, contracts, pipeline, domain, services, devtools), konboro_llm/, alembic/, tests/{unit,integration}
frontend/       React + TS + Vite + MUI, RTL. src/theme/tokens.ts mirrors the prototype tokens. e2e/ = Playwright
eval/           golden-set evaluation harness: normalizers, metrics, cassettes, baseline.json ([eval/README.md](eval/README.md))
infra/          local service config (ElasticMQ queues)
golden/ specs/ prototype/   reference material; do not modify without the user
docs/           strategy, roadmap, session files, bug log
```

Schema changes are Alembic migrations in `backend/alembic/versions/`. Update `docs/db-schema.md` in the same PR. Tests marked `integration` need `make up`; they create their own `konboro_test` database, their own prefixed SQS queues and their own S3 bucket (`konboro-test`, emptied per run; E2E and the eval have theirs too, BUG-020).

**The pipeline** (00 §4–5, 12 §3):
- **Contracts.** `konboro/contracts/` holds one Pydantic model per stage boundary, taken from each spec's §6. `tests/unit/test_contracts.py` validates every spec example against its model and pins each schema. A contract change is a change to the spec that defines it and to every spec that consumes it.
- **Stages.** `konboro/pipeline/stages/sN_*.py` are stubs since S05; stage 1 is real since S08 (its parts are in `pipeline/intake/`; since S28b a drawing with the factory's technical-data or template page is a factory drawing, and a factory drawing is one panel, the names of its cells and parts its `aliases`, `intake/drawing.py`), stage 2 since S10 (`pipeline/extraction/`; OCR goes through the `OcrEngine` interface, `ClaudeVisionOcr` until S31), stage 3 since S12 (`pipeline/detection/`; the `symbol_detection` route stands in for the family detector until phase 4, the symbol library is data in `detection/library.py` seeded into the global tables, and its reference drawings come from `python -m konboro.devtools.draw_symbols`; since S24b, `detection/evidence.py` weighs an unsure class after the model: a device's end circles, a residual rating, peers in a row, a changeover switch drawn as its three contacts (BUG-036), and the designator prefixes in `detection/prefixes.json`, which a factory overrides in `tenant_settings.matching.designator_prefixes`) and stage 4 since S13 (`pipeline/association/`; the spelling grammar and the scope phrases are data in `association/grammar.json`, the attribute schemas in `association/schemas.py` seeded into `attribute_schemas`, and stage 4 writes the `components` rows). The BOM-only path is real since S14: stage 1 reads every `bom_table` page into a `bom_table` artifact (`pipeline/bom/`: spreadsheets in code, pictures through `table_transcription`, column mapping by code first and the model only for unknown headers, never with a number from the file), and on a `bom_only` drawing stage 4 turns the rows into components (`association/bom.py`) while stages 2–3 pass through. The quote audit is real since S15 (`pipeline/audit/`): a drawing uploaded with `POST /audits` (`purpose` = `audit`) goes from stage 4 to the audit step (stage 8 in `stage_runs`, stages 5–7 skipped), which reads the quote (`quote.py`, on the BOM path with its prices kept), signs each line by stage 4's grammar (`signature.py`), matches lines to components in code (`match.py`), and writes the differences and their money (`differences.py`) to `audits`, `audit_quote_lines` and `audit_differences`. Stage 5 is real since S20 (`pipeline/matching/`): the signature, an explicit SKU or series in the component's text (`model_tokens` in the catalog), the match memory, the brand and series by 05 §5.4's order, fill-in where the schema allows a default (current and poles never), circuit inference by rules as data (`matching/inference.json`), the candidate query that never relaxes an `exact` value, the decision rules, the `catalog_disambiguation` agent between the candidates left (shown no price), alternatives, kits and accessories (`catalog_kits`, `catalog_accessories`). The factory's auxiliary families (terminals) get no SKU. Stage 5 writes each component's `match_status` and `catalog_item_id`; `services/match_memory.py` writes the memory (S23). Stage 6 is real since S21 (`pipeline/validation/`): one model per panel (`model.py`: final values, the tree when the wire graph is built, the main device, the front view's tags, the notes' requirements, a designer's BOM), the rule pack as data (`rules.json`, seeded into `validator_rules`, with the factory's `tenant_rule_overrides`), one check per rule (`checks.py`), the BOM cross-check (`crosscheck.py`), the `validator_review` agent per panel with five components or more (`agent.py`, shown no price), and the caps on the rows' colour (`engine.py`). Stage 6 writes its findings on the drawing and stage 7 attaches them to the quote version; `services/validation.py` re-runs the rules on one panel after an edit (S23). Stage 7 is real since S22 (`pipeline/pricing/`, code only, no model): the price book and one product's price (`book.py`: the identical product only, by catalog item or manufacturer SKU), lines from the matches, kits, accessories and missing rows (`lines.py`), derived items as rules stored as data (`derived.json`, a copy per tenant in `derived_item_rules`; enclosure by dimensions or modules from the sample catalog's enclosures, rails, busbars, terminals, labels, consumables, a required service) and labor (`derived.py`), the final colour with every reason (`status.py`), the pure engine (`engine.py`), the version diff (`diff.py`), and the database side (`load.py`, `run.py`: which version is priced, what a rerun keeps by `quote_lines.line_key`, the snapshot). `services/quote_versions.py` sends and locks, recalculates (a draft in place, after a sent one as N+1 with a diff) and opens N+1. A new factory's entry is `services/onboarding.py` (S24): the markup answer is the `default` margin rule, the brands its preference per family, the data terms gate every upload while `onboarding` is on, and the counters of 10 §9.1. The pilot approval queue is `services/knowledge.py` (S24): a candidate's payload is a whitelist per kind, a factory product with a SKU the master catalog lacks is a `catalog_item` candidate, and only an approval promotes one, through the SECURITY DEFINER function `konboro_promote` (migration 0020), owned by the NOLOGIN `konboro_promoter`; the app role still never writes a global table. **Catalog lines** (S27b, 13 §4.10, behind `catalog_lines`): stage 5 adds the factory's products made in "מוצר חדש" to its candidates (`matching/catalog.py` `with_products`, `prd:<id>`) and, when nothing matches, up to 3 nearest products with what differs (`matching/nearest.py`, a suggestion, never a choice); stage 7 applies each component's choices (`quote_versions.component_edits`, by `c:`/`m:` key) and then merges the lines of one product in a panel and group (`pricing/merge.py`, key `p:…`, `component_ids`), a line with no product `pending`, unpriced; stage 6's `PRODUCT_NOT_IN_CATALOG`; the review's choices on merged and waiting lines, the split by designators and "מוצר חדש" are `services/catalog_lines.py`, and sending is refused while a line waits. The review screen's actions are real since S23 (`services/review.py`, routes in `api/routes/quotes.py`), and its product picker since S23b (`services/review_picker.py`: the search, stage 5 again for one line in code with no model, a missing line's candidates, a marked component's manual line and detector crop, the brand discount from a row): each keeps what undo needs in its correction event (`before.restore`), changes the lines' carried state (`approved_at`, `deleted_at`, `override`, `edits`) or the price list, and runs stages 6 and 7 again with every line it did not touch keeping its price (`pipeline/pricing/edits.py`): the whole engine on a drawing with stage outputs, the stored lines (`pipeline/pricing/stored.py`) on a quote with none, such as the fixture. A later session replaces one by writing a function `run(ctx) -> Contract` that reads earlier outputs through `ctx.output(n, Model)` and calls the model only through `ctx.llm`, which writes each call to `llm_calls`. The coordinator (`pipeline/coordinator.py`) doesn't change.
- **Queues.** One SQS queue per stage (`konboro-s1-intake` … `-s7-pricing`, and `konboro-audit` for the audit step), each sending to `konboro-dlq` after 3 failed receives (a model provider refusing the account, `konboro_llm.LLMAccountError`, fails the drawing on the first, BUG-061). Messages carry IDs only (`StageMessage`). Files and stage outputs live in S3 under `tenants/{tenant_id}/`, through `services/storage.py`, which refuses another tenant's key.
- **Pricing.** The price list is real since S18. Its rules are pure `Decimal` functions in `konboro/domain/pricing/`:
  - `cost`: which cost enters a quote (07 §7.2.2's order, expiry, brand discount, FX).
  - `margin`: the margin rule that applies, its formula, and the floors (07 §7.3).
  - `sanity`: the checks on a cost typed by hand (10 §8).
  - `rounding`: the unit price by the factory's setting, to the agora, a shekel, 5 or 10 (07 §7.6).

  They and `domain/totals.py` have 100% branch coverage, enforced by `make test-unit`'s `--cov`. `services/price_list.py` loads rows into those functions and logs every change in `price_history`. The `/price-list` routes have no flag since S28, and `POST /quotes/{id}/lines/{line_id}/price` changes a line's price (07 §7.2.3). The master catalog is loaded from CSV with `python -m konboro.db.catalog`, with its kits and accessory fits ([docs/catalog-import.md](docs/catalog-import.md)). `make seed` loads a sample of about 190 ABB and Schneider items (S20), with enclosures, DIN rails, busbars, terminals and a label for stage 7's derived items (S22), then `db/catalog/common.csv`: 15 real products the user listed from three factory drawings, with no price (S27b).

**The flags' two documents and the layer** (13 §4.1, §4.4; S26). `services/unresolved.py` reads the "לא פוענח" spots in code from stages 3–5's outputs in S3, the current lines and the open findings (`GET /quotes/{id}/unresolved`, behind `unresolved_overlay`). `services/export.py` builds a version's customer document from `quotes.read_quote(…, version_no)`; `export_pdf.py` writes its HTML (every value escaped, the app's fonts embedded from `services/fonts/`, OFL) and prints it with Chromium through the Python `playwright`, offline; `export_xlsx.py` writes the internal Excel; `document_template.py` keeps the factory's template in `tenant_settings.document` and its logo under `tenants/{tenant_id}/branding/`. The routes are in `api/routes/export.py` and `document.py`, behind `export_doc`; the Excel also needs `COSTS_READ` (07 §12).

**The chat quote builder** (13 §4.2, S27, `services/build.py`, routes in `api/routes/build.py` behind `chat_quote_builder`, voice also behind `voice_input`). A build is a drawing of `origin` = `chat`: `bom_only`, no files, its rows a stage-1 `bom_table` artifact of source `chat` (`pipeline/bom/chat.py`), its conversation `build_messages`. One message: `chat_bom_extraction` (`konboro_llm/stages/chat_bom_extraction.py`) is shown the message with amounts stripped, the panels and the draft's lines by short name (`L1`: description, the words said, quantity; no price), and answers items and changes; `chat.check` keeps an item only when its words are in the message and every number in it was said (digits or Hebrew words, `pipeline/bom/numbers.py`), and a change only for a line of this draft; then stages 4, 5, 6 (rules only) and 7 run in the request through the stages' own `run(ctx)` (`pipeline/inline.py`, with a write-through storage for the message), and every line already priced keeps its price. A component of a chat build is named by its first row (`association/bom.components(by_row=True)`), so a line keeps its key while rows come and go; a change is made on the rows, and undo restores the rows of the message before. The quote is made, and counted in the quota, at the first line. A recording (`services/transcribe.py`: the stand-in until S29) is never stored; its words wait as a `pending` message for "הוסף". **The chat home** routes in code first and asks `home_intent` (Haiku) for the rest, shown the text only (`services/home_route.py`, `POST /home/route` behind `home_chat`).

**The chat** (08, S25, `konboro/chat/`, routes in `api/routes/chat.py` behind `chat_layer`). The API runs one turn in the request: the quote brief and the screen context, the history by `chat_context_budget_tokens` with `chat_compaction` (`history.py`), then `LLMClient.run_tools` on `chat_command` (`konboro_llm/stages/chat_command.py`: the prompt and the tools' schemas). The tools are code (`tools.py`): they show the model lines, panels, findings and proposals by short names (`L3`, `B1`, `F2`, `CH1`) and every amount as a reference (`$T1`, `$P1`), kept in `chat_conversations.state` (`state.py`); the screen gets the amounts, the model never does, and `tests/integration/test_chat.py::test_no_amount_from_the_quote_reaches_the_model` checks it. `propose_change` (`proposals.py`) runs the review screen's own actions (`services/review.py`, `review_picker.py`, and `chat/actions.py` for the types the screen has no button for) in a SAVEPOINT on in-memory storage, with stages 6–7 once at the end (`review.Deferred`), diffs the quote and rolls back. Apply is the user's click on the API: the same actions with `source` = `chat` and the proposal's id on every event, so `review.undo` takes the whole proposal back. The answer is checked in code (`check.py`, 08 §8.2). The API's model is Claude with a key, the stand-in in tests and in `make dev` without one (`services.llm.chat_providers`). Since S25b: `explain_line` (`explain.py`) answers a "why" about one line through the `line_explanation` sub-agent (`konboro_llm/stages/line_explanation.py`), given the line's trace without money and one crop of the drawing with the line's instances framed, its citations checked in code, and the instances named `I1` for `{{instance:…}}`; `list_quotes` names the factory's other quotes `QT1…` (their names and customers never reach the model, matched by the user's words in code), and `compare` pairs another quote's lines by signature (`compare.py`, `quote_lines.signature`); a brand or SKU swap can be remembered for the customer or the factory (`remember_options`, the card's chips), which writes the match memory under each line's signature and `brand_context` (`review.save_memory`, a `memory_saved` event that undo takes back).

## Commands

| Command | What it does |
| --- | --- |
| `make install` | uv sync, pnpm install, and the Playwright Chromium, for E2E and for the backend's customer PDF (S26; the two pin the same Playwright version) |
| `make migrate` | Create the `konboro_app` role, then `alembic upgrade head` |
| `make seed` | Migrate, then load the demo tenant (made-up names, the prototype's price list, and `common.csv`'s products in it with no cost; every flag on, also for a demo tenant from before the flag, S28b) , the NURSERY-1 review fixture (with an earlier sent quote, for the chat's compare) and the 26-993 audit fixture, with their page images in S3. Needs `make up`. Safe to rerun |
| `make up` / `make down` | Start or stop local services: Postgres + pgvector (host port 5433), S3Mock as S3 (9000), ElasticMQ as SQS (9324) |
| `make dev` | API on port 8000 (uvicorn, reload), the pipeline worker (`python -m konboro.pipeline.worker`) and the Vite dev server on port 5180. Needs `make up`. Dev login: `demo@konboro.local` with `KONBORO_DEV_PASSWORD` from `.env`. The worker calls Claude with `ANTHROPIC_API_KEY` from the environment or `.env` (BUG-040), and logs which model it runs on; without a key it uses the stand-in model (`devtools/fake_llm.py`), whose answers are made up and marked `stand-in:` on the page, so a later run with a key classifies those pages again instead of reusing them (BUG-041) |
| `make test-unit` | pytest unit tests + Vitest |
| `make test-int` | pytest integration tests against the compose services |
| `make e2e` | Playwright, desktop and mobile projects. Needs `make up`: it starts its own API and pipeline worker on 8001 over a fresh `konboro_e2e` database with fixed E2E tenants (`konboro/devtools/e2e.py`, `frontend/e2e/fixtures.ts`), on its own `e2e-` queues, and Vite on 5181 |
| `make fidelity` | Prototype vs app screenshots into `frontend/e2e/fidelity/report.html`, for the user's review |
| `make check-screenshots` | Compare the accepted screens with their baselines, in Playwright's Linux Docker image (the same check runs in CI) |
| `make screenshots` | Rewrite those baselines, only after the user accepts a visual change |
| `make eval` | Golden-set evaluation against `eval/baseline.json`, which fails on any drop, with the overall rows that need no edit and the wrong green rows (00 §10.2, `eval/metrics/rows.py`, S28). It runs the chat's test set too (`eval/chat_set.json`, `eval/chat.py`, S25), and the chat builder's and the chat home's (`eval/build_set.json`, `eval/home_set.json`, `eval/build.py`, S27). Replay by default; `EVAL_MODE=live` uses real Claude, and `EVAL_RECORD=1` saves its answers as cassettes (`=missing`: only calls with none yet; `EVAL_MAX_USD` caps the spend); `EVAL_CATALOG_LINES=1` runs it with `catalog_lines` on (S27b, reported, not the baseline). Needs `make up` ([eval/README.md](eval/README.md)) |
| `make fixture-audit` | Write the 26-993 audit fixture (`devtools/fixtures/audit_993.json` and its page images, title block blanked) from a replay run, after a change that moves 26-993's audit. Needs `make up` |
| `make eval-baseline` | Make this run's metrics the committed baseline, after a change that moves a score on purpose |
| `make gen-client` | Regenerate the TS API client from FastAPI's OpenAPI (`frontend/src/api/openapi.json` → `schema.ts`). Run it after any API change and commit both files |
| `make check-client` | Fail if the committed client is stale. CI runs the same check |
| `make licenses` | Fail on GPL or AGPL dependencies, Python and npm |
| `make secrets` | Scan every commit for secrets with the pinned gitleaks Docker image. CI runs the same scan |
| `make check` | Everything CI runs: lint, types, licenses, secrets, client freshness, unit, integration, eval, e2e, screenshots |

Tooling: uv for Python 3.12 (`backend/.python-version`), pnpm with Node 22 (`.nvmrc`; run `nvm use` first). Ports can be changed in `.env` (see `.env.example`).

## Testing rules

- Every session adds tests at every layer it touches:
  - Unit tests for logic.
  - Integration tests for API, DB, queue or storage work.
  - Playwright tests for any UI work.
- Tests never call real LLM or OCR services. Use `FakeProvider`, the stand-in model (`konboro.devtools.fake_llm`, which the E2E worker and the integration fixtures use), or the replay cassettes under `eval/cassettes/`.
- Pricing code needs 100% branch coverage (07 §10.1).
- Playwright selectors, in order of preference:
  1. Role and accessible name.
  2. `data-testid`, named after the prototype's `data-act` or `id` (`data-testid="approve"`, `"chat-input"`).
- Run E2E tests on both the `desktop` and `mobile` (375×812) projects.
- A screen is done only after its prototype-fidelity screenshots are reviewed ([docs/dev-strategy.md](docs/dev-strategy.md#5-prototype-fidelity)).
- A failing golden-eval metric on a pipeline PR is a regression. Fix it, or explain it in the PR and the session file.

## Session workflow

Work is split into numbered sessions (`S01`, `S02`…), listed in [docs/roadmap.md](docs/roadmap.md). One session is one branch (`sNN-short-slug`) and one PR into `main`.

1. **Start with `/session-start`.** It:
   - picks the next session;
   - creates `docs/sessions/SNN-*.md` from the template if the file is missing;
   - creates the branch;
   - reads the cited specs and prototype lines;
   - proposes a plan.
2. **Work:**
   - Keep the session file's task checklist current.
   - Log every bug in [docs/bugs.md](docs/bugs.md). Fix it now only if it is P0 or blocks the session's goal.
   - Stay inside the session's scope. Write new ideas into the roadmap's backlog section.
3. **Finish with `/session-close`.** It:
   - runs `make check`;
   - updates the session file (done, decisions, follow-ups) and the roadmap status;
   - commits;
   - opens the PR.

The user merges the PR.

Each phase ends with a **gate session** that fixes the open bug list and checks the phase's exit criteria. It ends with a `phase-N` tag.

## Known spec inconsistencies

Resolve each one with the user when its session arrives, then fix the spec in the same PR.

- Flag keys differ between the two references. The prototype uses `chat_builder`, `voice` and `unresolved`; spec 13 uses `chat_quote_builder`, `voice_input` and `unresolved_overlay`. **The spec's keys win** everywhere in code.
- `golden/NEVIS-1/labels.json` uses page kind `single_line` where the other files use `single_line_diagram`. The eval normalizer maps it; the file stays as is.
