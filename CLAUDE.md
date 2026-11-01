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
Built so far: login, shell, classic and chat home (S04); new quote: pick, run, done (S05); confirm pages and page-kind change (S08); review lines, filters and line detail on the NURSERY-1 fixture, behind `review_screen` (S09).

| Screen | Route | Function | Lines |
| --- | --- | --- | --- |
| Design tokens (light and dark) | — | `:root` | 9–32 |
| Login | (not authed) | `vLogin` | 660–688 |
| Shell: rail, mobile tab bar, quota meter | — | `shell`, `navItems` | 690–714 |
| Home, classic and chat (`home_chat` flag) | `#home` | `vHome`, `vHomeChat` | 716–751, 1253–1284 |
| New quote: pick, run, done | `#new` | `vNew`, `validateFile`, `runPipeline` | 754–869 |
| Review: lines, line detail, drawing | `#review` | `vReview` | 872–1004 |
| Chat drawer and proposal cards | `#review` | `vChat`, `applyProp` | 1007–1064 |
| Audit of an existing quote | `#audit` | `vAudit` | 1066–1096 |
| Price list and product editor | `#prices` | `vPrices`, `openEditor` | 1098–1208 |
| Approval queue | `#queue` | `vQueue` | 1210–1226 |
| Settings and flags | `#prefs` | `vPrefs` | 1228–1251 |
| Chat quote builder (`chat_quote_builder` flag) | `#build` | `parseBom`, `vBuild` | 1287–1357 |
| Export modal (`export_doc` flag) | — | `exportModal` | 1360–1378 |

Mock data in the prototype (lines 393–580) suggests field names for the API: `makeLines`, `makeFindings`, `QUOTES`, `CATALOG`, `QUEUE`, `AUDIT`, `UNRESOLVED`. The specs still win on the data model.

## Non-negotiables

1. **The coordinator is code.** An LLM only decides inside one stage, picks from a closed list, and code checks its answer afterwards (00 §3, §7.2). The chat coordinator (08) is the one exception.
2. **Every LLM call goes through `konboro_llm`**, with one route per stage key in `config.py`. Never call a provider SDK directly. Changing a model requires a golden-set run.
3. **Every value has evidence.** If it is not written in the drawing, it is `null`. Stage 4 reads, stage 5 fills in, and each value keeps its source (00 §5.3, 04 §5.5).
4. **Current and poles never get a default.** Changing an electrical value requires user approval (05 §4.4).
5. **Money is `Decimal` in code, `numeric` in the database, and a string in JSON. Never float.** Pricing is code only (07).
6. **Prices, costs and customer details are never sent to any model.** In chat, amounts reach the model only as references such as `$T1` (08). A test enforces this.
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
- **Stages.** `konboro/pipeline/stages/sN_*.py` are stubs since S05; stage 1 is real since S08 (its parts are in `pipeline/intake/`) and stage 2 since S10 (`pipeline/extraction/`; OCR goes through the `OcrEngine` interface, `ClaudeVisionOcr` until S31). A later session replaces one by writing a function `run(ctx) -> Contract` that reads earlier outputs through `ctx.output(n, Model)` and calls the model only through `ctx.llm`, which writes each call to `llm_calls`. The coordinator (`pipeline/coordinator.py`) doesn't change.
- **Queues.** One SQS queue per stage (`konboro-s1-intake` … `-s7-pricing`), each sending to `konboro-dlq` after 3 failed receives. Messages carry IDs only (`StageMessage`). Files and stage outputs live in S3 under `tenants/{tenant_id}/`, through `services/storage.py`, which refuses another tenant's key.

## Commands

| Command | What it does |
| --- | --- |
| `make install` | uv sync, pnpm install, and the Playwright Chromium |
| `make migrate` | Create the `konboro_app` role, then `alembic upgrade head` |
| `make seed` | Migrate, then load the demo tenant (made-up names, the prototype's price list). Safe to rerun |
| `make up` / `make down` | Start or stop local services: Postgres + pgvector (host port 5433), S3Mock as S3 (9000), ElasticMQ as SQS (9324) |
| `make dev` | API on port 8000 (uvicorn, reload), the pipeline worker (`python -m konboro.pipeline.worker`) and the Vite dev server on port 5180. Needs `make up`. Dev login: `demo@konboro.local` with `KONBORO_DEV_PASSWORD` from `.env`. Stage 1 calls Claude with `ANTHROPIC_API_KEY`; without a key the local worker uses the stand-in model (`devtools/fake_llm.py`) and logs a warning |
| `make test-unit` | pytest unit tests + Vitest |
| `make test-int` | pytest integration tests against the compose services |
| `make e2e` | Playwright, desktop and mobile projects. Needs `make up`: it starts its own API and pipeline worker on 8001 over a fresh `konboro_e2e` database with fixed E2E tenants (`konboro/devtools/e2e.py`, `frontend/e2e/fixtures.ts`), on its own `e2e-` queues, and Vite on 5181 |
| `make fidelity` | Prototype vs app screenshots into `frontend/e2e/fidelity/report.html`, for the user's review |
| `make check-screenshots` | Compare the accepted screens with their baselines, in Playwright's Linux Docker image (the same check runs in CI) |
| `make screenshots` | Rewrite those baselines, only after the user accepts a visual change |
| `make eval` | Golden-set evaluation against `eval/baseline.json`, which fails on any drop. Replay by default; `EVAL_MODE=live` uses real Claude, and `EVAL_RECORD=1` saves its answers as cassettes (`=missing`: only calls with none yet; `EVAL_MAX_USD` caps the spend). Needs `make up` ([eval/README.md](eval/README.md)) |
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

- 02 §2.6 says duplicates are removed after stage 4, but 03 §3.5 moved that into stage 3. Due in S12.
- Flag keys differ between the two references. The prototype uses `chat_builder`, `voice` and `unresolved`; spec 13 uses `chat_quote_builder`, `voice_input` and `unresolved_overlay`. **The spec's keys win** everywhere in code.
- `golden/NEVIS-1/labels.json` uses page kind `single_line` where the other files use `single_line_diagram`. The eval normalizer maps it; the file stays as is.
