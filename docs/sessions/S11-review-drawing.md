# S11: Review II, drawing

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s11-review-drawing` |
| **Depends on** | S09, S10 |
| **Status** | in review |
| **PR** | (link) |

## Goal

The review screen's drawing pane is real: each page's stage-2 render opens in an OpenSeadragon viewer, tile by tile, with SVG highlight boxes over the components, a page strip, and "הצג בשרטוט" from a line or a finding. On the phone the drawing is its own tab. A toast and an undo stack (5 s, 30 actions) are in place for the actions S23 adds.

## References

- Specs: 09 §5.2 (phone tabs), §6.5 (drawing pane: toolbar, page strip, classification row, overlays), §7.1 (selecting a line moves the drawing), §7.11 (undo), §8 (PgDn/PgUp, Esc), §13 (accessibility), §14 (performance: row select or page change < 150 ms, lazy thumbnails); 12 §6 (OpenSeadragon with an SVG layer); 00 §6.2 (PDF points, origin top left), §6.3 (confidence colors).
- Prototype: `prototype/konboro-app.html` lines 942–1004 (`vReview` drawing pane, `boxesFor`), 1397–1428 (`setupViewer`, `showOnDrawing`), 1437–1444 (`selectLine`), 620–635 (`toast`, `pushUndo`, `doUndo`), CSS 237–252, 273–275, 306–308.
- Golden: NURSERY-1 through the S09 fixture. No eval change.
- Earlier sessions: S09 (review screen, fixture, `GET /quotes/{id}`, `review_screen` flag), S10 (stage 2 writes `render.png` and the packed DZI pyramid: `dz/page.dzi`, `dz/tiles.bin`, `dz/index.json`; backlog item "serve the packed pyramid").

## Tasks

### Backend
- [x] Quote read API: the drawing's pages (number, sheet, kind, route, confidence, classified by, quality, panels and their regions, size in points, thumbnail, viewer URL, red/yellow counts) and each line's instances (`page_id`, `bbox`) and each finding's box.
- [x] Pyramid routes behind `require(Permission.QUOTES_READ)`: `GET /pages/{page_id}/dz/page.dzi` and `GET /pages/{page_id}/dz/page_files/{level}/{col}_{row}.png`, a ranged S3 read of `tiles.bin` through `index.json`, inside the tenant check; long cache headers.
- [x] `services/storage.py`: ranged get, tenant-checked.
- [x] NURSERY fixture: the prototype's 9 page images as renders and thumbnails, and their pyramids in S3 (decision 2). Safe to rerun.
- [x] `make gen-client`.

### Frontend
- [x] OpenSeadragon (BSD) viewer component, auth header on tile requests, SVG overlay in page points.
- [x] Overlays for every instance (decision 1): status color, red dashed, selected in the accent color, filtered dimmed, hover title, click selects the line. The finding box ("בשרטוט"). Panel frames on a page with 2+ panels, the inactive one veiled with "לחצו למעבר".
- [x] Page strip with lazy thumbnails, red/yellow count and tag; "עמוד x מתוך y" with prev/next; page chips (kind, route, note); classification row, read-only, with its warnings; zoom tools (decision 4). Context pages: image only, no boxes; skipped pages dimmed.
- [x] "הצג בשרטוט" from the line detail and the bottom sheet; selecting a line moves to its page and centres it when zoomed (7.1).
- [x] Phone: drawing tab.
- [x] Toast (5 s, "בטל") and the undo stack (30 actions per quote), Ctrl+Z.
- [x] Keyboard: PgDn/PgUp, Esc order.
- [x] Port the prototype's drawing-pane and toast CSS into `app.css`.

### Unit tests
- [x] Vitest: point-to-viewport mapping, page choice for a line (current page if it has an instance, else the first), counts per page, undo stack (cap 30, order), toast timing.
- [x] pytest: pyramid index lookup and range read.

### Integration tests
- [x] Pyramid routes: tenant isolation (another tenant's page is 404), unknown tile 404, bytes equal the packed tile; flag off is 404.
- [x] Quote read API returns pages, instances and finding boxes for the fixture.
- [x] Route audit.

### UI tests (Playwright)
- [x] Desktop and mobile: open the drawing, change page, select a line and see its boxes, "הצג בשרטוט" from the detail and from a finding, zoom, phone drawing tab, PgDn/PgUp.
- [x] Screenshot baselines for the accepted drawing states, light and dark, desktop and mobile: `review-showdraw`, `review-finding`, `review-drawing` (phone), and the earlier review states again, now with the drawing.
- [x] Prototype-fidelity report reviewed by the user (accepted 2026-11-01; no color legend under the drawing, as the prototype).

### Eval (pipeline sessions)
- [x] Not a pipeline session; `make eval` unchanged.

### Docs
- [x] Spec 09 §5.2 and §6.5 updated for decision 4 (free zoom, no 760 px minimum, no dropdown until S23).
- [x] `docs/db-schema.md` if a column or S3 key changes; CLAUDE.md "built so far"; backlog item "serve the packed pyramid" closed.

## Acceptance criteria

- [x] The fixture's 9 pages open in the viewer; tiles load from the API, never another tenant's.
- [x] Selecting a line shows its boxes; on another page the viewer moves there (09 §7.1).
- [x] Row select or page change responds in < 150 ms on the fixture (09 §14).
- [x] Thumbnails load lazily.
- [x] Toast shows for 5 s; the undo stack holds the last 30 actions.
- [x] RTL, keyboard and screen-reader labels per 09 §13.

## Out of scope

- Draw mode, marking a missed component (09 §6.6): no session had it; now in the roadmap backlog, for S23 or later (it needs the manual line and the product picker).
- Page-kind change from the review screen (09 §7.9) and "העלה קובץ מקורי" (7.10): S23.
- The actions themselves and their server-side revert (09 §7, §10): S23.
- `unresolved_overlay` (13 §4.1): S26.

## Open questions

1. **Overlays: spec vs prototype.** The prototype draws boxes only for the selected line (`boxesFor`). 09 §6.5 and principle 2 draw every component in its status color (red dashed), the selected line thick in the accent color, filtered lines dimmed, a hover title, and a click on a box selects its line (7.1).
2. **Fixture images.** The S09 fixture has no renders or pyramids. The golden PDF's title block carries real names; the prototype's 9 page images (1400 × 989 JPEG) have it blanked.
3. **Undo with no actions yet.** S11 has the toast and the stack, but the first undoable actions are S23's.
4. **Drawing toolbar: spec vs prototype.** The prototype has the strip ("n · kind"), page chips (kind, route, note) and zoom tools with free zoom. 09 §6.5 adds prev/next with "עמוד 5 מתוך 7 · E-104 · חד-קווי", red/yellow counters and tags in the strip, a classification row with warnings, fixed zoom steps ×1/×1.5/×2.25/×3, and on the phone a 760 px minimum width with horizontal scroll.

### Answered at kickoff (2026-11-01, user)

1. **Overlays: the spec.** Every instance is boxed in its line's status color, red dashed (09 §13: shape as well as color). The selected line is thick in the accent color, and so is every one of its instances. Rows hidden by the filter are dimmed, a hover shows the line's name, and a click on a box selects its line and scrolls the table to it (7.1). Styled with the prototype's `.hl` classes.
2. **Fixture images: the prototype's.** Its 9 page JPEGs (1400 × 989, title block blanked) become the fixture's renders and thumbnails, packed into a DZI pyramid with stage 2's `deepzoom.pack`. The boxes stay in PDF points (842 × 595), mapped by the page's size. They blur at high zoom, which is acceptable for a fixture.
3. **Undo: client stack and toast now.** The toast (5 s, "בטל"), a stack of the last 30 actions per quote with a typed interface, Ctrl+Z and the header's undo button, all tested in Vitest. S23's actions plug in, with their server-side revert.
4. **Toolbar: the prototype, with the spec's extras in its style.** "עמוד x מתוך y" with prev/next, each thumbnail's red (or else yellow) count and its tag, and PgUp/PgDn. The classification row shows the route, the confidence and the warnings, but no dropdown (7.9 is S23). Zoom is free, and the buttons step ×1.5. There is no 760 px minimum on the phone: OpenSeadragon pans. Spec 09 §5.2 and §6.5 are updated to match.

## Outcome

Filled in at `/session-close`.

- **Done:**
  - Pyramid routes `GET /pages/{page_id}/dz/page.dzi` and `…/dz/page_files/{level}/{col}_{row}.png` (`api/routes/pages.py`, `services/viewer.py`): a ranged S3 read of stage 2's pack (`Storage.get_range`), the index cached per page, tenant-checked, behind `review_screen`.
  - `GET /quotes/{id}` now has the drawing's pages (kind, route, confidence, quality, size in points, panels on the page, thumbnail, red and yellow counts), each line's boxes and each finding's box.
  - The NURSERY-1 fixture's pages: the prototype's images as renders, thumbnails and pyramids (`seed_nursery_pages`), in the demo and E2E tenants.
  - The drawing pane (`screens/review/Drawing.tsx`, `Viewer.tsx`, `drawingModel.ts`):
    - OpenSeadragon 6.1.1 (BSD) with an SVG layer of boxes in PDF points;
    - the page strip with lazy thumbnails, counts and tags;
    - page chips (title, route, confidence, vector or scanned, the role of a context page, warnings);
    - previous / next, zoom, PgUp / PgDn;
    - panel frames on a page with two panels;
    - "הצג בשרטוט" from a line and "בשרטוט" from a finding;
    - the phone's drawing tab.
  - Toast with "בטל" for 5 s and the undo stack (`screens/review/undo.ts`): 30 per quote, Ctrl+Z, the header's button.
  - Tests:
    - pytest unit (`test_viewer.py`);
    - integration (`test_api_viewer.py`, and additions to `test_api_quotes.py`, `test_api_drawings.py`, `test_seed.py`);
    - Vitest (`drawingModel.test.ts`, `undo.test.tsx`, `Toast.test.tsx`);
    - Playwright (`e2e/drawing.spec.ts`, 14 tests on desktop and mobile);
    - 10 new screenshot baselines, and the 12 review baselines again.
  - The fidelity report was reviewed and accepted by the user (2026-11-01).
  - Docs: spec 09 §5.2 and §6.5, `docs/db-schema.md`, CLAUDE.md, the Makefile's `seed` help, BUG-023, the roadmap backlog.
- **Decisions made:** the 4 kickoff answers above. Made while building (2026-11-01, Claude; for the user's review at close):
  - **Tiles through the API, not presigned URLs.** `GET /pages/{page_id}/dz/page.dzi` and `…/page_files/{level}/{col}_{row}.png` (`api/routes/pages.py`, `services/viewer.py`), behind `require(Permission.DRAWINGS_READ)` and `review_screen`. OpenSeadragon sends the bearer token on every request (`loadTilesWithAjax`, `ajaxHeaders`). A tile is a ranged read of `tiles.bin`; each page's `index.json` is cached in the API process (256 pages, LRU), since a page's pyramid never changes. The browser caches tiles (`private, max-age=86400, immutable`).
  - **Thumbnails stay presigned,** for an hour on the review screen (the strip loads them lazily), five minutes on the done step as before.
  - **The fixture's page images are files in the repo** (`devtools/fixtures/nursery_pages/p1–p9.jpg`, 612 kB, byte for byte the prototype's), packed by `seed_nursery_pages` with stage 2's own `deepzoom` code. `make seed` and the E2E seed write them; S3 is now needed for `make seed`.
  - **The boxes are one SVG, added to OpenSeadragon as an overlay over the whole image** (`viewBox` in PDF points), so they pan and zoom with the page, and a drag that starts on a box still pans. A click is hit-tested at the pointer (OpenSeadragon captures the pointer, so the event's target is its canvas). Strokes keep their width at any zoom. Selected: accent, 3 px; red: dashed; dimmed: 30% opacity.
  - **Focus:** "הצג בשרטוט" and a finding's "בשרטוט" frame the box at a third of the view, as the prototype's `focusOn`; selecting a row goes to its page (fitted), and on the same page centres the box only when zoomed in (09 §6.5). A focus waits for its page to open and for the viewer to have a size (the phone's tab).
  - **Box click on the phone opens the line's sheet**; on the desktop it selects the line, widens the filter or switches the panel if they hid it, and scrolls the table to it.
  - **A toast with "בטל" stays 5 s (09 §7.11);** a plain toast keeps the prototype's 4.2 s.
  - **Undo:** one stack per quote for the life of the page (`screens/review/undo.ts`), Ctrl+Z / ⌘Z by key position, also on the phone's keyboard; the header's button is disabled while the stack is empty, which it is until S23.
  - **The classification warnings say what is wrong without pointing at a control** ("הסיווג של העמוד לא ודאי") until S23 adds the kind dropdown and "העלה קובץ מקורי".
  - **No color legend under the drawing** (09 §6.5 "מתחת לשרטוט"): the prototype has none, and the boxes' colors are the rows' colors, with red dashed. Accepted by the user with the fidelity report (2026-11-01).
  - **OpenSeadragon's console is filtered to text:** its warnings log whole tile objects, the `Authorization` header included, and Vite forwards the browser console to `make dev`'s terminal.
  - **Viewport margins** (16 px at the sides, room for the chips above and the tools below), like the prototype's fit at 96%.
- **Eval / metrics:** not a pipeline session; `make eval` (replay) shows no change against `eval/baseline.json`.
- **Bugs logged:** BUG-023 (P2, fixed in S11): since S10 the done step's thumbnails were stage 2's full render.
- **Notes:** `make screenshots` timed out on 8 shots under a load average of 38 (other work on the machine), including screens S11 doesn't touch; with `--workers=2` all 46 passed, and `SCREENSHOTS_CHECK=1` passed 46 of 46. The fidelity capture of an open line detail logs a harmless "ResizeObserver loop" warning, not reproduced in the app.
- **Follow-ups (in the roadmap backlog):**
  - Draw mode, marking a missed component (09 §6.6).
