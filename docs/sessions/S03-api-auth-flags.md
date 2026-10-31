# S03: API, auth, flags and quota

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s03-api-auth-flags` |
| **Depends on** | S02 |
| **Status** | todo |
| **PR** | |

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
- [ ] `konboro/api/app.py`: app factory, settings (pydantic-settings), CORS for the Vite origin, error envelope with Hebrew `message` and English `code`, `/health`.
- [ ] Auth (`services/auth.py`):
  - A dev JWT issuer and verifier with the same claims Cognito will give: `sub`, `email`, `custom:tenant_id`, `custom:role`.
  - `POST /auth/login` (dev only, behind a setting) and `POST /auth/logout`.
  - Verification sits behind an interface, so S29 can swap in Cognito JWKS.
- [ ] Dependency `current_actor` does three things:
  - reads the token;
  - opens `tenant_session`;
  - checks `require(permission)`. Every permission maps to `owner` in v1.0.

  **Every router uses it.** A test enumerates the routes to prove it.
- [ ] `GET /me`: user, tenant, plan, evaluated flags, quota summary.
- [ ] `domain/flags.py`: evaluation order tenant override, then plan, then global, then default, with `depends_on` (e.g. `voice_input` requires `chat_quote_builder`). Use spec 13 keys. Cache in-process with a short TTL. Add a `require_flag(key)` dependency.
- [ ] `domain/quota.py`:
  - `reserve`, `confirm` and `release`, atomic (`SELECT … FOR UPDATE` or a conditional update) and logged to `quota_events`.
  - Expiry of reservations older than 24 h.
  - `GET /quota`.
- [ ] Settings endpoints for later screens: `GET/PATCH /settings` (tenant prefs, flag overrides the owner may change).
- [ ] `make gen-client`: export the OpenAPI spec, then run `openapi-typescript` into `frontend/src/api/schema.ts`. Add a thin fetch wrapper with the auth header.

### Frontend
- [ ] `src/api/client.ts` + TanStack Query provider. Store the token in memory plus `sessionStorage`. On a 401, go to login.

### Unit tests
- [ ] Flag evaluation: every precedence combination, `depends_on`, unknown key.
- [ ] Quota arithmetic: 80% warning, 100% block, release.

### Integration tests
- [ ] Login → `/me` returns the tenant's flags and quota.
- [ ] A token for tenant A cannot read B's data on any endpoint.
- [ ] Route audit: every route except `/health` and `/auth/login` requires an actor.
- [ ] Quota: 20 concurrent reserves against a limit of 10 give exactly 10 successes.
- [ ] A flag turned off returns 404/403 from a flag-gated test route, and turning it on makes the route work.
- [ ] CI fails when the generated client is stale.

## Acceptance criteria

- [ ] All of the above tests are green in CI.
- [ ] `docs/db-schema.md` and CLAUDE.md mention the actor and permission rule.

## Out of scope

- Cognito (S29).
- Password reset. The prototype only shows a toast; keep it as a stub endpoint returning 202.

## Open questions

- Do dev login credentials come from the seed? Default: yes, with values in `.env.example`.

## Outcome

- **Done:**
- **Decisions made:**
- **Bugs logged:**
- **Follow-ups:**
