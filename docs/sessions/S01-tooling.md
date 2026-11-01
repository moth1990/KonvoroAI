# S01: Tooling and repo layout

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s01-tooling` |
| **Depends on** | S00 |
| **Status** | done |
| **PR** | [#2](https://github.com/moth1990/KonvoroAI/pull/2) |

## Goal

Lay down the monorepo every later session builds on:
- `make up`, `make check` and CI work on an empty but real backend and frontend;
- the existing `konboro_llm` tests pass from their new home;
- the React app renders an RTL page with the prototype's theme.

## References

- Specs: 12 §3 (backend stack), §6 (frontend stack), §7 (CI/CD), §8 (licenses).
- Prototype: lines 9–32 (`:root` tokens, light and dark), 6–336 (CSS, fonts, breakpoints).
- [dev-strategy.md §3](../dev-strategy.md#3-target-architecture): repo layout and local stand-ins.

## Tasks

### Backend
- [x] `backend/pyproject.toml` (uv, Python 3.12):
  - packages `konboro` and `konboro_llm`;
  - dependencies: fastapi, pydantic v2, pydantic-settings, sqlalchemy 2, alembic, psycopg, boto3, anthropic, uvicorn;
  - dev group: pytest, pytest-cov, ruff, mypy, pip-licenses.
- [x] `git mv konboro_llm backend/konboro_llm` and `git mv tests backend/tests/unit/llm`. Imports needed no change. Path mentions updated in README §4 and HANDOFF §2. Specs 00 and 12 name the module, not the folder, so they stay as is.
- [x] Empty package skeleton `backend/konboro/{api,db,contracts,pipeline/stages,domain,services}/__init__.py`.
- [x] `anthropic` is a dependency, so the Bedrock test always runs. `AnthropicBedrockMantle` exists in the pinned SDK (2.3.0), so there was no bug to log.
- [x] ruff (lint + format) and mypy configs.
  - mypy is strict on `konboro_llm`, `konboro.contracts` and `konboro.domain`.
  - `konboro_llm` needed type arguments on its generics and two annotations to pass. No behavior changed.

### Frontend
- [x] `frontend/`: Vite 8, React 19, TypeScript 6.0 (strict), MUI 9.5, pnpm, Node 22 LTS (`.nvmrc`), ESLint and Prettier, Vitest.
- [x] MUI with an RTL cache (`stylis-plugin-rtl`), `dir="rtl"` and `lang="he"` on `<html>`.
- [x] `src/theme/tokens.ts`: every prototype `:root` variable, light and dark. `rootCss()` emits the prototype's three selectors unchanged.
  - `theme.ts` builds the MUI theme from the tokens.
  - `ThemeRoot` follows `prefers-color-scheme`, with a `data-theme` override.
- [x] Fonts self-hosted through `@fontsource` (OFL): Rubik, IBM Plex Sans Hebrew, IBM Plex Mono.
- [x] `base.css` ports the prototype base styles (lines 34–52) and the `.mono` / `.des` / `.num` / `.muted` / `.small` / `.eyebrow` utilities.
- [x] Placeholder page: logo (prototype line 378), a sample designator, and an 18-token swatch list.

### Infra
- [x] `docker-compose.yml`, with healthchecks on all three services:
  - `pgvector/pgvector:pg16` on host port 5433;
  - S3Mock as S3 on 9000, creating the `konboro-files` bucket on start;
  - ElasticMQ on 9324, configured in `infra/elasticmq.conf`: 7 stage queues plus a DLQ, 3 receives before a message goes to the DLQ.
- [x] `Makefile`: `help`, `install`, `up`, `down`, `dev`, `lint`, `licenses`, `test-unit`, `test-int`, `e2e`, `check`. `eval` and `gen-client` are placeholders that point to S06 and S03.
- [x] `.github/workflows/ci.yml` runs on PRs and on push to `main`:
  - **backend job:** ruff, format, mypy, licenses, unit tests; then `docker compose up --wait` and integration tests.
  - **frontend job:** lint, types, licenses, Vitest, Playwright with Chromium.
- [x] License gate:
  - Python: `python -m konboro.licenses`. GPL and AGPL fail; LGPL is allowed.
  - npm: `pnpm run license-check` (license-checker `--failOn`).
- [x] `.gitignore` additions; `.env.example` with key names and ports only.
- [x] `.claude/launch.json` (`web`) for the built-in browser preview.

### Unit tests
- [x] The 4 `konboro_llm` tests pass under `make test-unit`.
- [x] `test_layout.py` checks two things:
  - every package imports;
  - `ROUTES` covers exactly the 11 stage keys of 00 §7.1.
- [x] `test_licenses.py` covers 13 cases: GPL and AGPL fail; LGPL, permissive and dual licenses pass; our own package is skipped.
- [x] Vitest, 10 tests:
  - `tokens.test.ts` **parses the prototype** and fails if any color, shadow, font or radius drifts, or if a new prototype token isn't ported;
  - `theme.test.ts` checks RTL, the palette from tokens, and the color-mode rule.

### Integration tests
- [x] `test_local_services.py` (4 tests): pgvector works; S3 round trip with Hebrew content; all 7 stage queues and the DLQ exist; queue round trip.

### UI tests (Playwright)
- [x] `playwright.config.ts` with `desktop` (1440×900) and `mobile` (375×812, touch) projects. Vite starts as `webServer`.
- [x] `smoke.spec.ts`, 6 tests × 2 projects:
  - `dir=rtl` and `lang=he`;
  - designators render LTR-isolated;
  - `--bg` matches the light and dark tokens;
  - `data-theme` overrides the OS in both directions.
- [ ] Prototype-fidelity report: not applicable. There is no prototype screen yet; the first report comes in S04.

### Docs
- [x] CLAUDE.md commands, layout, tooling note and license rule. The "until S01" notes are removed.
- [x] dev-strategy: S3Mock, license gate, layout. Roadmap and S05 no longer mention MinIO.

## Acceptance criteria

- [x] From a clean checkout, install, up and the full check pass. A local fresh-clone run was blocked by a permission prompt, but CI does the same steps on a clean runner: `uv sync --frozen`, `pnpm install --frozen-lockfile`, `docker compose up --wait`, then every check. It passed ([run 41180022912](https://github.com/moth1990/KonvoroAI/actions/runs/41180022912)).
- [x] The CI run on the PR is green: backend 43 s, frontend 53 s.
- [x] `git log --follow backend/konboro_llm/client.py` shows the history (moved with `git mv`).
- [x] The license check fails when an AGPL package is added on purpose. Tested locally and not committed:
  - Python: PyMuPDF failed with exit 1.
  - npm: a fake package declaring `AGPL-3.0` failed with exit 1.
  - Both were clean again after removal.

## Out of scope

- DB models (S02).
- API endpoints (S03).
- Real screens (S04 onward).

## Open questions

Answered at kickoff; see Outcome.

## Outcome

- **Done:**
  - Monorepo layout; `konboro_llm` moved with history.
  - Backend skeleton: strict types, ruff, and the license gate.
  - Local AWS stand-ins, healthy and tested.
  - React 19 + MUI 9 RTL frontend on the prototype's tokens.
  - Playwright on desktop and mobile; Makefile; CI.
  - Test counts: 27 unit and 4 integration (pytest), 10 Vitest, 12 Playwright.
- **Decisions made:**
  - From the user, at kickoff:
    - The frontend uses pnpm.
    - Versions: Node 22 LTS, React 19, Python 3.12. Python is installed through uv, because the machine has only 3.14.
    - CI runs on every PR and every push to `main`.
  - **MUI 9.5, not 7.** At kickoff I wrongly presented MUI 7 as the latest version; it is 9.5. The user chose 9.5 once corrected.
  - **TypeScript 6.0, not 7.** typescript-eslint supports TypeScript up to 6.0.
  - **S3Mock instead of MinIO** for local S3. MinIO images are no longer published on Docker Hub; the pull fails. S3Mock is Apache 2.0 and speaks the S3 API to boto3. The cloud (S29) uses real S3, so app code doesn't change.
  - **Host ports 5433 (Postgres) and 5180 (Vite).** 5432 and 5173 are taken on the dev machine. Both can be changed in `.env`.
  - **LGPL is allowed** (psycopg): linked as a library, never modified. Spec 12 §8 bans GPL and AGPL only.
  - **Fonts are self-hosted** through `@fontsource` instead of the prototype's Google Fonts link. Same families and weights; works offline and in CI.
- **Bugs logged:** BUG-001 (found and fixed in this session).
- **Follow-ups:** none.
