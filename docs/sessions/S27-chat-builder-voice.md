# S27: Flags: chat builder, home chat, voice

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s27-chat-builder-voice` |
| **Depends on** | S25 |
| **Status** | in review |
| **PR** | (link) |

## Goal

With `chat_quote_builder` on, an estimator describes a panel in Hebrew on `/build`, in one message or several ("מפסק ראשי 4X63, 12 מא"ז 1X16, פחת 4X40"), and the draft's lines appear beside the conversation, matched to the catalog and priced from the factory's price list by stages 5–7 as on any BOM, with every unpriced line marked; "פתח במסך הבדיקה" opens the draft as a regular quote. With `voice_input` on, the mic records, a transcriber (a stand-in until S29's Amazon Transcribe) turns the speech into text, the same extraction normalizes its terms ("שלוש על שש עשרה" → 3X16A), and the estimator sees what was heard and what was understood. With `home_chat` on, the home prompt routes for real: a panel description to the builder, an attached drawing to a new quote, "בדוק את הצעה …" to the audit, a question about an existing quote to that quote with its chat open, and an ambiguous request to a short question. Each flag off leaves the app and the API as they are today.

## References

- Specs:
  - 13 §2 (`voice_input` depends on `chat_quote_builder`), §3 (the server decides; off is as if the feature did not exist; data stays when a flag goes off; each flag is measured), §4.2 (the chat builder is the BOM path with a conversation as its input: `chat_bom_extraction`, stages 5–7 as usual, the same fill-in rules, the draft opens in review; voice: Transcribe `he-IL`, no Hebrew custom language model, so the same LLM stage normalizes the terms, and the user sees what was heard and what was understood before lines are added), §4.3 (the chat home, its routing table, "the routing is a suggestion, not an action", a small LLM call only when the text doesn't say), §5 (order: builder, then home, then voice).
  - 01 §5.8 (the BOM-only path: each row through stage 4's spelling grammar, a component in 04 §6.3's contract with `source` = `bom`, stages 5–7 as usual, stage 6 data rules only, what the path lacks; S14's decisions on terms and quantities), §4.3 and §4.5 (the quota).
  - 04 §5.1 (the spelling grammar), §6.3 (the component contract).
  - 05 §5.5 (fill-in: `system_default` 30mA), §5.5.1 (an untyped "מפסק" by its current).
  - 07 §7.2.3 (a price changed from a quote, "update the price list too?"), §12 (what the customer document never shows: unchanged).
  - 08 §5.4 (amounts as references, never to the model), §6.7 (`add_line`), §12 (performance), §15.3 (voice "not in version 1": see the open questions).
  - 12 (Amazon Transcribe `he-IL`, real in S29).
  - 00 §3, §7.1–7.2 (an LLM decides inside one stage from a closed list, code checks it; every call through `konboro_llm` with its stage key).
- Prototype: `prototype/konboro-app.html`
  - 1252–1284 (`HOME_SUGG`, `vHomeChat`, `homeSubmit`), 1286–1357 (`PRICE_OF`, `parseBom`, `buildSay`, `startRec`, `vBuild`).
  - 316–328 (`.hero`, `.prompt`, `.prompt-bar`, `.round`, `.round.rec` and its `pulse`, `.hero-sugg`, `.build`, `.build .msgs`).
  - 823 (the new-quote screen's "בלי שרטוט? בנו את ההצעה בצ'אט" card, built in S05), 1554–1556 (`mic`, `mic-home`, `home-sugg`), 1562–1565 (the price input's Enter, the home textarea's Enter), 1603–1606 (`home-form`, `build-form`).
  - 561–563 (the three flags' names and descriptions on the settings screen, built in S24).
- Golden: none. No flag here moves the drawing pipeline (13 §3 rule 6). The builder's extraction and the home routing get their own eval sets (Eval below).
- Earlier sessions:
  - S04: the chat home's layout, keyword routing (`screens/homeRoute.ts`) and the `/build` placeholder; no mic.
  - S14: the BOM path (`pipeline/bom/`, `association/bom.py`: terms, the grammar, quantities, the merge).
  - S20–S22: stages 5–7. S23: the review actions, `pipeline/pricing/edits.py`, lines carried by `line_key`. S23b: stage 5 for one line in code.
  - S25–S25b: the chat drawer, `strip_amounts`, the stand-in model's chat answers, `list_quotes` matching a quote by the user's words in code, `chat_conversations`.

## Design (proposed; confirm under Open questions)

1. **A chat build is a drawing with no files.** A `drawings` row with `origin` = `chat` (new column), `input_kind` = `bom_only`, one panel, and a quote. Its stage outputs are written like a BOM-only drawing's: stage 1's (the panel, no pages) by code when the build starts, and the conversation's items as its `bom_table` artifact. So the draft has components, a panel and stage outputs, and the review screen's actions, product picker, "why", overlay and export work on it unchanged. The quote's `drawing_id` is set (`docs/db-schema.md` says it is null for a chat quote; that line changes).
2. **One message, one round trip, in the request** (like a review action): `chat_bom_extraction` → the code check → rows appended → stages 4, 5, 6 (data rules only, 01 §5.8 item 3: no `validator_review` call per message) and 7 through the stages' own `run(ctx)`. A line the user touched keeps its state by `line_key` (S23 decision 2). Stage 5 asks `catalog_disambiguation` as it does in the pipeline, and reuses its earlier answer for a component whose signature didn't change.
3. **`chat_bom_extraction`** (the route is in `config.py` already) is shown the message, with amounts stripped as in the chat (08 §5.4), the panel names so far, and the draft's lines by short name (`L1`…: description and quantity, no price). It answers items to add `{text, quantity, panel, quote}`, and changes to existing lines `{line, action: set_qty | remove, quantity, quote}` (decision 4). For an item: `text` in the drawing's spelling ('מא"ז 1X16A'), `quote` the words of the message it came from. **Code checks** that `quote` is in the message and that every number in `text` and `quantity` is in `quote`, as digits or as Hebrew number words (a converter in code: "שנים עשר" → 12, "ארבע על ארבעים" → 4X40). An item that fails is dropped and named in the reply. A change is checked the same way, and its line must be one of this draft's live lines. The checked `text` goes through stage 4's BOM reading (`association/bom.read_item`: terms, grammar): the model never sets a family or a value itself (00 §3, non-negotiable 3).
4. **Panels.** Lines go to the build's one panel; a message that names a panel ("בלוח 2: …") opens that panel, by the BOM path's panel names.
5. **Voice.** A `Transcriber` interface (`services/transcribe.py`) with a stand-in that returns the prototype's sentence, until S29. `POST /builds/{id}/voice` takes the recording (WebM/Opus, MP4/AAC or WAV, at most 60 s and 2 MB), transcribes it, and runs the same extraction. The recording is never stored; the transcript is kept as the message's "heard" text.
6. **Home routing** (`services/home_route.py`). Code first: an attached file goes to `/new`; audit words go to `/audit`; a quote named by number or name (matched in code against the factory's quotes, as `list_quotes` does) with a question goes to `/review/:id` with the chat open and the question sent; a panel description (a BOM term and a value the grammar reads) goes to `/build` with the text sent; "מחירון" goes to `/prices`. Anything else goes to a new stage key `home_intent` (Haiku), shown the text only (amounts stripped), which picks from `build`, `audit`, `quote_question`, `price_list`, `unclear`. `unclear`, or a question that names no quote or several, gets a short question with choices under the prompt, never an action.

## Tasks

### Backend
- [x] Migration 0024: `drawings.origin` (`upload` | `chat`) and `build_messages` (`bmg_`, by drawing, since the quote comes at the first line); the RLS factory row; `docs/db-schema.md`.
- [x] `services/build.py`: start a build (drawing, panel, stage 1–3 outputs); a message (extraction, the check, the rows, stages 4–7 in the request; the quote and its quota at the first line, decision 2); changes made on the rows (decision 4); a recording as a `pending` message that applies on "הוסף" (decision 1); undo of the last applied message. The earlier message and its question go with an answer to it.
- [x] `pipeline/inline.py`: stages run in the request with their outputs and `stage_runs` written as the coordinator writes them, and a write-through storage for one message (S3Mock: 5.5 s → 3.5 s for a first message, 3.7 s → 2.3 s after).
- [x] `pipeline/bom/chat.py` (the check, the rows, `tidy`) and `pipeline/bom/numbers.py` (Hebrew number words, "חד/דו/תלת"); `BomTable.source` = `chat`, `BomRow.removed`; components named by their first row (`by_row`); stage 5 keeps its answers for a chat build (`s5-asked.json`); stage 6 without its agent on a chat build.
- [x] `konboro_llm/stages/chat_bom_extraction.py`: prompt, schema; the lines by short name with the words said; short names replaced by descriptions in its question.
- [x] `konboro_llm/stages/home_intent.py` and its route (Haiku); `services/home_route.py`: code rules, quotes matched by name (whole, with a prefix, without the file's extension), project, customer and drawing number on the text as typed, "ההצעה האחרונה", the model, the question with choices and each quote's time.
- [x] `services/transcribe.py`: `Transcriber`, `StandInTranscriber` (the prototype's sentence), the checks (type, empty, 2 MB).
- [x] Routes: `POST /builds`, `GET /builds/{drawing_id}`, `POST /builds/{drawing_id}/messages`, `…/messages/{id}/apply|dismiss`, `…/undo`, `POST /builds/voice` and `/builds/{drawing_id}/voice` (also `voice_input`), behind `chat_quote_builder`; `POST /home/route` behind `home_chat`. Each with its permission; `test_api_routes.py` covers them.
- [x] A price typed on the build table through the review's own price action and its "לעדכן גם במחירון?" choice (decision 3): the existing `price-entry` route, no new backend.
- [x] The stand-in model (`devtools/fake_llm.py`): `chat_bom_extraction` (the prototype's `parseBom`, numbers from words, the corrections) and `home_intent`.
- [x] A structured log line for each build message and each recording (13 §3 rule 4).
- [x] `make gen-client`.

### Frontend
- [x] `screens/build/` (`Build.tsx`, `model.ts`, `recorder.ts`): the prototype's `vBuild`, the price field with "לעדכן גם במחירון?" and undo in the toast, "פתח במסך הבדיקה", "בטל את השינוי האחרון", "פריטים נלווים ועבודה (N)"; `/build` → `/build/:drawingId` at the first message; a new build on `/build` again; the quota meter and the recent list refreshed at the first line; "הצעה חדשה" marked on the rail and the tab bar (prototype `shell("new")`).
- [x] Voice: `MediaRecorder`, a stop on the second click or at 60 s, the upload, the card with "שמעתי: …", what was understood, "הוסף" and "תקן"; the stand-in's note under the field.
- [x] Home: `POST /home/route` replaces the keyword rules; the mic (`mic-home` → `/build`, recording); the question with its choices (a quote's time only when two share a name); "מה חסר בהצעה של …?" on the latest quote; the review opened with the chat and the question sent once (a one-shot token).
- [x] The prototype's CSS (`.build`, `.build .msgs`, `.round.rec`, `pulse`) in `theme/app.css`; dark checked in the fidelity shots.

### Unit tests
- [x] `tests/unit/test_build_check.py` (50): the number words, the check (quote, numbers, quantities, panels, changes), the rows (merge, a line keeps its first row, set and add), the stand-in through the check, the prompt.
- [x] `tests/unit/test_home_route.py` (22): audit and price words, a panel description, a quote's words, questions, "בלי שרטוט", the recording's checks, the stand-in transcriber.
- [x] Vitest: `screens/build/model.test.ts` (8), `screens/homeRoute.test.ts` (6).

### Integration tests
- [x] `tests/integration/test_build.py` (16): the prototype's message (three lines, the RCD's 30mA, the main switch an MCB by its current), a merge, a correction and a removal with undo, a message with no product, the quota once at the first line, a factory at its limit, the draft read and changed like any quote and kept by later messages, a typed price, the overlay and the export on a draft with no pages, the flag, another factory, no price to the model; voice: the card waits for "הוסף" and the recording is stored nowhere, "תקן", a recording that isn't audio or is too big, the two flags.
- [x] `tests/integration/test_home_route.py` (14): each routing row, a quote named whole, by its project, with a date, with a prefix; two quotes, none; the builder off; `home_chat` off; the model sees the text only.

### UI tests (Playwright)
- [x] Desktop and mobile: `e2e/build.spec.ts` (5 × 2), `e2e/voice.spec.ts` (2 × 2, a tone made in the page as the microphone: Chromium's fake device hangs in headless on macOS), `e2e/home.spec.ts` (the mic, the latest quote's question, the unclear request).
- [x] Prototype-fidelity shots (`build-empty`, `build-lines`, `build-voice`, `home-ask`, `home-chat`; light and dark, desktop and phone). Accepted by the user (2026-11-06).
- [x] `home-chat`'s four screenshot baselines rewritten after the review (`e2e/visual/update.sh -g home-chat`: the mic and the fourth suggestion). No new baselines, as in S24–S26.

### Eval
- [x] `eval/build_set.json` (42 cases, 51 turns: typed, spoken and multi-turn), `eval/home_set.json` (30 requests), `eval/build.py`, in `make eval`.
- [x] Recorded live (`EVAL_RECORD=missing`, `EVAL_MAX_USD=3`); only the new stages' calls were missing, the golden set and the chat replayed unchanged; the baseline written with `make eval-baseline` (8 new metrics).

### Docs
- [x] 08 §15.3 resolved; 13 §4.2–4.3 "החלטות ב-S27"; 00 §7.1's model map (`home_intent`, `chat_bom_extraction`).
- [x] `docs/db-schema.md`: `drawings.origin`, `build_messages`, the chat quote's `drawing_id`, `bmg_`.
- [x] CLAUDE.md: the builder, the home's routing, the transcriber, the eval; the prototype map.
- [x] `eval/README.md`; the roadmap's backlog (four follow-ups); BUG-099.

## Acceptance criteria

- [ ] The prototype's message gives three lines: a 4P 63A main switch (its class by its current), 12 × MCB 1P 16A, an RCD 4P 40A 30mA (`system_default`), each matched in the sample catalog and priced from the demo price list. **Met but for the main switch**: it is typed an MCB by its current (05 §5.5.1), and the sample catalog has no 4P 63A MCB, so the line is red, "לא מצאנו בקטלוג", with a price field, as on any BOM. The MCBs (ABB S201M-C16, ₪42) and the RCD (ABB F204, ₪300) are matched and priced (`test_build.py`, and live in `make dev`).
- [x] The prototype's transcript gives four lines with the right numbers, and no line carries a number the message doesn't have (`test_a_recording_waits_for_add…`; `build_invented_values` 0 of 79 in the eval).
- [x] No price, cost, margin or customer detail reaches `chat_bom_extraction` or `home_intent` (`test_no_price_reaches_the_model`, `test_the_model_sees_the_text_only`; `build_money_to_model` 0 of 54, `home_money_to_model` 0 of 10).
- [x] The build eval: at least 95% of lines exact on replay (98.7%, 75 of 76), no invented number (0); the home eval: every request to its route (30 of 30).
- [x] Each 13 §4.3 row routes as the table says; an ambiguous request gets a question, never an action (`test_home_route.py`, the home E2E).
- [x] Each flag off: as today (S04's home, no `/build`, no mic, the routes 404).
- [x] A draft built in chat opens in the review screen, and the review's actions work on it: tested a quantity, a typed price, the overlay and the export; the others run the same `review.refresh` on the same stage outputs.
- [x] A build message answers within 3 s on the stand-in model: about 0.3 s in the integration tests; 3.5 s for a first message and 2.3 s after on `make dev`'s S3Mock, whose bucket holds every dev upload (each S3 call ~0.25 s there). With Claude, `chat_bom_extraction` took 4.0 s on top.

## Out of scope

- Amazon Transcribe itself, its IAM and streaming: S29 (infrastructure).
- Streaming the answer over SSE: the chat's backlog item.
- A tenant's own BOM words: the backlog item from S14.
- Recording in noise and real estimators' recordings (13 §6 item 1): the pilot.
- The usage table for every flag (S26's backlog item); S27 logs, as S26 did.

## Open questions

1. ~~Voice: confirm before adding, or add at once?~~ Decided (decision 1).
2. ~~When a chat build counts in the monthly quota.~~ Decided (decision 2).
3. ~~A price typed on the build table.~~ Decided (decision 3).
4. ~~Corrections by message.~~ Decided (decision 4).
5. ~~08 §15.3 says voice is "not in version 1"; 13 §1 and §4.2 put it in 1.0 behind `voice_input`.~~ Decided (decision 5).

## Outcome

- **Done:** the chat quote builder behind `chat_quote_builder`: a build is a drawing of `origin` = `chat` with stage outputs like any BOM-only drawing; each message runs `chat_bom_extraction`, a code check of every number against the message, and stages 4–7 in the request; corrections by message with undo; a typed price with "לעדכן גם במחירון?"; the quote counted at its first line; it opens in the review screen, where every action, the overlay and the export work on it. The chat home routed by the server behind `home_chat` (code first, `home_intent` for the rest, a question with choices when it can't tell, a question about a quote opens it with the chat and asks). Voice behind `voice_input`: the browser's recorder, a stand-in transcriber until S29, the card that waits for "הוסף", the recording never stored. Two eval sets in `make eval`, recorded live and in the baseline. Everything in Tasks is done; acceptance criterion 1 is met but for the main switch, which the sample catalog has no product for.
- **Decisions made:** (with who decided, and why)
  1. **Voice is confirmed before it adds anything** (the user, 2026-11-06; the spec wins over the prototype's `startRec`). After a recording, a card shows "שמעתי: …" and what was understood (lines to add, quantities to change, lines to remove), with "הוסף" and "תקן" ("תקן" puts the transcript in the input to edit and send). Nothing changes until the click. A typed message applies at once.
  2. **A chat build counts once, at its first line** (the user). The draft becomes a quote when a message first adds a line, and the quota is counted then, in the same transaction. A factory at its limit can't start a build, like "הצעה חדשה" (01 §4.3 check 1). A build that never adds a line is not counted.
  3. **A price typed on the build table asks, as in review** (the user; 07 §7.2.3, S23). "לעדכן גם במחירון?" with "רק בהצעה הזו" and "גם במחירון", through the review's own price action, its correction event and undo. Not the prototype's save straight to the price list.
  4. **A message can add, change and remove lines** (the user; the prototype only adds). The model may also set a line's quantity or remove a line, naming the draft's lines by short names (`L1`, `L2`…, as in the review chat), applied at once with undo. Code checks each change: the line exists in this draft, and a new quantity is a number written in the message. The reply says what changed. A change is made on the build's rows, the source the lines come from (Claude, at build time): a later "ועוד 2" adds to the corrected quantity, and undo puts the rows back. The review's own actions on the same draft (a quantity, a price) are line edits, carried by `line_key` through every later message. Unlike the review chat (08 §1 principle 1), there is no proposal card: the build is the estimator's own draft being written, and every change is on the table in front of them with undo.
  5. **Voice is in version 1.0** (Claude proposed, the user confirmed with the plan's go-ahead): 13 §1 and §4.2 are later than 08 §15.3 and decide it explicitly; 08 §15.3 now says so, and voice stays out of the review screen's chat.
  6. **A build is a drawing with no files, its stages run in the request** (Claude, design 1–2): so the review screen, the picker, "why", the overlay and the export need nothing new, and the estimator gets the lines in one round trip; stage 6 runs its rules only (01 §5.8 item 3), and stage 5 keeps its model's answers for the build (`s5-asked.json`). A write-through storage for one message cut a first message from 5.5 s to 3.5 s on the dev S3Mock.
  7. **A chat build's components are named by their first row** (Claude): stage 4's names are positional, and a removed row would rename every line after it and carry a typed price to the wrong line.
  8. **What the model must say, code checks** (Claude, design 3): its words are in the message, every number in a line was said (digits, or Hebrew words read by `numbers.py`, with "חד/דו/תלת" for 1P/2P/3P and "שלושים ושתיים עשרה" as 32 then 10), a change names a line of this draft. Code also spaces glued values ("1P16A" → "1P 16A"). The model sees each line's words as said, and the message before when it asked a question; its question's short names become descriptions.
  9. **A said current gets its "A"** (Claude, from the eval): the model wrote "מגן מנוע 2.5-4" as said, which the grammar can't read; the prompt asks for the unit, which invents no number. Changing the drawing grammar instead would move the golden set.
  10. **The home matches quotes on the text as typed** (Claude, from the dev data): `strip_amounts` read the "06.11" of a chat build's name as a price (BUG-099). A name is matched whole without its file's extension, with a prefix on its first word, then by its distinctive words; "ההצעה האחרונה" is the latest; the choices show a quote's time only when two share a name.
  11. **A build's quote is named "הצעה בצ'אט dd.mm HH:MM"** in the factory's time zone (Claude): two builds on one day are told apart.
  12. **The voice E2E records a tone made in the page** (Claude): Chromium's fake microphone hangs in headless on macOS; the page's own `MediaRecorder` still records a real stream.
  13. **No new screenshot baselines** (Claude, as S24–S26): the chat home's four were rewritten after the user accepted the fidelity shots.
- **Eval / metrics:** `make eval` in replay: the golden set and the chat set unchanged (no regression; only S27's calls were missing from the cassettes, recorded live with `EVAL_RECORD=missing EVAL_MAX_USD=3`). New, in the baseline: `build_line_accuracy` 98.7% (75/76), `build_turn_accuracy` 98.0% (50/51), `build_clarification_accuracy` 100% (51/51), `build_invented_values` 0 of 79, `build_dropped` 1 of 51 (s07: the model read "שלושים ושתיים עשרה קילו" as 12kA and the check dropped it), `build_money_to_model` 0 of 54, `home_route_accuracy` 100% (30/30), `home_money_to_model` 0 of 10. Live in `make dev`: `chat_bom_extraction` took 4.0 s with Sonnet.
- **Bugs logged:** BUG-099 (P3, open: the review chat strips a date like "06.11" before the model), BUG-100 (P3, watch: `bom.spec.ts` timed out once on mobile in the full E2E run).
- **Follow-ups:** in the roadmap's backlog: grow the builder's test set at the pilot; a value changed by message; an enclosure said in the builder; `validator_review` on a chat build. Amazon Transcribe is S29's (its roadmap row).
