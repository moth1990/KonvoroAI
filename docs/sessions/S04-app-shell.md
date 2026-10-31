# S04: App shell, login and home

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s04-app-shell` |
| **Depends on** | S03 |
| **Status** | done |
| **PR** | [#5](https://github.com/moth1990/KonvoroAI/pull/5) |

## Goal

A user can log in and land on a home screen that looks like the prototype, in both versions (classic, and `home_chat` behind its flag). Navigation works on desktop and mobile. The prototype-fidelity pipeline exists, and its first report has been reviewed.

## References

- Prototype:
  - 660–688 `vLogin`, 1596–1603 (submit).
  - 690–714 `shell` / `navItems`: rail, bottom tab bar under the breakpoint, pending-queue badge, quota meter.
  - 716–751 `vHome`; 1254–1284 `vHomeChat` and `homeSubmit`.
  - 623 `toast`; 637–644 `modal`.
  - CSS breakpoints 820 / 1000 / 1100 / 620 px, safe-area insets, reduced motion.
- Specs: 09 §5 (layout, breakpoint), §13 (accessibility and language); 13 §4.3 (`home_chat`); 01 §4.5 (quota banner at 80%, block at 100%).
- [dev-strategy.md §5](../dev-strategy.md#5-prototype-fidelity).

## Tasks

### Frontend
- [x] React Router (path routes): `/login`, `/home`, `/new`, `/review/:quoteId`, `/audit`, `/prices`, `/queue`, `/prefs`, `/build`. Placeholders for the screens that come later. An unknown path goes to `/home`, as the prototype's `route()` does. `/build` exists only when `chat_quote_builder` is on (13 §3.2).
- [x] Auth guard: no token → `/login`, keeping the target to return to after login. The 401 handler from S03 navigates to `/login` through the router.
- [x] Login (660–688, 1596–1603):
  - Brand panel, email and password.
  - Show/hide password (`data-testid="pw"`).
  - Hebrew validation messages, the same rules and copy as the prototype; a `role=alert` error.
  - Server errors show the envelope's Hebrew message.
  - "Forgot password" calls `POST /auth/password-reset` and shows a toast.
  - The prototype's demo hint and "prototype" tag are left out.
- [x] Shell (690–714):
  - Rail with `aria-label="ניווט"` and `aria-current="page"`.
  - Pending-queue badge.
  - Quota meter in the rail foot: "12 מתוך 50" and the plan name.
  - User email and logout.
  - Bottom tab bar under the **860 px** breakpoint, respecting safe areas.
- [x] Quota (01 §4.5), driven by the server's `state`:
  - `quota_near` (above 80%): amber meter and a top banner, "נותרו N הצעות החודש".
  - `quota_reached`: "new quote" is disabled everywhere, with the reason and a pointer to upgrading the plan. Existing quotes stay fully available.
  - An unlimited plan (`limit: null`) shows the count with no meter.
- [x] Home, classic (716–751):
  - The two primary actions.
  - Three stat tiles: quota, plus "—" with "אין עדיין נתונים" for coverage and "approved without correction".
  - Recent work from `GET /quotes`, with an empty state.
  - "Waiting for you" from `GET /home/summary`, with an empty state.
- [x] Home, chat (`home_chat`, 1253–1284):
  - Hero with the real weekday and the remaining quota, the prompt, and the attach link to `/new`.
  - Suggestion chips and the recent list.
  - Enter submits; Shift+Enter adds a new line.
  - The submit routes with keyword rules (`homeRoute`): audit, price list, and chat build when `chat_quote_builder` is on. Otherwise a toast points to a new quote from a drawing.
  - No mic button: voice is S27.
  - Real intent comes in S27.
- [x] Shared components:
  - `Toast`: `role=status`, auto-hides after 4.2 s, optional undo, one at a time, above the tab bar on mobile.
  - `Modal`: `role=dialog` with `aria-modal`, closes on Esc or a backdrop click, traps focus and returns it on close.
- [x] Icons: the prototype's `ic()` set as one `Icon` component.
- [x] `data-testid` names follow the prototype's `data-act` and ids.
- [x] Remove the S01 token placeholder page.

### Backend
- [x] `GET /quotes?limit=`: recent quotes, newest first (empty until S05).
- [x] `GET /home/summary`: the pending approval-queue count (`knowledge_candidates`), quotes with lines missing a price, and audits with omissions. Every count is tenant-scoped, and all of them are zero for now except the queue.
- [x] `make gen-client`.
- [x] `konboro.devtools.e2e` (seeds and serves the E2E API): fixed E2E tenants, each with its own login in the dev directory:
  - `home_chat` on and off.
  - Quota at 12/50, 43/50 (86%) and 50/50.

### Unit tests
- [x] Vitest:
  - Route guard and post-login return.
  - Quota-meter and banner states from the server state, including unlimited.
  - Toast timer.
  - `homeRoute` keyword rules.
  - Login validation.
  - Modal Esc, backdrop and focus return.

### Integration tests
- [x] `/home/summary` and `/quotes` are tenant-scoped (a tenant never sees another's quotes or queue count), and the route audit covers them.
- [x] The E2E seed is idempotent and produces the stated quota states.

### UI tests (Playwright, desktop + mobile, against the real API on the E2E database)
- [x] Login: valid credentials succeed, invalid ones show the error, the password toggle works, and "forgot password" shows the toast.
- [x] Navigation through every rail item on desktop, and every tab-bar item on mobile, with `aria-current`.
- [x] `home_chat` on and off render the two different homes (two E2E tenants).
- [x] At 86% the banner and the amber meter show; at 100% "new quote" is disabled and explains why.
- [x] Dark mode (`colorScheme: 'dark'`) renders the dark tokens on the shell.
- [x] Keyboard only: tab through login, rail and home, with a visible focus ring.
- [x] Logout returns to login, and a protected URL then redirects to login.
- [x] **Fidelity:** `frontend/e2e/fidelity/capture.ts` captures login, home (classic) and home (chat), from the prototype and from the app, on desktop and mobile, light and dark, into `report.html`. The user reviews it. Accepted screens become `toHaveScreenshot` baselines.

### CI and docs
- [x] CI: the E2E run gets Postgres, migrations, the E2E seed and the API. `make e2e` starts the API itself. Screenshot baselines are checked in Playwright's Linux image (`make check-screenshots`, and a CI step).
- [x] CLAUDE.md:
  - Remove the breakpoint inconsistency (860 everywhere).
  - Prototype map: the screens built so far.
  - Commands table: `make e2e` needs `make up`.
- [x] Roadmap: the S03 follow-up "Settings shows flags read-only" moves to S24, which builds the settings screen.

## Acceptance criteria

- [x] The user has reviewed the fidelity report for login, shell and home. Every deviation is fixed or logged.
- [x] Keyboard only: every control can be reached, with a visible focus ring.
- [x] E2E green on both projects, locally and in CI ([PR #5](https://github.com/moth1990/KonvoroAI/pull/5): backend and frontend jobs, including the screenshot check).

## Out of scope

- The upload flow (S05).
- Real chat intent (S27).
- Voice (S27).
- The settings screen and its read-only flags (S24).

## Open questions

- The mobile breakpoint is 860 px in 09 §5.2 and 820 px in the prototype. Which one? Answered, see decisions.
- The "91% approved without correction" stat tile: hide it until there is real data, or show "—"? Answered, see decisions.

## Outcome

- **Done:** Path routing with an auth guard that returns you where you were going, and a router-driven 401 handler. Login, the shell (rail, phone tab bar at 860px, queue badge, quota meter, logout) and the quota banner and block of 01 §4.5. Classic and chat home on real data from the new `GET /quotes` and `GET /home/summary` (permission `quotes.read`). `Toast`, `Modal`, the prototype's icons, and its component CSS ported to `src/theme/app.css`. Fixed E2E tenants and API (`konboro.devtools.e2e`), Playwright against the real API in CI, the fidelity report (`make fidelity`), and screenshot baselines for the accepted screens, rendered and checked in Playwright's Linux image (`make screenshots`, `make check-screenshots`).
- **Decisions made:**
  - Branching (2026-10-31, user): S03's PR #4 is merged first, and S04 branches from the updated `main`.
  - Mobile breakpoint, spec vs prototype (2026-10-31, user): **860 px (09 §5.2) everywhere**, including login and the shell. An 11-inch iPad in portrait (834 px) gets the tab bar. The prototype file stays as it is, and the CLAUDE.md inconsistency is closed.
  - Quota warning, spec vs prototype (2026-10-31, user): **spec 01 §4.5 wins.**
    - The server's `state` drives the UI: `quota_near` is strictly above 80%, as S03 built it, where the prototype turns amber at 80% or more.
    - Above 80%: a top banner, "נותרו N הצעות החודש", styled from the prototype's warn tokens.
    - At 100%: "new quote" is blocked, with the reason and a pointer to upgrading.
  - Stat tiles without data (2026-10-31, user): all three tiles stay so the layout matches the prototype. Coverage and "approved without correction" read "—", with "אין עדיין נתונים" and an empty meter.
  - E2E data: flags are read-only through the API (S03 decision), so the tests don't toggle `home_chat` through the API. They log in as fixed E2E tenants that `konboro.devtools.e2e` seeds into a fresh `konboro_e2e` database on every run, one tenant per state. That module also serves the API (port 8001) for Vite on 5181, so E2E never touches the dev database or a running `make dev`.
  - Prototype flag keys `chat_builder` and `voice` become `chat_quote_builder` and `voice_input` (spec 13 wins, CLAUDE.md).
  - Fidelity report (2026-10-31, user): **accepted as is**, with these deliberate differences:
    - Left out: the login demo hint, the "prototype" tags, the mic button (voice is S27), and the chat-home suggestion about the NURSERY demo quote.
    - The app's link-buttons are not underlined (the prototype's `a.btn` has no text-decoration rule), and the app has no 8px page margin (the prototype has no body reset).
    - The password placeholder no longer runs under the "הצג" button (BUG-003).
    - The phone tab bar shows the approval-queue count on "תור"; the prototype shows it in the rail only.
    - With `chat_quote_builder` off, the chat home never mentions chat building (13 §3.2): its toast points to attaching a drawing, where the prototype says to turn the feature on in settings.
  - Screens use the prototype's CSS classes (`src/theme/app.css`); MUI stays for theming and behaviour. This keeps every rule comparable with the prototype.
  - "Missing prices" counts live lines of a quote's current draft version with no unit price; a sent version is final and never counts. Pricing (S22) may narrow this. Omissions are `missing_in_quote` differences of ready audits that are not rejected; the amount at risk is their priced sum, shown floored to whole shekels without going through a float.
  - Logout lives in the rail, which is hidden on phones; until the settings screen (S24), the settings placeholder offers it too.
  - Screenshot baselines are compared only inside Playwright's pinned Linux image, locally and in CI, so fonts and rasterization never differ between baseline and check. Clock-dependent text (weekday, "today, 18:52", renewal date) is masked.
- **Bugs logged:** BUG-002 (P2, body text 16px instead of 14px, fixed), BUG-003 (P3, prototype's password placeholder under the button, fixed in the app).
- **Follow-ups:**
  - S05: the "new quote" screen replaces the `/new` placeholder and keeps the 100% block; wire quota reservations.
  - S09: the review screen replaces `/review/:quoteId`; recent-work rows already link there.
  - S24: settings with read-only flags and logout (then drop the placeholder's logout); the approval queue behind the badge.
  - S27: real intent for the chat home, the mic button, and the `/build` screen.
