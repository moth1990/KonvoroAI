# S07: Gate 0, foundations

| | |
| --- | --- |
| **Track** | G |
| **Branch** | `s07-gate-0` |
| **Depends on** | S06 |
| **Status** | in progress |
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
- [x] On a fresh clone: `make up && make seed && make check`.
- [x] Full Playwright suite on `desktop` and `mobile`, in light and dark.
- [x] Fidelity report for login, shell, home and new-quote. Compare it with the accepted baselines.
- [x] `make eval` in replay. Record the numbers. (No live run: the stubs make no model calls, so S08 records the first cassettes.)
- [x] Security spot checks:
  - the RLS suite;
  - the route-actor audit;
  - no secrets in the repo: a new `make secrets` target (pinned gitleaks Docker image, full history), also in `make check` and CI;
  - the license gate.
- [x] Manual smoke as a user: log in, upload each golden PDF, cancel one, and check the quota meter.

### Fix
- [ ] All open P0 and P1 bugs. P2 bugs that fit in the session.
  - [x] BUG-005 (P2): intermittent local E2E failures. Reproduce with back-to-back runs and after `make test-int && make eval`, find the shared state, fix it. Root cause: BUG-010 (P0, PDFium used from two threads at once), fixed with a process-wide lock.
- [x] Items S05 left for this gate, each logged in `bugs.md` first:
  - [x] A drawing whose stage-1 message was never sent (SQS failed after the commit) stays `uploaded` with its quota reserved. It should be re-queued. (BUG-006, and BUG-007 found on the way.)
  - [x] Per-tenant pipeline concurrency limit (00 §4.3): logged and scheduled for S29, not fixed here.
  - [x] Stage summaries for stages 2–7: only once those stages are real, so this moves to their sessions.
- [x] Each fix starts with a failing test.

### Docs
- [ ] CLAUDE.md, dev-strategy and the roadmap match reality (commands, layout, statuses).
- [x] Resolve and fix any spec inconsistency touched in phase 0: rewrite the 00 §14 phase table to follow README §7, and remove the item from CLAUDE.md.
- [x] Update README §6 readiness checkboxes for the items phase 0 completed.

### Close
- [ ] Merge, tag `phase-0`, and set the S01–S07 status to `done`.
- [x] Prepare the phase 1 session files S08 and S09 from the template, so the next session starts immediately.

## Acceptance criteria (phase 0 exit)

- [ ] Eval runs automatically on the golden set, in CI and through `make eval`.
- [ ] The skeleton E2E (login → upload → stub pipeline → done) is green on both projects.
- [ ] The cross-tenant RLS tests are green, and so is the test that fails on a tenant table without RLS.
- [ ] No open P0 or P1 bugs.
- [ ] External blocker B1 (golden set at 10 drawings) has its status recorded. Missing drawings are a known gap, not a failed gate.

## Outcome

- **Done:**
- **Decisions made:**
  - Eval at this gate (2026-10-31, user): replay only. A live run with stub stages records nothing; the first cassettes come with S08.
  - Secret scan (user): a `make secrets` target running the pinned gitleaks Docker image over the full git history, added to `make check` and CI.
  - S05 gaps (user): fix the re-queue of drawings stuck at `uploaded` in this session. The per-tenant concurrency limit (00 §4.3) is logged and scheduled for S29, when the workers scale out.
  - Finding stuck uploads across tenants (user): a `SECURITY DEFINER` function owned by the owner role returns only `(tenant_id, drawing_id, trace_id)` for stage-1 runs that were never claimed and are older than a threshold. Only `konboro_app` may execute it. The worker calls it on a timer, re-checks each row inside `tenant_session`, and only then re-sends. The alternative, re-queueing from the progress poll, was rejected because a drawing nobody reopens would stay stuck.
    - As built (Claude, during the build): the function is owned by a dedicated `konboro_sweeper` role (NOLOGIN, no BYPASSRLS, column-level SELECT, its own read-only policies) rather than the table owner, so the rule "the app never runs as the owner" holds. It covers every stage, not only stage 1: a stage's hand-off is sent after its commit too, so a crash in between loses it the same way. It also returns `stage`.
  - Duplicate claims (user): fix here. `_claim` drops a copy of a message whose stage is still `running`; a redelivery after a worker crash still runs.
    - As built (Claude): the test is the queue's receive count, not a time window. The crashed worker's own message comes back with a count of 2 or more, while a copy (an SQS duplicate, or a re-send) arrives with a count of 1. A window equal to the visibility timeout would have dropped the real redelivery, which arrives right at that boundary.
  - Phase order (user): README §7 wins. 00 §14 is rewritten to match, and the item leaves CLAUDE.md's inconsistency list.
- **Manual smoke** (`make dev` in the browser pane, demo tenant; the new `dev-backend` entry in `.claude/launch.json` runs the API and the worker):
  - Logged in as `demo@konboro.local`. Quota at the start: 14 of 50.
  - 26-993, 6199-2-50, NEVIS-1 and NURSERY-1 each ran all 7 stages to the done step, with real thumbnails. The meter went 15, 16, 17, 18.
  - BOM-HW-1.jpg was cancelled during stage 1: "הפענוח בוטל. המקום במכסה שוחרר", back to picking with the file kept, the meter stayed at 18.
  - DB: the four finished drawings have `reserve,confirm`, the cancelled one `reserve,release`; `quota_usage` 18 used, 0 reserved. No server errors.
  - The built-in browser has no file chooser, so each file was handed to `#file-in` from a script; everything after that went through the UI.
- **Eval / metrics:** replay, commit `022f73e` on a fresh clone, no change against the baseline:
  - Stage 1: page kind 0% (0/24), route 58.3% (14/24), missed process pages 0 of 14, `input_kind` 20% (1/5), panel count 80% (4/5).
  - Stage 4: component recall 0% (0/147), unit recall 0% (0/411).
  - Audit: n/a. Backtest: 0 of 3 within ±5%.
- **Bugs fixed:**
  - BUG-010 (P0, found here): PDFium is not thread-safe, and the upload check and the stage-1 renderer called it from different threads of one process. Two uploads at the same moment hung both requests; a standalone probe segfaulted. Every PDFium call now goes through `konboro/services/pdf.py`'s lock, and a test fails if anything else imports pypdfium2. This was BUG-005's cause. How it was found: 20 E2E runs with the traces kept; every failure was a pair of `POST /drawings` started ~80 ms apart that never answered. Vite reloads and machine load were ruled out on the way.
  - BUG-005 (P2): `make e2e` 20 of 20 green after the fix, against 16 of 20 before.
  - BUG-006 (P1): stage messages that never arrive are sent again.
  - BUG-007 (P1): a copy of a running stage's message is dropped.
- **Known gaps:**
- **Follow-ups:**
  - S10 (tiling renders far more than thumbnails): the PDFium lock serializes all rendering in a process. If that becomes the bottleneck, render in a process pool instead of threads. Added to the roadmap backlog.
