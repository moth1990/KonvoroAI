# Konboro developer commands. `make check` runs everything CI runs (CLAUDE.md, Commands).
# Backend: uv (Python 3.12). Frontend: pnpm (Node 22, see .nvmrc).

BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help install up down migrate seed dev lint licenses test-unit test-int e2e eval gen-client check-client check

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

seed: migrate ## Demo data: tenant "לוחות דמו", price list from the prototype. Safe to rerun
	$(BACKEND) uv run python -m konboro.db.seed

dev: ## Run the API (port 8000) and the web app (port 5180). The worker joins in S05
	@trap 'kill 0' EXIT; \
	(cd backend && uv run uvicorn --factory konboro.api.app:create_app --reload --port $${KONBORO_API_PORT:-8000}) & \
	cd frontend && pnpm dev

lint: ## Lint, format check and types, backend and frontend
	$(BACKEND) uv run ruff check .
	$(BACKEND) uv run ruff format --check .
	$(BACKEND) uv run mypy
	$(FRONTEND) pnpm lint
	$(FRONTEND) pnpm typecheck

licenses: ## Fail on GPL or AGPL dependencies (specs/12-tech-stack.md §8)
	$(BACKEND) uv run python -m konboro.licenses
	$(FRONTEND) pnpm run license-check

test-unit: ## Backend unit tests and frontend Vitest
	$(BACKEND) uv run pytest -m "not integration"
	$(FRONTEND) pnpm test

test-int: ## Backend integration tests against the local services (needs `make up`)
	$(BACKEND) uv run pytest -m integration

e2e: ## Playwright, desktop and mobile projects
	$(FRONTEND) pnpm e2e

eval: ## Golden-set evaluation (arrives in S06)
	@echo "eval: not built yet, see docs/sessions/S06-golden-eval.md"

gen-client: ## Regenerate the TS API client from FastAPI's OpenAPI (frontend/src/api/schema.ts)
	$(BACKEND) uv run python -m konboro.api.openapi ../frontend/src/api/openapi.json
	$(FRONTEND) pnpm run gen:client

check-client: gen-client ## Fail if the committed API client is stale (run `make gen-client` and commit)
	git diff --exit-code -- frontend/src/api/openapi.json frontend/src/api/schema.ts

check: lint licenses check-client test-unit test-int e2e ## Everything CI runs
