# S09: Review I, lines

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s09-review-lines` |
| **Depends on** | S07 |
| **Status** | todo |
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
- [ ] Quote read API: header, versions, panels, lines grouped per panel, totals, `status_reasons`. Money as strings (non-negotiable 5); behind `require(Permission.X)`.
- [ ] Fixture seed: NURSERY-1 written through the quote write path in the services layer, priced from `actual_quote.json`, for the dev and E2E tenants. Made-up customer names only.
- [ ] Behind its flag, evaluated on the server (13), if the screen is new to users.
- [ ] `make gen-client`, and commit both files.

### Frontend
- [ ] Port the prototype's review CSS into `frontend/src/theme/app.css` with the same class names.
- [ ] Split layout (desktop), tabs for lines, drawing and chat (phone, ≤ 860 px). The drawing pane is a placeholder until S11.
- [ ] Header: project, version, total before VAT, margin, price-list coverage.
- [ ] Panel tabs with non-green counts; filters (all, review only, green, yellow, red) with counts; progress bar.
- [ ] Virtualized, grouped lines table: line order from 09 §6.3, status shape and color, reason chips, child lines, the panel total row, the empty state.
- [ ] Line detail: the expanded row on desktop, the bottom sheet on phone.
- [ ] Keyboard (09 §8). RTL throughout; designators and numbers in `dir="ltr"`.

### Unit tests
- [ ] Grouping and order, filter counts, the color-to-shape map, money formatting from strings (Vitest).
- [ ] Totals and grouping in the read API's service (pytest).

### Integration tests
- [ ] The read API returns the fixture exactly, is tenant-isolated, and refuses another tenant's quote with 404.
- [ ] Route audit: the new routes depend on `require(...)`.

### UI tests (Playwright)
- [ ] Desktop and mobile: open the fixture quote, filter, expand a line, keyboard navigation, the phone bottom sheet.
- [ ] Screenshot baselines for the accepted states.
- [ ] Prototype-fidelity report reviewed by the user.

### Docs
- [ ] `docs/db-schema.md` if any column changes; CLAUDE.md's "built so far" list.

## Acceptance criteria

- [ ] The fixture quote's line count, panel totals and total before VAT match `actual_quote.json` exactly (Decimal, no float).
- [ ] Every non-green line shows at least one reason chip (09 principle 3).
- [ ] 150 lines scroll smoothly on the mobile project (virtualized).
- [ ] The fidelity report is accepted.

## Out of scope

- Drawing viewer, highlights and "show on drawing": S11.
- Every editing action, approve, send and versions: S23.
- The chat drawer: S25.

## Open questions

1. Does the screen sit behind a flag of its own while it is incomplete, or behind the existing route only?
2. Which virtualization library? It must pass `make licenses`; `@tanstack/react-virtual` (MIT) is the default proposal.
3. The fixture's line colors and reasons: hand-written to cover every state, or derived from the real quote only, which would make most lines green?
4. Any spec-vs-prototype difference found while reading 09 §6 and lines 872–995 is asked at kickoff.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
