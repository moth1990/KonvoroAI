# S08: Stage 1, intake and page classification

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s08-stage1-intake` |
| **Depends on** | S07 |
| **Status** | in review |
| **PR** | |

## Goal

Stage 1 is real. Each drawing gets these from code:
- pages rendered and normalized;
- rotation and quality;
- geometry and text source;
- reuse of earlier results by hash, within the tenant.

The `page_classification` agent gives each page a kind and a route, with confidence. The drawing gets its `input_kind`, panel count and title-block context. The user can confirm the pages, or change a page's kind, on the done step. The first model calls are recorded as cassettes, so `make eval` replays them.

## References

- Specs:
  - 01 (all), especially §5.1–5.8 (process), §6 (output contract), §7 (routing), §8 (errors) and §10 (metrics);
  - 00 §3 and §7.2 (an LLM decides only inside a stage, from a closed list, checked by code);
  - 12 §8 (licenses: pypdfium2, never PyMuPDF).
- Prototype: `prototype/konboro-app.html` lines 840–855 (the done step's page strip and page-kind select).
- Golden: all five drawings for stage 1 (`page_kind`, `route`, `input_kind`, panel count). BOM-HW-1 has no pages to classify.
- Earlier sessions:
  - S05 left the stage-1 stub, its thumbnail key and the read-only page-kind select. Its follow-ups are listed under Tasks.
  - S06 built the eval harness and the empty `eval/cassettes/`.
  - S07 added `stage_runs.sent_at` and the re-queue sweep.

## Tasks

### Backend
- [x] Replace `pipeline/stages/s1_intake.py`. Keep the `run(ctx) -> Contract` shape and the S05 thumbnail key.
- [x] Normalize (01 §5.1): render with pypdfium2, and read EXIF rotation for images. HEIC thumbnails, and a real DPI for image page sizes (S05 follow-ups).
- [x] Geometry and text source (01 §5.2), and quality and rotation (01 §5.3), in code.
- [x] Reuse by sha256 within the tenant only (01 §11).
- [x] The `page_classification` agent (01 §5.4): one route in `config.py`, a closed list of page kinds, and code that checks the answer. Only the reduced image and a text excerpt go to the model (01 §11).
- [x] Routing (01 §7). Add the missing `technical_data` and `factory_template` rows. This is the known inconsistency due in this session; the S06 normalizer's mapping is the starting proposal.
- [x] Context extraction (01 §5.5) through `context_extraction`: `technical_data`, front-view designators, panel `notes_block` (§5.5.1), `feed_diagram` (§5.5.2), `general_notes`. Legend crops are S12, `bom_table` is S14.
- [x] Factory templates (01 §5.7): a fingerprint with the title block masked, matched only within the tenant and the same designer or producer; a match is `classified_by=template` with no model call.
- [x] ~~Title block from a second image: a 1024 px crop of the title-block corner.~~ Changed while building: read once per drawing from a crop of the region the classifier found (see Decisions made).
- [x] Cassette keys: an `ImageInput` can carry a stable key (page sha256 + render settings), used instead of the pixels, so replay does not depend on how PDFium renders on each platform.
- [x] The confirmation step when it is needed (01 §5.6): the coordinator stops after stage 1 with `awaiting_confirmation` and sends stage 2 only on confirm. The endpoint to change a page's kind writes a `correction_events` row; if the route changes after stage 1 is done, stages 2–7 run again (not counted in the quota).
- [x] The revision check (01 §4.5): same drawing number, or ≥50% identical pages, plus the `revision_counted_as_new` notice (S05 follow-up).
- [x] A visibility heartbeat while a stage runs, so a long stage is never delivered twice (BUG-009).
- [x] The stage-1 summary on the run step stays correct with real data.

### Frontend
- [x] The done step's page-kind select becomes editable (S05 follow-up).
- [x] Confirmation: when stage 1 asks, the run step shows the done step's page grid with a line saying why, low-confidence pages marked, and "אשר והמשך".

### Unit tests
- [x] Routing table, quality and rotation rules, the agent-answer check, and the revision rule.

### Integration tests
- [x] Stage 1 on each golden PDF through the queue. `FakeProvider` or cassettes only; never a real model in tests.
- [x] Hash reuse never crosses tenants.
- [x] Changing a page kind is checked against the actor and the tenant.

### UI tests (Playwright)
- [x] Desktop and mobile: change a page kind on the done step, and confirm pages when asked.
- [x] Fidelity report for the done step and the confirmation step reviewed by the user (`make fidelity`, `new-done` and `new-confirm`). Accepted 2026-11-01; `make screenshots` rewrote the four `new-done` baselines and the two mobile `new-run` ones (the stage-1 summary now names the factory templates and wraps onto a second line at 375 px).

### Eval (pipeline sessions)
- [x] Record the first cassettes: `EVAL_MODE=live EVAL_RECORD=1 make eval`. Commit the cassettes and the new baseline (`make eval-baseline`).
- [x] Score the title block per field (01 §10); the stage-1 metric has no title-block score yet.
- [x] `make eval` in replay; numbers recorded under Outcome.

### Docs
- [x] 01 §7 routing table completed. Remove the item from CLAUDE.md's inconsistency list.
- [x] `docs/db-schema.md` for any new column.

## Acceptance criteria

From 01 §10, measured on the golden set. They are starting values, calibrated after this first run (01 §12 item 5):

- [x] Missed `process` pages: **0**. Measured 0 of 14.
- [ ] `page_kind` accuracy ≥ 97%. Measured 95.8% (23/24); accepted by the user (see Decisions).
- [ ] Panel count accuracy ≥ 95%. Measured 60% (3/5); accepted by the user (see Decisions).
- [x] Title-block field accuracy ≥ 90% per field. Measured 100% on all six fields.
- [x] The eval baseline is updated on purpose, and the cassettes replay deterministically. Two replays gave identical reports, equal to the recording run.

## Out of scope

- Text extraction and tiling: S10.
- Symbols: S12.
- The BOM-only path's table import: S14.
- DWG and DXF (01 §12 item 1, version 2.0).

## Open questions

All answered at session start (2026-11-01); see Decisions made.

1. ~~01 §7 lacks `technical_data` and `factory_template`. Do the S06 normalizer's routes apply (`context` and `skip`)?~~
2. ~~Which model does the `page_classification` route use, and what is the image size budget per page?~~
3. ~~A live run is needed once to record cassettes. Is the local `ANTHROPIC_API_KEY` the right key, and is there a cost ceiling for the run?~~
4. ~~When the revision check finds a match by page hashes only, with a different drawing number, which wins?~~

## Outcome

- **Done:**
  - Stage 1 is real (`pipeline/stages/s1_intake.py`, with its parts in `pipeline/intake/`):
    - pages rendered with pypdfium2, EXIF rotation, HEIC through `pi-heif`;
    - geometry and text source, sharpness and size checks;
    - reuse by content sha256 within the tenant;
    - the `page_classification` agent, its answer checked by code;
    - routing with the completed 01 §7 table;
    - the title block read once per drawing, with a whole-page fallback (BUG-014);
    - context extraction;
    - factory templates;
    - `input_kind`, panels merged by name, and the confirmation reasons.
  - Coordinator:
    - the `awaiting_confirmation` stop, with `POST /drawings/{id}/confirm`;
    - `PATCH /drawings/{id}/pages/{page_id}` to change a page's kind; it writes a `page_reclassified` correction and runs stages 2–7 again if the route changed;
    - the quota outcomes `reuse` and `revision` at stage 1;
    - the visibility heartbeat (BUG-009).
  - Migration 0005: `page_templates`, `drawings.title_block`, and correction source `new_quote`.
  - `konboro_llm`:
    - `page_classification` and `context_extraction` stages;
    - stable image keys for cassettes;
    - the Anthropic provider asks for JSON output instead of forcing a tool, because Sonnet 5.5 and Opus 5.5 reject a forced tool (BUG-013).
  - The stand-in model (`devtools/fake_llm.py`) for E2E, the integration fixtures, and `make dev` without a key.
  - Frontend:
    - the confirmation step (`ConfirmStep`), and the editable page-kind select on the done step;
    - notices, and the "reused" counted-as text.
  - Eval:
    - title-block accuracy per field, and `confirmation_rate`;
    - the first cassettes (39) and a new baseline from a live run.
  - Docs:
    - spec 01 (§4.5, §5.4, §5.6, §5.7, §6, §7);
    - CLAUDE.md;
    - `docs/db-schema.md`;
    - bugs BUG-009 and BUG-011 to BUG-014;
    - the roadmap, where S01–S07 are done and `phase-0` is tagged.
- **Decisions made:**
  - Confirmation screen (2026-11-01, user; 01 §5.6 vs the prototype, which has none): reuse the done step's page grid. After stage 1 the pipeline stops with `awaiting_confirmation`. The run step shows the grid with a line saying why, the low-confidence pages marked, and "אשר והמשך", which sends stage 2.
  - Revision rule (2026-11-01, user): as 01 §4.5 is written, either condition is enough: the same drawing number, or ≥50% identical pages by sha256. If neither holds, the drawing counts as new, with `revision_counted_as_new`. A match the user did not mark only links `revision_of` and reuses results; the quota is unchanged.
  - Live recording (2026-11-01, user): the local `ANTHROPIC_API_KEY`, with a $5 ceiling. Stop and ask before passing it.
  - Page-kind change after stage 1 (2026-11-01, user): a `correction_events` row and the new kind. If the route changes, stages 2–7 run again for the drawing, not counted in the quota.
  - Defaults stated at session start (2026-11-01, Claude; the user did not object):
    - 01 §7 gets the rows from §5.4: `technical_data` → `context`, `factory_template` → `skip`. Like `title_cover`, a `factory_template` below 0.85 goes to `process`.
    - Models stay as `config.py` has them: `page_classification` on `claude-haiku-5-5`, `context_extraction` on `claude-sonnet-5-5`.
    - Each page sends two images: the 1024 px overview and a 1024 px crop of the title-block corner. Every golden PDF has its text drawn as lines, so the text excerpt is empty, and a 1024 px overview of a 1.4 m page cannot be read.
    - Cassettes key an image by the page sha256 plus the render settings, not by pixels.
    - Context extraction covers `technical_data`, front-view designators, `notes_block`, `feed_diagram` and `general_notes`. Legend crops are S12, `bom_table` is S14. Factory templates (01 §5.7) are in.
    - Rotation comes from the PDF's `/Rotate` and the image's EXIF tag. Where there is no text layer, the classifier returns an orientation from {0, 90, 180, 270}, and code re-renders the page.
  - Made while building (2026-11-01, Claude; for the user's review at close):
    - **Title block, read once per drawing.** The default above (a 1024 px crop of the bottom-right corner) failed on 6199-2-50: its title block is a narrow column on the left. Stage 1 now crops the `title_block` region the classifier found, at 1568 px, and reads it with one `context_extraction` call. That is one extra call per drawing, not per page. 01 §5.4 says so.
    - **Contract additions** (01 §6, snapshot rewritten): `TitleBlock.panel_name` (factory title blocks name the panel, e.g. NEVIS-1 "KARWANI") and `IntakeResult.title_block` (the drawing's). The classifier also answers `orientation` and `component_labels`, the stand-in for "tags and models" in 01 §4.4 until stage 3 exists (S12).
    - **Panels.** Merged by name across process pages (01 §12 item 2). An unnamed panel takes the title block's `panel_name`, or else the drawing's only named panel, or else "לוח 1". Everything the classifier found is kept in `pages.regions`, panels included, so a page-kind change rebuilds the panels.
    - **Page hash** is of the content, not pixels: each path's points, the text and the images' raw data, rounded to 0.01 pt. Cassettes key on it, so they replay on any platform.
    - **Templates.** A 64 × 64 ink map, compared outside the title block; a match needs ≥ 0.70. A match is tentative until the title block names the producer; another producer's page goes to the model. NURSERY-1 page 2 is a re-layout of NEVIS-1 page 2, so only page 3 matches (BUG-011). Only `factory_template` pages become templates: the factory's technical-data form scores 0.999 against itself filled in.
    - **Quota outcomes at stage 1.** The same files again (every file's sha256 already decoded in the tenant): `reuse`, released. A blurry page: the drawing fails at once, released, no model call. A marked new version that is not one: reserved and confirmed at stage 1; with the month used up, the drawing fails with `quota_reached`, uncounted.
    - **The stand-in model** (`konboro/devtools/fake_llm.py`): fixed answers that classify like NURSERY-1's labels; a file name with "unsure" makes page 1 low-confidence. Used by the E2E worker and the integration fixtures, and by `make dev` when there is no API key (with a warning). Never in the eval.
    - **HEIC** through `pi-heif` (BSD-3 and LGPL libheif, decode only, no x265). The license gate passes.
    - **Concurrency and heartbeat.** Four pages are classified at a time. The heartbeat extends a running stage's message every 10 s by 60 s (`stage_heartbeat_seconds`, `stage_visibility_seconds`).
  - Baseline below the 01 §10 targets (2026-11-01, user): accept the first live run as the S08 baseline, with `page_kind`, panel count and the confirmation rate below target and recorded as follow-ups, rather than tune the prompt on five drawings.
    - **Eval.** Title-block accuracy is scored per field the label states (drawing number, date, project, panel, revision, status), with spacing and separators ignored. `confirmation_rate` (lower is better; 01 §10 target ≤ 15%) is scored too. In the eval, a drawing waiting for confirmation is confirmed as classified.
- **Eval / metrics:** first live recording (2026-11-01): 39 calls, `page_classification` 25 on `claude-haiku-5-5` (109k in, 28k out) and `context_extraction` 14 on `claude-sonnet-5-5` (41k in, 5.6k out), about $0.16. Three live runs in all, about $0.33 of the $5 ceiling. The cassettes and `eval/baseline.json` are from the second run (the first stopped on BUG-013); replay reproduces it exactly, twice.

  | 01 §10 metric | Target | Measured |
  | --- | --- | --- |
  | Missed `process` pages | 0 | **0** (0/14) |
  | `page_kind` accuracy | ≥ 97% | **95.8%** (23/24) |
  | Route accuracy | — | 100% (24/24) |
  | Input kind | — | 100% (5/5) |
  | Panel count accuracy | ≥ 95% | **60%** (3/5) |
  | Title block, per field | ≥ 90% | 100% for drawing number (4/4), date (4/4), project (3/3), panel (3/3), revision (1/1), status (1/1) |
  | Drawings that needed the confirmation screen | ≤ 15% | **25%** (1/4) |

  Before S08, from the stub: page kind 0%, route 58%, input kind 20%, panel count 80% (the stub always said one panel).

  The misses:
  - NEVIS-1 page 7: `single_line_diagram`, labelled `control_diagram`. Both are `process`, so nothing is lost.
  - 26-993: QEN1 and QEN2 on page 3 are the boards that feed MAIN ELECTRICAL BOARD; the classifier counts them as panels (3 instead of 1). A prompt rule against it made no difference in one live run, and was taken out.
  - BOM-HW-1: no panel. Stage 1 counts panels only from `process` pages (01 §5.5); the BOM form's heading names the panel, and that is the BOM route's to read (01 §5.8, S14). The stub's one panel was hard-coded.
  - 26-993 waits for confirmation: page 5 at 0.80, below 0.85.

  Live answers vary between runs. The run after the recorded one lost 6199-2-50's whole title block (BUG-014, fixed) and scored 75% or less on four title-block fields; panel count stayed at 60%.
- **Bugs logged:** BUG-009 (closed), BUG-011, BUG-012, BUG-013 (P0, found in the live recording) and BUG-014 (P1, found comparing two live runs), all fixed in S08.
- **Follow-ups:** panel count on 26-993 (feed sources counted as panels) and the confirmation rate, in the roadmap backlog. BOM-HW-1's panel comes with S14.
