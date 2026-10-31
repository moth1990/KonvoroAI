# Playwright's Linux image (same version as @playwright/test) plus uv, to render screenshot baselines the way
# CI does. Used by `make screenshots` (e2e/visual/update.sh).
FROM mcr.microsoft.com/playwright:v1.64.1-noble
COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /bin/
RUN corepack enable
