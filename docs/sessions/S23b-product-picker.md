# S23b: Review IV, product picker

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s23b-product-picker` |
| **Depends on** | S23 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#28](https://github.com/moth1990/KonvoroAI/pull/28) |

## Goal

The review screen is complete. The estimator can:
- change a line's current or breaking capacity, which matches the line again;
- resolve a missing line from up to three products, from "מוצר אחר…" (a catalog search), or with "אין כאן רכיב";
- mark a component the detection missed by drawing a rectangle on the drawing and picking a product;
- price every unpriced line of a brand at once from a row ("מחירון יצרן פחות __%").

Each action is undoable and writes its correction event, as in S23. Then `review_screen` comes out.

## References

- Specs:
  - 09 §6.4: the detail. "מה נקרא מהשרטוט" with current and breaking capacity in a dropdown, the missing line (explanation, up to 3 products, "מוצר אחר…", "אין כאן רכיב"), the unmatched line (an empty current dropdown), the price box's bulk brand entry.
  - 09 §6.5–6.6: "סמן רכיב שפוספס" in the toolbar (a parsed page, a draft only); draw mode (a cross cursor, a rectangle ≥ 10 points, the product picker, a manual line with an instance there, the panel by the rectangle's centre, the rectangle kept as a detector example).
  - 09 §7.4 (attribute edit: source `user`, the confidence penalty removed, stage 5 for the line with the same brand, then 6 and 7; "אין בקטלוג…" when nothing fits; `attribute_changed`), §7.6 (deleting a missing line: a negative example), §7.8 (`missing_resolved`, a positive example), §7.13 (the bulk brand entry, yellow "מחיר: הנחה ממחירון יצרן", `brand_discount_set`), §8 (1–3 for a missing line's products, Esc leaves draw mode), §9 ("נוסף ידנית"), §10 (`attribute_changed`, `missing_resolved`, `component_marked`, `brand_discount_set`).
  - 05 §4.4 (current and poles never get a default; the user's value is `user`), §5.4 (brand order), §11 (match memory). 04 §11 (what an attribute change and a missing line's resolution keep). 03 §11 (a marked rectangle: crop, bbox and class, as a detector example). 07 §7.2 priority 2 and the bulk discount paragraph (a brand discount, saved in the factory's settings), §7.2.3 (other drafts do not change by themselves).
- Prototype: lines 942–1004 (`vReview`, the toolbar, `boxesFor`) and 872–941 (`lineRow`, `lineDetail`), whose classes the new parts reuse. **The prototype has no screen for any of the four actions**: the detail's sources are read only (`l.src`), there is no missing line, no picker, no draw mode, and the bulk brand discount is only on the price list (lines 1139–1143, built in S19). Line 412's `hint` only says "מוצר אחר" in the text.
- Golden: none. The R track works on the NURSERY-1 fixture and on the E2E pipeline drawing (stand-in model).
- Earlier sessions: S11 (the viewer, `Viewer.tsx`, boxes in PDF points), S19 (the bulk brand discount on the price list, `price_list.set_brand_discount`), S20 (stage 5: `matching/match.py`'s `prepare`/`decide_prepared`/`finish`, `query.py`), S22 (`line_key`, what a rerun keeps), S23 (`services/review.py`'s `Ctx`, `refresh`, `_restore_of`, `_event`, `edits`; decision 8 keeps `review_screen` until now).
- Backlog items for S23b: "Draw mode: mark a missed component" (from S11), "Remove `review_screen`" (from S09).

## Tasks

Written at kickoff, refined as they landed.

### Backend
- [x] **The product picker's search**: `GET /quotes/{id}/products?q=&family=` (`services/review_picker.search`): the master catalog's active items and the factory's own products, every word in the description, SKU, maker or series; a catalog item the factory has a product for is listed once, with the product's price; priced first. Code only.
- [x] **Attribute edit**: `POST /quotes/{id}/lines/{line_id}/attribute` (`current_a`, `breaking_capacity_ka`). The component with the user's value (`user`, a new 04 §6.2 source), confidence 1.0, the line's brand asked for; stage 5's `prepare` / `decide_prepared` / `finish` with no model (`ask=None`: ambiguous takes the first, yellow). Kept in `quote_lines.edits` as `attrs` and `match`; `edits.apply` gives the line the SKU, wording, reasons and alternatives; `review.edited_outputs` gives the rules the value. No candidate: red "אין בקטלוג מוצר עם הערכים האלה". The dropdown's values come with the line (`attribute_options`, the catalog's values per family). The fixture's prototype keys (`current: "160A"`) are read as the schema's.
- [x] **Missing line**: `GET …/lines/{line_id}/candidates` (up to 3, stage 5's code on the missing instance); `POST …/lines/{line_id}/resolve` (a candidate or a picked product): an approved component line, `edits.replaced` + `resolved`, carried by its `m:` key. "אין כאן רכיב" is `review.delete`, its event `negative_example`.
- [x] **Draw mode**: `POST /quotes/{id}/marks`: a manual line, its box in `quote_lines.boxes` (migration 0019), in the panel whose area holds the rectangle's centre, else the active one; the crop cut from the page's render to S3 (`…/marks/{trf}.png`) and a `tenant_reference_crops` row in the family's default class. Refused: no drawing, another drawing's page, a page not parsed, outside the page, under 10 points.
- [x] **Bulk brand discount from a row**: `POST …/lines/{line_id}/brand-discount`: S19's `set_brand_discount`, then this quote's lines of the brand with no price of their own priced again. The price book prices a catalog item at the brand discount with no product (BUG-058).
- [x] Undo for all four: the lines (now with `line_type`), the created line and crop (`review_picker.undo_created`), the brand discount (`undo_brand_discount`). Events `attribute_changed`, `missing_resolved`, `component_marked`, `brand_discount_set`, `row_deleted` with `negative_example`.
- [x] Manual lines are priced from the list when an action touches them, and keep their stored price otherwise (`engine.manual_line`, `load.carry`'s `kept`); their products and SKUs reach the book (`run.price_drawing`, `stored.book_for`).
- [x] A missing line keeps its box (`Draft.boxes`, BUG-059).
- [x] Remove `review_screen`: migration 0019 deletes the flag and its rows, the routes and the seed lose it, the 404 tests go.
- [x] `make gen-client`.

### Frontend
- [x] Detail: current and breaking capacity as a dropdown in "מאיפה כל ערך" (`SourceRow`), units on bare numbers, "נקבע ידנית" after a change; an editable value not read is an empty list.
- [x] Missing line: the explanation, up to 3 products with keys 1–3, "מוצר אחר…", "אין כאן רכיב" (`MissingBox`); no price, cost or alternatives boxes.
- [x] The product picker (`ProductPicker.tsx`): free search, the family filter, ↑ / ↓ / Enter, price or "אין מחיר".
- [x] Draw mode (`Viewer.tsx`'s `DrawLayer`, `Drawing.tsx`): "סמן רכיב שפוספס" on a parsed page of a draft, a crosshair, the band, PDF points, "גררו מלבן סביב הרכיב" under 10 points, Esc, the hint; a pointer, so a finger draws on the phone. A manual line's box is in the accent colour.
- [x] Price box: "כל המוצרים של X: מחירון יצרן פחות __%" (`BrandBulk`).
- [x] Every action through `run` (toast, undo stack); nothing on a sent version.
- [x] `review_screen` out of the client (`App.tsx`, the E2E placeholder test).

### Unit tests
- [x] pytest: the contract snapshot (`user` source); `test_review_picker.py` (the crop at the render's scale, the family's default class, the fixture's values, a catalog item at the brand discount with no product, a rematch and a resolution through `LineEdits` and `apply`); the existing suites with the book's fallback and manual pricing (1,018 pass).
- [x] Vitest: units, the dropdown's value, the discount fraction, the missing text, the picker's meta, the new reasons, the drag rectangle, the 10-point rule, `canMark`, the accent box, Esc on a dialog over a dialog (BUG-060); 245 pass.

### Integration tests
- [x] `test_review_picker.py` (15): the search (and another tenant's product), an attribute and its undo, a value the catalog lacks, refusals; a missing line resolved and undone, "אין כאן רכיב", refusals, the candidates on a pipeline quote and a rerun keeping the resolution; a mark with its box, crop and undo, refusals, the panel by centre; the brand discount and its undo, a line with no list price; a sent version's 409s and another tenant's 404s.
- [x] Performance: the attribute rerun, the candidates, a mark and the brand discount each under 1 s on the fixture or the pipeline quote.

### UI tests (Playwright)
- [x] Desktop and mobile (`review-picker.spec.ts`, two new E2E tenants with a missing line): an attribute, the brand discount, a missing line through "מוצר אחר…", "אין כאן רכיב", draw mode with a too-small drag and a mark, Esc; each undone.
- [x] Screenshots of the new states reviewed and accepted by the user (no prototype screen, decision 1); baselines `picker-attr`, `picker-brand`, `picker-missing`, `picker-search`, `picker-draw` written (`make screenshots`).

### Eval
- [x] `make eval` in replay: no change against the baseline.

### Docs
- [x] 09 "החלטות ב-S23b"; 04 §6.2 (`user`); 07 §7.2 (priority 2 by SKU).
- [x] `docs/db-schema.md` (migration 0019, the flag, the crops), CLAUDE.md, the roadmap's backlog, BUG-058, BUG-059.

## Acceptance criteria

- [x] 09 §7.4, §7.8, §6.6 and §7.13's bulk entry work from the screen on desktop and phone, and each writes its correction event (09 §10).
- [x] Each is undoable, and an undo restores the state before it, including the brand discount and the crop.
- [x] Current and poles never get a default. An edited value has source `user`, and stage 5 never relaxes it (05 §4.4).
- [x] No model call and no price or cost in any request to a model from these routes (`ask=None`).
- [x] An action responds in ≤ 1 s, an attribute rerun included (09 §14). Not measured on a 150-line quote: the rerun reads the whole catalog once (backlog: the picker at catalog scale).
- [x] `review_screen` is gone from the code, the database and the tests.

## Out of scope

- Pasting rows from a supplier quote (09 §7.13, not in the prototype): backlog.
- Stage 3 reading the tenant's crops at detection time: the similarity index is phase-4 work. S23b stores the examples.
- Page reclassification and re-upload (09 §7.9, §7.10): S08 built the classification change. A re-upload has no session yet.
- The chat's version of these actions: S25.

## Open questions

1. **No prototype screen** for the attribute dropdown, the missing line, the product picker, draw mode and the bulk entry in a row. Build them from 09 with the prototype's classes, and review fidelity screenshots of the new states instead of a comparison?
2. **What the picker searches** (09 §6.6 "רשימת מוצרים עם מחיר", §6.4 "חיפוש בקטלוג"). Proposed: the master catalog and the factory's products together, filtered to the line's family when there is one, products with a price first, each shown with its price or "אין מחיר".
3. **A rerun that needs the model** (09 §7.4). Stage 5 may call `catalog_disambiguation` when the rules leave several candidates. Proposed: code only in the review route, which takes the rules' top candidate, yellow, with the others as alternatives. This keeps the 1 s target and S23's "no model call in these routes".
4. **The scope of an attribute edit** (09 §7.4 says "לשורה"; §7.3's alternative covers every line with the same signature). Proposed: the one line, as written. The alternative is to apply it to every line with the same signature.
5. **The detector example's class** (03 §11, `tenant_reference_crops.symbol_class` is required). Proposed: the default class of the product's family in the symbol library, with no extra question in the picker.
6. **Draw mode on the phone.** Proposed: yes. In draw mode a touch drag draws instead of panning, and the button sits in the drawing tab's toolbar.
7. **Pasting from a supplier quote** (09 §7.13). S23's out-of-scope list put it in this session, but the roadmap row doesn't include it. Proposed: backlog.

## Outcome

Filled in at `/session-close`.

- **Done:** The review screen is complete. A current or breaking capacity from a list matches the line again (stage 5 in code, the line's brand, no model); a missing line shows its products, "מוצר אחר…" opens the picker, "אין כאן רכיב" deletes it; draw mode marks a missed component as a manual line with its box and keeps the crop as a detector example; an unpriced line sets the brand discount ("מחירון יצרן פחות __%") and this quote's lines of the brand get a price. The product picker searches the catalog and the price list. Each action has its correction event and its undo. `review_screen` is removed (migration 0019, which also adds `quote_lines.boxes`).
- **Decisions made:** (with who decided, and why)
  1. **Built from 09, reviewed by screenshots** (user, at kickoff; question 1). No prototype screen exists. The new parts use the prototype's classes, and the user reviews screenshots of the new states instead of a side-by-side comparison.
  2. **The picker searches the catalog and the price list** (user, at kickoff; question 2). The master catalog and the factory's products together, filtered to the line's family when there is one. Priced products come first, each with its price or "אין מחיר".
  3. **An attribute rerun is code only** (user, at kickoff; question 3). No `catalog_disambiguation` call from a review route. When several candidates are left, the rules' top one is taken, the line is yellow, and the rest become alternatives.
  4. **An attribute edit is for the one line** (user, at kickoff; question 4, 09 §7.4 "לשורה").
  5. **A marked rectangle's class is its family's default** (Claude's proposal, accepted with the plan; question 5). The symbol library's first class for the product's family; the picker asks nothing more.
  6. **Draw mode on the phone too** (Claude's proposal, accepted; question 6). In draw mode a touch drag draws instead of panning.
  7. **Pasting from a supplier quote goes to the backlog** (Claude's proposal, accepted; question 7).
  8. **A missing line resolved** (Claude, 09 §7.8). An approved component line tagged "נבחר ידנית", carried by its `m:` key through a rerun; "אין כאן רכיב" is the delete, its event a negative example.
  9. **A manual line from draw mode** (Claude, 09 §6.6). In the outputs group, quantity 1, the rectangle as its box (`quote_lines.boxes`), priced from the list by its product; manual lines are now priced from the list when an action touches them and keep their price otherwise, like component lines (07 §7.2.3).
  10. **The brand discount from a row** (Claude, 09 §7.13, 07 §7.2). Shown on an unpriced line whose catalog item has a list price; it sets the factory's brand discount and prices this quote's lines of the brand with no price of their own. Priority 2 applies to a SKU with no price-list product too (BUG-058, 07 §7.2 amended).
  11. **The fixture's breakers are `circuit_breaker`** (Claude). The S09 fixture's components were all `device`, so no dropdown could show; its breakers take the schema's family, and F18 its catalog item (S203M-C20), for the bulk entry. Its prototype-shaped values ("160A") are read as the schema's for a rematch.
  12. **`user` joins stage 4's attribute sources** (Claude, contract change, 04 §6.2). Stage 4 never writes it; stage 5 reads it on a rerun for one line. The schema snapshot is updated.
- **Eval / metrics:** `make eval` in replay: no change against the baseline. Speed: the attribute rerun, a mark, the brand discount and a missing line's candidates each under 1 s in the integration tests.
- **Checks:** `make check` under Node 22: lint, types, licenses, secrets, client, unit (1,018 pytest with pricing at 100% branch coverage, 245 Vitest), integration (648), eval (no change), E2E (179 passed, desktop and mobile), screenshots (82 of 86; the four that timed out right after the E2E suite, the dark desktop `review-detail`, `review-red`, `review-showdraw`, `review-finding`, passed rerun alone: BUG-038, no pixel difference). Baselines rewritten for the accepted changes: the five `picker-*` states, and `review-detail` and `review-showdraw` (F1's current is a dropdown now, and the drawing's toolbar has "סמן רכיב שפוספס").
- **Bugs logged:** BUG-038 seen again (screenshot timeouts only). BUG-058 (P2, a brand discount priced no SKU without a price-list product; fixed), BUG-059 (P2, a missing line had no box on the drawing; fixed), BUG-060 (P2, Esc in the picker closed the phone's sheet too; fixed).
- **Follow-ups:** in the roadmap's backlog: pasting from a supplier quote; stage 3 reading the tenant's crops; a rematch and the kit; the rules on a resolved missing line; the picker at catalog scale; the picker's price for a catalog item at a brand discount. Not covered: the rematch's speed on a 150-line quote (the S23 performance test covers the other actions); keys 1–3 on a missing line are covered by Vitest and the API, not Playwright (the E2E fixture has no stage outputs, so no candidates). The S23 states (send, price dialog, locked) still have no screenshot baseline.
