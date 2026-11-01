# Konboro developer commands. `make check` runs everything CI runs (CLAUDE.md, Commands).
# Backend: uv (Python 3.12). Frontend: pnpm (Node 22, see .nvmrc).

# Secret scanner, pinned by version and digest (S07). gitleaks is MIT.
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46

BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help install up down migrate seed dev lint licenses secrets test-unit test-int e2e fidelity screenshots check-screenshots eval eval-baseline gen-client check-client check

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies and the Playwright browser
	$(BACKEND) uv sync
	$(FRONTEND) pnpm install --frozen-lockfile
	$(FRONTEND) pnpm exec playwright install chromium

up: ## Start Postgres + pgvector, S3 (S3Mock) and SQS (ElasticMQ), and wait until healthy
	docker compose up -d --wait

down: ## Stop the local services (data volumes are kept)
	docker compose down

migrate: ## Create the app DB role, then apply migrations (docs/db-schema.md)
	$(BACKEND) uv run python -m konboro.db.bootstrap
	$(BACKEND) uv run alembic upgrade head

seed: migrate ## Demo data: tenant "לוחות דמו", price list from the prototype, review fixture (needs `make up`). Safe to rerun
	$(BACKEND) uv run python -m konboro.db.seed

dev: ## Run the API (port 8000), the pipeline worker and the web app (port 5180). Needs `make up`
	@trap 'kill 0' EXIT; \
	(cd backend && uv run uvicorn --factory konboro.api.app:create_app --reload --port $${KONBORO_API_PORT:-8000}) & \
	(cd backend && uv run python -m konboro.pipeline.worker) & \
	cd frontend && pnpm dev

lint: ## Lint, format check and types, backend and frontend
	$(BACKEND) uv run ruff check . ../eval
	$(BACKEND) uv run ruff format --check . ../eval
	$(BACKEND) uv run mypy
	$(FRONTEND) pnpm lint
	$(FRONTEND) pnpm typecheck

licenses: ## Fail on GPL or AGPL dependencies (specs/12-tech-stack.md §8)
	$(BACKEND) uv run python -m konboro.licenses
	$(FRONTEND) pnpm run license-check

secrets: ## Scan every commit for secrets with the pinned gitleaks image (needs Docker)
	docker run --rm -v "$(CURDIR):/repo" $(GITLEAKS_IMAGE) git /repo --log-opts="--all" --redact --no-banner

test-unit: ## Backend unit tests and frontend Vitest
	$(BACKEND) uv run pytest -m "not integration"
	$(FRONTEND) pnpm test

test-int: ## Backend integration tests against the local services (needs `make up`)
	$(BACKEND) uv run pytest -m integration

e2e: ## Playwright, desktop and mobile, against a fresh konboro_e2e DB and the API on 8001 (needs `make up`)
	$(FRONTEND) pnpm e2e

fidelity: ## Prototype vs app screenshots into frontend/e2e/fidelity/report.html (needs `make up`)
	$(FRONTEND) pnpm exec playwright test -c e2e/fidelity/fidelity.config.ts

screenshots: ## Rewrite the screenshot baselines in Playwright's Linux image, after an accepted change (needs `make up`, Docker)
	frontend/e2e/visual/update.sh

check-screenshots: ## Compare the screens against the baselines, in the same image (needs `make up`, Docker)
	SCREENSHOTS_CHECK=1 frontend/e2e/visual/update.sh

eval: ## Golden-set eval vs eval/baseline.json. Replay by default; EVAL_MODE=live, EVAL_RECORD=1 re-records, =missing records only new calls (needs `make up`)
	$(BACKEND) PYTHONPATH=.. uv run python -m eval.run

eval-baseline: ## Make this run's metrics the committed baseline, after an intended change (needs `make up`)
	$(BACKEND) PYTHONPATH=.. uv run python -m eval.run --write-baseline --allow-regression

gen-client: ## Regenerate the TS API client from FastAPI's OpenAPI (frontend/src/api/schema.ts)
	$(BACKEND) uv run python -m konboro.api.openapi ../frontend/src/api/openapi.json
	$(FRONTEND) pnpm run gen:client

check-client: gen-client ## Fail if the committed API client is stale (run `make gen-client` and commit)
	git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.ts

check: lint licenses secrets check-client test-unit test-int eval e2e check-screenshots ## Everything CI runs
