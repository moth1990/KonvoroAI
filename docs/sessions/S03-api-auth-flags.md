# S03: API, auth, flags and quota

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s03-api-auth-flags` |
| **Depends on** | S02 |
| **Status** | done |
| **PR** | [#4](https://github.com/moth1990/KonvoroAI/pull/4) |

## Goal

There is a running FastAPI app that:
- authenticates a user;
- sets tenant context on every request;
- checks the `owner` permission;
- serves the evaluated feature flags and the quota state.

The frontend gets a generated, typed client for it.

## References

- Specs:
  - 00 §14.1: one user per tenant, but permission checks are in code.
  - 01 §4.5: quota reserve, confirm and release, the 80% warning and 100% block.
  - 13 §2–3: flag model, evaluation order, server enforcement.
  - 12 §7: Cognito with `tenant_id` in the token.
- Prototype: lines 384–388 (`konboro:authed`, user, flags), 560–572 (`FLAGS` list, `requires`), 1596–1603 (login submit).

## Tasks

### Backend
- [x] `konboro/api/app.py`: app factory, settings (pydantic-settings, `konboro/settings.py`), CORS for the Vite origin, error envelope with Hebrew `message` and English `code` (`api/errors.py`), `/health`.
- [x] Auth (`services/auth.py`):
  - A dev JWT issuer and verifier with the same claims Cognito will give: `sub`, `email`, `custom:tenant_id`, `custom:role`.
  - `POST /auth/login` (dev only, behind a setting) and `POST /auth/logout`.
  - Verification sits behind an interface, so S29 can swap in Cognito JWKS.
- [x] Dependency `current_actor` (`api/deps.py`) does three things:
  - reads the token;
  - opens `tenant_session`;
  - checks `require(permission)`. Every permission maps to `owner` in v1.0.

  **Every router uses it.** A test enumerates the routes to prove it.
- [x] `GET /me`: user, tenant, plan, evaluated flags, quota summary.
- [x] `domain/flags.py`: evaluation order tenant override, then plan, then global, then default, with `depends_on` (e.g. `voice_input` requires `chat_quote_builder`). Spec 13 keys. A short in-process TTL cache (`services/flags.py`). A `require_flag(key)` dependency.
- [x] Quota: pure arithmetic in `domain/quota.py`, DB work in `services/quota.py`:
  - `reserve`, `confirm` and `release`, atomic (a conditional update) and logged to `quota_events`.
  - Expiry of reservations older than 24 h.
  - `GET /quota`.
- [x] Settings endpoints for later screens: `GET/PATCH /settings` for tenant prefs only. Flags are read-only to the owner (see decisions).
- [x] Migration `0002`: `quota_events.reservation_id`, a composite FK to the reserve event. Update `docs/db-schema.md` §4.
- [x] `make gen-client`: export the OpenAPI spec (`python -m konboro.api.openapi`), then run `openapi-typescript` into `frontend/src/api/schema.ts`. A thin fetch wrapper (openapi-fetch) with the auth header.

### Frontend
- [x] `src/api/client.ts` + TanStack Query provider. Store the token in memory plus `sessionStorage`. On a 401, go to login.

### Unit tests
- [x] Flag evaluation: every precedence combination, `depends_on`, unknown key (`tests/unit/test_flags.py`).
- [x] Quota arithmetic: 80% warning, 100% block, release (`tests/unit/test_quota.py`).
- [x] Vitest: token storage, auth header, 401 handling, error envelope, retry policy (`src/api/client.test.ts`).

### Integration tests
- [x] Login → `/me` returns the tenant's flags and quota (`test_api_auth.py`, `test_api_account.py`).
- [x] A token for tenant A cannot read B's data on any endpoint (`test_api_isolation.py`, plus the forged-token cases).
- [x] Route audit: every route except `/health`, `/auth/login` and `/auth/password-reset` requires an actor (`test_api_routes.py`).
- [x] Quota: 20 concurrent reserves against a limit of 10 give exactly 10 successes (`test_quota.py`).
- [x] A flag turned off returns 404 from a flag-gated test route, and turning it on makes the route work.
- [x] CI fails when the generated client is stale (`make check-client`, and one CI step each for the backend and frontend jobs). Checked by hand: a changed field description makes it exit non-zero.

## Acceptance criteria

- [x] All of the above tests are green in CI ([PR #4](https://github.com/moth1990/KonvoroAI/pull/4): backend and frontend jobs).
- [x] `docs/db-schema.md` and CLAUDE.md mention the actor and permission rule.

## Out of scope

- Cognito (S29).
- Password reset. The prototype only shows a toast; keep it as a stub endpoint returning 202.

## Open questions

- Do dev login credentials come from the seed? Answered: yes, see decisions.

## Outcome

- **Done:** A running FastAPI app (`make dev`, port 8000). Dev login, the `current_actor` and permission dependency on every route, `/me`, `/quota` and `/settings`. Flag evaluation with dependencies and a cache, and `require_flag`. Atomic quota reservations with 24 h expiry (migration 0002). OpenAPI → `schema.ts`, with a freshness gate in `make check` and CI. On the frontend: the typed client, token storage and the TanStack Query provider. Checked live: the demo owner logs in from the Vite origin and `/me` returns "12 / 50" and all five flags. A bad token clears the token and routes to login.
- **Decisions made:**
  - Dev login (2026-10-31, user): the email must match a seeded user, and the password is one shared value from `.env` (`KONBORO_DEV_PASSWORD`, with an example in `.env.example`). No password column. Cognito replaces this in S29.
  - Flag edits, spec vs prototype (2026-10-31, user): **spec 13 wins.** The owner cannot change flags. They resolve from tenant overrides, then plan, then global, then default, all set by us (seed or admin). `/me` returns them, and S04's Settings shows them read-only. `PATCH /settings` covers tenant prefs only.
  - Reservation tracking (2026-10-31, user): add `quota_events.reservation_id`. `reserve` returns its event id, and `confirm` and `release` reference it. Reserves older than 24 h with no closing event are released lazily at the start of `reserve` and `GET /quota`, so no scheduler is needed yet.
  - A disabled flag returns **404** on a gated route, not 403. 13 §3.2 says it must behave as if the feature does not exist.
  - **The dev "user pool" is a setting, not a cross-tenant query.** RLS stops `konboro_app` from finding an email in another tenant, and opening a hole for login would weaken isolation. So `KONBORO_DEV_USERS` maps `email=tenant_id`, the job Cognito's `custom:tenant_id` attribute does later, and login then looks the user up inside that tenant. The default is the demo owner from the seed.
  - **The DB role counts, not the token's.** `current_actor` loads the user in the token's tenant (by `auth_subject`, or by id while there is none), and the permission check uses `users.role`. A token for a user who isn't in its tenant gets a 401, and a suspended tenant gets a 403 `tenant_suspended`.
  - **The tenant transaction ends with the route function** (`Depends(..., scope="function")`), so it commits before the response goes out and a failed commit can't look like success.
  - `/auth/password-reset` is public, like login: the user has no token yet. It always answers 202, so it never reveals whether an email exists.
  - Logout is stateless until Cognito: it confirms the token and returns 204, and the client drops the token.
  - `PATCH /settings` covers brand preferences, attribute defaults, enclosure includes, the two margin floors and `stale_days`. `labor` and `rounding` are read-only here until the pricing sessions. Attribute defaults for `current_a` and `poles` are always refused (05 §4.4). For other attributes, the family's schema decides, once the catalog sessions add schemas.
  - Decimals travel as strings in both directions. A number for a margin is a 422.
  - `GET /quota` (and `/me`) may write: it releases expired reservations first, so the numbers it returns are current.
  - Settings read the repo-root `.env`. The OpenAPI export and the tests ignore it, so they are hermetic.
  - Dev JWTs need a key of at least 32 bytes (RFC 7518 §3.2), and dev login cannot be on when `KONBORO_ENV=production`.
- **Bugs logged:** none.
- **Follow-ups:**
  - S04: the Settings screen shows flags read-only (this deviates from the prototype's toggles, per the decision above), and the login screen uses `login()` from `src/api/client.ts`. Replace the default 401 handler (`#login`) with the shell's router.
  - S05: wire `services.quota.reserve` to "new quote", `confirm` to a successful stage 1, and `release` to rejected, failed or cancelled uploads. Map `QuotaReachedError` to a 403 `quota_reached` (the message is already in `api/errors.py`).
  - S29: a Cognito JWKS `TokenVerifier`, `KONBORO_DEV_LOGIN_ENABLED=false`, and `auth_subject` filled from Cognito's `sub`.
