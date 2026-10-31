# S07: Gate 0, foundations

| | |
| --- | --- |
| **Track** | G |
| **Branch** | `s07-gate-0` |
| **Depends on** | S06 |
| **Status** | todo |
| **PR** | |

## Goal

Close phase 0 only after confirming that the foundations hold:
- every test layer runs green;
- the bug list contains no P0 or P1;
- the docs describe the real repo.

Phase 1 starts from a tagged, stable `phase-0`.

## References

- [dev-strategy.md §7](../dev-strategy.md#7-definition-of-done-bugs-gates): gate procedure.
- [roadmap.md, phase 0 exit](../roadmap.md#phase-0-foundations-and-thin-end-to-end-skeleton).
- [bugs.md](../bugs.md).

## Tasks

### Verify
- [ ] On a fresh clone: `make up && make seed && make check`.
- [ ] Full Playwright suite on `desktop` and `mobile`, in light and dark.
- [ ] Fidelity report for login, shell, home and new-quote. Compare it with the accepted baselines.
- [ ] `make eval` in replay, plus one live run to refresh the cassettes after the stubs. Record the numbers.
- [ ] Security spot checks:
  - the RLS suite;
  - the route-actor audit;
  - no secrets in the repo (`gitleaks` or similar);
  - the license gate.
- [ ] Manual smoke as a user: log in, upload each golden PDF, cancel one, and check the quota meter.

### Fix
- [ ] All open P0 and P1 bugs. P2 bugs that fit in the session.
- [ ] Each fix starts with a failing test.

### Docs
- [ ] CLAUDE.md, dev-strategy and the roadmap match reality (commands, layout, statuses).
- [ ] Resolve and fix any spec inconsistency touched in phase 0.
- [ ] Update README §6 readiness checkboxes for the items phase 0 completed.

### Close
- [ ] Merge, tag `phase-0`, and set the S01–S07 status to `done`.
- [ ] Prepare the phase 1 session files S08 and S09 from the template, so the next session starts immediately.

## Acceptance criteria (phase 0 exit)

- [ ] Eval runs automatically on the golden set, in CI and through `make eval`.
- [ ] The skeleton E2E (login → upload → stub pipeline → done) is green on both projects.
- [ ] The cross-tenant RLS tests are green, and so is the test that fails on a tenant table without RLS.
- [ ] No open P0 or P1 bugs.
- [ ] External blocker B1 (golden set at 10 drawings) has its status recorded. Missing drawings are a known gap, not a failed gate.

## Outcome

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs fixed:**
- **Known gaps:**
- **Follow-ups:**
