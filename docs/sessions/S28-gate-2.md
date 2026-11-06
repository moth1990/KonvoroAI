# S28: Gate 2, full quotes (v1.0)

| | |
| --- | --- |
| **Track** | G |
| **Branch** | `s28-gate-2` |
| **Depends on** | S27b |
| **Status** | in progress |
| **PR** | (link) |

## Goal

Close phase 2 only after confirming that what it built holds:
- stages 1–7, the price list, onboarding, the approval queue, the chat and the flagged v1.0 features pass a **live** golden eval;
- a new factory produces a quote on its first day;
- "rows that need no edit" is measured on the golden set, against 00 §10.2's 85% for phase 2;
- every prototype flow is covered by E2E, green on both projects;
- the bug list has no P0 or P1.

Phase 3 (cloud and pilot readiness) starts from a tagged, stable `phase-2`.

## References

- [dev-strategy.md §7](../dev-strategy.md#7-definition-of-done-bugs-gates): gate procedure. §8: phase 2 exit criteria.
- [roadmap.md, phase 2 exit](../roadmap.md#phase-2-full-quotes-v10): a new tenant produces a quote on day one; ≥85% of golden rows need no edit; every prototype flow is covered by E2E.
- Specs: 00 §10.2 (the overall rows "שורות שאושרו בלי תיקון", 70% → 95%, and "שורות ירוקות שגויות" ≤ 1%), 00 §14 (phase 2: 85%); 10 §2, §11 (the first quote with an empty price list, ≤ one working day from sign-up); 13 §3 rules 5–6 (a flag is removed in the end; the eval runs both states of a flag that moves the pipeline); each stage's §10 for the stage metrics.
- Golden: all seven drawings (25.26.100, 26-993, 6199-2-50, BOM-HW-1, MINHAROT-1, NEVIS-1, NURSERY-1); the audit and the backtest on the four with actual quotes; the chat, builder and home sets.
- Prototype: every screen in CLAUDE.md's map, and every `data-act` in the click handler (lines 1446–1559).
- [bugs.md](../bugs.md): no P0 open. P1 open: BUG-051, BUG-053. P2 open: BUG-086, BUG-082, BUG-074, BUG-054, BUG-055, BUG-057, BUG-046, BUG-038, BUG-036, BUG-035, BUG-008 (S29).
- [S17](S17-gate-1.md), the previous gate.
- Items earlier sessions left for this gate:
  - **PR #29 never reached `main`.** [moth1990/KonvoroAI#29](https://github.com/moth1990/KonvoroAI/pull/29) (BUG-051, 053, 054, 055, 057, MINHAROT-1's reading) was merged into `fix-minharot-golden` on 2026-11-04, after that branch had landed in `main` through #27. Its merge commit `0a3bb3c` is not in `main`; a trial merge conflicts in `association/merge.py`, `test_association.py`, `eval/baseline.json`, the bug log and the roadmap.
  - Remove `price_list` (S18 decision 5, S19 decision 5: due here at the latest).
  - The backtest's unpriced lines, checked again (S22).
  - The chat set grown to about 200 with an estimator's phrasing (S25 decision 4).
  - The backlog: every item scheduled into a session or dropped (roadmap, "Backlog").

## Tasks

### Verify
- [ ] `make up && make seed && make check` in the working tree.
- [ ] Full Playwright suite on `desktop` and `mobile`; screenshot baselines (`make check-screenshots`).
- [ ] Fidelity report for every built screen (`make fidelity`), for the user's review.
- [ ] `make eval` in replay, then `EVAL_CATALOG_LINES=1 make eval` (13 §3 rule 6), then a live run (`EVAL_MODE=live`, capped). All under Outcome.
- [ ] Security spot checks (inside `make check`): the RLS suite, the route-actor audit, `make secrets`, the license gate, no price or cost to a model (chat, builder, home, `catalog_disambiguation`, `validator_review`).
- [ ] The prototype-flow matrix: every `data-act` of the prototype and every screen in CLAUDE.md's map, against the E2E test that covers it, written under "Flow coverage" below; a test for each gap.

### Fix
- [ ] All open P0 and P1 bugs, each starting with a failing test:
  - [ ] BUG-051, BUG-053 (P1), with BUG-054, BUG-055, BUG-057 (P2): bring PR #29's fix into `main` (question 1).
- [ ] P2s that fit (question 5).
- [ ] Bug log housekeeping: BUG-076 and BUG-065 are `fixed` but still in the Open table.

### Exit criteria work
- [ ] **Rows that need no edit** (00 §10.2): a metric in the eval, its definition decided with the user (question 2), with **wrong green rows** (≤ 1%) beside it. Unit tests for the metric; in the baseline.
- [ ] **A new factory's first day** (10 §2, §11): one E2E from a new tenant to a sent quote: the two questions and the terms, a drawing through the 7 stages (stand-in model), prices typed on the rows with "לעדכן גם במחירון?", send and lock. On both projects.
- [ ] Remove `price_list`: the flag (a migration), the routes' `require_flag`, the seed, its 404 tests (`test_api_price_list*.py`), the `prices-off` E2E tenant, the client's guard. The other build-time flags get a `remove_by` for Gate 3 (decision 4).

### Eval
- [ ] Replay, `catalog_lines` on, and live numbers under Outcome; the baseline updated (`make eval-baseline`) where a fix here moves it.

### Docs
- [ ] Backlog triage: each item scheduled into S29–S32, phase 4, or dropped; the table under Outcome, the roadmap updated.
- [ ] S29 and S30 session files prepared from the template.
- [ ] CLAUDE.md, dev-strategy, db-schema and the specs where this gate changes them (the flag removal; the new metric in eval/README).
- [ ] README §6.1: the phase 2 line.
- [ ] B1 and the other external blockers recorded.
- [ ] The roadmap: S27b `done`, S28's status.

### Close
- [ ] Merge, tag `phase-2`, set S28 to `done`. After the user merges the PR.

## Flow coverage

Filled in during the session: prototype flow → E2E test → status.

## Acceptance criteria (phase 2 exit)

- [ ] A new factory produces a quote on day one: the day-one E2E green on both projects.
- [ ] ≥ 85% of golden rows need no edit (00 §10.2, §14), in the live run, by the definition in decision 2; wrong green rows ≤ 1%. A shortfall is recorded as a known gap with its owner (dev-strategy §7).
- [ ] Every prototype flow covered by E2E (the matrix above has no gap), the whole suite green on both projects.
- [ ] `make check` green, and CI green on the PR.
- [ ] No open P0 or P1 bugs.
- [ ] External blockers recorded (B1–B8).

## Out of scope

- Phase 3: infrastructure, deployment, Cognito, Bedrock, Transcribe, the OCR engine (S29–S31).
- New features. Backlog items stay in the backlog unless the triage schedules them here.
- The spec-13 v1.0 flags (`unresolved_overlay`, `export_doc`, `chat_quote_builder`, `home_chat`, `voice_input`) and `catalog_lines` stay: 13 §3 rule 5 removes a flag after a month on for every factory, and no factory is live yet.

## Open questions

1. PR #29: merge its tip (`0a3bb3c`) into this branch and re-record the cassettes it moves, or redo the fixes on `main`.
2. How "rows that need no edit" is measured.
3. The live eval: the spending cap, and whether it re-records cassettes.
4. Which build-time flags go at this gate beyond `price_list`.
5. Which P2s this gate fixes.
6. Known gaps: B1 (the golden set), B7 (the usability test), the chat set's estimator phrasing.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
  1. **PR #29: merge its tip** (user, at kickoff; question 1). `0a3bb3c` is merged into `s28-gate-2` and its conflicts resolved on today's code. The eval replays; only calls that miss a cassette are recorded live (`EVAL_RECORD=missing`), and the baseline is rewritten from the replay.
  2. **Rows that need no edit: strict, end to end** (user, at kickoff; question 2). A labelled row counts when the pipeline's quote has a line for it with the label's family, every labelled value right, the labelled quantity, and a SKU from stage 5: a line with no SKU has no price, so it needs an edit. Wrong green rows (00 §10.2, ≤ 1%) are measured beside it: green lines that fail the same test. A shortfall against 85% is a known gap, not a failed gate.
  3. **Live eval: measure only, $15 cap** (user, at kickoff; question 3). `EVAL_MODE=live`, no recording, `EVAL_MAX_USD=15`. Live and replay numbers side by side; the cassettes and the baseline stay. If the cap stops the run before the chat sets, the live numbers it did not reach are recorded as not measured.
  4. **Only `price_list` is removed** (user, at kickoff; question 4). `quote_audit`, `bom_column_mapping`, `onboarding`, `settings_screen`, `approval_queue` and `chat_layer` get a `remove_by` and go at Gate 3 (S32), before the pilot.
- **Eval / metrics:**
- **Bugs logged:**
- **Known gaps:**
- **Follow-ups:**
