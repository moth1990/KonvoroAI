# S17: Gate 1, parsing and quote audit

| | |
| --- | --- |
| **Track** | G |
| **Branch** | `s17-gate-1` |
| **Depends on** | S16 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#18](https://github.com/moth1990/KonvoroAI/pull/18) |

## Goal

Close phase 1 only after confirming that what it built holds:
- stages 1–4, the BOM path and the quote audit pass a **live** golden eval;
- the audit's difference accuracy is at least 80% on the golden drawings that have actual quotes;
- the audit and review E2E are green on both projects;
- the bug list has no P0 or P1.

Phase 2 starts from a tagged, stable `phase-1`.

## References

- [dev-strategy.md §7](../dev-strategy.md#7-definition-of-done-bugs-gates): gate procedure. §8: phase 1 exit criteria.
- [roadmap.md, phase 1 exit](../roadmap.md#phase-1-parsing--quote-audit-p-alongside-the-review-screen-on-fixtures-r).
- Specs: 11 §10 (difference accuracy ≥ 80%: confirmed differences out of shown ones, confidence ≥ 0.6); 01 §10, 04 §10 for the stage metrics.
- Golden: all five drawings; the audit on the three with actual quotes (26-993, NEVIS-1, NURSERY-1).
- Prototype: every screen built so far (login, shell, home, new quote, confirm pages, review lines and drawing, audit).
- [bugs.md](../bugs.md): open for this gate are BUG-031, BUG-030, BUG-025 and BUG-018 (all P2). BUG-027 (P3) and BUG-008 (P2, S29) stay.
- [S07](S07-gate-0.md), the previous gate.

## Tasks

### Verify
- [x] `make up && make seed && make check`, in the working tree: a fresh clone in the scratchpad was refused by the tool (it copies `.env`). Every step green but the audit screenshots, then green after decision 10.
- [x] Full Playwright suite on `desktop` and `mobile` (131 passed); screenshot baselines 58/58 after the four audit shots were accepted (BUG-037 caught on the way, BUG-038 logged).
- [x] Fidelity report for every built screen (64 captures); only the audit results changed.
- [x] `make eval` in replay, then a live run (`EVAL_MODE=live`, capped). Both under Outcome.
- [x] Security spot checks (all inside `make check`): the RLS suite, the route-actor audit, `make secrets`, the license gate, and the test that no price or cost reaches a model (the audit's quote page being 11 §5.2's one exception).
- [ ] ~~Manual smoke as a user~~ not run (decision 12) (`make dev`): a new quote on each golden file, the BOM mapping, the review screen, an audit on 26-993 with a decision and "צור הצעה מתוקנת".

### Fix
- [x] All open P0 and P1 bugs: none at kickoff, none found here.
- [x] P2s for this gate, each starting with a failing test:
  - [x] BUG-031, the parts that move the audit (decision 3):
    - MS1–MS3 are three tagged CTs: a list of tags the model read beside one symbol is its designator (stage 3), and stage 4 makes a device per tag (decision 6).
    - TC-G1/TC-G2: the dictionary's designator shape takes "TC-G1", so "TC" names the shunt trip and no model call decides it (0.49 → 0.9).
    - SG and EMS's quote line are BUG-036; the panel split found on the way is BUG-035.
  - [x] BUG-030: a panel name from a picture's heading gets the `bom_panel_name_from_picture` notice (decision 5).
  - [x] BUG-025: the queue round-trip test uses the run's prefixed queue.
  - [x] BUG-018: `ulid()` is monotonic within a process.

### Eval
- [x] Replay and live numbers under Outcome; the baseline updated (`make eval-baseline`).

### Docs
- [x] S18 and S19 session files, linked from the roadmap.
- [x] 03 §3.7 item 5 and §4.6, 04 §5.8: the tag-list and "TC-G1" rules.
- [x] CLAUDE.md, dev-strategy and db-schema need no change (no command, rule or table changed); the roadmap, eval/README (the live key and one run at a time) and the specs are updated.
- [x] README §6.1: the phase 1 line.
- [x] B1's status recorded (decision 11).

### Close
- [ ] Merge, tag `phase-1`, set S17 to `done`. After the user merges the PR (open).
- [x] Phase 2's first session files, S18 and S19, prepared from the template.

## Acceptance criteria (phase 1 exit)

- [x] ≥ 80% difference accuracy (11 §10) on the golden drawings with actual quotes, in the live run: 100% (7/7) live, 100% (9/9) replay.
- [x] Audit and review E2E green on both projects (`audit.spec.ts` 16/16, the whole suite 131).
- [ ] `make check` green (working tree, not a fresh clone), and CI green on the PR.
- [x] No open P0 or P1 bugs. Open: BUG-035, BUG-036, BUG-038, BUG-008 (P2), BUG-027 (P3).
- [x] B1 recorded: still 5 drawings from one factory, a known gap owned by the user and the estimator.

## Out of scope

- Stages 5–7, the price list, onboarding (phase 2, S18 onward).
- The detection rate on quotes with injected omissions (11 §10, second row): no such set exists yet.
- New screens or features. Backlog items stay in the backlog.

## Open questions

1. The live eval: the spending cap, and whether it re-records cassettes.
2. How "≥ 80% difference accuracy" is measured: pooled over the three quotes, or on each drawing.
3. How much of BUG-031 (stages 3–4 on 26-993) this gate fixes.
4. BUG-030 (BOM-HW-1's panel name): fix here or later.
5. B1: has the golden set grown since gate 0?

## Outcome

- **Done:** phase 1 checked end to end, and its four open P2 bugs fixed:
  - The audit on 26-993 finds what the factory confirmed: MS1–MS3 come out as three tagged current transformers (a list of tags the model read on one symbol, 03 §3.7 item 5, 04 §5.8), and TC-G1/TC-G2 are classed by the dictionary (03 §4.6) instead of a model call at 0.49 (BUG-031). Audit precision 100% and recall 88.9% over the three quotes in replay; precision 100% live.
  - A panel name read from a photographed form's heading is flagged on the done step (BUG-030); the queue test has its own queue (BUG-025); ids made in one millisecond keep their order (BUG-018).
  - The eval splits a tag list; the baseline, the 26-993 audit fixture, `audit.spec.ts` and the four audit screenshots follow.
  - A live golden eval on the final code (about $7.60), side by side with replay.
  - Full `make check` green (in the working tree), E2E 131 on both projects, screenshots 58/58, fidelity report 64 captures.
  - Docs: S18 and S19 session files; the specs' new rules; eval/README (the live key is read from the shell, one run at a time); README §6.1's phase 1 line; the roadmap and the bug log.
- **Decisions made:**
  1. **Live eval: measure only, $15 cap** (user, at kickoff; question 1). `EVAL_MODE=live` with no recording, `EVAL_MAX_USD=15`. Live and replay numbers go side by side, and the cassettes stay. Only calls whose prompt or input a fix here changes get re-recorded, with `EVAL_RECORD=missing`.
  2. **The 80% is pooled** (user, at kickoff; question 2). Shown and confirmed differences are added up over 26-993, NEVIS-1 and NURSERY-1. Per-drawing precision and recall are recorded too, and a drawing below 80% is a known gap, not a failed gate.
  3. **BUG-031: fix the parts that move the audit** (user, at kickoff; question 3). These are MS1–MS3 (the CT omission gets its designators) and the shunt trips TC-G1/TC-G2 (shown, not in "לבדוק"). EMS detection and SG as a changeover switch go to S20/S21 if they need symbol-library or detector work. Stage 3 and 4 cassettes are re-recorded only where the fix changes them.
  4. **BUG-030: mark the panel name uncertain** (user, at kickoff; question 4). When the heading is read with low confidence, the panel name is `uncertain` and the user gets a question. No re-read and no re-recording.
  5. **BUG-030: a picture's heading is always checked** (user, in session; replaces decision 4's test). `table_transcription` returns `panel_name` with no confidence, so there is no low confidence to test. When the panel name comes from a photographed form's heading, stage 1 adds the warning `bom_panel_name_from_picture`, which the done step shows as a notice with the name. Spreadsheets and title blocks are not flagged. A title block that names a panel does not hold the notice back: `bom_table.panels` names the rows by the heading first (found by `test_bom.py`, in session). No schema change and no re-recording.
  6. **A list of tags needs the model's reading** (Claude, in session). At first any span shaped like "MS1/MS2/MS3" near a symbol was its designator; the regenerated fixture showed a terminal beside the CTs taking it too and merging with SG. A list now counts only when the model read it beside that symbol (03 §3.7 item 5).
  7. **The eval splits a tag list** (Claude, in session). `eval/normalizers/common.designators` splits "MS1/MS2/MS3" as it expands "F1–F17", so stage 3's designator recall counts the three CTs. No golden label writes a list.
  8. **The 26-993 fixture is regenerated** (Claude, in session; S16 decision 2). It is the pipeline's own output, and that output now finds the factory's three omissions. `audit.spec.ts` follows; the audit screenshots wait for the user's review.
  9. **The live eval waits for API credits** (user, in session). The first measure-only live run ran stages 1–4 of 26-993 and stopped at the audit's `table_transcription` call: "credit balance is too low". The user tops up the account, and the live run is repeated before the gate closes.
  10. **Audit screenshots accepted** (user, at close). The four `audit-results` baselines (light and dark, desktop and mobile) show the regenerated fixture; no other screen changed.
  11. **B1 is still 5 drawings from one factory** (user, at close). A known gap, owned by the user and the estimator.
  12. **No manual smoke test** (user, at close). The tool refused to read the dev password from `.env`, and the user chose to rely on the E2E suite (131 tests on both projects) for the same flows.
- **Eval / metrics:**
  - **Replay** (committed baseline, two identical runs). Audit: 26-993 precision 50% → 100% (2/2), recall 33% → 100% (3/3); all three quotes precision 87.5% → **100% (9/9)**, recall 66.7% → **88.9% (8/9)**, type agreement 100%. Stage 3 designator recall on 26-993 89.2% → 97.3%, all drawings 96.7% → 99.2%; the `current_transformer` family 0% → 100%. Stage 4 unchanged (26-993 component recall 50%: BUG-035). No metric dropped. Three calls had no cassette after the stage 3 change and were recorded live (`EVAL_RECORD=missing`, 2 disambiguation and 1 tile-agent call, about $0.04).
  - **Live** (2026-11-02, measure only, report `eval/reports/20261102T171608Z`): 724 calls, 2.7M tokens in and 0.25M out, **about $7.60** at list prices, under the $15 cap. Audit precision **100% (7/7)**: the exit criterion holds live. Recall 77.8% (7/9): 26-993 3/3, NEVIS-1 3/4, NURSERY-1 1/2 (2/2 in replay; the live run missed one of its omissions). Stage 1 page kind and route 100% (24/24), `input_kind` 100% (5/5), panel count 80% (4/5). Stage 2 designator recall 99.2%. Stage 3 designator recall 99.2%, family accuracy 98.3%. Stage 4 factory drawings component recall 75.0%, precision 65.6%, `current_a` 100%, poles 93.1%, values without evidence 0. BOM-HW-1's heading read "קומה י"א" live, and BUG-030's notice still asks the user to check it. The live run differs from replay on 40 metrics down and 46 up; cassettes and baseline are unchanged (decision 1).
- **Bugs logged:**
  - Fixed: BUG-031, BUG-030, BUG-025, BUG-018 (from earlier sessions); BUG-037 (found here: a rewritten home baseline with an empty list, caught before commit).
  - Opened: BUG-035 (26-993 read as three panels; stage 4's per-panel recall can't count the CTs), BUG-036 (SG as a terminal, EMS's quote line unmatched, for S20/S21), BUG-038 (four dark review shots timed out once under load).
  - Still open: BUG-008 (S29), BUG-027 (P3).
- **Known gaps:**
  - B1, the golden set: 5 drawings from one factory (owner: user and estimator). README §6.2 asks for 50–100 by the end of phase 1.
  - No fresh-clone run and no manual smoke test (decisions 12 and the Verify list).
  - The 11 §10 detection rate on quotes with injected omissions is not measured: no such set exists.
- **Follow-ups:**
  - BUG-035 and BUG-036, as above. Live recall on NURSERY-1 was 1/2 against 2/2 in replay: worth a second live run before a pilot quotes it.
  - After merge: tag `phase-1` on the merge commit, set S17 to `done`.
