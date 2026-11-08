# S28c: The live decoding screen

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s28c-live-run` |
| **Depends on** | S28 |
| **Status** | in review |
| **PR** | [#43](https://github.com/moth1990/KonvoroAI/pull/43) |

## Goal

While a drawing decodes, the app shows what the system does now, how long is left and what it costs in dollars, with an icon for each stage and a log. Before the start, the start bar shows the expected time and cost. At the end, the done step shows the run's time and cost and a breakdown by stage. The user can leave the screen and is told at the end wherever they are. The whole screen sits behind `live_run`, which is on for every factory.

## References

- Specs:
  - 01 §4.6, the live run, its time and its cost;
  - 12 §7, the cost per tenant;
  - 13 §4.11, `live_run`;
  - 11 §5.1, the audit's run.
- Prototype: `prototype/konboro-app.html` lines 813–1064: `vNew`, `runState`, `updateRun`, `runPipeline` and `runFinished`. The CSS is at lines 175–220 and the icons at lines 423–432.
- Golden: none. The pipeline's outputs don't change; the stages only report.
- Earlier work: PR #41 (the prototype and specs, the user's 14 answers); S05 (the run step); S21 and S22 (the stage 6 and 7 lines).

## Tasks

### Backend
- [x] Migration 0027:
  - `pipeline_events`, with forced RLS and the composite foreign key;
  - the new `llm_calls` columns: the cache tokens, `ok`, `cost_usd`, `pipeline_stage`, and an index by drawing;
  - the `konboro_stats` role with `konboro_stage_medians(interval)`, which returns aggregates only;
  - a row in `factory.py`, and `docs/db-schema.md`.
- [x] Every attempt is recorded in `konboro_llm/client.py`:
  - a schema mismatch's tokens join the answer;
  - a call that never answers is a row with `ok` false;
  - an unusable answer (a refusal, cut short, not JSON) keeps its tokens through `LLMError.usage`;
  - the Anthropic provider reads the cache tokens.
- [x] `services/run_cost.py`:
  - the list prices in `Decimal`, with the cache prices and Haiku's long-prompt price;
  - each row is priced when written;
  - a drawing's cost by stage and model;
  - `SpendingCap` uses the same prices.
- [x] `pipeline/events.py`:
  - templates in code, with at most one write a second per stage run, each write in its own transaction;
  - stages 1–3 report page by page, and stages 4–8 report at their two ends, from their output.
- [x] `services/run_estimate.py`:
  - page units by route, and by size before stage 1;
  - the seed, every factory's medians, then the factory's own;
  - the time left, with the 0.5–2 clamp, rounding to 10 s and the 20% cap.
- [x] `services/run_live.py` and the progress endpoint's `live` object, filled only with the flag on. `shown_left` comes back on each poll.
- [x] `POST /drawings/check`: the upload's checks and the estimate, with nothing stored or counted, behind the flag.
- [x] Plain stage names in `NAMES`. The summaries drop "OCR", and stage 3 counts "רכיבים".
- [x] Flag `live_run` with `default_on`. It is the first such flag, so the seed's upsert keeps `default_on` only for a flag that declares it.

### Frontend
- [x] The icons: `ai`, `bell`, `clock`, `s_intake` … `s_price`, and `s_audit` for stage 8.
- [x] The live CSS in `app.css`:
  - the 900 px rule becomes 1000 px and the 820 px rule becomes 860 px;
  - `ai-pulse`;
  - reduced motion stops the animations.
- [x] `LiveRun.tsx`:
  - the header's live sentence, the meter, and time, progress and cost;
  - the page view with the scan line, the tiles and the boxes;
  - the counters, the log, the stages with their icons, and "הודע לי".
- [x] The done step's time and cost tiles and the "פירוט לפי שלב" table.
- [x] The start bar's estimate (`useStartEstimate`), on the new-quote and audit screens.
- [x] `RunWatcher`: the end of a run is told on another screen; while the tab is hidden, the title says "✓ מוכן", and with "הודע לי" a notification is shown.
- [x] Polling every 2 s with `live_run` on; the cancel message gives the cost so far; the settings screen has the flag's row.

### Unit tests
- [x] `test_run_cost.py`, `test_run_estimate.py`, `test_pipeline_events.py`, `llm/test_attempt_cost.py`.
- [x] `live.test.ts`: the formats, the estimate's gate, the words, the boxes, the hidden tab's title and notification, and the watched run.

### Integration tests
- [x] `test_live_run.py`:
  - the flag is on for a new factory;
  - progress has times, cost and events, and leaves out chat;
  - the flag off hides the object and answers the check with 404;
  - the check stores nothing;
  - a cancel keeps the cost;
  - a call that never answers is billed;
  - the medians are aggregates.
- [x] The RLS suite covers `pipeline_events`.

### UI tests (Playwright)
- [x] Desktop and mobile projects (the whole suite passes; the new-quote, audit and settings specs changed):
  - the estimate;
  - the live run;
  - the phone without the page view and the log;
  - the done step's tiles and breakdown;
  - the cancel's cost;
  - the end message on another screen;
  - the classic run with the flag off;
  - the audit's five stages live.
- [x] Prototype-fidelity report reviewed and accepted by the user. Then `make screenshots` rewrote the baselines: new-run, new-done, and one new-pick.
  - The visual spec masks what moves from run to run: the estimate, the sentence, the clock, progress and cost, the counters, the log, the page being read, the stages' times, and the done step's time and cost.
  - A mask hides content but not its size. So `e2e/visual/steady.css` (`stylePath`) keeps that text at one size, and a phone never wraps it differently.
  - The run shot cancels its slow run after the shot, so the done shots get the workers.
  - It waits up to 150 s for stage 2. That shot is its tenant's first decode, and stage 1 took over 97 s at that load.
  - The pick shot waits for the server's check to add the page count to the file row. The first light phone baseline was taken before that answer came back.

### Docs
- [x] Spec 01 §4.6:
  - the seed comes from the prototype's times until 20 runs;
  - the check endpoint;
  - A4 as one page unit;
  - the price is fixed when the row is written.
- [x] Spec 11 §5.1 (the audit's live run) and 13 §4.11.
- [x] README decision 23, HANDOFF 37, the roadmap row and two backlog items, CLAUDE.md.

## Acceptance criteria

- [x] With `live_run` on, NURSERY-1's start bar says "9 עמודים · כ-3 דקות · כ-$0.44" before the start. This is the prototype's seed, checked in the browser.
- [x] The run step shows the live sentence, time, progress and cost, the page with its boxes, the counters, the log, and the 7 stages with icons, times and cost. On a phone at 375 px it has no page view and no log, and no horizontal scroll.
- [x] A cancel's message gives the cost so far, and the end of a run is told on another screen.
- [x] With the flag off, the run step is the classic one and the start bar has no estimate.
- [x] A run's cost counts every attempt, a failed call too, and leaves out chat. No model is called for the screen.

## Out of scope

- A live eval run to seed the time left (decision 2): in the backlog.
- The audit's time and cost on its results screen: in the backlog.
- SSE: polling every 2 s is enough (01 §4.6).
- Email at the end: after 1.0.

## Open questions

None open.

## Outcome

- **Done:** the live run step, the start bar's estimate, the done step's time and cost, and the end message on any screen, behind `live_run`, for a new quote and for an audit.
- **Decisions made:**
  1. The page count before the start comes from a new `POST /drawings/check`, which reuses the upload's checks and stores nothing. A rejected file shows as soon as it is picked (the user).
  2. No live eval for now. The seed is the prototype's NURSERY times and costs in code, until 20 runs (the user). The live eval is in the backlog.
  3. The audit's run gets the live screen too, with its five stages. Stage 8 has the audit icon with the sparkle (the user).
  4. A page unit is an A4 page, NURSERY's and the factory drawings' size, between half and four by area. A3 as one made NURSERY's estimate half the prototype's: 9 A4 pages came out as "כדקה · $0.22". Decided in the session, from the golden drawings' sizes.
  5. Each `llm_calls` row is priced when it is written (`cost_usd`), so a price change never rewrites a run's cost, and the medians across factories can sum dollars in SQL.
  6. Pipeline events are written even with the flag off. The flag only decides what the screen shows (13 §4.11), so the eval needs no second mode.
  7. In the breakdown, a stage that could call a model and did not says "בלי מודל". "קוד בלבד" is pricing's (07).
- **Eval / metrics:** `make eval` (replay): no change against the baseline. Unit: 1371 backend, 330 frontend. Integration: 841 (840 in `make check`, and the seed test fixed and passing). E2E: 259 passed, desktop and mobile.
- **Bugs logged:**
  - BUG-116 (P3, watch): at load average 80–108, stage 1's heartbeat missed its window. A second worker ran the stage, and `retry_later` raised on a stale receipt. The drawing still finished, and S28c did not cause it.
  - BUG-115 (P2, open, from PR #41) failed again on this PR's CI: the review action `/qty` took 1.18 s against the 1 s guard, on a runner where every step ran about 1.75× slower than on main. Locally it takes 0.09 s. The bug's entry has the numbers.
  - Test harness fixes, not bugs:
    - The fidelity harness waited 15 s for the prototype's done step. Since PR #41, its demo run takes about 15 s, so the wait is now 30 s.
    - The E2E slow project's stages took 1.5 s each, shorter than the live step's 2 s poll, so `make screenshots` once missed stage 2 running. Each slow stage now takes 3 s (`devtools/e2e.SLOW_STAGE_S`).
  - `make screenshots`' first pass had seven timeouts at that load and no pixel difference (BUG-038's pattern). All seven passed when rerun alone.
  - `make check` ran three times. The first run's Vitest workers did not start: the shell had Node 20, and the project needs Node 22 (`nvm use`). The second run's integration step had one failure: `test_e2e_seed.py` lacked the two new `live-off` E2E tenants, which are added now.
- **Follow-ups:** the two backlog items above.
