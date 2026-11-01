# Bug log

Every bug found during development goes here, including bugs fixed in the same session. Severities and the fix policy are in [dev-strategy.md §7](dev-strategy.md#7-definition-of-done-bugs-gates):

| Severity | Meaning | Fix by |
| --- | --- | --- |
| P0 | Cross-tenant leak, wrong money, a value made up without evidence, data loss, a broken main flow | Now, in the current session |
| P1 | A feature in scope doesn't work, or fidelity is badly off | The phase gate |
| P2 | Minor functional or visual deviation | The gate, or scheduled later |
| P3 | Cosmetic, or an idea | Backlog |

**How to add a bug:**
- Use the next free id.
- Write the repro as steps someone can follow.
- Link the failing test once one exists.
- When it is fixed, set the status to `fixed` and fill in "Fixed in" with the session and PR.

## Open

| ID | Found in | Sev | Area | Summary | Repro | Status | Fixed in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BUG-008 | S05 | P2 | Pipeline | No per-tenant concurrency limit (00 §4.3): one tenant's large drawings can fill every worker. One local worker has nothing to share yet; it matters when workers scale out | — | open, scheduled for S29 | |

## Closed

| ID | Found in | Sev | Area | Summary | Fixed in |
| --- | --- | --- | --- | --- | --- |
| BUG-009 | S07 | P2 | Pipeline / queue | A stage that runs longer than the queue's visibility timeout (30 s by default) is delivered again while it still runs, and the copy runs it twice. A heartbeat thread now pushes the message's visibility out every `stage_heartbeat_seconds` while the stage runs; `tests/integration/test_stage1.py::test_a_long_stage_is_not_delivered_twice` (with its control) | S08 |
| BUG-011 | S08 | P3 | Spec / golden | 01 §5.7 said NURSERY-1 repeats NEVIS-1's template pages 2–3. Page 3 is the same page; page 2 holds the same tables in another layout, so no fingerprint can match it and it goes to the model. The spec now says so | S08 |
| BUG-014 | S08 | P1 | Pipeline / stage 1 | A drawing lost its whole title block when the classifier boxed no title block on any page and read none from its 1024 px overview. On 6199-2-50, a large single sheet, one live run of two did that, and every title-block field was null. Stage 1 now reads the first page whole at the detail size in that case, once. `tests/integration/test_stage1.py` covers it. Found by comparing two live eval recordings | S08 |
| BUG-013 | S08 | P0 | LLM / Anthropic provider | Every call routed to Claude Sonnet 5.5 or Opus 5.5 failed with a 400: the provider forced its answer tool (`tool_choice` `tool`), which those models reject ("type tool and any are not supported for this model"). Stage 1's title block and context crops never ran live; the stand-in model and the cassettes hid it. The provider now asks for JSON output (`output_config.format`, schema made strict by the SDK's `transform_schema`), and treats a refusal, a cut answer or non-JSON as an `LLMError`. `tests/unit/llm/test_client.py` covers it. Found in the first live eval recording | S08 |
| BUG-012 | S08 | P2 | New quote | On a drawing whose pages were reused, a page still below the confirmation threshold read "כמו בשרטוט שכבר פוענח" instead of "ביטחון נמוך. בדקו את הסוג", hiding what the user had to act on. Low confidence now comes first; `model.test.ts` covers it. Found in the fidelity review | S08 |
| BUG-001 | S01 | P1 | CI / licenses | The npm license gate never ran. The script was named `licenses`, and `pnpm licenses` is a built-in pnpm command that shadows it: it printed a usage error and exited 1. The script is now `license-check`, called with `pnpm run`. A probe with an AGPL package now fails as it should | S01 |
| BUG-002 | S04 | P2 | Frontend / theme | Body text rendered at 16px instead of the prototype's 14px: MUI's CssBaseline gives `<body>` the theme's `body1` (1rem), which overrode `base.css`. The theme now sets `body1` to 14px / 1.5, and `e2e/smoke.spec.ts` checks the computed size. Found in the fidelity review | S04 |
| BUG-003 | S04 | P3 | Login (prototype) | The password placeholder runs under the "הצג" button: the input is LTR, so its text starts on the button's side. Fixed in the app (`.pw .input` keeps room); the prototype file is unchanged | S04 |
| BUG-004 | S05 | P3 | Shell / rail | A long user email wrapped onto two lines in the rail foot, under the quota meter. The span had the prototype's ellipsis but could wrap. It now stays on one line, right-aligned, with the full address as a tooltip. Found in the S05 fidelity review | S05 |
| BUG-005 | S06 | P2 | E2E / pipeline | Local `make e2e` failed intermittently: 2 of 10 runs on `s06-golden-eval`. One was inside `make check`, right after the integration tests and the eval: `new-quote.spec.ts` "the run step … can be cancelled" (mobile) never reached the run step, and "a new version does not count" (desktop) waited 30s for `done`. The other run had 8 failures, including a login `toHaveURL`. The E2E API logged no error. `main` passed 5 of 5 on the same machine. The branch's only change on that path builds the worker's LLM client, which makes no calls in E2E. Not reproduced on demand. Root cause was BUG-010. After the fix, `make e2e` passed 20 of 20 back to back (16 of 20 before, the 4 failures always a pair of simultaneous uploads) | S07 |
| BUG-006 | S05 | P1 | Pipeline / queue | A stage message that is never delivered leaves the drawing waiting forever. Stage 1 is sent by the upload's background task after the commit, and every later stage by the worker after it deletes the message it handled. If that send fails, or the process dies first, nothing sends it again. A stuck upload keeps its quota reservation | S07 |
| BUG-007 | S07 | P1 | Pipeline / coordinator | A second copy of a stage message, delivered while the first copy's stage is still `running`, is claimed too, so the stage runs twice. SQS delivers at least once, and the BUG-006 re-send makes a copy more likely | S07 |
| BUG-010 | S07 | P0 | Upload / pipeline | PDFium is not thread-safe, and nothing serialized it. The upload check (`count_pages`, in the API's thread pool) and stage 1's renderer (in the worker thread, which shares the process in `make dev` and E2E) called it at the same time. Two uploads at once, in any two tenants, hung both requests; in a standalone probe the process segfaulted or aborted. This is the root cause of BUG-005 | S07 |
