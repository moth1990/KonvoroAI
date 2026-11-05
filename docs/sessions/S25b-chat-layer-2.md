# S25b: Chat layer II

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s25b-chat-layer-2` |
| **Depends on** | S25 |
| **Status** | in review |
| **PR** | (link) |

## Goal

The chat answers "why" about one line from its trace and a crop of the drawing, and points at the component on the drawing. It compares the open quote with another quote of the same factory, line by line through the components' signatures. A proposal that swaps a brand or a SKU can be remembered for this customer or for the whole factory, so the next drawing gets the same product, and undo takes the memory back with the change.

## References

- Specs:
  - 08 §6.4 (`explain_line`: its input, output, and the rules: only from the trace and the crop, read vs filled in, `focus`), §6.5 (`compare` with another quote by signatures), §7.1 (`remember_options`, `remember_default`), §7.3 (the card's memory row), §7.4 (scopes, `quote_only` default, prices always `quote_only`), §7.5 (undo), §10 (isolation: another quote of the same factory only; drawing text is data), §11 (errors), §12 (`explain_line` p95 12 s), §13 (the test set and targets), §15.6 (the explanation model with vision).
  - 05 §3 (the signature), §5.3 (memory: customer before factory, never over the drawing's SKU or brand), §11 (the memory record and what writes it).
  - 00 §7 (the `line_explanation` route: one line's trace and the crop; no amounts, not the rest of the conversation).
  - 09 §7 "ללמידה" (a row's `sku_replaced` is this quote only; "לזכור" for a customer or the factory only from the chat or an explicit action).
- Prototype: `prototype/konboro-app.html` lines 1007–1064 (`vChat`, `propCard`). The prototype has no memory row on the card and no compare or explanation answer; they follow the existing classes.
- Golden: none for the pipeline. The chat test set (`eval/chat_set.json`, S25) grows with this session's requests, on NURSERY-1.
- Earlier sessions:
  - S20: `services/match_memory.py` (`remember`, `approve`), stage 5's recall (`pipeline/matching/factory.py`: customer first, then factory, by signature and brand context).
  - S22: `pipeline/pricing/diff.py`, used by `compare` against a version.
  - S23: undo restores `before.restore["memory"]`.
  - S25: the tool loop, names and money refs, `propose_change`, apply and undo of a whole proposal, the answer check (which strips `{{instance:…}}` until this session), the drawer and the card.

## Tasks

### Backend
- [x] **`explain_line`** (08 §6.4), a tool the coordinator calls with a line and the user's question.
  - Code builds the sub-agent's input: the line's trace as `get_line_details` shows it without the price trace (00 §7: no amounts), the instances and their bboxes, the spans the line's values were read from, and one crop of the drawing around the line's instances with each instance boxed. On a line with no instance (derived, manual, missing) the tool answers from the trace with no crop.
  - The sub-agent runs on `line_explanation` through `konboro_llm` (`konboro_llm/stages/line_explanation.py`: prompt and output schema), not the rest of the conversation.
  - Code checks its answer: every cited line, instance and span exists on this line; `trace_supported` false makes the coordinator say there is not enough information and offer the drawing.
  - The tool returns the answer, instance names (`I1…`) for `{{instance:…}}`, and a `focus` UI action.
- [x] **`compare` with another quote** (08 §6.5).
  - `list_quotes` (decision 1): the factory's other quotes as `QT1…QT10`, newest first, with date, status, version and line count; no name, no customer, no amount. `compare` takes `quote` (an alias) or `version`.
  - Lines are paired by the component's signature, then by SKU for lines with no component (derived, manual). Output: lines added, removed and changed (SKU, quantity, attributes, unit price and line total as refs), the total difference as a ref (net before VAT; the two quotes' panels need not match, so no per-panel sums).
  - Only quotes of the same tenant, under RLS; another tenant's id answers `unknown_quote`.
  - The signature is kept on `quote_lines` (migration 0022, `signature`), written by stage 7 from stage 5's match and by the fixtures' seed, so a quote with no stage outputs (the fixtures) can be compared.
- [x] **Remember** (08 §7.4, 05 §11).
  - A proposal's `remember_options`: `quote_only` always; `customer` when the quote has a customer; `tenant`. Only `replace_brand` and `replace_sku` changes offer more than `quote_only`; prices, margins and the discount stay `quote_only`.
  - Apply takes `remember` in a new optional body (`ChatApplyIn`). For each line the proposal changed to a new SKU, write `match_memory.remember` with the line's signature, the customer or none, and the line's `brand_context` (decision 6). A line that kept its SKU (no match in the new brand) writes nothing.
  - `tenant` checks `SETTINGS_WRITE` (08 §7.4, "ניהול העדפות").
  - The correction event keeps the memory rows' previous state in `before.restore["memory"]`, so undo of the proposal deletes or restores them.
- [x] **Answer check**: `{{instance:I…}}` is kept when the instance was named in this conversation, removed (with `invalid_ref`) otherwise.
- [x] Tool schemas and prompt in `konboro_llm/stages/chat_command.py`: `explain_line`, `compare`'s other quote, the rule that "why" about one line goes to `explain_line` when `get_line_details` does not answer it.
- [x] Stand-in model (`devtools/fake_llm.py`): scripted answers for an explanation, a compare with another quote, and the `line_explanation` stage.
- [x] Seed: a second demo quote on NURSERY-1's components (a few lines changed) so compare has a quote to compare against; the fixture lines' signatures.
- [x] `make gen-client`.

### Frontend
- [x] `{{instance:…}}` in the chat's text: a chip that focuses the drawing on that instance (the pane's "הצג בשרטוט").
- [x] The explanation's `focus` UI action boxes the component on the drawing when the answer shows.
- [x] The proposal card's memory choice (decision 2), three `.fchip` chips, with "רק בהצעה הזו" selected; sent with "החל". Hidden when the proposal offers only `quote_only`; "לזכור ללקוח" hidden when the quote has no customer.
- [x] `{{quote:Q…}}` in the text shows the quote's real name, resolved by the server like money refs; compare's differences as amounts.

### Unit tests
- [x] `explain_line`'s input: no amount, no price trace, no other turn (`tests/unit/chat/test_explain.py`). The crop itself (one page, framed, a PNG with a stable cassette key) is checked in the integration test.
- [x] The explanation check: an unknown instance, span or line is dropped; `trace_supported` false.
- [x] Compare by signature: pairing, a line with no signature paired by SKU, added and removed, the differences as refs.
- [x] The memory context per brand source (`test_matching.py::test_the_memory_context_is_the_customers_brand_or_none`). Remember options per change type and customer, and which lines write memory, are integration tests (they need the quote).
- [x] The answer check keeps a named instance and drops an unknown one.
- [x] The no-money test covers the `line_explanation` request and the compare result.
- [x] Vitest: the instance chip, the memory choice's states.

### Integration tests
- [x] `explain_line` on NURSERY-1 through the stand-in model: the crop is made from the page image in S3, the call is logged in `llm_calls` on `line_explanation`, the answer focuses the instance.
- [x] Compare with the second demo quote, and with another tenant's quote id → `unknown_quote`.
- [x] Apply with `customer` and with `tenant`: the memory rows are written; stage 5 on a fresh run of the same components picks the remembered SKU; undo removes them and puts back a row that existed before.
- [x] `tenant` without `SETTINGS_WRITE` → 403 (`proposals.apply` with a role that has no permissions; v1.0 has only the owner); `customer` on a quote without a customer, and any memory on a quantity change → 422 `remember_not_offered`.

### UI tests (Playwright)
- [x] Desktop and mobile projects (`e2e/chat.spec.ts`, 16 passed):
  - Ask "why" about a line: the answer shows and the drawing boxes the component; the instance chip focuses it again.
  - Ask to compare with the other quote: the answer lists the differences.
  - A brand proposal, choose "לזכור למפעל", "החל", then undo.
- [x] Fidelity shots: the card with the memory choice (`chat-proposal`), an explanation answer (`chat-explain`) and a compare answer (`chat-compare`), desktop and mobile. `make fidelity`.
- [ ] Prototype-fidelity report reviewed by the user.

### Eval
- [x] 15 new requests in `eval/chat_set.json` (77 in all): "why" questions (explain vs details), compare with another quote, "תזכור את זה" phrasing, and an explanation where the trace does not explain.
- [x] Recorded live with `EVAL_RECORD=missing`, within the $8 of decision 4; `make eval` against the baseline (replay, report `20261105T174111Z`).

### Docs
- [x] `docs/db-schema.md`: `quote_lines.signature` and `brand_context`, `chat_proposals.remember_options` and `remembered`, `memory_saved`, the `Q`/`I` names.
- [x] Spec fixes: 08 §6.1 (`list_quotes`), §6.4 (what the sub-agent does not get, the code check), §6.5 (pairing, how the other quote is named), §7.3 (the memory chips), §7.4 (what is written, undo, the permission); 05 §6 (`brand_context`).
- [x] CLAUDE.md: the chat paragraph, the built list, `make seed`.
- [x] Roadmap status.

## Acceptance criteria

- [x] No request of the test set, the E2E conversation or `explain_line` carries an amount from the quote (08 §13.2, checked automatically).
- [x] `explain_line` cites only instances, spans and lines that belong to the line; a value with `source` `tenant_default` is explained as the factory's default, not as read.
- [x] Compare never reads another tenant's quote, and pairs NURSERY-1's lines with the second demo quote's by signature.
- [x] A proposal applied with `customer` or `tenant` writes the memory that stage 5 then recalls on the next drawing; undo removes it.
- [x] Chat test set: tool and arguments ≥ 95%, clarification ≥ 90%, and 0 for amounts to the model, unsupported claims and instructions from the drawing.

## Out of scope

- Growing the chat set to about 200 requests: before Gate 2 (S25 decision 4).
- Settings changed from the chat with approval (08 §15.4).
- Streaming the answer, `set_attribute` for any value, "ליצור מחדש" with the original changes (backlog, from S25).
- The stage-3/4 reading bugs found in S25 (BUG-066 to BUG-072): the reading session.

## Open questions

None open. The answers are under Decisions made.

## Outcome

Filled in at `/session-close`.

- **Done:** everything under Tasks and the acceptance criteria, except the user's review of the fidelity shots (`chat-proposal`, `chat-explain`, `chat-compare`), which is open.
  - `explain_line`: the line's trace without money, one framed crop of the page in S3, the `line_explanation` sub-agent through `konboro_llm`, its citations checked in code, the instances named `I1…` for `{{instance:…}}` chips that box the component on the drawing.
  - `list_quotes` and `compare` with another quote: aliases `QT1…`, names resolved on the screen only; lines paired by `quote_lines.signature`, then SKU; added, removed and changed lines with the amounts as references. A second demo quote on NURSERY-1 (`NURSERY, הצעה קודמת`) in the seed, the E2E tenants and the eval.
  - Remember: `remember_options` on brand and SKU proposals, three chips on the card, apply with `customer` or `tenant` writes the match memory under each line's signature and `brand_context`, `memory_saved` events that undo takes back.
  - Migration 0022, the regenerated client, the stand-in model's scripted answers, 15 new requests in the chat set.
  - Tests: 16 integration tests in `test_chat_memory_compare.py`, the unit tests for compare, explain and the answer check, Vitest for the chips, Playwright desktop and mobile in `chat.spec.ts`.
- **Decisions made:**
  1. **The other quote is named by an alias** (user, at kickoff). A `list_quotes` tool gives the model `QT1…QT10` with the date, status, version and line count, never the quote's name or customer. The screen shows `{{quote:QT2}}` as the quote's real name, as it does money refs. When the request does not settle which quote, the model asks with those aliases as chips. 08 §6.5 is fixed to say so.
  2. **The memory choice is three chips** (user, at kickoff): the prototype's `.fchip` row under the diff, "רק בהצעה הזו" selected first, then "לזכור ללקוח הזה" and "לזכור למפעל". Only on brand and SKU swaps; "לזכור ללקוח" only when the quote has a customer. 08 §7.3 is fixed to say so.
  3. **The card always starts at "רק בהצעה הזו"** (user, at kickoff). The model cannot pre-select a scope; when the user says "תמיד", it may say in its text that the card offers "לזכור".
  4. **The chat set is recorded live once, all of it, capped at $8** (user; at kickoff $5 for the new requests, raised while building). The cassettes key on the system prompt and the tools' definitions, which S25b changed, so S25's 62 requests are recorded again with the 15 new ones: `EVAL_MODE=live EVAL_RECORD=missing EVAL_MAX_USD=8`.
  5. **The signature is kept on the line** (Claude): `quote_lines.signature`, written by stage 7 from stage 5's match and by the fixtures' seed, so compare and memory work on a quote with no stage outputs. A line with no signature (derived, manual) pairs by SKU and never writes memory.
  6. **A memory's brand context is the customer's brand or none** (Claude, changed while building): stage 5 keeps on each match the context a memory for it belongs to, `brand_context`, which is the customer's brand when the customer's preference chose the brand and null otherwise. The first version used the brand the drawing named, but a brand the drawing or its notes name wins over memory (05 §5.3), so such a memory would never apply; under null it fills in when the next drawing names no brand. 05 §6 has the field.
- **Eval / metrics:** the chat set, 77 requests, recorded live and replayed (report `20261105T174111Z`); the pipeline's metrics match the baseline.
  - tool and arguments 98.4% (62/63; S25: 95.8%), clarification 92.2% (71/77; S25: 93.5% on 62), forbidden calls 0, amounts to the model 0 of 395, instructions from the drawing 0 of 4, invalid references 0.
  - The clarification misses are six of S25's requests (o01, o02, o04, o05, o07, m06) that decline or answer correctly and then offer a next step with option chips, which the scorer counts as a clarifying question. S25 had four of these.
  - Two prompt rules came from the live runs: a question about which quotes exist is answered by `list_quotes` alone (k04), and a question gets an answer, not a proposal, even when it points at a mistake (x02).
  - `eval/baseline.json` takes these chat metrics (accepted by the user); only the chat's totals moved.
  - The cassettes keyed on earlier prompts were deleted: `eval/cassettes/chat_command` holds only the 383 this prompt uses.
- **Bugs logged:** BUG-038 seen again (four picker shots timed out in `make check`, all passing in a full rerun). BUG-097 (P3, open): the quote chip's contrast in dark mode, from the fidelity shots. BUG-077 to BUG-096 were found by the user during this session on 25.26.100's live runs and fixed on `fix-25-26-100-main-panel`, merged into this branch; their rows name that branch.
- **Follow-ups:**
  - The user's review of the three new fidelity shots, desktop and mobile; BUG-097 with it.
  - The clarification metric counts an offer with option chips ("להכין אותה?") as a clarifying question; 08 §13 could tell an offer from a question when the chat set grows before Gate 2 (S25 decision 4).
  - `eval/cassettes/chat_command` has no pruning: each prompt change leaves the old set behind. This session deleted them by hand; a `make eval-prune` belongs with the eval harness.
