# S26: Flags: overlay and export

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s26-overlay-export` |
| **Depends on** | S23 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#36](https://github.com/moth1990/KonvoroAI/pull/36) |

## Goal

With `unresolved_overlay` on, the review screen's drawing shows a dashed red box, with its label, around everything the system did not recognise or recognised only in part, a "לא פוענח N" button turns the layer on and off, and the page strip marks the pages that have one. With `export_doc` on, "הורדה" opens the prototype's export modal, which downloads the customer PDF (no cost, margin, supplier or row colour) and the internal Excel (every line with its cost, price source, colour, tags and the findings). Both flags off leave the screen and the API as they are today.

## References

- Specs:
  - 13 §3 (the server decides; a flag that is off is as if the feature did not exist; data stays when a flag goes off; each flag is measured), §4.1 (`export_doc`: the button, the customer PDF, the internal Excel, unpriced lines, Chromium through Playwright and openpyxl), §4.4 (`unresolved_overlay`: the four kinds and their sources), §6 item 2 (the PDF template per factory: open).
  - 07 §7.6 (the order of the totals, the discount on the quote, VAT, rounding: the document shows the stored totals), §12 (the customer document: description, SKU by the factory's setting, quantity, unit price, line total, discount, VAT and total; never cost, margin, supplier or colour).
  - 03 §4.4 (`unknown_symbol`), §3.6 (orphan texts), §6 (the detection's `status`); 04 §5.7 (texts left unassociated); 06 (the `FRONT_VIEW_DESIGNATOR_MISSING` finding and its box, S21 decision 11).
  - 12 (PDF from HTML through Chromium, Excel with openpyxl).
  - 09 §6.5 (the drawing pane, the strip, the boxes).
- Prototype: `prototype/konboro-app.html`
  - 575–580 (`UNRESOLVED`: the four spots on NURSERY), 329–330 (`.ux`), 985 (the strip's red dot), 989 (the "לא פוענח" button), 1001 (`boxesFor`'s overlay), 1553 (`ux` toggles it).
  - 959 (the "הורדה" button), 1360–1378 (`exportModal`), 331–335 (`.doc`, `.modal.wide`), 315 (`.v2`), 1551–1552 (`export`, `exp`).
- Golden: none. Neither flag moves the pipeline (13 §3 rule 6 asks for both states only for a flag that does).
- Earlier sessions:
  - S11: the viewer, its SVG boxes, the strip and its counts (`screens/review/Viewer.tsx`, `Drawing.tsx`, `drawingModel.ts`).
  - S21: stage 6's findings with `page_id` and `bbox`; the fixture's F26–F29 finding on page 4.
  - S22–S23: the quote's stored totals, versions (draft, sent, N+1), the lines' carried state.
  - S23b: draw mode's marked component (a manual line with a rectangle).

## Tasks

### Backend
- [x] **The unresolved spots** (`services/unresolved.py`), for the quote's current version, read in code (no model):
  - `unknown_symbol`: stage 3's detections with status `unknown` (class `unknown_symbol`), unless a manual line drawn in draw mode covers it.
  - `orphan_text`: stage 3's orphan texts that no stage-4 instance read (their span ids are in no instance's values), and that became no missing line. Stage 3 keeps as orphans only the spans stage 2 tagged as a device's value, which is decision 4's filter already. Measured on the golden set (Outcome).
  - `partial`: an instance of a live, unapproved line whose product is not identified, or whose current or poles were not read (decision 7), one box per instance on the drawing, named by the line.
  - `front_only`: the version's open `FRONT_VIEW_DESIGNATOR_MISSING` findings with a box; a dismissed one drops off.
  - Each spot: `kind`, `page_id`, `bbox` (PDF points, origin top left), `label` (the prototype's four labels), `note` (the tooltip), and the `line_id` or `finding_id` it came from.
- [x] `GET /quotes/{id}/unresolved` behind `require_flag("unresolved_overlay")` (404 when off), the quote routes' read permission (`Reader`).
- [x] **The export** (`services/export.py`, `services/export_pdf.py`, `services/export_xlsx.py`):
  - The document's data from the stored version: lines in the screen's order (live lines; a kit part "כלול" left out of the customer PDF), panel groups when there is more than one panel, the stored totals (07 §7.6) as `Decimal`.
  - Customer HTML (built in code with every value escaped, RTL, the app's fonts embedded from the backend's own copy) with description, SKU by the factory's setting, quantity, unit price, line total, discount, VAT and total; an unpriced line has no amount. Printed to PDF by Chromium through the Python `playwright` package (Apache-2.0), in the request, with a timeout.
  - Internal Excel (openpyxl), right to left: a lines sheet (panel, group, description, SKU, brand, quantity, unit cost, cost source and supplier, unit price, line total, margin, price source, colour and its reasons, tags), a findings sheet, a totals sheet. Money cells are numbers with a shekel format, written from `Decimal`.
  - The factory's template (decision 1): logo, company details (name, ח.פ., address, phone), terms text, and whether SKUs show. A draft's PDF carries a "טיוטה" mark on every page; a sent version has none (decision 3).
- [x] **The template's storage** (decision 1): a migration adds `tenant_settings.document` (JSONB: details, terms, `show_sku`, the logo's storage key). The logo is a PNG or JPEG up to 1 MB under `tenants/{tenant_id}/branding/` through `services/storage.py` (no SVG: it can carry script into Chromium), embedded in the HTML as a data URI. `docs/db-schema.md` in the same PR. The demo tenant is seeded with made-up details.
- [x] `GET` / `PUT /settings/document` and `PUT` / `DELETE /settings/document/logo`, behind `export_doc`, each with an actor.
- [x] `GET /quotes/{id}/versions` (number, status, sent date, total) and `GET /quotes/{id}/versions/{n}/document` (the customer document's rows and totals as JSON, the same data the PDF prints, so the modal's preview is the PDF's), behind `export_doc` (decision 2).
- [x] `GET /quotes/{id}/versions/{n}/export.pdf` and `.xlsx` behind `require_flag("export_doc")`, attachment with a Hebrew file name (`filename*=UTF-8''…`). Another tenant's quote, or a version that doesn't exist, is 404.
- [x] Each download writes a structured log line (tenant, user, quote, version, format) for 13 §3 rule 4 (decision 6).
- [x] `make install` and CI install the Python Playwright's Chromium; `make licenses` passes with `playwright`.
- [x] The NURSERY-1 fixture gets the prototype's spots: a stage-3 output (`seed_nursery_detections`) with the block of 4 terminals under Q0 (`unknown`) and the "9 / 5" text by RNV; RNV and C1–C4 are partial by decision 7; F26–F29 is the fixture's finding already. The fixture keeps no stage 4–6 outputs, so the review actions still price its stored lines.
- [x] `make gen-client`.

### Frontend
- [x] **Overlay** (`screens/review/Drawing.tsx`, `Viewer.tsx`, `drawingModel.ts`): the spots as dashed red SVG boxes with the prototype's label tab and the note as the tooltip; the "לא פוענח N" button in `.vtools` with `aria-pressed`, on by default (prototype `showUnresolved: true`); a red dot in a page's strip label when the layer is on and the page has a spot. Hidden entirely when the flag is off. Refetched with the quote after every action.
- [x] **Export** (`screens/review/ExportModal.tsx`): the "הורדה" button in `.rv-head` between undo and chat; the prototype's modal: title, the "דגל" chip, the version, the white `.doc` preview of the customer document from `/document`, "N שורות בלי מחיר יופיעו במסמך בלי סכום.", the explanation line, "PDF ללקוח", "Excel פנימי", "סגור". A version selector in the header row when the quote has more than one version, defaulting to the current one; the preview and both downloads follow it (decision 2). A draft's preview shows the "טיוטה" mark. Each button downloads from the API; a failure shows a toast.
- [x] The prototype's CSS (`.ux`, `.doc`, `.modal.wide`, `.v2`) into `theme/app.css` with the same class names, with a dark variant where the tokens need one.
- [x] **"המסמך ללקוח" on the settings screen** (`screens/prefs/`, decision 1; no prototype screen, so the settings screen's own classes): the logo (upload, preview, remove), the company details, the terms, "הצג מק"ט במסמך". Shown when `export_doc` is on.

### Unit tests
- [x] The spot builder: each of the four kinds, an orphan text a stage-4 instance read is not a spot, a dismissed finding and an approved or resolved line drop off, a manual line over an unknown symbol hides it, the orphan filter.
- [x] The customer document: the HTML has no cost, margin, supplier, colour or price source (a test enforces 07 §12), an unpriced line has no amount, totals are the stored strings, the discount row only with a discount, RTL and `dir="ltr"` on numbers and SKUs, the SKU column only with `show_sku`, the "טיוטה" mark only on a draft, every template value escaped.
- [x] The logo check: PNG and JPEG by their bytes, not the name; SVG, other types and over 1 MB refused.
- [x] The Excel: sheets, headers, right to left, money cells are numbers equal to the stored `Decimal`s, every live line is a row, findings listed.
- [x] Vitest: the overlay model (boxes per page, the strip's dot, the count), the modal's preview rows and its warning.

### Integration tests
- [x] `GET /quotes/{id}/unresolved` on the NURSERY fixture returns the prototype's spots and RNV and C1–C4; flag off is 404; another tenant's quote is 404; after "אשר" on RNV or a dismissed F26–F29 finding the spot is gone.
- [x] A pipeline drawing (the stand-in model) answers with spots from its real stage outputs.
- [x] `export.pdf` returns a PDF (Chromium) whose text has the lines' amounts and the totals and none of the costs; `export.xlsx` opens with openpyxl and its money equals the API's; flag off is 404; another tenant is 404; an older sent version exports its own lines; a draft's PDF has "טיוטה", a sent one doesn't.
- [x] The template: `PUT /settings/document` and the logo round-trip, the logo lands under the tenant's own prefix, another tenant never sees it, and the PDF shows the details and terms.
- [x] Each new route is covered by `test_api_routes.py` (an actor and a flag).

### UI tests (Playwright)
- [x] Desktop and mobile projects:
  - The overlay on NURSERY: the labelled boxes over pages 4, 5 and 8 (12, decision 7), the button's count, the strip's dots, the toggle hides and shows them; on the phone in the drawing tab.
  - Export: "הורדה" opens the modal with the preview and the unpriced warning; "PDF ללקוח" downloads a `.pdf` and "Excel פנימי" a `.xlsx` with the expected names; after sending and opening version 2, the selector switches the preview to version 1.
  - Settings: "המסמך ללקוח" saves the details and the terms, uploads and removes a logo.
  - A tenant with both flags off: no "הורדה", no "לא פוענח", no boxes.
- [x] Prototype-fidelity shots for the overlay (pages 4 and 8), the export modal and the settings section, light and dark, desktop and mobile, and a printed PDF page for review: accepted by the user (decision 12); the review and picker screenshot baselines rewritten with `make screenshots`.

### Eval (pipeline sessions)
- [x] Not a pipeline session: `make eval` ran in `make check`: no change against the baseline.

### Docs
- [x] 13 §4.1 and §4.4, and §6 item 2: the decisions below.
- [x] `docs/db-schema.md` if the template needs a column.
- [x] CLAUDE.md: the built list and the prototype map (overlay and export modal built), the Playwright Chromium for the backend in Commands.
- [x] `docs/roadmap.md`: S26's status; the backlog's "הורד דוח" for an audit can reuse the export.

## Acceptance criteria

- [x] On the NURSERY fixture with the flag on, the drawing shows the prototype's spots on their pages with the prototype's labels, and RNV and C1–C4 as partly read (decision 7): the button counts 12, and the strip marks pages 4, 5 and 8.
- [x] With `unresolved_overlay` off, `GET /quotes/{id}/unresolved` is 404 and the screen has no button, boxes or dots.
- [x] The customer PDF's text has every live priced line's description, quantity, unit price and line total, and the stored net, VAT and gross totals, and none of the lines' costs, margins or suppliers (a test reads the PDF).
- [x] The internal Excel has every live line with its cost, price source, colour and tags, and its money equals the API's to the agora.
- [x] With `export_doc` off, both export routes are 404 and the screen has no "הורדה".
- [x] The customer PDF carries the factory's logo, details and terms from "המסמך ללקוח", SKUs only when the factory shows them, and "טיוטה" on every page of a draft only.
- [x] The modal's selector exports an earlier version's own lines and totals.
- [x] `make check` passes: lint, licenses, secrets, unit, integration, eval, E2E; the client check after the commit; the screenshots with BUG-038's picker timeouts passing rerun alone and BUG-098 (midnight) passing on the next run.

## Out of scope

- "הורד דוח" for an audit (11 §7): in the backlog, and it can reuse this session's export.
- ERP export (phase 4).
- A template editor (layout, colours, fonts): the template is the logo, details, terms and the SKU toggle (decision 1, 13 §6 item 2).
- Sending the PDF to the customer from the app (email): the factory downloads it and sends it.
- A usage table for every flag (13 §3 rule 4): this session logs its downloads (decision 6); a table that counts every flag's use goes to the backlog.

## Open questions

All answered at kickoff; see the decisions below.

## Outcome

Filled in at `/session-close`.

- **Done:**
  - The "לא פוענח" layer (13 §4.4, `unresolved_overlay`): `services/unresolved.py` reads the four kinds in code from stages 3–5's outputs, the current lines and the open findings; `GET /quotes/{id}/unresolved`; the drawing's dashed red boxes with their tabs, the toolbar's "לא פוענח N", the strip's red dots, on by default. The NURSERY fixture has a stage-3 output with the prototype's unknown symbol and orphan text (`seed_nursery_detections`).
  - The export (13 §4.1, `export_doc`): `GET /quotes/{id}/versions`, `/versions/{n}/document`, `/export.pdf` (Chromium through the Python `playwright`, offline, the app's fonts embedded, every value escaped, "טיוטה" on a draft) and `/export.xlsx` (openpyxl, right to left, lines, findings, totals; cost permission). The prototype's modal with a version selector, from the review header.
  - The customer PDF's template (decision 1): migration 0023 (`tenant_settings.document`), `/settings/document` and its logo (PNG or JPEG, checked by its bytes, under the tenant's `branding/`), the settings screen's "המסמך ללקוח", the demo factory seeded.
  - Tests: unit (the spot rules, the customer HTML and its 07 §12 words, the logo check, the formatting), integration (the layer on the fixture and on a pipeline drawing, the PDF read back, the Excel's money against the API, versions, the template, flags, tenants, cost permission), Vitest, Playwright on desktop and mobile (`unresolved.spec.ts`, `export.spec.ts`), fidelity shots accepted, and 25 review and picker baselines rewritten.
  - `make install` and CI install the backend's Chromium; Playwright pinned to the frontend's 1.64.1.
- **Decisions made:**
  1. **The customer PDF's template** (the user, 13 §6 item 2). A "המסמך ללקוח" section on the settings screen: logo upload, company details (name, ח.פ., address, phone), terms text, and a show-SKU toggle, stored in `tenant_settings` and seeded for the demo. No prototype screen; it follows the settings screen's classes.
  2. **Which version** (the user, 13 §4.1 over the prototype). The modal has a version selector when the quote has more than one version, defaulting to the current one; the preview and both downloads follow it.
  3. **A draft's customer PDF** (the user). Allowed, with a "טיוטה" mark on every page; a sent version has none. The internal Excel works on any version.
  4. **Orphan texts on the overlay** (the user). Only an unclaimed text that reads as a rating, a designator or a model code, by stage 2's tags and stage 4's grammar; the count per golden drawing is measured and reported.
  5. **The prototype's overlay boxes** (Claude). `boxesFor` reads an overlay box as `b[1]…b[4]`, as if it began with a page number like a line's boxes, so the prototype draws its four spots shifted and with no height. The app uses the box as given (x0, y0, x1, y1); the fidelity shots differ there.
  6. **Measuring the two flags** (Claude, 13 §3 rule 4). Each download writes a structured log line (tenant, user, quote, version, format); no flag is counted in a table yet, so a usage table for every flag goes to the backlog.
  7. **"פוענח חלקית"** (the user, 13 §4.4 vs the prototype). The spec marks every drawn line with no SKU or a missing required value; on NURSERY that is Q0, NVR, RNV, C1–C4 and the enclosure, where the prototype's hand-made list has RNV only. Chosen: a live, unapproved line whose product is not identified (stage 5 found none, several or a conflict, and the user chose none) or whose current or poles were not read (missing, or inferred from the circuit). A missing price or a filled-in kA is not a reading problem. NURSERY shows RNV and C1–C4.
  8. **Orphan texts are stage 3's already** (Claude, decision 4). Stage 3 keeps as orphans only the spans stage 2 tagged as a device's value (current, curve, kA, mA, poles, setting; `detection/orphans.py`), so wire and terminal numbers never reach the layer and no second filter is needed. The fixture's "9 / 5" is the prototype's text, written into its stage-3 output by hand.
  9. **One box per place, one tab per line** (Claude). Two spots in the same place are drawn once, the more specific kind (the fixture's "9 / 5" sits on RNV's own contact; on a real drawing an orphan is far from every symbol). A line's boxes on a page share one tab, on the topmost: C1–C4's eight symbols on page 8 would otherwise run eight tabs into each other.
  10. **The customer document from the screen's own read** (Claude). `quotes.read_quote` takes a version number, and the PDF, its preview and the Excel are built from it, so a document never says what the screen doesn't. A kit part included in its parent's price is not a row of the customer document; it is a row of the Excel. SKUs are off by default, as the prototype's document has none.
  11. **The Excel needs cost permission** (Claude, 07 §12). The PDF and its preview don't. The fonts are the app's (@fontsource, OFL), copied into `backend/konboro/services/fonts/` with their license, so the PDF needs no network; Chromium prints offline and every request is refused.
  12. **The screens are accepted** (the user, dev-strategy §5). The fidelity report's S26 screens (the layer on pages 4 and 8, the export modal, "המסמך ללקוח") and the sample customer PDF with a stand-in logo. The review and product-picker baselines change with them: their drawing shows the layer and their header "הורדה".
- **Eval / metrics:** not a pipeline session. The layer on the golden set (the last eval run's outputs, scratch script): 25.26.100 13 boxes, 26-993 17, 6199-2-50 72 (71 partial on 42 lines, 1 orphan text "250A"), BOM-HW-1 3, MINHAROT-1 23, NEVIS-1 27 (1 unknown symbol), NURSERY-1 15 (2 unknown symbols). The eval has no price list, so every partial note says "ואין מחיר" there. The customer PDF prints in about 1.5 s.
- **Bugs logged:** BUG-098 (P3, the phone's home shot across midnight: a mask's width follows the relative time; not S26's code). BUG-038 seen again: desktop picker shots timed out in `make check`'s screenshot step (four) and in a standalone `make check-screenshots` (three), at load average 24–27, no pixel difference; all ten passed rerun alone.
- **Follow-ups:** in `docs/roadmap.md`'s backlog: a usage table for every flag (decision 6); the customer PDF's template beyond decision 1 (a template editor, after the pilot factory's view); the audit's "הורד דוח" can reuse `export_pdf.py` and `export_xlsx.py`. Not done: the layer reads stages 3–5 from S3 on each request (fine for the fixture's sizes; cache it if a large drawing makes the review screen slow).
