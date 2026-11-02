# S14: BOM-only path

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s14-bom-only` |
| **Depends on** | S08 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#15](https://github.com/moth1990/KonvoroAI/pull/15) |

## Goal

A bill of materials with no drawing becomes components. An Excel or CSV file is read directly, its columns mapped (item, quantity, panel); a photographed, scanned or handwritten BOM is transcribed through `table_transcription`, with a confidence per cell. Every row goes through stage 4's spelling grammar and the abbreviation dictionary into the stage-4 contract, each value with `source` = `bom` and the row's place on its page. BOM-HW-1 goes through the pipeline for the first time.

## References

- Specs:
  - 01 §5.8 (the BOM-only path: sources and methods, rows through the grammar, `source` = `bom`, row position, continued rows, the form's heading, Hebrew terms, untyped "מפסק", `bom_possibly_cropped`), §4.2 (XLSX and CSV: one sheet with data = one page), §4.4 (`input_kind`), §4.5 (a BOM-only upload counts in the quota), §7 (`bom_table` routes to `context`), §8 (`bom_possibly_cropped`, `unsupported_format`), §11 (no customer details).
  - 00 §4.4 table (BOM-only: stage 1 reads the table instead of stages 2–4), §7.1 (`table_transcription`: what it gets; the customer's contact details are not kept from its answer), §7.2 (closed answers, checked in code).
  - 04 §5.1 (the spelling grammar), §6.3 (the component contract), the `bom` row of the evidence table.
  - 03 §4.6 (the abbreviation dictionary, global level: Hebrew terms → family).
  - 05 §5.5.1 (an untyped "מפסק" is decided by its current, in stage 5: S14 leaves the class open).
  - 06 §6.3 (a drawing's `bom_table` is compared with the quote: S21; S14 only produces the artifact).
  - 11 §4 (the quote audit reads an existing quote through the same transcription: S15 reuses this session's table reader).
  - 12 (openpyxl for Excel).
- Prototype: none for the path itself. The new-quote screen (754–869) already takes XLSX and CSV and shows `input_kind` on the done step; the home list's mock row 478 is BOM-HW-1 ("לוח חשמל קומה י"א", "כתב כמויות בכתב יד · 19 מוצרים").
- Golden: BOM-HW-1 (19 products, 91 units; row 8 continues on the next line; row 2 "מפסק 3X40" is a mistake in the form, merged into row 15 by the owner; "פחת" with no mA; heading → panel and project; customer not kept). Today its stage-4 metrics are 0 (no path).
- Earlier sessions:
  - S08: stage 1 lists each spreadsheet sheet as a `bom_table` page (code, no model); `input_kind` is `bom_only` when every page is a `bom_table`; the form's heading is left to this session; no panel for BOM-HW-1.
  - S13: the grammar (`association/grammar.json`, `grammar.py`), attribute schemas, the `components` table, `MergeResult`, stage 5's stub passing components through.

## Tasks

### Backend
- [x] Excel and CSV reader (`pipeline/bom/sheets.py`, openpyxl, MIT): every worksheet a page, cells as text (whole numbers without ".0", dates as ISO, formulas as Excel's saved value), CSV in UTF-8 or cp1255 with `,` `;` or tab.
- [x] Column mapping (`pipeline/bom/mapping.py`): the header row found among the first 15 rows, a Hebrew and English header dictionary (price is checked first: "מחיר יחידה" is not a unit), `table_transcription` only for the headers code doesn't know, columns by letter and every number masked (decision 2). Each column keeps who gave its role (`code` / `model` / `user`).
- [x] A picture of a BOM (a photo, or a PDF page classified `bom_table`): `table_transcription.transcribe`, a closed schema with no field for the customer (heading's panel and project, columns with roles, cells with a confidence each, a box per row on a 0–1000 grid). Code drops price cells, clamps confidences and boxes, and turns boxes into points (`pipeline/bom/table.py`).
- [x] Row rules: a picture's row with no quantity continues the one above; a spreadsheet's row with an empty quantity cell is a heading; empty and total rows dropped; an unreadable quantity is kept with none (decision 8); the panel cell carries down.
- [x] `bom_possibly_cropped` when a picture's last row reaches the bottom 1.5%; `bom_no_rows` when no table reads a product.
- [x] The heading names the panel and the project on a BOM-only drawing (title block fields left empty are filled from it); its panels come from the tables, also when a page kind or a column role changes (`corrections._rebuild_panels`).
- [x] Every `bom_table` page kept as a `bom_table` context artifact, any input kind; a reused page keeps its table.
- [x] Stage 4 on a BOM-only drawing (`association/bom.py`, `s4_association.run_bom`): normalized as stage 2 does, the family from the BOM words (decision 6), the grammar's values with `source` = `bom` and no span, the row numbers and box on the instance (decision 5), merge by panel, family, class, values, model text and brand. Unknown products stay red; an unconfirmed mapping keeps rows yellow.
- [x] BOM words (`pipeline/bom/terms.py`, decision 6) instead of the drawing's abbreviation dictionary: "מא"ז", "פחת", "מגען", "מגן מתח יתר", "סליל הפסקה", "משנה זרם", "רב מודד", "שעון שבת", "לחצן חירום" and more. "מפסק" alone gives the family, the class stays `unknown_symbol` for stage 5 (05 §5.5.1).
- [x] The user's side (`pipeline/bom/review.py`, `corrections.set_bom_columns`, `settle_bom_mappings`): `PUT /drawings/{id}/pages/{page_id}/bom-columns` behind `bom_column_mapping`, a `bom_columns_mapped` correction event (migration 0010), confirm refusing a mapping with no item or quantity (`bom_mapping_incomplete`), and the `bom_mapping` reason kept when the intake is rewritten.
- [x] The run step's lines for a BOM-only drawing: "כתב כמויות · 20 שורות · לוח אחד", "אין שרטוט, רק כתב כמויות", "20 שורות ב-20 מוצרים".
- [x] The progress API's pages carry their BOM table (columns, roles, who gave them, two samples, product rows).
- [x] `table_transcription` on Opus (decision 7); the stand-in model answers both calls (`devtools/fake_llm.py`).

### Frontend
- [x] The confirm step's mapping table, behind `bom_column_mapping`: column letter, header, samples, a role select and who gave the role. A change is sent at once (as a page kind is), and "אשר והמשך" waits for one item and one quantity column. On the phone the samples go under the header. The prototype's `.tbl` styles ported to `app.css`.
- [x] A spreadsheet's page card shows "גיליון, בלי תמונה" instead of a broken image (BUG-029).
- [x] The done step needs nothing new: input kind "כתב כמויות · בלי שרטוט", the panels and the page routes already show.

### Unit tests
- [x] `tests/unit/test_bom.py`: workbooks and CSV (encodings, delimiters, broken files), header roles and the header row, code-only mapping, the model seeing no number (on `map_sheet` and on the request the client sends), a picture checked in code, the continued row, spreadsheet rules, quantities, panels, every BOM word in the library, BOM-HW-1's labelled rows → components (91 units, every value `bom`, no span), merging, unknown and unreadable rows, the unconfirmed mapping, the stand-in's answers. Merged header cells are not handled: openpyxl's read-only mode gives the first cell only (none of the goldens has one).
- [x] Vitest: `bomPages`, `bomProblem`, the role names, the new confirmation reason.
- [x] The stage-4 contract snapshot rewritten for decision 5; the transcription answer has no customer field (tested; it is a model answer, not a stage contract).

### Integration tests
- [x] `tests/integration/test_bom.py`: a workbook through all 7 stages (two panels, components, run-step lines, no model call, quota counted, RLS), a CSV in UTF-8 and cp1255, a photographed BOM (panel and project from the heading, the continued row, boxes, one `table_transcription` call logged), `bom_possibly_cropped`, an unsure mapping waiting for the user (no digit sent, roles changed, confirm refused then accepted, the correction event), the flag off (goes on yellow, the route answers 404), another tenant's 404.

### UI tests (Playwright)
- [x] `e2e/bom.spec.ts`, desktop and mobile: a CSV through the 7 stages to the done step; an unsure CSV on the confirm step, a role changed, confirm disabled without a quantity column, then confirmed through to done. The flag-off path is the server's and is covered by the integration test.
- [x] Screenshots of the mapping step (desktop and mobile, light and dark) reviewed and accepted by the user (2026-11-02). No prototype screen to compare with.

### Eval (pipeline sessions)
- [x] BOM-HW-1's `table_transcription` call recorded live (`EVAL_RECORD=missing`, capped at $3); `make eval` replays; the baseline updated (`make eval-baseline`). Numbers under Outcome.

### Docs
- [x] 01 §5.8: "קומה י"א" (decision 4) and the S14 decisions. 04 §6.2: the instance's nullable `det_id` and `bbox`, `method` `bom`, `rows`. 13 §4.5: `bom_column_mapping`.
- [x] `docs/db-schema.md`: the `bom_table` artifact, BOM instances in `components.instances`, the new correction type. CLAUDE.md's pipeline paragraph and screens list.

## Acceptance criteria

- [x] BOM-HW-1: component recall ≥ 0.85 and unit recall ≥ 0.85 against its 19 products / 91 units. Recall 0.944 (17/18), unit recall 0.989 (90/91), precision 0.944.
- [ ] BOM-HW-1: panel named "לוח חשמל קומה י"א", project "פלבס", no customer name or contact detail stored anywhere. Project and privacy met. **The panel name is not**: Opus read the handwritten floor as "קומה ע" (Sonnet read "קומה ג'" and "קומה יג"). The eval pairs the drawing's one panel anyway. Logged as BUG-030, for the gate (S17).
- [x] Every component attribute on a BOM-only drawing has `source` = `bom`; `values_without_evidence` = 0 (the eval counts a BOM row as its value's evidence).
- [x] No model request in the BOM path contains a price or a number from a spreadsheet (unit and integration tests).
- [x] XLSX and CSV files go through the pipeline end to end; the four drawing goldens' eval numbers do not change.

## Out of scope

- Catalog matching of BOM rows, the untyped "מפסק" decided by current, the 30 mA default: stage 5 (S20).
- `BOM_ACCESSORY_HOST_COUNT`, `BOM_NO_ENCLOSURE`, and the BOM cross-check on `mixed` drawings (06 §6.3): S21.
- Ancillary items by module count (07 §7.4): stage 7.
- Highlighting low-confidence cells on the review screen: the review screen reads pipeline quotes from S22.
- Reading an existing quote for the audit: S15, on top of this session's table reader.

## Open questions

All four were answered at kickoff; see "Decisions made" under Outcome.

1. ~~01 §5.8 says the user confirms the Excel column mapping. The prototype has no screen for it. Build one, or not yet?~~ Decision 1.
2. ~~How much of a spreadsheet may the mapping model see, given that prices never go to a model?~~ Decision 2.
3. ~~Where do BOM rows become components?~~ Decision 3.
4. ~~01 §5.8 calls BOM-HW-1's panel "קומה י"ג"; fix the spec?~~ Decision 4.

## Outcome

Filled in at `/session-close`.

- **Done:** A BOM with no drawing goes through the pipeline. Stage 1 reads every BOM page into a `bom_table` artifact: a spreadsheet in code, with its columns mapped by the header dictionary and the model only for headers code doesn't know (no number from the file sent), and a picture through `table_transcription` on Opus. The form's heading names the panel and the project; customers have no field. On a `bom_only` drawing stage 4 turns the rows into components with `source` = `bom`, and stages 2–3 pass through. An unsure mapping stops on the confirm step for the user behind `bom_column_mapping`. BOM-HW-1 goes through the pipeline for the first time.
- **Decisions made:**
  1. **Column mapping is confirmed only when unsure** (user, at kickoff). Code maps the headers it knows. A mapping the model made, or one with no item or no quantity column, stops the drawing at the existing confirm step (`awaiting_confirmation`, reason `bom_mapping`). That step gets a small mapping table in the style of the prototype's confirm page, behind a new flag `bom_column_mapping`, with fidelity screenshots for the user. With the flag off, an unsure mapping goes on and its components are `uncertain`. 01 §5.8 is updated to say this.
  2. **What the mapping model sees** (user, at kickoff): the header text, plus up to 5 sample cells per column, with every number replaced by its shape (`<int>`, `<decimal>`), in text cells too ("מא"ז <int>X<int>"). Columns go by letter, so nothing from the file adds a digit to the request. No numeric value leaves (non-negotiable 6), and tests check the request.
  3. **Stage 1 reads, stage 4 builds** (user, at kickoff). Stage 1 reads every `bom_table` page into a `bom_table` context artifact, for every input kind (S15's audit and 06 §6.3 reuse it). On a `bom_only` drawing, stages 2 and 3 pass through with nothing to do, and stage 4 turns the rows into `components` through its own grammar. The contract keeps one writer, and the coordinator does not change.
  4. **BOM-HW-1's panel is "קומה י"א"** (user, at kickoff): the golden, its README and the prototype win over 01 §5.8's "י"ג", and the spec is fixed in this PR.
  5. **A BOM row is an instance with no detection** (in session, contract change). `Instance.det_id` and `Instance.bbox` may be null, `method` gains `bom`, and `rows` keeps the row numbers (01 §5.8 item 2: the row's place instead of a place on the drawing). The merge and the rest of the contract are unchanged; 04 §6.2 updated.
  6. **BOM words apart from the drawing's abbreviations** (in session). Adding Hebrew product names to `detection/library.py`'s dictionary would change stage 3's prompt (the dictionary is in it) and its cassettes on every drawing. The BOM words are their own list (`pipeline/bom/terms.py`); a tenant's own words are in the backlog.
  7. **`table_transcription` runs on Opus** (in session, measured on the golden set). Sonnet read BOM-HW-1 with recall 0.83 and unit recall 0.37 ("מצען" for "מגען", "1X10" for "1X16" ×54), and its first answer broke the box schema, costing a retry. Opus: recall 0.94, unit recall 0.99, quantity accuracy 1.0, one call. About $0.06 a page at the repo's list prices (3.6k tokens in, 2.3k out). Boxes past the grid are now clamped in code, not retried.
  8. **No quantity is made up** (in session). A spreadsheet row with an empty quantity cell is a heading; a quantity cell with no whole positive number in it ("2.5", "x") keeps the product with quantity 0, uncertain, with an issue; it never merges with another row.
- **Eval / metrics:** BOM-HW-1 (replay): component precision 0.944 (17/18), recall 0.944 (17/18), quantity accuracy 1.0 (17/17), unit recall 0.989 (90/91), values without evidence 0, panel count 1/1. The miss: "מגן מתח יתר 40KA" read as "מגן מתח ותדר", so the row is `unknown` (red). `bom_possibly_cropped` fires on BOM-HW-1: its last row sits on the photo's bottom edge (the owner says nothing follows; the warning is what 01 §5.8 asks for). Totals: stage-4 component recall 0.565 → 0.680, unit recall 0.470 → 0.689; the four drawings unchanged.
- **Bugs logged:** BUG-029 (fixed), BUG-030 (open, P2, for S17: BOM-HW-1's panel name misread).
- **Follow-ups:** in the roadmap backlog: a tenant's own BOM words, a misread BOM word, BOM tables in a vector PDF read from the text layer, the done step's product count.
