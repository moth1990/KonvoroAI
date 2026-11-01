# S09: Review I, lines

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s09-review-lines` |
| **Depends on** | S07 |
| **Status** | in review |
| **PR** | |

## Goal

`/review/:quoteId` shows a real quote from the quote read API, laid out like the prototype's review screen:
- the split layout and the header;
- the panel tabs and filters;
- the grouped lines table, with colors, shapes and reason chips;
- the line detail, with the raw text, the sources and why;
- keyboard navigation.

The data is a fixture quote seeded through the real quote API (NURSERY-1, priced from its actual quote), so this session never waits for the pipeline. The drawing pane (S11) and the actions (S23) come later.

## References

- Specs: 09 §5–6.4 (layout, header, filter row, lines table, line detail), §8 (keyboard), §9 (color and status), §13 (accessibility and language); 07 §6.2 and §7.5 (line shape, `status_reasons`); 00 §6.3 (confidence colors; stage 7 alone sets a row's final color).
- Prototype: `prototype/konboro-app.html` lines 872–941 (lines, filters) and 942–995 (line detail), `vReview`; mock data `makeLines` / `makeFindings` (393–580) for field names. `prototype/review-screen.html` is reference only (CLAUDE.md).
- Golden: `golden/NURSERY-1/actual_quote.json` for the fixture's lines and prices.
- Earlier sessions: S04 (shell, `MOBILE_MAX_PX` = 860), S05 (stage 7 creates the quote and its draft version).

## Tasks

### Backend
- [x] Flag `review_screen` in the global seed, default off. Turned on for the demo and E2E tenants. The route depends on `require_flag("review_screen")`.
- [x] Quote read API `GET /quotes/{quote_id}`, behind `require(Permission.QUOTES_READ)`. It returns the header (name, drawing, version, status), the price-list coverage, the panels with their lines in display order (09 §6.3), each line's component detail (raw text, sources for each attribute, why), the findings, and the totals (07 §6.1). Money is a string (non-negotiable 5), and lines that are soft-deleted are left out.
- [x] Service `konboro/services/quotes.py`: grouping and order, and totals recomputed in Decimal from the lines. The stored `totals` must equal the recomputed ones.
- [x] Quote write path in the services layer: `write_lines(...)` and `store_totals(...)`, with the sums in `konboro/domain/totals.py` (100% branch coverage, 07 §10.1). The fixture seed uses it, and stage 7 (S22) will reuse it.
- [x] NURSERY-1 fixture seed (`konboro/devtools/fixtures/nursery.py`) for the demo and E2E tenants: drawing, panel, components with attributes and sources, quote version 1 as a draft, the 14 lines, and the 4 findings. Line costs come from the demo price list. Customer names are made up. Safe to rerun.
- [x] `make gen-client`, and commit both files.

### Frontend
- [x] Port the prototype's review CSS into `frontend/src/theme/app.css` with the same class names.
- [x] Split layout (desktop), tabs for lines, drawing and chat (phone, ≤ 860 px). The drawing pane is a placeholder until S11.
- [x] Header: project, version, total before VAT, margin, price-list coverage.
- [x] Panel tabs, only with 2+ panels, each with its non-green count. Filters: הכל · רק לבדיקה · ירוק · צהוב · אדום, with counts, and a second click returns to הכל. Progress bar.
- [x] Read-only findings box (prototype `.findings`).
- [x] Virtualized, grouped lines table (`@tanstack/react-virtual`): groups by `line_group`, then missing lines, then derived and labor, then the panel total row. Stripe plus shape icon with an aria-label, reason chips, child lines, the empty state, and the phone's "4 × ₪" sub line. The foot row shows total, VAT, total with VAT, margin, and the lines with no cost.
- [x] Line detail, read-only: the expanded row on desktop, the bottom sheet on phone.
- [x] Keyboard (09 §8): ↑/↓, Space, Esc; Enter is left for S23. RTL throughout; designators and numbers in `dir="ltr"`.

### Unit tests
- [x] Grouping and order, filter counts, the color-to-shape map, money formatting from strings (Vitest).
- [x] Totals in `tests/unit/test_totals.py` (pytest); grouping, order and totals of the read service against the fixture in `tests/integration/test_quotes_fixture.py`.

### Integration tests
- [x] The read API returns the fixture exactly, is tenant-isolated, and refuses another tenant's quote with 404.
- [x] Route audit: the new routes depend on `require(...)`.

### UI tests (Playwright)
- [x] Desktop and mobile: open the fixture quote, filter, expand a line, keyboard navigation, the phone bottom sheet.
- [x] Screenshot baselines for the accepted states: `review-lines`, `review-detail`, `review-red`, light and dark, desktop and mobile (`e2e/visual.spec.ts`).
- [x] Prototype-fidelity report reviewed by the user (accepted 2026-11-01).

### Docs
- [x] `docs/db-schema.md` if any column changes; CLAUDE.md's "built so far" list.

## Acceptance criteria

- [x] The fixture quote is the NURSERY-1 draft: 13 products (plus Q0's kit child line), 42 units, ₪4,674.00 before VAT over 8 priced lines, 5 lines with no price. Its 7 prices that appear in `actual_quote.json` match exactly. All money is Decimal, never float. (`test_quotes_fixture.py`, `test_api_quotes.py`)
- [x] Every non-green line shows at least one reason chip (09 principle 3). (`reasonChips` falls back to a status chip; Vitest and `review.spec.ts`)
- [x] 150 lines scroll smoothly on the mobile project (virtualized). (`review.spec.ts`: under 60 rows in the DOM, the end reached in under 5 s)
- [x] The fidelity report is accepted (2026-11-01).

## Out of scope

- Drawing viewer, highlights and "show on drawing": S11.
- Every editing action, approve, send and versions: S23.
- The chat drawer: S25.

## Open questions

All answered at kickoff (2026-11-01). See "Decisions made" below.

## Decisions made at kickoff

Asked and answered at kickoff (2026-11-01). Where the spec and the prototype disagreed, the answer is noted as which one wins.

1. **Fixture = the pipeline's draft, not the sent quote.** NURSERY-1 as stage 7 would draft it today (golden README): 13 products, 42 units, 8 priced at **₪4,674** before VAT, 5 red with no price (Q0, F18–F21, RNV, C1–C4, enclosure), plus Q0's kit child line. The 7 prices that appear in `actual_quote.json` must match it exactly; FNV's ₪185 comes from quote 10288. The acceptance criterion below changes to match.
2. **New flag `review_screen`**, evaluated on the server (13): off by default, on for the demo and E2E tenants. When it is off, the quote read API answers 404 and the route shows the placeholder. Remove the flag when the screen is complete (S23).
3. **Status = the prototype's stripe plus the spec's shape icon** (09 §6.3, §13): a circle with a check for green, a triangle with an exclamation mark for yellow, a circle with an X for red, and a box for an accessory line, each with an `aria-label`: "בטוח", "לבדיקה", "לא זוהה או שגוי".
4. **Filter row = the spec's behaviour drawn in the prototype's style.** הכל · רק לבדיקה · ירוק · צהוב · אדום, each with a count; clicking the active filter again returns to "הכל"; "X מתוך Y שורות מוכנות" with a progress bar (09 §6.2). Drawn with `.fchip` and `.sw`. "רווחיות" and price-list coverage stay where the prototype puts them.
5. **Grouping = both.** Inside a panel, component lines are grouped by `line_group` (feed, outputs, control, enclosure) in pipeline order, as in the prototype. Then come missing lines, then "פריטים נלווים ועבודה", then the panel total row (09 §6.3). Child lines sit indented under their parent.
6. **Phone row = the spec** (09 §5.2): status, item and total; "4 × ₪185.00" goes in the sub line. This replaces the prototype's mobile columns.
7. **Line detail = read-only in S09.** Inline on desktop, a bottom sheet on the phone. It shows the raw drawing text, the source of each value, why, the price and its source, cost and margin, the alternatives (as a list), and the line's findings. Action buttons arrive in S23 and "הצג בשרטוט" in S11.
8. **Colors and reasons follow from the real draft.** States that NURSERY lacks (missing, derived, labor, low confidence, brand swap, two panels) are covered by hand-written frontend fixtures in Vitest, plus a component-level screenshot.
9. **Keyboard:** ↑/↓ moves the selection, Space opens and closes the detail, Esc closes the sheet and then clears the selection (09 §8). Enter does nothing until S23 gives it "approve". The key hint follows the spec.
10. **Panel tabs show only with 2+ panels.** NURSERY has one panel, so the screen matches the prototype. The tabs are tested with a two-panel Vitest fixture.
11. **Findings box: read-only, from seeded findings.** NURSERY's 4 findings are seeded into `findings`: FRONT_VIEW_DESIGNATOR_MISSING (warning), MISSING_PRICE (error), and two info findings, DATA_INFERRED_ATTRIBUTE and DATA_MODEL_TEXT_CONFLICT. Their action buttons wait for S23, and "בשרטוט" waits for S11.
12. **Virtualizer: `@tanstack/react-virtual`** (MIT).

## Outcome

- **Done:**
  - Quote read API `GET /quotes/{quote_id}` (`api/routes/quotes.py`), behind `require(Permission.QUOTES_READ)` and `require_flag("review_screen")`. It returns 404 for another tenant's quote, an unknown quote, or the flag off.
  - `services/quotes.py`: the write path (`write_lines`, `store_totals`) that stage 7 will reuse in S22, and the read model (lines in 09 §6.3 order, totals summed again from the live lines).
  - `domain/totals.py`: line amounts and quote sums (07 §7.6) in Decimal, with 100% branch coverage.
  - The NURSERY-1 fixture (`devtools/fixtures/nursery.py`): 9 pages, a panel, components with the source of each value, 14 lines and 4 findings. It is in the demo tenant (`make seed`, safe to rerun) and in a new E2E tenant, `review@e2e.konboro.local`.
  - The flag `review_screen` (off by default, on for the demo and E2E tenants).
  - The review screen (`screens/review/`):
    - the header, phone tabs, the filter row with counts, and the progress bar;
    - panel tabs for 2+ panels and the read-only findings box;
    - the virtualized grouped table with stripe, shape icon and reason chips;
    - the foot totals;
    - line detail (inline on desktop, a bottom sheet on the phone) and the keyboard (09 §8).
  - `Shell` has a `bare` mode and `Modal` a bottom-sheet variant. The prototype's review CSS is in `app.css`, with the breakpoint at 860px.
  - Tests:
    - pytest unit (`test_totals.py`);
    - integration (`test_quotes_fixture.py`, `test_api_quotes.py`, the seed tests);
    - Vitest (`review/model.test.ts`, 40 tests);
    - Playwright (`e2e/review.spec.ts`, 18 tests on desktop and mobile);
    - 12 screenshot baselines.
  - The fidelity report was reviewed and accepted by the user (2026-11-01).
- **Decisions made:** the 12 kickoff decisions above (asked and answered at kickoff, 2026-11-01). Made while building:
  - `quote_lines.margin_rule` also holds a fixed price's source: `{kind: "fixed", source, quotes}` (db-schema §6.1). That is how the screen shows "מקור: הצעה 10271".
  - The API sends `unit_margin` per line, so the screen does no money arithmetic (09 principle 7).
  - Findings are listed errors first. Runs of 3 or more tags are one chip (F18–F21).
  - Moving the selection with ↓/↑ leaves an open detail open, as the prototype's `selectLine` does.
  - The Space key's hint reads "Space", not "רווח", which would clash with the "רווחיות" (margin) toggle beside it.
  - The circuit's load (`attributes.load`) is shown in the row's sub line, not under "מאיפה כל ערך".
- **Eval / metrics:** not a pipeline session; `make eval` is unchanged against `eval/baseline.json`.
- **Bugs logged:** BUG-017 (P2, fixed in S09): the status icon's class `.st` clashed with the new-quote stage label and changed two accepted phone screenshots. It is now `.ln-st`. Found by `make check-screenshots`.
- **Follow-ups (in the roadmap backlog):**
  - Remove `review_screen` when the screen is complete (S23).
  - 09 §6.3's sub line also lists the catalog number, multiplicity and pages, which the prototype's row doesn't show. Decide at S23.
  - Price hints for unpriced lines, the accessories footnote, and "רווח נמוך" chips against the margin floors arrive with pricing (S22).
  - Costs only for a role that may see them (09 §12): there is one owner role in 1.0, so the server sends costs to everyone.
