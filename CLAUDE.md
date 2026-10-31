# CLAUDE.md: Konboro

Konboro turns electrical-panel drawings into price quotes that are ready for review, for panel-building factories. It is a 7-stage pipeline where the coordinator is code and LLMs only handle ambiguous cases. Next to it are a split review screen, a chat command layer, and onboarding that happens through use.

- Product summary and decisions: [README.md](README.md). Conversation history: [HANDOFF.md](HANDOFF.md).
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
7. **Tenant isolation:** every tenant table has `tenant_id` and a Postgres RLS policy. Every endpoint checks permission against the single `owner` role (00 §8, §14.1). Cross-tenant tests are mandatory.
8. **Every new feature sits behind a flag**, evaluated on the server (13).
9. **No AGPL or GPL dependencies.** That rules out PyMuPDF and Ultralytics YOLO (12 §8). CI checks licenses.
10. **RTL from day one.** Use `dir="rtl"`, logical CSS properties, and wrap numbers and designators in `dir="ltr"` (the prototype's `.mono` and `.des` classes).
11. **IDs, coordinates, confidence and colors** follow 00 §6:
    - ID prefixes: `drw_`, `pg_`, `ln_`…
    - Coordinates are PDF points with the origin at the top left.
    - Confidence maps to colors: ≥0.85 green, 0.5–0.85 yellow, <0.5 red.
    - Stage 7 alone sets a row's final color.

## Repository layout

```
backend/        Python 3.12 (uv): konboro/ (api, db, contracts, pipeline, domain, services), konboro_llm/, alembic/, tests/
frontend/       React + TS + Vite + MUI, RTL. src/theme/tokens.ts mirrors the prototype tokens. e2e/ = Playwright
eval/           golden-set evaluation harness
golden/ specs/ prototype/   reference material; do not modify without the user
docs/           strategy, roadmap, session files, bug log
```

The layout is built during phase 0. Until S01 lands, `konboro_llm/` and `tests/` are still at the repo root.

## Commands

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start or stop local services: Postgres + pgvector, MinIO (S3), ElasticMQ (SQS) |
| `make dev` | API, worker and Vite dev server |
| `make test-unit` | pytest unit tests + Vitest |
| `make test-int` | pytest integration tests against the compose services |
| `make e2e` | Playwright, desktop and mobile projects |
| `make eval` | Golden-set evaluation. Replay by default; `EVAL_MODE=live` uses real Claude |
| `make gen-client` | Regenerate the TS API client from FastAPI's OpenAPI |
| `make check` | Everything CI runs: lint, types, license check, unit, integration, e2e, client freshness |

Until the Makefile exists (S01), run the LLM tests with `python -m pytest tests/`.

## Testing rules

- Every session adds tests at every layer it touches:
  - Unit tests for logic.
  - Integration tests for API, DB, queue or storage work.
  - Playwright tests for any UI work.
- Tests never call real LLM or OCR services. Use `FakeProvider`, or the replay cassettes under `eval/cassettes/`.
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

- 09 §10, the event table, lacks the `price_changed` and `supplier_selected` events that §7.14–7.15 use. Due in S23.
- 01 §6.3: `classified_by` has no `template` value, but §5.7 uses it. Due in S08.
- 01 §7, the routing table, lacks `technical_data` and `factory_template`. Due in S08.
- 02 §2.6 says duplicates are removed after stage 4, but 03 §3.5 moved that into stage 3. Due in S12.
- 00 §14 and README §7 order the phases differently. The roadmap follows README §7.
- Flag keys differ between the two references. The prototype uses `chat_builder`, `voice` and `unresolved`; spec 13 uses `chat_quote_builder`, `voice_input` and `unresolved_overlay`. **The spec's keys win** everywhere in code.
- The mobile breakpoint is 860px in 09 §5.2 and 820px in the prototype. Ask in S04.
- `golden/NEVIS-1/labels.json` uses page kind `single_line` where the other files use `single_line_diagram`. The eval normalizer maps it; the file stays as is.
