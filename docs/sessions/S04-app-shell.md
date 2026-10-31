# S04: App shell, login and home

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s04-app-shell` |
| **Depends on** | S03 |
| **Status** | todo |
| **PR** | |

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
- [ ] Router (React Router) with the prototype's routes: `/home`, `/new`, `/review/:quoteId`, `/audit`, `/prices`, `/queue`, `/prefs`, `/build`. Placeholders for the screens that come later.
- [ ] Auth guard and redirect to login.
- [ ] Login screen: brand panel, email and password, show/hide password, Hebrew validation messages, `role=alert` error, and a "forgot password" toast.
- [ ] Shell:
  - Rail with `aria-label="ניווט"` and `aria-current`.
  - Pending-queue badge.
  - Quota meter, warning at ≥80%.
  - Logout.
  - Bottom tab bar on mobile.
- [ ] Home, classic: the two primary actions, 3 stat tiles, recent work, and "waiting for you". Data comes from the API: `GET /quotes?recent`, returning an empty state for now, plus `/me`.
- [ ] Home, chat (flag `home_chat`): hero prompt, suggestion chips, attach link, recent quotes. In this session the submit routes with simple keyword rules, as in the prototype. Real intent comes in S27.
- [ ] Shared components: `Toast` (`role=status`, auto-hide 4.2 s, optional undo) and `Modal` (`role=dialog`, closes on Esc or a backdrop click, focus trap).
- [ ] `data-testid` names follow the prototype's `data-act` and ids.

### Backend
- [ ] `GET /quotes` (list, empty for now) and `GET /home/summary` (counts for "waiting for you"). Minimal, but with real tenant scoping.

### Unit tests
- [ ] Vitest: route guard, quota-meter thresholds, toast timer.

### Integration tests
- [ ] `/home/summary` and `/quotes` are tenant-scoped.

### UI tests (Playwright)
- [ ] Login: valid credentials succeed, invalid ones show the error, the password toggle works.
- [ ] Navigation through every rail item, on desktop and mobile (tab bar).
- [ ] `home_chat` on and off render the two different homes. Toggle the flag through the API in the test setup.
- [ ] Quota at 85% shows the warning; at 100% the "new quote" action is disabled.
- [ ] Dark mode (`colorScheme: 'dark'`) renders the dark tokens.
- [ ] **Fidelity:** `frontend/e2e/fidelity/capture.ts` captures login and home from the prototype and from the app (desktop and mobile, light and dark) into `report.html`. The user reviews it. Accepted screens become `toHaveScreenshot` baselines.

## Acceptance criteria

- [ ] The user has reviewed the fidelity report for login, shell and home. Every deviation is fixed or logged.
- [ ] Keyboard only: every control can be reached, with a visible focus ring.
- [ ] E2E green on both projects.

## Out of scope

- The upload flow (S05).
- Real chat intent (S27).
- Voice (S27).

## Open questions

- The mobile breakpoint is 860 px in 09 §5.2 and 820 px in the prototype. Which one?
- The "91% approved without correction" stat tile: hide it until there is real data, or show "—"?

## Outcome

- **Done:**
- **Decisions made:**
- **Bugs logged:**
- **Follow-ups:**
