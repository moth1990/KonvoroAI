# Development strategy

How Konboro gets built: who builds it, in what order, against which references, and how each piece is proven to work. The rules every session must follow are in [CLAUDE.md](../CLAUDE.md). The session list is in [roadmap.md](roadmap.md).

## 1. Working model

- **One developer driving Claude Code.** The unit of work is a **session**: one goal, one branch `sNN-slug`, one PR into `main`.
- **Sessions follow the roadmap.** A session file in `docs/sessions/` holds the goal, the references, the tasks for each layer, the acceptance criteria and the outcome.
- **Phases end with a gate session** (see §7). A phase is closed only when its exit criteria are met and no P0 or P1 bugs are open.
- **Two tracks run in parallel from phase 1, alternating session by session.** **P** is the pipeline and backend: stages 1–4, then the quote audit. **R** is the review UI on fixture data. The two meet in the quote API, so the UI never waits for the pipeline. **X** marks cross-cutting sessions.
- **Tracking lives in the repo:** the roadmap status column, the session files, and [bugs.md](bugs.md).

## 2. Sources of truth

| Area | Reference | How to use it |
| --- | --- | --- |
| Business logic, contracts, thresholds, data model | `specs/00`–`13` | Implement what the spec says, and cite `NN §x.y` in code and PRs |
| Screens, flows, Hebrew copy, layout, colors, interaction details | `prototype/konboro-app.html` | Port each screen faithfully. Use the line map in [CLAUDE.md](../CLAUDE.md#prototype-map) |
| Correct pipeline output | `golden/` | The evaluation baseline. Never edit it to make a test pass |

When a spec and the prototype disagree, ask the user, record the answer in the session file, and fix the losing document in the same PR.

The prototype simulates everything:
- **Timers** stand in for the pipeline.
- **Regexes** stand in for chat.
- **In-memory state** stands in for the API.

The behavior the user sees is the reference. The way the prototype produces it is not.

## 3. Target architecture

This follows [specs/12-tech-stack.md](../specs/12-tech-stack.md). Locally, each AWS service has a stand-in that speaks the same API, so the code does not change when it moves to the cloud.

| Concern | Production (phase 3) | Local / CI (phases 0–2) |
| --- | --- | --- |
| API | FastAPI on ECS Fargate | `uvicorn` |
| Pipeline workers | ECS Fargate, one SQS queue per stage plus a DLQ | Worker process + **ElasticMQ** (SQS API, same boto3 code) |
| Database | RDS PostgreSQL + pgvector, RLS | `pgvector/pgvector` container |
| Files | S3 with KMS, one prefix per tenant | **S3Mock** (`adobe/s3mock`; MinIO images are no longer published) |
| Auth | Cognito, `tenant_id` claim | Dev JWT issuer with the same claims |
| LLM | Claude through Bedrock (`AnthropicProvider.for_bedrock()`) | Direct Anthropic API key. Tests use `FakeProvider` or replay cassettes |
| OCR | Google Vision or Azure, chosen in S31 | `OcrEngine` interface. Interim implementation: `ClaudeVisionOcr` |
| Voice | Amazon Transcribe `he-IL` | Fake transcriber |
| Frontend hosting | S3 + CloudFront | Vite dev server |

### Repository layout

```
backend/
  pyproject.toml        uv-managed, Python 3.12
  konboro/
    api/                FastAPI routers. Every handler checks permission and tenant
    db/                 SQLAlchemy 2 models, session with tenant context (SET app.tenant_id), RLS helpers
    contracts/          Pydantic stage contracts from 00 §5 (the single source for stage I/O)
    pipeline/           coordinator, worker loop, stages/s1_intake … s7_pricing
    domain/             pricing, quota, flags, versions: pure logic, no I/O
    services/           storage (S3), queue (SQS), ocr, auth, transcribe
  konboro_llm/          the model gateway (moved from the repo root in S01)
  konboro/licenses.py   the Python license gate (GPL/AGPL fail, LGPL allowed)
  alembic/              migrations, one per schema change
  tests/unit/  tests/integration/
frontend/
  src/theme/tokens.ts   prototype :root tokens (light and dark) → MUI theme, direction rtl
  src/api/              generated TS client (openapi-typescript) + TanStack Query hooks
  src/screens/          one folder per prototype screen
  e2e/                  Playwright specs, fixtures, fidelity/
eval/
  normalizers/          one per golden label format → canonical schema
  metrics/              one per stage + audit differences
  run.py  compare.py    `make eval`, and the comparison with baseline.json (committed)
  cassettes/            recorded LLM responses for replay mode
  reports/              generated, git-ignored
infra/elasticmq.conf    one queue per stage + DLQ
docker-compose.yml  Makefile  .github/workflows/ci.yml  .nvmrc  .env.example
```

### Conventions that cross the stack

- **Contracts first.** A stage's output is a Pydantic model in `konboro/contracts/`. The API exposes Pydantic response models. The TS client is generated from the OpenAPI spec. CI fails if the generated client is stale.
- **Money** is `Decimal` in Python, `numeric(14,4)` in Postgres, a string in JSON, and a decimal library in TS for any arithmetic. In the browser, money is formatted only, never computed: totals come from the API.
- **Tenant context.** Every request and every worker job opens a DB session that runs `SET LOCAL app.tenant_id`. RLS policies read that setting. The app role is not the table owner and has no `BYPASSRLS`.
- **Flags** are evaluated on the server (13): tenant override, then plan, then global, then default. The client receives the evaluated set and hides UI to match. The server enforces flags on every endpoint.
- **IDs** use the prefixes in 00 §6.1, plus a ULID suffix.

## 4. Test strategy

| Layer | Tool | Covers | Where | When |
| --- | --- | --- | --- | --- |
| Unit | pytest, Vitest | Pure logic and stage functions with fake LLM and OCR. **Pricing at 100% branch coverage** (07 §10.1) | `backend/tests/unit`, `frontend/src/**/*.test.ts` | Every PR |
| Integration | pytest against the compose services | Endpoints with a real DB, migrations, **cross-tenant RLS tests** (00 §8.1), quota atomicity under concurrency, flag evaluation, queue → worker → DB, S3 round trips, **no money in any LLM request** (08 §13.2) | `backend/tests/integration` | Every PR |
| UI / E2E | Playwright (TS) | Prototype flows per screen against the real API with seeded data and fake LLM. Projects `desktop` (1440×900) and `mobile` (375×812). RTL, keyboard shortcuts, flag on/off | `frontend/e2e` | Every PR for touched screens. Full suite at gates |
| Visual regression | Playwright `toHaveScreenshot` | App screenshots against committed baselines | `frontend/e2e` | Every PR touching UI |
| Prototype fidelity | Playwright script | Side-by-side report, prototype vs app (§5) | `frontend/e2e/fidelity` | Sessions that build or change a screen, and gates |
| Golden eval | `eval/` CLI | Per-stage metrics against `golden/` (§6) | `eval/` | Pipeline PRs (replay), gates (live) |
| Contract | openapi-typescript | Generated client matches the API | CI | Every PR |
| License | `python -m konboro.licenses`, license-checker | Fails on AGPL or GPL. LGPL (psycopg) is allowed: linked as a library, never modified | CI | Every PR |
| Lint and types | ruff, mypy (strict for `domain/` and `contracts/`), ESLint, `tsc --noEmit` | | CI | Every PR |

Rules:
- **No network in tests.** LLM calls use `FakeProvider` or replay cassettes. OCR uses a fake engine or recorded output.
- **Integration tests own their data.** Each test creates its own tenants inside a transaction or truncated schema. Never depend on the demo seed.
- **Every flag-gated feature is tested both on and off** (13 §3).
- **A bug fix starts with a failing test** that reproduces the bug.
- **E2E selectors:** role and accessible name first, then `data-testid`. Testids reuse the prototype's `data-act` and `id` names (`approve`, `chat-input`, `drop`), so the prototype doubles as the selector map.

## 5. Prototype fidelity

The prototype is the visual contract, but its DOM is different from the React app, so pixel diffing the two is meaningless. Instead:

1. **Port the tokens before any screen.** The prototype's `:root` and dark-theme variables (lines 9–32) become `src/theme/tokens.ts` and the MUI theme. That covers palette, radii, shadow and the fonts (Rubik for headings, IBM Plex Sans Hebrew for body text, IBM Plex Mono for numbers and designators). MUI components are restyled to match the prototype, not the other way around.
2. **The fidelity script** (`frontend/e2e/fidelity/capture.ts`):
   - Serves `prototype/` statically (as UTF-8: the file declares no charset), sets `localStorage['konboro:authed']='1'` and its flags, and opens each hash route at desktop and mobile sizes, in light and dark. The prototype has no viewport meta, so its phone shots use a plain 375px window rather than mobile emulation.
   - Opens the matching app route as the E2E tenant in the same state.
   - Writes `frontend/e2e/fidelity/report.html`, self-contained, with the two screenshots side by side for each screen and the deliberate differences listed above them. Run it with `make fidelity`.
3. **Review:** the session that builds a screen ends with the user reviewing that report. Deviations are either fixed or logged as P2/P3 bugs with a reason.
4. **Regression:** once a screen is accepted, its app screenshots become `toHaveScreenshot` baselines (`frontend/e2e/visual.spec.ts`). They are rendered and checked only inside Playwright's pinned Linux image (`frontend/e2e/visual/`), locally and in CI, so fonts and rasterization never differ: `make screenshots` writes them, `make check-screenshots` compares. Text that changes with the clock is masked.

## 6. Golden evaluation

The golden set measures the system and catches regressions (README §6.2).

- **Normalizers.** Each of the 5 label files has a different shape: `bom[]`, `components[]`, `panels[].components[]`, and two kinds of `rows[]`. One normalizer per shape maps it to a canonical schema:
  - page kinds and routes;
  - `input_kind`;
  - components per panel (family, attributes, designators, quantity);
  - audit differences from `actual_quote.json`.

  Known quirks (for example `single_line` vs `single_line_diagram`) are mapped in code.
- **Metrics follow the acceptance sections of each spec:**
  - Stage 1: page kind accuracy, routes, `input_kind` (01 §10).
  - Stage 4: per-panel component P/R, `current_a` and poles accuracy, and quantity accuracy (04 §10). Components match by family + designators. Without designators (designer plans, BOM-only), they match by family + `current_a` + poles, with quantities added up (S06 decision).
  - Audit: difference accuracy and recall of omissions confirmed by the factory (11 §10).
  - Pricing: backtest against actual quote totals (07 §10.2).
  - Stages 2–3 need span- and box-level labels that do not exist yet. Those metrics are added once the labeling work provides them.
- **Modes:**
  - `replay` (default, CI) uses recorded LLM responses from `eval/cassettes/`. It is deterministic and free.
  - `live` calls Claude and can re-record cassettes with `EVAL_RECORD=1`.
- **Output:** `eval/reports/<timestamp>.json` and `.md`. The run compares itself with the committed `eval/baseline.json` (S06 decision). The CI `eval` job writes the markdown to the job summary, uploads the report, and fails on any drop. A PR that moves a score on purpose runs `make eval-baseline` and commits the new baseline, so reviewers see the change. Details are in [eval/README.md](../eval/README.md).
- **Growth:** new golden drawings go in `golden/<id>/` with a README and labels. README §6.2 targets 10 drawings by the first full measurement, from more than one factory.

## 7. Definition of done, bugs, gates

**A session is done when:**
- [ ] The goal and acceptance criteria in the session file are met.
- [ ] Tests were added for every layer touched: unit; integration for API, DB, queue or storage; Playwright for UI.
- [ ] `make check` passes locally, and CI passes on the PR.
- [ ] For UI work, the fidelity report was reviewed by the user.
- [ ] For pipeline work, `make eval` was run and the numbers are in the session file.
- [ ] The session file "Outcome" section is filled in, the roadmap status is updated, and bugs are logged.
- [ ] The PR is open with a summary, the spec references, and the test evidence.

**Bug severities** (logged in [bugs.md](bugs.md)):

| Severity | Meaning | When it gets fixed |
| --- | --- | --- |
| P0 | Data leak across tenants, wrong money, a value made up without evidence, data loss, broken main flow | Immediately, in the current session |
| P1 | A feature in the session's scope doesn't work, or fidelity is badly off | Before the phase gate passes |
| P2 | Minor functional or visual deviation | At the gate, or later if it is scheduled explicitly |
| P3 | Cosmetic, or an idea | Backlog |

**Gate sessions** (S07, S17, S28, S32):
1. Run everything: `make check`, the full E2E suite on both projects, the fidelity report for every screen built so far, and `make eval` (live at gates 1–3).
2. Fix all P0 and P1 bugs, and the P2 bugs that fit.
3. Check the exit criteria from the roadmap and record the evidence in the gate's session file.
4. Update CLAUDE.md, this strategy, and the specs where reality changed them.
5. Merge, then tag `phase-N`.

If an exit criterion is blocked by something outside the code (for example, not enough golden drawings), the gate records it as a known gap with an owner. Development continues, and the gate is marked passed with that gap.

## 8. Phases

| Phase | Goal | Exit criteria | README §7 |
| --- | --- | --- | --- |
| 0. Foundations | A thin, working, tested slice end to end: login → upload → stub pipeline → result, on a tenant-isolated DB, with eval running | Eval runs automatically on the golden set. Skeleton E2E green. RLS tests green | Phase 0 |
| 1. Parsing + audit ∥ review UI | Stages 1–4 and the BOM path. Quote audit, the first sellable product. Review screen I–II on fixtures | ≥80% difference accuracy on golden drawings that have actual quotes. Audit and review E2E green | Phase 1 |
| 2. Full quotes, v1.0 | Stages 5–7, price list, onboarding, approval queue, chat, flagged v1.0 features | A new tenant produces a quote on day one. ≥85% of golden rows need no edit. All prototype flows covered by E2E | Phase 2 |
| 3. Cloud and pilot readiness | AWS, deployment, observability, OCR engine choice | Staging runs the full E2E suite and the live eval. Security review passed | Pilot |

The timings and thresholds in the specs are starting values. They are calibrated after the first real measurement (README §8).
