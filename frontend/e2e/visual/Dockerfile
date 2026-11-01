# Playwright's Linux image (same version as @playwright/test) plus uv, to render screenshot baselines the way
# CI does. Used by `make screenshots` (e2e/visual/update.sh).
FROM mcr.microsoft.com/playwright:v1.64.1-noble
COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /bin/
# Node 26 no longer ships corepack, and the amd64 build of this tag was re-published with Node 26 (BUG-024).
# --force: the image has its own yarn, which corepack's shim replaces anyway.
RUN command -v corepack >/dev/null || npm install -g --force corepack@0.36.0; corepack enable
