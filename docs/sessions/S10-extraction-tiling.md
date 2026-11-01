# S10: Stage 2, extraction and tiling

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s10-extraction-tiling` |
| **Depends on** | S08 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#11](https://github.com/moth1990/KonvoroAI/pull/11) |

## Goal

Stage 2 is real. Every `process` page is rendered at a DPI chosen by code, its text comes out as positioned spans (from the PDF text layer, or from OCR through an `OcrEngine`), normalized with the raw text kept, and the page is cut into 1024 px tiles with 256 px overlap for stage 3. Deep-zoom tiles for the drawing viewer (S11) are written to S3. The run step's stage-2 line shows real numbers.

## References

- Specs:
  - 02 (all): §2.1 rendering and DPI, §2.2 vector extraction, §2.3 OCR and the re-read, §2.4 normalization, §2.5 wire graph, §2.6 tiling, §6 output contract, §7 decision rules, §8 issues, §10 metrics.
  - 12 §5 (pdfplumber, OCR candidates, Textract ruled out), §6 (OpenSeadragon tiles made in stage 2), §8 (licenses).
  - 00 §6.1–6.2 (ID prefixes `ts_`, `tl_`; PDF points, origin top left), §7.1 (stage 2 has no LLM: "OCR"), §7.2 (LLM rules), §7.3 (provider terms).
- Prototype: none for the stage itself. Line 762, the run step's stage-2 line: "שכבת טקסט חסרה, OCR על 6 עמודים · 58 אריחים".
- Golden: the four PDFs. All have their text drawn as lines (`text_source` = `ocr`); 26-993 has a 12-character misleading text layer. 6199-2-50 is a 1400 × 600 mm single page. No golden file labels text spans or symbol boxes.
- Earlier sessions:
  - S05 left the stage-2 stub and the run step's per-stage summary.
  - S07 serialized PDFium behind one lock (BUG-010); the backlog notes that S10's renders may need a process pool.
  - S08: `Page.geometry_source`, `text_source`, `rotation_applied`, `quality`, `panels[].bbox`; the stable image keys for cassettes; the stand-in model.
  - External blocker B4: no Google Vision or Azure keys. The engine choice is S31.

## Tasks

### Backend
- [x] Replace `pipeline/stages/s2_extraction.py` (`run(ctx) -> ExtractionResult`), with its parts in `pipeline/extraction/`. Pages run one after another, each page's tiles in parallel (8 OCR calls at a time); PDFium calls behind the existing lock.
- [x] Rendering (02 §2.1): upright, 300 DPI, 400 for `low_resolution`, and for large vector pages a DPI from the text height (`target_text_height_px` = 30, floor 150). Render to S3; `px_per_pt` recorded.
- [x] Vector extraction with pdfplumber (02 §2.2): text spans with bbox, font size, angle; lines, curves and rectangles with width and colour (02 §12 item 5) to `paths.json.gz`; layers (OCGs). Only where `geometry_source` / `text_source` say so (02 §7). `cad_blocks` and `pre_detections` stay empty (2.0).
- [x] `OcrEngine` interface: per-word text, bbox in the image's pixels, rotation, confidence. A `FakeOcrEngine` for unit tests, the stand-in model's OCR answer for integration and E2E, and `ClaudeVisionOcr` (decision 1).
- [x] OCR flow (02 §2.3): over the panels' area, rotated text, the `ocr_min_confidence` filter (0.4, dropped spans logged), the re-read of mid-confidence electrical-looking spans on a 600 DPI crop. In `mixed` pages, only where there is no reliable vector text; vector wins on > 50% bbox overlap (`text_layer_mismatch`).
- [x] Normalization (02 §2.4), as data plus code: units and spacing, poles tag, OCR fixes only to a dictionary token from a confusable source (O/0, l/1, S/5, B/8), never a number on its own, −10% confidence and a `corrections[]` entry per fix, Hebrew direction, merge of nearby spans with `merged_from`. Tags: `current_a`, `poles`, `curve`, `breaking_capacity_ka`, `residual_ma`.
- [x] Tiling (02 §2.6): the whole page (not the panels' union + 5%: BUG-019), 1024/256 grid, white padding recorded, `is_blank` at 99.9% white (not 02 §2.6's 98%: see Decisions), `panel_ids` and `span_ids` per tile, tile PNGs in S3.
- [x] Wire graph (02 §2.5), nodes and edges from the vector lines: wiring lines only (a PDF gives no per-line layer, so: inside the panels' area, not inside a text box, no rectangles, no letter-sized specks), segments joined within 0.5 pt, nodes at junctions and ends, `wires.json.gz` in S3. Block links stay 0 until stage 3 gives detections. `vector_too_complex` skips it. Raster pages: `status` per 02 §7 (contract aligned to the spec: `built`, `skipped`, `not_supported`).
- [x] Deep-zoom pyramid (12 §6) from the render: DZI, written under the page's S3 prefix. Serving it is S11.
- [x] Issues (02 §8): `render_failed`, `vector_too_complex`, `ocr_low_confidence`, `text_layer_mismatch`, `no_text_found`.
- [x] Stats (02 §6.1) and the run step's stage-2 summary from them (prototype line 762).
- [x] Settings for tile size, overlap, blank threshold, DPIs, OCR thresholds.

### Frontend
- [x] Nothing new: the run step already shows a stage's summary. The accepted `new-run` shots are unchanged (they catch stage 2 running, before its line shows).

### Unit tests
- [x] DPI choice; tile grid, padding and blank detection; tile coverage: every box no larger than the overlap lies wholly in some tile (property test); pt ↔ px conversions.
- [x] Wire graph: segment joining within tolerance, junction and end nodes, frame and table lines filtered out, on small synthetic path sets.
- [x] Normalization: each 02 §2.4 row, the "never fix a number alone" rule (`18A` stays), the −10% and `corrections[]`, span merging, tags.
- [x] OCR flow on `FakeOcrEngine`: the 0.4 filter, the re-read replaces only when confidence rises, vector-over-OCR merge.
- [x] The interim engine's answer check (whatever the answer to question 1 is).
- [x] Contract snapshot updated if the contract changes.

### Integration tests
- [x] Stage 2 through the queue on the golden PDFs with `FakeOcrEngine` (or cassettes): renders, tiles and DZI land under the tenant's S3 prefix; another tenant's key is refused.
- [x] A synthetic PDF with a real text layer goes the `pdf_text` path with no OCR call.
- [x] The progress endpoint returns the stage-2 summary.

### UI tests (Playwright)
- [x] Desktop and mobile: the run step shows the stage-2 summary once stage 2 is done (stand-in engine).
- [x] `new-run` screenshots: re-checked, all 36 accepted shots match (`make check-screenshots`); nothing to review.

### Eval (pipeline sessions)
- [x] A stage-2 metric that the labels can support (open question 4), plus `tile_count`, `blank_tile_count` and OCR cost per drawing.
- [x] Record cassettes for the interim engine live, within the agreed ceiling; `make eval` in replay; numbers recorded under Outcome; `make eval-baseline`.

### Docs
- [x] Spec 02 (and 00 §7.1, 12 §5 if the interim engine is an LLM) updated with this session's decisions.
- [x] `docs/db-schema.md` for any new column; CLAUDE.md "Stages" line (stage 2 is real).
- [x] 02 §12 has two items numbered 6; renumber.

## Acceptance criteria

From 02 §10, as far as the golden set can measure them now:

- [x] Tile coverage 100%: proven by construction (overlap ≥ the largest symbol) and the property test (`test_any_box_up_to_the_overlap_lies_whole_in_one_tile`); measured against symbol boxes when S12 labels them.
- [x] Every `process` page in the golden set has a render, tiles and a DZI pyramid; no page fails (14 of 14, no `render_failed`).
- [x] The stage-2 metric (designator recall, 99.2%) is in `eval/baseline.json`; two replays gave identical reports, equal to the live run.
- [x] 02 §9: a vector page with a text layer in 0.1 s (synthetic A4, `test_a_page_with_a_text_layer_needs_no_ocr`); a golden A4 page 1.1–1.5 s without OCR time, 6199-2-50 (A0) 5.5 s. OCR adds about 9 s per batch of 8 tiles with the interim engine, so an A4 page takes about 20 s (02 §9's 15 s target is the real OCR engine's, S31).

## Out of scope

- The engine choice between Google Vision and Azure, and the 97% OCR token target: S31 (blocked on keys, B4).
- DXF/DWG, block mapping, `pre_detections`: 2.0.
- Serving deep-zoom tiles and the viewer: S11.
- Symbol detection on the tiles: S12. Cross-tile de-duplication: S12 (03 §3.5).
- Image retention after 90 days (02 §9): later, with the storage lifecycle.

## Open questions

All answered at session start (2026-11-01); see Decisions made.

1. ~~**Interim OCR engine.** The roadmap names `ClaudeVisionOcr`, but 02 §2.3 says no LLM for OCR ("does not return reliable coordinates per word"), 02 §9 says stage 2 has no LLM, and 00 §7.1 lists stage 2 as OCR only. Without Google or Azure keys (B4), which interim engine?~~
2. ~~**Wire graph (02 §2.5).** The roadmap row for S10 leaves it out. Its consumer is stage 6 (S21), and with no CAD blocks in 1.0 it can link only to detections from stage 3. Build it now, or defer it?~~
3. ~~**Live recording.** A ceiling for the live run that records the OCR cassettes, and the key to use.~~
4. ~~**Stage-2 metric.** No label has text spans or boxes. Proposal: designator recall, the share of labelled designators (NEVIS-1, NURSERY-1, 26-993) found among the spans of the drawing's `process` pages after normalization. 6199-2-50 has none.~~

## Outcome

- **Done:**
  - Stage 2 is real (`pipeline/stages/s2_extraction.py`, its parts in `pipeline/extraction/`):
    - rendering at a DPI chosen from the text height (`render.py`), upright, with `px_per_pt`;
    - the PDF's words, lines, shapes, colours and layers with pdfplumber (`vector.py`), Hebrew put back in reading order;
    - the `OcrEngine` interface, `ClaudeVisionOcr` through the new `ocr_transcription` route at effort `low`, and the flow around it (`ocr.py`): code checks on every word, overlapping copies combined, the 0.4 filter, the 600 DPI re-read;
    - normalization with the electrical-token dictionary as data (`normalize.py`): units, tags, OCR fixes that never touch a digit, merged neighbours;
    - the wire graph from vector lines (`wires.py`);
    - tiles over the whole page (`tiles.py`), and the viewer's DZI pyramid, packed (`deepzoom.py`);
    - 02 §8 issues, stats, `pages.render_key` / `tiles_prefix` / `tile_count` (migration 0007), and the run step's stage-2 line.
  - `konboro_llm`: an optional `LLMRequest.effort`; cassettes key on it only when set.
  - Eval: `designator_recall` (s2), stage-2 counts per drawing, `EVAL_RECORD=missing`, `EVAL_MAX_USD`; 271 OCR cassettes and a new baseline.
  - Local S3: tests, E2E and the eval each in a bucket of their own, emptied per run (BUG-020).
  - Docs: specs 02, 00 §7.1 and 12 §5; `docs/db-schema.md`; CLAUDE.md; `eval/README.md`; bugs BUG-019 to BUG-021; roadmap backlog.
- **Decisions made:**
  - Interim OCR engine (2026-11-01, user; roadmap vs 02 §2.3, §9 and 00 §7.1): `ClaudeVisionOcr` behind the `OcrEngine` interface, with its own route `ocr_transcription` in `konboro_llm/config.py`, run per 1024 px tile. Code checks the answer: every box inside the tile, text non-empty; overlapping tiles' copies of a word are compared to set its confidence. Specs 02, 00 §7.1 and 12 §5 say it is temporary until S31 picks Google Vision or Azure.
  - Wire graph (2026-11-01, user): built in S10, nodes and edges from the vector lines (02 §2.5). Block links wait for stage 3's detections.
  - Live recording (2026-11-01, user): the local `ANTHROPIC_API_KEY`, $20 ceiling. Stop and ask before passing it.
  - Stage-2 metric (2026-11-01, user; refined while building): designator recall, counting only components the label places on a `process` page, words split at spaces, `/` and `,` ("MS1/MS2/MS3"), the share of labelled designators found among the normalized spans of the drawing's `process` pages (NEVIS-1, NURSERY-1, 26-993). Tile coverage is proven in code by a property test, and measured against symbol boxes once S12 labels them.
  - Made while building (2026-11-01, Claude; for the user's review at close):
    - **Blank tiles at 99.9% white, not 02 §2.6's 98%.** A line drawing is that white: on 6199-2-50, tiles holding symbols and text have 0.2–2% ink, so 98% would have skipped about 40% of the sheet's tiles, content included. 02 §2.6 now says so.
    - **DPI from drawn letters.** With no text layer, the text height is the 90th percentile of stroke heights between 2 and 12 pt (01 §5.2's glyph size); with one, the median word height. On the golden set that gives 253–300 DPI, not the ~160 02 §2.1 expected for 6199-2-50 (its letters are 7–8 pt, 2.5–2.8 mm). Photos keep their own resolution. A page over 120 MP at its DPI is rendered smaller.
    - **OCR engine settings.** `ocr_transcription` on `claude-sonnet-5-5` at effort `low` (a new optional `LLMRequest.effort`; the cassette key includes it only when set, so S08's cassettes keep theirs). Confidence: 0.9 for a word the model calls clear, 0.6 for unsure; disagreeing copies in overlapping tiles are capped at 0.6, so they are read again. To calibrate against the real OCR engine at S31.
    - **Code checks on every OCR word:** inside the tile and off its padding, over ink (the box shrinks to its ink, and keeps the ink's colour when it isn't black), not cut by a tile edge the page continues past.
    - **Words from the PDF's text layer** are grouped by our code from pdfplumber's characters: pdfplumber splits sideways words, and its matrices already include the page's /Rotate. A space character ends a word. Hebrew is put back in reading order.
    - **`mixed` pages:** every non-blank tile is read; where an OCR word and a PDF word overlap by more than half, the PDF's wins and a disagreement counts towards `text_layer_mismatch` (info). Masking the PDF's text out of the tiles was the alternative; none of the golden pages is `mixed`.
    - **Merged spans replace their parts**; `merged_from` keeps the parts' ids. Only electrical tokens merge, never a designator, and a number with its unit merges without a space.
    - **IDs are by place, not random**, so a rerun gives the same ids and later stages' cassettes keep replaying: `ts_{nnn}_{mmmm}`, `tl_{nnn}_r{row}c{col}`, `nnn` the page's place among the drawing's process pages. `*_uri` fields hold the S3 key.
    - **Tags beyond 02 §6.2:** `setting_a` (`INC=8A`), `voltage_v`, `power_kw`, `cable_cores`, `cable_type`.
    - **Tiles over the whole page, not the panels' union + 5% (BUG-019).** Stage 1's panel boxes missed the lower half of 26-993 page 3 (7 of 37 tags), and 20–84% of the ink on most golden pages lay outside them. About 40% more tiles; 02 §2.6 says so.
    - **Wire graph filter by place:** a PDF gives no per-line layer that pdfplumber can read, so wiring is every line outside the text boxes, the title block stage 1 found and the frame (strokes wholly in a 4% border band, lines longer than 80% of the page), without rectangles; a connected piece smaller than 12 pt both ways is a drawn letter and is dropped. The PDF's layer names are kept (`vector.layers`); the golden PDFs have them (`TEXT`, `EL-panel`, …).
    - **Contract** (02 §6, snapshot rewritten): `Render.dzi_uri`, `TextSpan.color`, and `WireGraph.status` as `built`, `skipped`, `not_supported` (was `built`, `partial`, `unavailable`).
    - **The viewer's pyramid:** DZI, 510 px tiles with 1 px overlap, PNG, every level down to one pixel, under `pages/{page_id}/dz/`, packed into `tiles.bin` with an `index.json` of byte ranges (BUG-020; S11 serves it with ranged reads).
    - **Own buckets for tests, E2E and the eval**, emptied at the start of each run (BUG-020).
    - **E2E runs stage 2 at 100 DPI** (`devtools/e2e.py`): the screenshot check runs the worker in an emulated amd64 container, where full-size renders made the new-quote shots wait past 90 s. The stand-in model's OCR answer is one ink lookup per tile.
    - **Eval recording:** `EVAL_RECORD=missing` records only calls without a cassette, so S08's stage-1 answers stay as recorded; `EVAL_MAX_USD` stops a live run at a spending cap.
    - **Migration 0007, `pages.tile_count`:** the run step's line counts tiles without reading the stage output from S3. The line counts the tiles that go on to detection (not blank).
    - **`render_failed`** only for a failed render. A model or storage error fails the stage, so it is retried and a missing cassette can't hide.
- **Eval / metrics:**
  - First live recording (2026-11-01), tiles over the panels' area: 196 `ocr_transcription` calls, $1.78 at list prices. Designator recall NEVIS-1 100% (42/42), NURSERY-1 100% (41/41), 26-993 75.7% (28/37). The 26-993 misses led to BUG-019; those cassettes were deleted as stale.
  - Committed recording (2026-11-01), whole-page tiles: 271 calls on `claude-sonnet-5-5` at effort `low`, 629k tokens in and 115k out, **$2.41** at list prices. About $4.20 for the session, against the $20 ceiling (two attempts in between stopped at their first call: the account's credit had run out, nothing was charged). S08's 39 cassettes were not touched (`EVAL_RECORD=missing`).

  | Drawing | Process pages | Tiles (blank) | OCR spans | Wire edges | Designator recall |
  | --- | --- | --- | --- | --- | --- |
  | NEVIS-1 | 5 | 60 (0) | 762 | 932 | 100% (42/42) |
  | NURSERY-1 | 5 | 60 (1) | 765 | 974 | 100% (41/41) |
  | 26-993 | 3 | 36 (0) | 468 | 932 | 97.2% (35/36) |
  | 6199-2-50 | 1 | 144 (37) | 667 | 3,292 | n/a (no designators) |
  | **Total** | | | | | **99.2% (118/119)** |

  The one miss, 26-993's RF, is not written on the plan (its label says "בתוכנית בלי תג"). Two replays gave identical reports, equal to the live run; `eval/baseline.json` rewritten with `make eval-baseline`, every earlier metric unchanged. One tile takes about 9 s live; 8 run at a time.
- **Bugs logged:** BUG-019 (P1, tiles missed what stage 1's panel boxes missed), BUG-020 (P2, S3Mock slows with every object; own buckets, packed pyramid), BUG-021 (P2, a keyboard E2E test raced the home page), BUG-022 (P2, a new-quote E2E test that decodes twice outran 30 s on CI), all fixed in S10.
- **Follow-ups:** in the roadmap backlog: serve the packed pyramid (S11); reuse stage 2 for a page reused by hash; calibrate OCR confidence and the blank threshold with the chosen engine (S31). The interim engine reads an A4 page in about 20 s, over 02 §9's 15 s target for the real engine (S31).
