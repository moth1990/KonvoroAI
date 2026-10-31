# Konboro developer commands. `make check` runs everything CI runs (CLAUDE.md, Commands).
# Backend: uv (Python 3.12). Frontend: pnpm (Node 22, see .nvmrc).

BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help install up down dev lint licenses test-unit test-int e2e eval gen-client check

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

dev: ## Run the web app (the API and worker join in S03 and S05)
	$(FRONTEND) pnpm dev

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

gen-client: ## Regenerate the TS API client from OpenAPI (arrives in S03)
	@echo "gen-client: not built yet, see docs/sessions/S03-api-auth-flags.md"

check: lint licenses test-unit test-int e2e ## Everything CI runs
