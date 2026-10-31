# S01: Tooling and repo layout

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s01-tooling` |
| **Depends on** | S00 |
| **Status** | todo |
| **PR** | |

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
- [ ] `backend/pyproject.toml` (uv, Python 3.12):
  - packages `konboro` and `konboro_llm`;
  - dependencies: fastapi, pydantic v2, sqlalchemy 2, alembic, psycopg, boto3, anthropic;
  - dev group: pytest, pytest-cov, ruff, mypy, pip-licenses.
- [ ] `git mv konboro_llm backend/konboro_llm` and `git mv tests backend/tests/unit/llm`. Fix the imports. Update the path mentions in README §4, HANDOFF §2 and specs 00 §7 / 12 §4 if they name the folder.
- [ ] Empty package skeleton `backend/konboro/{api,db,contracts,pipeline/stages,domain,services}/__init__.py`.
- [ ] Make the Bedrock test skip cleanly when `anthropic` is missing. Better: add `anthropic` as a dependency so it always runs. Check that `AnthropicBedrockMantle` exists in the pinned SDK; if it does not, log a bug.
- [ ] ruff (lint + format) and mypy configs. mypy is strict on `konboro_llm`.

### Frontend
- [ ] `frontend/`: Vite + React 18 + TypeScript (strict), pnpm, ESLint and Prettier, Vitest.
- [ ] MUI with an RTL cache (`stylis-plugin-rtl`), `dir="rtl"` and `lang="he"` on `<html>`.
- [ ] `src/theme/tokens.ts`:
  - Port every `:root` variable from the prototype, light and dark: `--bg --surface --surface-2 --line --fg --muted --faint --accent --copper --ok/-soft --warn/-soft --bad/-soft`, radii, shadow.
  - Build the MUI theme from these tokens.
  - Dark mode follows `prefers-color-scheme`, plus a `data-theme` override.
- [ ] Fonts as in the prototype: Rubik, IBM Plex Sans Hebrew, IBM Plex Mono. Add the `.mono`/`.des` LTR-isolate utility.
- [ ] A placeholder page that shows the brand name and a token swatch, so the theme can be eyeballed.

### Infra
- [ ] `docker-compose.yml`: `pgvector/pgvector:pg16`, MinIO (bucket created on start), ElasticMQ (queue config file). Healthchecks on all three.
- [ ] `Makefile`: `up`, `down`, `dev`, `test-unit`, `test-int` (placeholder), `e2e`, `eval` (placeholder), `gen-client` (placeholder), `lint`, `check`.
- [ ] `.github/workflows/ci.yml`:
  - Jobs: backend lint, types and unit tests; frontend lint, types and unit tests; license check; e2e (Playwright with browsers cached).
  - Compose services start in CI for the jobs that need them (integration from S02).
- [ ] License gate: fail on AGPL/GPL, in pip-licenses and in `license-checker` for npm.
- [ ] `.gitignore`: node_modules, dist, playwright reports, `eval/reports/`, `.env*`.
- [ ] `.env.example`, with the Anthropic key name only and no values.

### Unit tests
- [ ] The 4 existing `konboro_llm` tests pass under `make test-unit`.
- [ ] One Vitest test: the theme builds, and `direction` is `rtl`.

### UI tests (Playwright)
- [ ] `frontend/playwright.config.ts` with `desktop` (1440×900) and `mobile` (375×812) projects. Vite starts as `webServer`.
- [ ] Smoke test: the page loads, `html[dir=rtl]` is set, and the body background equals the `--bg` token in light and in dark.

### Docs
- [ ] CLAUDE.md "Commands" and "Repository layout" match reality. Remove the "until S01" notes.

## Acceptance criteria

- [ ] On a clean clone, `make up && make check` passes.
- [ ] The CI run on the PR is green.
- [ ] `git log --follow backend/konboro_llm/client.py` shows the history (moved with `git mv`).
- [ ] The license check fails when an AGPL package is added on purpose. Test this locally; do not commit it.

## Out of scope

- DB models (S02).
- API endpoints (S03).
- Real screens (S04 onward).

## Open questions

- pnpm or npm? Default: pnpm.
- Should CI also run on pushes to `main`, or only on PRs? Default: both.

## Outcome

- **Done:**
- **Decisions made:**
- **Bugs logged:**
- **Follow-ups:**
