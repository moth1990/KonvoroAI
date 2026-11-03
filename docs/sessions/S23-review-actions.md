# S23: Review III, actions

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s23-review-actions` |
| **Depends on** | S19, S22 |
| **Status** | in review |
| **PR** | (link) |

## Goal

The estimator can act on the review screen, and every action reaches the server. They can approve a line and move on to the next one to check, delete a line, choose an alternative, change a quantity, and dismiss a finding with a reason. They can enter a price for an unpriced line, change a sale price ("לעדכן גם במחירון?"), switch a line's supplier, and look at profitability. Then they send the quote, which locks it, and open version N+1. The server recalculates stages 6 and 7 after each action, every action except sending can be undone, and each one writes its correction event (09 §10).

## References

- Specs:
  - 09 §7: actions. 7.1 select, 7.2 approve and auto-advance, 7.3 alternative, 7.5 quantity, 7.6 delete (and restoring a derived item), 7.7 dismiss a finding, 7.11 undo, 7.12 send, 7.13 cost entry, 7.14 a price change, 7.15 a supplier switch. §6.1 header (profit, coverage, "אשר ושלח"), §6.3 row (price chips, the profit column, the summary row's profit and "N שורות בלי עלות"), §6.4 detail (price, cost and profit, findings with a reason, alternatives, actions), §8 keyboard (Enter approves, 1–3 pick an alternative, Delete), §9 colours, §10 correction events, §12 (costs only with the permission), §14 performance (an action ≤ 500 ms, an alternative ≤ 1 s).
  - 07 §7.2.2 (several suppliers, which cost wins: the line's chosen supplier first), §7.2.3 (a price change from a quote, what drafts do: "מחיר חדש במחירון: X"), §7.3 (floors), §7.4 (a deleted derived line stays deleted), §7.7 (versions: edit in place before sending, lock, recalculate with a comparison).
  - 06 §6.3, §11 (dismissal with `rule_id` and a reason). 05 §11 (match memory from `row_confirmed`, `sku_replaced` scoped to this quote).
  - 10 §8 (sanity of a typed cost).
- Prototype: lines 872–1004 (`lineRow`, `lineDetail`, `vReview`), 1446–1559 (`data-act`: `approve`, `del`, `alt`, `send`/`dosend`, `newver`, `f-*`, `margin`, `editprice`, `price-db`/`price-here`, `takefresh`, `addcost`, `mkpref`, `savelist`), 1566–1580 (the row's price input, Enter to the next), 582–619 (`status`, `totals`, `prefSup`, `lineCost`, `margin`, `profit`, `coverage`).
- Golden: none (the R track works on the NURSERY-1 fixture, seeded through the real quote API).
- Earlier sessions: S09 (the lines, detail, keyboard; decision 9: Enter waits for approve), S11 (undo stack, toast), S18 (`services/price_list.change_line_price`, `price_history`, the `price_changed` event), S19 (the price list screen and editor), S21 (`services/validation.revalidate_panel`, stable finding ids), S22 (`services/quote_versions.py`: send, recalculate with a preview, open N+1; `line_key` carry on a rerun; decision 4 moved the read-only pricing details here).
- Backlog items for S23: remove `review_screen`; the row sub line, spec vs prototype; review pricing details; undo a line's price change; the editor's toast count; the price list's rounded sale price; version routes and buttons; what a rerun keeps beyond prices and deletions. Draw mode "at the earliest".

## Tasks

Written at kickoff; refined with the answers below.

### Backend
- [x] Line actions in `services/review.py` (routes in `api/routes/quotes.py`), each one transaction: approve (open findings dismissed as "אושר ידנית" once every line they name is approved; the match memory strengthened), delete (its kit parts with it; a derived line stays deleted), restore deleted lines ("החזר"), quantity (a whole number ≥ 1; a kit part follows), alternative (every line with the same signature, each approved), each running stages 6 and 7 again.
- [x] Findings: dismissed with a reason (`intended`, `checker_wrong`, `other` + text), kept in `findings.dismissal` (migration 0018); a dismissed finding's reasons leave its lines; pricing's are not dismissed.
- [x] Pricing actions: a price typed in the row (to the price list as a fixed price, or this quote only), a cost and supplier (to the price list, sanity 10 §8), the price change's two scopes, "עדכן בהצעה", a supplier for this quote only and "הפוך למועדף במחירון". Every line of the product follows a price saved to the list.
- [x] The read model: `fresh_price`, `below_floor`, `price_hints`, `suppliers` (cost, lead days, preferred, in force, chosen), `supplier_id`, `override`, `product_id`, `qty_editable`; the panel's `removed` lines; the quote's floors, `derived_note`, `can_see_costs`; a finding's `source`.
- [x] Undo: `POST /quotes/{id}/undo/{event_id}` puts back what the event's `before.restore` kept (lines, findings, the price-list product, the match memory), marks it `undone` and writes an `undo` event.
- [x] Correction events (09 §10) for every action, with `before` / `after`.
- [x] Versions: `POST /quotes/{id}/send`, `POST /quotes/{id}/versions`, `GET` and `POST /quotes/{id}/recalculation`. A sent version answers 409 to every action.
- [x] A recalculation or a rerun keeps a line's approval, quantity, chosen supplier and replaced SKU by `line_key` (`quote_lines.edits`), and its id.
- [x] The price list's sale price after rounding (`ProductOut`), and `used_in_drafts[].fresh`.
- [x] `review_screen` kept; it comes out at the end of S23b (decision 8).
- [x] Permissions `costs.read` (no cost or margin without it) and `quotes.send`.

### Frontend
- [x] Header: the profit chip in warning colour under the floor, "אשר ושלח" / "פתח גרסה N+1", the locked bar; no edit control on a sent version.
- [x] Row: "מחיר להצעה הזו", "מחיר חדש במחירון: X", "רווח נמוך X%", "אושר", the price cell on an unpriced line (Enter saves and moves on; on the phone in place of the total), the profit column's warning.
- [x] Detail: approve ("אשר שורה" / "אשר למרות הממצא"), delete / "הסר מההצעה", quantity − / +, alternatives with "החלף" and keys 1–3, findings with a reason and "דחה", the price box with "עדכן" and "לעדכן גם במחירון?", "עדכן בהצעה", "שמור למחירון להצעות הבאות", the cost box, the supplier select and "הפוך למועדף במחירון", "קרובים במחירון"; the group's "X פריטים נלווים הוסרו" with "החזר"; the derived footnote.
- [x] Findings box: "הצג רק אותן", "פתח את השורה", "דחה…" with the reason.
- [x] Keyboard: Enter approves and moves on, 1–3, Delete / Backspace; the key hint.
- [x] Send dialog and the recalculation's comparison ("N מחירים חדשים במחירון").
- [x] Every action pushes onto S11's undo stack and shows its toast. The screen waits for the server's answer rather than showing an amount first (decision 10).
- [x] The editor's toast count; the price list's rounded price comes from the server.

### Unit tests
- [x] Vitest: auto-advance order, the next unpriced line, typed amounts, the price chips, an approved line's chips, the removed row, the send warnings, the editor's toast.
- [x] pytest: the edits on a draft (quantity and kit parts, alternative, supplier, kept price, dismissed finding, approval's colour, the column round trip), pre-S23 rows' pricing issues; the contract snapshot.

### Integration tests
- [x] Each action on the fixture (`test_review_actions.py`, 20 tests) and on a pipeline quote (`test_review_pipeline.py`): happy path, refusals, 409 on a sent version, another tenant's 404.
- [x] Stages 6 and 7 again: a price turns a red line green; a deleted derived line stays deleted after a recalculation and comes back with "החזר"; the draft does not follow a price-list change by itself. A quantity that makes a BOM count agree is not tested on its own: the pipeline drawing has no BOM.
- [x] Undo of each action, the price list's included, and `undone` on the event (all six for an alternative on six lines).
- [x] Correction events' shape; no cost, margin or supplier without `costs.read`.
- [x] Send, open N+1, the recalculation's comparison; a recalculation keeps the approval.
- [x] Performance: approve, quantity and an alternative on a 150-line quote under 500 ms / 1 s; every action on the pipeline quote under 1 s.

### UI tests (Playwright)
- [x] Desktop and mobile (`review-actions.spec.ts`): approve and move on, Enter (desktop), a price typed in the row, a price change, "עדכן בהצעה", a supplier, a cost, a dismissed finding, an alternative, the quantity, a delete, each undone; send, lock and version 2.
- [x] Prototype-fidelity screenshots for the new states (`review-send`, `review-price`, `review-locked`), reviewed and accepted by the user; the review baselines rewritten (`make screenshots`).

### Docs
- [x] 09 (§6.3, §7.13, "החלטות ב-S23") and 07 (§6.2, "החלטות ב-S23").
- [x] `docs/db-schema.md` (migration 0018), CLAUDE.md, the roadmap's backlog and the S23b row.

## Acceptance criteria

- [x] Every action in 09 §7.2, 7.3, 7.5–7.7, 7.11–7.15 works from the screen and writes its correction event.
- [x] Every action except sending is undoable, and an undo restores the state before it, including the price list.
- [x] A sent version never changes: every edit route answers 409, and the screen shows the locked bar.
- [x] An action responds in ≤ 500 ms on a 150-line quote, an alternative in ≤ 1 s (09 §14).
- [x] Cost and margin never reach a user without the cost permission (09 §12); no price reaches a model (no model call in these routes).

## Out of scope

Proposed at kickoff (question 2):
- Editing an attribute (09 §7.4, a stage-5 rerun per line), resolving a missing line with a product picker and "מוצר אחר…" (7.8), draw mode (6.6), the bulk brand discount from a row (7.13), pasting from a supplier quote: a new session, "Review IV: product picker".
- One editor at a time and `revision` (09 §11): later, with more than one user.
- The customer document: `export_doc`, S26. The chat's proposal cards: S25.
- Dismissal statistics and the proposal to turn off a rule: S24.

## Open questions

1. **B7, the usability test "before S23", is still open.** Build S23 now, or wait?
2. **Scope.** S23 as listed above, with attribute edit, missing-line resolution, draw mode and the bulk brand discount moved to a new "Review IV" session that shares the product picker?
3. **Spec vs prototype: entering a price on an unpriced line.** 09 §7.13 types a *cost* and a supplier in the detail, and Enter moves to the next unpriced line. The prototype (lines 879, 1566–1580) types a *sale price* in the row's cell, with Enter to the next one and "שמור למחירון" in the detail, and the cost is typed separately in the detail ("שמור עלות").
4. **Spec vs prototype: the row's sub line** (backlog, S09). 09 §6.3 shows SKU, "×2 בשרטוט" and "עמ׳ 4, 5". The prototype, which S09 follows, shows tags, chips and the circuit's load.
5. **Spec vs prototype: approving** (proposed: spec). 09 §7.2 approves any line ("אשר שורה" / "אשר למרות הממצא"), Enter approves, and the selection moves to the next line to check. The prototype approves only an inferred line ("אשר את ההסקה").
6. **Spec vs prototype: an alternative's scope** (proposed: spec, 09 §17.1). 09 §7.3 replaces the SKU on every line with the same signature in every panel. The prototype replaces it on one line.
7. **Spec vs prototype: dismissing a finding** (proposed: spec). 09 §6.4 and §7.7 pick a reason from a list (מכוון / הבודק טעה / אחר) and then "דחה". The prototype has one button per finding with the reason in its label ("שאריות בחזית, התעלם").
8. **The `review_screen` flag** (proposed). The new routes sit behind `review_screen`, and the flag comes out when Review IV finishes the screen. Alternative: take it out at the end of S23.

## Outcome

Filled in at `/session-close`.

- **Done:** The review screen's actions (09 §7.2, 7.3, 7.5–7.7, 7.11–7.15), each to the server and back: approve and move on, delete and "החזר", quantity, alternatives across the signature, a finding dismissed with a reason, a price typed in the row, "לעדכן גם במחירון?", "עדכן בהצעה", a cost, a supplier and "הפוך למועדף במחירון", send and lock, version N+1, the recalculation's comparison. Each writes its correction event (09 §10) and is undone from the toast or the header (`POST /quotes/{id}/undo/{event_id}`). The server runs stages 6 and 7 again after each one, pricing only what it touched (`pipeline/pricing/edits.py`, `stored.py`, `services/review.py`). The read model's new-price, low-margin, supplier, hint and removed-line fields; `costs.read` and `quotes.send`; the price list's rounded price and the editor's toast count. Migration 0018 (`quote_lines.edits`, `findings.dismissal`). The E2E review tenant has the demo price list, and two new tenants carry the action tests.
- **Decisions made:** (with who decided, and why)
  1. **Go ahead without B7** (user, at kickoff; question 1). S23 builds on the spec; findings from the usability test, when it runs, go to the backlog.
  2. **Review IV splits out** (user, at kickoff; question 2). Editing an attribute (09 §7.4), resolving a missing line with a product picker (7.8), draw mode (6.6) and the bulk brand discount from a row (7.13) go to a new session, S23b "Review IV: product picker", which shares the picker.
  3. **Price entry follows the prototype, both inputs** (user, at kickoff; question 3, 09 §7.13 vs prototype lines 879, 902, 1566–1580). A sale price in the row's cell, Enter saves and moves to the next unpriced line, "שמור למחירון להצעות הבאות" on by default in the detail; the cost and supplier typed separately in the detail ("שמור עלות"). 09 §7.13 is rewritten to match.
  4. **The row's sub line stays as the prototype** (user, at kickoff; question 4, 09 §6.3 vs the prototype, S09 backlog). Tags, chips and the circuit's load; the SKU stays in the detail. 09 §6.3 is fixed to match.
  5. **Approving follows the spec** (Claude's proposal, accepted with the plan; question 5). Any line but a missing or manual one; Enter approves and the selection moves to the next line that is not green, wrapping. An open finding is dismissed as "אושר ידנית" once every line it names is approved. The other reasons stay, turned green, with `was`; a line with no price stays red. Approving strengthens the match memory that chose the line (05 §11).
  6. **An alternative's scope follows the spec** (Claude's proposal, accepted; question 6, 09 §17.1). Every line with the same signature, in every panel; without stage 5's results, the lines with the same SKU and wording. The product it had becomes an alternative. Nothing is remembered for the factory (`sku_replaced` is this quote's).
  7. **A finding is dismissed with a reason** (Claude's proposal, accepted; question 7). "מכוון", "הבודק טעה" or "אחר" with its text, behind a "דחה…" button in the findings box, and in the line's detail. Pricing's findings are not dismissed: a price answers them.
  8. **`review_screen` stays** (Claude's proposal, accepted; question 8) until S23b finishes the screen.
  9. **Only what an action touched is priced from the list** (Claude, 07 §7.2.3). Every other line keeps its stored price while its product and SKU stay; derived items and labor are worked out again. A drawing with stage outputs goes through the whole engine; a quote with none (the fixture, a quote built by hand) through its stored lines (`pipeline/pricing/stored.py`), with the same edits code (`edits.py`). A line keeps its id across a recalculation.
  10. **No optimistic display** (Claude, against 09 §14's "shown at once"). The screen computes no amount (09 principle 7), and the server answers within the target, so the screen waits for it instead of showing a total it might take back. In the backlog, to measure in the pilot.
  11. **Undo** (Claude, 09 §7.11). The event table allows no update but `undone`, so each event is written once, with `before.restore`: the lines' state, the findings, the price-list product, the match memory. A product the action created is deleted on undo, unless another quote uses it by then. Sending, opening N+1 and a recalculation are not undoable; the recalculation shows its comparison first.
  12. **The price's reason keeps its pricing issues** (Claude, contract change, 07 §6.2). `issues` and `floor` on the price's reason and `was` on an approved line's (`StatusReason`, schema snapshot updated). A row priced before S23 has them worked out (`load.legacy_issues`).
  13. **"N שורות בלי מחיר" is stage 7's** (Claude). `missing_cost`'s title is the prototype's count and its body the prototype's wording. The fixture's pricing finding now comes from the same code (a warning, as 07 §8 says; it was a hand-written error), so it follows the front-view finding, as in the prototype.
  14. **A price typed in the row** (Claude, with decision 3). With "שמור למחירון" on, the line's product becomes `fixed` at that price (made from the line when it has none) and every line of it is priced; off, an override for this quote. A typed cost is the product's supplier, preferred when it has none.
  15. **Recalculation on the screen** (Claude, no prototype screen). When lines show "מחיר חדש במחירון", the filter row has "N מחירים חדשים במחירון", which opens the comparison; "עדכן את כל השורות" applies it.
  16. **Permissions** (Claude, 09 §12). `costs.read` and `quotes.send` join the single role. Without `costs.read` the quote has no cost, margin or supplier at all.
  17. **Sending with an open error** (Claude, 06 §13 item 3). Not blocked: the dialog warns about red, yellow and unpriced lines and says "שלח בכל זאת".
  18. **Price hints** (Claude, prototype `l.hint`). Up to three products whose name starts as the line's (kind, maker, series), nearest current first, with their price today. A hint, never the line's price (07 §7.2).
  19. **The derived footnote** (Claude, prototype line 978). From `enclosure_includes_default`'s busbars, N and PE, with "שינוי" to the settings.
- **Eval / metrics:** `make eval` in replay: no change against the baseline. Speed (09 §14): approve, quantity and an alternative on a 150-line quote under 500 ms / 1 s (`test_review_actions.py`); every action on a pipeline quote under 1 s (`test_review_pipeline.py`).
- **Checks:** `make check` under Node 22: lint, licenses, secrets, client, unit (1,012 pytest + 234 Vitest), integration (623, after the E2E tenant pin was updated), eval (no change), E2E (170 passed, desktop and mobile), screenshots (61 of 66 in the full run; the five that timed out right after the E2E suite, `review-detail`, `review-red`, `review-showdraw`, `review-finding` dark and `new-run` light, passed rerun alone: BUG-038, no pixel difference).
- **Bugs logged:** BUG-049 (P2, a resolved or dismissed stage-6 issue still coloured its line; fixed), BUG-050 (P2, rows priced before S23 lost their pricing finding on the first action; fixed). BUG-038 seen again in `make screenshots` (four dark review shots, timeouts only).
- **Follow-ups:** S23b, "Review IV: product picker" (roadmap): attribute edit, missing-line resolution, draw mode, the bulk brand discount from a row, then removing `review_screen`. Backlog: one editor at a time (09 §11), the usability test (B7), showing an action before the server answers. Done and struck in the backlog: the row sub line, review pricing details, undo of a price change, the editor's toast count, the rounded price, version routes and buttons, what a rerun keeps. Not covered by a test: a quantity that makes a BOM count agree clearing its finding (no golden drawing in the integration suite has a BOM with a mismatch). The new fidelity screens (send, price dialog, locked) have no screenshot baseline yet.
