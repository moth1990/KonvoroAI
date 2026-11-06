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
- [x] `make check`'s steps in the working tree, one at a time (decision 7): lint and types, licenses, secrets (133 commits, no leaks), client freshness, unit (backend 1287 with pricing at 100% branch coverage; Vitest 279 on Node 22), integration (818), the replay eval, E2E, screenshots. Not yet as one `make check` run: `/session-close` runs it.
- [x] Full Playwright suite on `desktop` and `mobile`: 251 passed, 101 skipped (the screenshot tests outside Docker and the layout-specific ones). Screenshot baselines: 86 of 86 (`make check-screenshots`).
- [x] Fidelity report for every built screen (`make fidelity`, 152 captures), for the user's review.
- [x] `make eval` in replay, then `EVAL_CATALOG_LINES=1 make eval` (13 §3 rule 6), then a live run (`EVAL_MODE=live`, capped). All under Outcome.
- [x] Security spot checks, inside the suites above: the RLS suite and the route-actor audit (integration), `make secrets`, the license gate, and no amount to a model (the chat's `money_to_model` 0 of 361 live, the builder's 0 of 54, the home's 0 of 10).
- [x] The prototype-flow matrix: every `data-act` of the prototype and every screen in CLAUDE.md's map, against the E2E test that covers it, written under "Flow coverage" below; a test for each gap (four).

### Fix
- [x] All open P0 and P1 bugs (none P0):
  - [x] BUG-051, BUG-053 (P1), with BUG-054, BUG-055, BUG-057 (P2): PR #29's fix merged into this branch (decision 1), with its own tests.
- [x] P2s that fit (decision 5): BUG-074 and BUG-046, each starting with a failing test.
- [x] Bug log housekeeping: BUG-076 and BUG-065 moved to Closed.

### Exit criteria work
- [x] **Rows that need no edit** (00 §10.2): `eval/metrics/rows.py`, by decision 2, with **wrong green rows** (≤ 1%) beside it. Unit tests (`golden_eval/test_metrics.py`); in the baseline.
- [x] **A new factory's first day** (10 §2, §11): `day-one.spec.ts`, from a new tenant to a sent quote: the two questions and the terms, a drawing through the 7 stages (stand-in model), a price typed on a line and saved to the price list, send and lock. On both projects.
- [x] Remove `price_list`: the flag (a migration), the routes' `require_flag`, the seed, its 404 tests (`test_api_price_list*.py`), the `prices-off` E2E tenant, the client's guard. The other build-time flags get a `remove_by` for Gate 3 (decision 4).

### Eval
- [x] Replay, `catalog_lines` on, and live numbers under Outcome; the baseline rewritten from the replay after PR #29's merge and again after BUG-074, BUG-046 and the rows metric.

### Docs
- [x] Backlog triage: every item scheduled, in "Backlog triage" below; nothing dropped.
- [x] S29 and S30 session files prepared from the template, linked from the roadmap.
- [x] CLAUDE.md (the price list's flag, the eval row), db-schema (the seeded flags), 06 decision 2's note, 11 §5.4, eval/README (the overall section). dev-strategy needs no change.
- [x] README §6.1: the phase 2 line.
- [x] B1 and the other external blockers recorded (Outcome, known gaps).
- [x] The roadmap: S27b `done`, S28's status, the price list's backlog item.

### Close
- [ ] Merge, tag `phase-2`, set S28 to `done`. After the user merges the PR.

## Flow coverage

Every `data-act` of the prototype's click handler (lines 1446–1559) and every screen in CLAUDE.md's map, against the Playwright spec that covers it. "S28" marks a test added here for a gap.

| Screen | Prototype actions | Spec |
| --- | --- | --- |
| Login | `pw`, `forgot` | `login.spec.ts` |
| Shell | navigation, `logout`, the quota meter | `shell.spec.ts`, `home.spec.ts` |
| Home, classic and chat | `home-sugg`, `mic-home`, `chat` | `home.spec.ts`, `build.spec.ts`, `voice.spec.ts` |
| New quote: pick | `upmode`, `rmfile`, `clearfiles` (S28), `start`; `sample` left out (S05: demo only, 01 §4.6 item 5) | `new-quote.spec.ts`, `bom.spec.ts` |
| New quote: run and done | `cancelrun`, `toreview`; the confirm step and page kinds | `new-quote.spec.ts` |
| A new factory's first day | the two questions, the terms, a drawing, a typed price, send (no prototype screen) | `welcome.spec.ts`, `day-one.spec.ts` (S28) |
| Review: lines | `filter`, `margin` (S28), `approve`, `del`, `undo`, `toast` | `review.spec.ts`, `review-actions.spec.ts` |
| Review: line detail | `editprice`, `price-here`, `price-db`, `takefresh`, `addcost`, `mkpref`, `alt`, `prod`, `savelist` (S28), `dismiss`, `close` | `review-actions.spec.ts`, `review-picker.spec.ts`, `catalog-lines.spec.ts` |
| Review: findings | `f-onlyred` (S28), `f-show`, `goline` | `review-actions.spec.ts`, `drawing.spec.ts` |
| Review: drawing | `page`, `tab`, `zin`, `zout`, `zfit`, `showdraw`, `ux` | `drawing.spec.ts`, `unresolved.spec.ts` |
| Review: send and versions | `send`, `dosend`, `newver` | `review-actions.spec.ts`, `export.spec.ts` |
| Chat drawer and proposals | `ask`, `apply`, `newchat`, line chips (`goline`), `mic` | `chat.spec.ts` |
| Audit | upload, results, decisions, "הצג בשרטוט", corrected quote | `audit.spec.ts` |
| Price list and editor | `pricef`, `prod`, `prod-new`, `ed-save`, `ed-addsup`, `ed-rmsup`, `cons`, the brand discount | `prices.spec.ts` |
| Approval queue | `qok`, `qno` | `queue.spec.ts` |
| Settings | `pref`; `flag` shown read-only (S03, S24) | `prefs.spec.ts` |
| Chat quote builder | the conversation, `price-here`, `mic` | `build.spec.ts`, `voice.spec.ts` |
| Export modal | `export`, `exp` | `export.spec.ts` |

Not ported: the prototype chat's canned answers with their own buttons (`onlyred` in a message, line 1035): the app's chat answers come from the model, with line chips.

## Backlog triage

Every open item of the roadmap's backlog, scheduled (dev-strategy §7, the roadmap's "Each one is scheduled into a session, or dropped, at the next gate"). "Reading II" is the session proposed at close for the reading gaps the rows metric shows (question 7). "Pilot" means a triage session after S32 decides it from what the pilot factory finds. "Phase 4" is after the pilot.

| Where | Items |
| --- | --- |
| S29, infrastructure | BUG-008, the per-tenant pipeline limit; a test database per checkout (S23b's merge), with the environment settings |
| S30, deploy and observability | a usage table for every flag (S26 decision 6); exchange rates in production (S18); cassettes that replay the same on every platform (S24b decision 15, BUG-073) |
| S31, OCR engine | reuse stage 2 for a reused page (S10); calibrate OCR confidence and the blank threshold (S10) |
| S32, Gate 3 | the data terms' wording (S24, with B5); the review screen's usability test (S23 decision 1, B7); remove the six build-time flags (S28 decision 4); a manual line joins its product's line (S27b, before `catalog_lines` goes); a product deleted after it was queued (S24) |
| Reading II (proposed) | panel count: feed sources are not panels (S08, BUG-035); a terminal with a device's tag (S24b, BUG-036, BUG-051's rest); time switches and impulse relays missed (S12, BUG-082); the backtest's unpriced lines (S22); an audit scoped to the quoted panel (S24b decision 18); end circles before the disambiguation call (S24b decision 5); disambiguation share above target (S12); a drawing's BOM SKUs and a CT's count (S20); an auxiliary contact's device and drawn twice (S12, S13); dashed frames for supply scope (S13); line confidence: no golden line is green apart from its price (S28) |
| Pilot | PDFium in a process pool (S07); confirmation rate and `page_kind` (S08); a tenant's own BOM words and a misread BOM word (S14); the price list in the audit's money (S15); "הורד דוח" for an audit and audits in home's recent work (S16); the audit's summary counts (S16); matching, labor and derived-rule settings (S20, S22); the picker's price at a brand discount (S23b); a rematch and the kit, the rules on a resolved missing line (S23b); paste rows from a supplier quote (S23b decision 7); show an action before the server answers (S23 decision 10); the chat streams its answer, `set_attribute` for any value, "ליצור מחדש" (S25); grow the chat set to 200 and the builder's set (S25, S27, with estimators); a value changed by message, an enclosure said, `validator_review` on a chat build (S27); the customer PDF's template (S26 decision 1); a product's delete or archive, similar products without the catalog (S18) |
| Phase 4 | eval each stage on labelled input and symbol-box labels (S06, S12); legend crops (S12); stage 3 reads the tenant's crops (S23b); the picker at catalog scale (S23b, with B3); BOM tables in a vector PDF (S14); a model for quote lines code can't sign (S15); the audit's, pricing's and the dismissals' learning loops (S15, S21, S22); the factory tunes an inference rule and tenant-level proposals (S20, S24); more sources for the approval queue, stage 4 reads `spelling_patterns`, re-review of `pilot_engineer` records (S24); `QTY_RANGE_MISMATCH`'s own count, the agent's catch rate (S21); one editor at a time and costs by permission (S23, S09: with a second user or role) |
| External | 25.26.100's sub-panel labels (S24b decision 11, the user); the prefix table and thresholds (S24b, B2, the electrical expert) |

## Acceptance criteria (phase 2 exit)

- [x] A new factory produces a quote on day one: `day-one.spec.ts` green on both projects.
- [ ] ≥ 85% of golden rows need no edit (00 §10.2, §14), by decision 2: **not met**, 54.2% live (117/216) and 51.4% in replay (111/216). Wrong green rows ≤ 1%: not measurable, no line is green apart from its price (BUG-103). A known gap (decision 2), for Reading II (question 7).
- [x] Every prototype flow covered by E2E (the table above has no gap), the whole suite green on both projects (251).
- [ ] `make check` green, and CI green on the PR: every step green, run one at a time (decision 7); the single run and CI at `/session-close`.
- [x] No open P0 or P1 bugs.
- [x] External blockers recorded (B1–B8, under Outcome).

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
7. At close: a "Reading II" session before Gate 3, for the reading gaps the rows metric shows (51% against 85%).

## Outcome

Filled in at `/session-close`.

- **Done:** phase 2 checked end to end; its open P1s fixed; two of its exit criteria met and one measured for the first time.
  - PR #29 (MINHAROT-1's reading: BUG-051 and BUG-053, P1; BUG-054, 055, 057) had been merged into a branch that had already landed, so it never reached `main`. It is merged here, both sides of `association/merge.py` kept; the replay needs no new cassette, and its numbers are the PR's own.
  - BUG-074: a quote line repeated word for word is a double count, shown (25.26.100's audit: precision 33% to 50%, recall 20% to 40%). BUG-046: a front view on a page no panel holds goes to the panel with its tags, and a device read as terminals may be its near match; 26-993's SE/SG now waits only for BUG-035.
  - `price_list` removed (migration 0026); the six other build-time flags dated for Gate 3.
  - The eval's `overall` section: rows that need no edit, and wrong green rows (00 §10.2).
  - `day-one.spec.ts`: a new factory to a sent quote. The flow table, and tests for the four built flows that had none.
  - Every step of `make check` green, one at a time; the full E2E suite (251), screenshots (86/86), the fidelity report (152 captures); replay, `catalog_lines` on, and a live eval.
  - Docs: S29 and S30 session files, the backlog triage, CLAUDE.md, db-schema, 06, 11, eval/README, README §6.1, the roadmap and the bug log.
- **Decisions made:**
  1. **PR #29: merge its tip** (user, at kickoff; question 1). `0a3bb3c` is merged into `s28-gate-2` and its conflicts resolved on today's code. The eval replays; only calls that miss a cassette are recorded live (`EVAL_RECORD=missing`), and the baseline is rewritten from the replay.
  2. **Rows that need no edit: strict, end to end** (user, at kickoff; question 2). A labelled row counts when the pipeline's quote has a line for it with the label's family, every labelled value right, the labelled quantity, and a SKU from stage 5: a line with no SKU has no price, so it needs an edit. Wrong green rows (00 §10.2, ≤ 1%) are measured beside it: green lines that fail the same test. A shortfall against 85% is a known gap, not a failed gate.
  3. **Live eval: measure only, $15 cap** (user, at kickoff; question 3). `EVAL_MODE=live`, no recording, `EVAL_MAX_USD=15`. Live and replay numbers side by side; the cassettes and the baseline stay. If the cap stops the run before the chat sets, the live numbers it did not reach are recorded as not measured.
  4. **Only `price_list` is removed** (user, at kickoff; question 4). `quote_audit`, `bom_column_mapping`, `onboarding`, `settings_screen`, `approval_queue` and `chat_layer` get a `remove_by` and go at Gate 3 (S32), before the pilot.
  5. **P2s fixed here: BUG-074 and BUG-046** (Claude's proposal at kickoff, the user's go-ahead). BUG-035, BUG-036, BUG-082 and BUG-086 need many cassettes re-recorded live, beyond a measure-only run: they go to Reading II (question 7). BUG-008 stays with S29.
  6. **Known gaps owned by the user** (Claude's proposal at kickoff, the user's go-ahead): B1, B7 and the chat set in an estimator's own words are recorded, not gating.
  7. **`make check` one step at a time** (Claude, in session). The live eval cannot overlap any other eval run, `test_eval.py` included: the first live attempt was stopped after six minutes when the integration suite recreated `konboro_eval` (about $2 at the second run's rate). The second ran alone, capped at $13.50 so the two stay within decision 3's $15, and cost $11.89. The single `make check` run is `/session-close`'s.
  8. **The 26-993 audit fixture is regenerated** (Claude, in session; S16 decision 2): the same nine differences and summary, one terminal (EM2) fewer in a "not a difference" note, from changes since S17. The audit screenshots did not move.
  9. **Wrong green rows are coloured apart from the price** (Claude, in session; decision 2's measure). The eval's factory has no price list (S20), so every line's price reason is red there; the colour from the other reasons is what the pipeline vouched for. It found no green line at all: BUG-103.
  10. **The rows metric compares the family's schema values** (Claude, in session). A label's other notes (`model_token`, `brand`, `dims_mm`) are no value of a line. Rows with no designators are a group by family, current and poles, compared by quantity and SKU. Terminals are auxiliary material, left out on both sides.
  11. **Gate 3's date is 2026-12-31** (Claude, in session): `remove_by` needs a date, and S32 has none yet.
  12. **Vitest runs on Node 22** (Claude, in session). The shell's default Node 20 cannot start Vitest's workers (undici); the project pins 22 (`.nvmrc`). An environment note, no code change.
- **Eval / metrics:**
  - **Replay** (the committed baseline). After PR #29: MINHAROT-1's stage 4 quantity accuracy 76% to 94%, units 81% to 98%; NEVIS-1's units 79% to 91%; injected errors caught 97% to 100%; NURSERY-1's component precision 80% to 75% and quantity 92% to 83% (its lamps now split by colour against one labelled row), and the front-view warnings BUG-055 adds. After BUG-074 and BUG-046: the audit's precision 83.3% to 84.6% and recall 64.3% to 71.4% over the four quotes; 26-993 one warning more. **Rows that need no edit 51.4% (111/216)**: 25.26.100 50%, 26-993 38%, 6199-2-50 38%, BOM-HW-1 95%, MINHAROT-1 78%, NEVIS-1 62%, NURSERY-1 69%. Wrong green rows n/a.
  - **`catalog_lines` on** (replay, reported): rows unchanged (51.4%); stage 6 warnings 3.9 to 5.4 per drawing (`PRODUCT_NOT_IN_CATALOG`).
  - **Live** (2026-11-06, measure only, report `eval/reports/20261106T155007Z`): 1,202 calls, 4.4M tokens in and 0.37M out, **$11.89** at list prices. **Rows that need no edit 54.2% (117/216)**. Audit precision 78.6% (11/14), recall 71.4% (10/14), type agreement 90%. Stage 1 page kind 97%, route 100%, `input_kind` 100%, panel count 86%. Stage 2 and 3 designator recall 99.4%, family accuracy 95.5%. Stage 4 component recall 75.6%, precision 68.3%, `current_a` 100%, poles 100%, quantity 82.4%, values without evidence 0. Stage 5 with SKU 76%, value accuracy 100%, consistency 100%, model share 4.6%. Stage 6 golden findings 82%, injected caught 100%. Backtest within 5%: 1 of 4. The chat: tools 98.4%, clarification 96.1%, no amount to the model (0 of 361), no injection followed. The builder: lines 98.7%, turns 98.0%, no value invented; the home: routing 100%.
- **Bugs logged:**
  - Fixed: BUG-051, BUG-053 (P1), BUG-054, BUG-055, BUG-057 (PR #29); BUG-074, BUG-046 (here). Moved to Closed: BUG-076, BUG-065.
  - Opened: BUG-103 (P2, no golden line green apart from its price).
  - Still open: P2 BUG-086, 082, 038, 036, 035 (Reading II), BUG-008 (S29); P3s.
- **Known gaps:**
  - **Rows that need no edit, 54% against 85%** (decision 2), and wrong green rows not measurable (BUG-103): the reading's recall, quantities and SKUs. Owner: Reading II, if the user schedules it (question 7).
  - B1, the golden set: 7 drawings; MINHAROT-1 not checked with its factory, 25.26.100's sub-panel unlabelled (owner: the user and the estimator).
  - B7, the review screen's usability test (owner: the user).
  - The chat set: 77 requests written by Claude, not about 200 in an estimator's words (owner: the user, at the pilot).
  - `make check` as one run and CI: at `/session-close`.
- **Follow-ups:**
  - Question 7: a Reading II session before Gate 3 (the triage's "Reading II" row).
  - The user reviews the fidelity report.
  - After merge: tag `phase-2` on the merge commit, set S28 to `done`.
