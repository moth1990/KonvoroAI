#!/usr/bin/env bash
# Regenerates (or, with SCREENSHOTS_CHECK=1, checks) the Linux screenshot baselines (e2e/visual.spec.ts-snapshots/) inside Playwright's Linux image.
# Needs `make up`: the container reaches the local Postgres, S3 and SQS through host.docker.internal.
# The repo is mounted; node_modules and .venv get container-only volumes, so the host's installs are untouched.
set -euo pipefail
cd "$(dirname "$0")/../../.."
image=konboro-playwright:1.64.1
# SCREENSHOTS_CHECK=1 compares against the committed baselines instead of rewriting them.
if [[ -n "${SCREENSHOTS_CHECK:-}" ]]; then mode=--update-snapshots=none; else mode=--update-snapshots; fi
# amd64, like the GitHub runners: font rasterization is then the same as in CI.
docker build -q --platform linux/amd64 -t "$image" frontend/e2e/visual >/dev/null
docker run --rm --platform linux/amd64 \
  --add-host=host.docker.internal:host-gateway \
  -e KONBORO_MIGRATION_DSN="postgresql+psycopg://konboro:konboro@host.docker.internal:${KONBORO_PG_PORT:-5433}/konboro" \
  -e KONBORO_S3_ENDPOINT="http://host.docker.internal:${KONBORO_S3_PORT:-9000}" \
  -e KONBORO_SQS_ENDPOINT="http://host.docker.internal:${KONBORO_SQS_PORT:-9324}" \
  -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
  -e KONBORO_VISUAL=1 \
  -e npm_config_store_dir=/work/frontend/node_modules/.pnpm-store \
  -e CI="${CI:-}" \
  -v "$PWD":/work \
  -v /work/frontend/node_modules \
  -v /work/backend/.venv \
  -w /work \
  "$image" bash -c '
    set -e
    (cd backend && uv sync --frozen -q)
    cd frontend && pnpm install --frozen-lockfile --silent
    pnpm exec playwright test e2e/visual.spec.ts "$@"
  ' _ "$mode" "$@"
