# S12: Stage 3 v1, symbols

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s12-stage3-symbols` |
| **Depends on** | S10 |
| **Status** | in review |
| **PR** | (link) |

## Goal

Stage 3 is real. Every non-blank tile of every `process` page is searched for symbols by an LLM-vision pass that picks from the closed family and class lists, with the library's examples and the abbreviation dictionary in hand, and code checks every box against the tile's ink. Detections are moved to page points, de-duplicated across overlapping tiles, each given one owner tile, linked to its designator, and electrical text with no symbol near it is searched again or handed on as `orphan_text`. Stage 4 (S13) gets each symbol exactly once.

## References

- Specs:
  - 03 §3.4 (the disambiguation agent: candidates, closed choice, `none_of_these`, `not_a_symbol`), §3.5 (page coordinates, cross-tile de-duplication, owner tile), §3.6 (orphan text and re-detection), §3.7 (designator linking, reserved words, ranges, "no tag"), §6 (output contract, confidence formula, status bands), §10 (metrics). Also read: §4.3–4.6 (library, families, roles, labelled boxes and the abbreviation dictionary), §7 decision rules, §8 issues, §13 privacy.
  - 00 §6.1–6.3 (`det_` ids, PDF points, confidence colours), §7.1–7.2 (routes, LLM rules), §10 (measurement), §12 (de-duplication moved to stage 3), §14 (phase 1: stage 3 with LLM vision, examples and the abbreviation dictionary; the dedicated detector in phase 3/4).
  - 02 §2.6 (tiles, padding, overlap) and §6 (the stage-2 contract stage 3 reads).
- Prototype: none for the stage itself. The run step already shows a stage's summary line (prototype line 762's style).
- Golden: NEVIS-1, NURSERY-1, 26-993 (designators on the drawing), 6199-2-50 (no designators, labelled boxes "מ.פ.", "C1", "TC", "SATEC 135E"). No golden file has symbol boxes.
- Earlier sessions:
  - S02: empty global tables `symbol_classes`, `reference_crops`, `abbreviations`; tenant tables `tenant_abbreviations`, `tenant_reference_crops`.
  - S08: stage 1's `context_artifacts` (legend) and `title_block.designer`; the stand-in model; image-keyed cassettes.
  - S10: tiles with padding and `span_ids`, spans with `tags`, ids by place (`ts_{nnn}_{mmmm}`, `tl_{nnn}_r{row}c{col}`), the interim `ClaudeVisionOcr` and its code checks on boxes, `EVAL_RECORD=missing`, `EVAL_MAX_USD`.
  - Known inconsistency due now: 02 §2.6 says the merge after stage 4 removes tile duplicates; 03 §3.5 and 00 §12 moved it into stage 3.

## Tasks

### Backend
- [x] Replace `pipeline/stages/s3_symbols.py` (`run(ctx) -> DetectionResult`), its parts in `pipeline/detection/`. Pages one after another, tiles in parallel (8 calls at a time, like stage 2).
- [x] Library as data: the families of 03 §4.4–4.5 (with `labeled_box`), their symbol classes and `billable`, and the global abbreviation dictionary (03 §4.6), seeded into `symbol_classes` / `abbreviations` by a migration or the seed; tenant and designer abbreviations read under `tenant_session`. A library version string.
- [x] Reference examples for the prompt: 36 drawn symbols (`devtools/draw_symbols.py`), one sheet per library version. The drawing's legend goes to the disambiguation call as text; crops wait for legend entry boxes (backlog).
- [x] Tile detection through `ctx.llm` on a new route (question 1): the tile, the families and classes as a closed list, the examples, the tile's spans numbered. Answer: boxes in tile pixels, family, class, role, confidence, an optional designator span id from the list.
- [x] Code checks on every answer (00 §7.2): family and class from the lists, box inside the tile, centre not in padding (`padding_reject`), over ink, shrunk to its ink; a span id that is in the tile. Failures dropped and counted.
- [x] Labelled boxes (03 §4.6): the text inside the box classified by the abbreviation dictionary in code (global < tenant < designer); a model token goes to the catalog later (S20); an unknown text to the disambiguation call.
- [x] Disambiguation (03 §3.4) on `symbol_disambiguation` for the uncertain ones only: crop with 50% margin, 3–5 candidates, the legend entries; `choose` / `none_of_these` / `not_a_symbol`, the class checked against the candidates. `llm_budget_exceeded` past 25%.
- [x] Page placement and de-duplication (03 §3.5): `page_pt = (tile.bbox_px[0:2] + det_px) / px_per_pt`; same family and IoU > 0.5 merge, the most confident kept, the rest in `seen_in_tile_ids`; owner tile = the tile holding the box whole, farthest from its edges. `duplicates_removed`.
- [x] Orphan text (03 §3.6): every span with `tags` and no detection within `orphan_radius_pt` (40) gets one re-detection on an enlarged crop at the lower threshold; found → `orphan_recovery`, else `orphan_texts[]`.
- [x] Designator linking (03 §3.7), in code: tag-shaped spans within two symbol heights, reserved words (`L1`–`L3`, `N`, `PE`, bus names) only when next to a matching symbol, "no tag" on tagged drawings. The model's tag is a hint checked against the spans. Ranges on front views and the dashed aux-contact link: backlog.
- [x] Confidence and status (03 §6.3), `panel_id` from stage 1's panel boxes, `crop_uri` (crops in S3 under the page's prefix), `det_` ids by place so reruns keep cassettes replaying.
- [x] Issues (03 §8): `no_symbols_found`, `high_unknown_ratio`, `llm_budget_exceeded`, `many_orphan_texts`; a model error fails the stage (retried), as in S10.
- [x] Stats (03 §6.1) and the run step's stage-3 summary line.
- [x] Settings: thresholds, radius, budget, concurrency.

### Frontend
- [x] Nothing new: the run step shows the stage-3 summary from the existing per-stage line. Re-check the accepted `new-run` / `new-done` shots.

### Unit tests
- [x] Tile → page conversion; IoU; de-duplication across 2–4 overlapping tiles; owner tile choice (whole, farthest from edges); property test: a box seen in several tiles comes out once.
- [x] Answer checks: unknown family or class, box outside the tile, centre in padding, box over no ink, a span id not in the tile.
- [x] Abbreviation lookup with the three scopes, `מ.פ.` / `TC` / `C1` / `K1`, and an unknown text routed to disambiguation.
- [x] Disambiguation: the three decisions, a class not among the candidates refused, the 25% budget.
- [x] Orphan text: radius, one recovery attempt, `orphan_texts`.
- [x] Designator linking: nearest tag, reserved words on NEVIS-1's `L1`–`L3` lamps, ranges, "no tag".
- [x] Confidence formula and status bands; issue thresholds.
- [x] Contract snapshot updated if the contract changes.

### Integration tests
- [x] Stage 3 through the queue on a golden drawing with the stand-in model (or cassettes): crops land under the tenant's S3 prefix, another tenant's key refused; `llm_calls` rows per call.
- [x] Tenant and designer abbreviations apply only to their tenant (RLS).
- [x] The progress endpoint returns the stage-3 summary.

### UI tests (Playwright)
- [x] Desktop and mobile: the run step shows the stage-3 summary once stage 3 is done (stand-in model).
- [x] `new-run` / `new-done` screenshots re-checked (`make check-screenshots`).

### Eval (pipeline sessions)
- [x] The stage-3 metrics the labels can support (question 3), per family and in total, plus duplicates left, LLM share and cost per drawing.
- [x] Record cassettes live within the agreed ceiling; `make eval` in replay twice, identical; numbers under Outcome; `make eval-baseline`.

### Docs
- [x] 02 §2.6: de-duplication is stage 3's (03 §3.5, 00 §12); remove the item from CLAUDE.md's known inconsistencies.
- [x] 03 (and 00 §7.1, 12 if a route or the privacy rule changes) with this session's decisions.
- [x] `docs/db-schema.md` for seeded library data or any new column; CLAUDE.md "Stages" line (stage 3 is real); `eval/README.md`.

## Acceptance criteria

From 03 §10, as far as the golden set can measure them now:

- [x] Billable recall, per family and in total, on the metric agreed in question 3, recorded in `eval/baseline.json`. Target 98% (03 §10); a family under target is named in the Outcome with its cause. **Designator recall 96.7% (116/120), family accuracy 98.3%, 6199-2-50 family count recall 90.4%: under target; see Outcome.**
- [x] Duplicates left after 3.5: 0 (same family, IoU > 0.5, on one page). **0 on every drawing.**
- [x] Share of detections that reach the disambiguation call: recorded (target ≤ 10%, 03 §10). **19.7%, over target (backlog).**
- [x] Two replays give identical reports, equal to the live run.
- [x] Every `process` page in the golden set has a stage-3 result; no stage failure.

## Out of scope

- The dedicated family detector, the embedding model and the kNN index (03 §3.2–3.3): phase 4. `cad_block` and `pre_detections` (03 §3.1): 2.0.
- Reading current, poles and other attributes from text, multiplicity marks, merging by designator: S13 (04).
- The learning loop (03 §11): corrections into the library come with the review actions (S23) and draw mode (backlog).
- Graphic pole reading (03 §14 item 3): stage 4.

## Open questions

All answered at session start (2026-11-01); see Decisions made.

1. ~~**Detector in v1.** 03 §3.2 and §13 say the detector is ours, on our GPU, and page images never go to an outside provider in 3.2–3.3. The roadmap and 00 §14 say phase 1 detects with LLM vision. Which route, and what do the specs say meanwhile?~~
2. ~~**Library examples.** The golden set is frozen and not for training (00 §10.1), and there are no other drawings in the repo. Where do the reference examples come from?~~
3. ~~**Stage-3 metric.** No label has symbol boxes. What does the eval measure?~~
4. ~~**Known inconsistency:** 02 §2.6 vs 03 §3.5 on where tile duplicates are removed.~~
5. ~~**Live recording.** A ceiling and the key.~~

## Outcome

- **Done:**
  - Stage 3 is real (`pipeline/stages/s3_symbols.py`, its parts in `pipeline/detection/`):
    - the library as data (`library.py`): 31 families, 35 classes, roles, the global abbreviation dictionary, confusable families; seeded by `seed_global`, read back with the tenant's and the designer's abbreviations on top, in a fixed order;
    - 36 reference drawings (`reference/`, `devtools/draw_symbols.py`) and the reference sheet (`sheets.py`);
    - tile search on the new `symbol_detection` route with code checks on every answer (`search.py`), boxes with text through the dictionary;
    - de-duplication across tiles and the owner tile (`candidates.py`);
    - text with no symbol near it: grouped re-searches, `orphan_texts` (`orphans.py`);
    - the disambiguation call on `symbol_disambiguation`, closed candidates, budget, billable only (`disambiguate.py`);
    - designators from spans, reserved words, `no_tag` (`designators.py`);
    - confidence and status (03 §6.3), panels, crops in S3, 03 §8 issues, stats; migration 0008 and the run step's stage-3 line.
  - Contract: `llm_vision` and `Detection.flags` (snapshot rewritten). The stand-in model answers both new routes.
  - Eval: `eval/metrics/stage3.py` (designator recall, family accuracy, family count recall, recall by family, duplicates left, LLM share), stage-3 counts in the report; 267 `symbol_detection` and 97 `symbol_disambiguation` cassettes; new baseline.
  - Tests: `tests/unit/test_detection.py` (54), stage-3 eval metric tests, `tests/integration/test_stage3.py` (3), the run step's stage-3 line in `new-quote.spec.ts` (desktop and mobile).
  - Docs: specs 02 §2.6, 03 (§3.2א, §3.4, §3.5, §3.6, §3.7, §4.6, §6.2–6.3, §13), 00 §7.1, 12; `docs/db-schema.md`; CLAUDE.md (stages line, the inconsistency removed); `eval/README.md`; roadmap backlog.
- **Decisions made:**
  - Detector in v1 (2026-11-01, user; 03 §3.2, §13 vs roadmap and 00 §14): LLM vision per non-blank 1024 px tile on a new route `symbol_detection` in `konboro_llm/config.py`, choosing from the closed family and class lists; code checks every box against the tile's ink. 03 §3.2, §13 and 00 §7.1 say it is interim until the phase-4 detector, as S10 did for OCR.
  - Library examples (2026-11-01, user): one or two IEC 60617-style symbols per class drawn by us, stored as global `curated` reference crops with a short description of each family. Nothing is cut from the golden set (00 §10.1). As built: drawn with PIL by `konboro/devtools/draw_symbols.py` (no SVG renderer dependency), 36 PNGs committed; the drawing's legend reaches the disambiguation call as text, since stage 1's legend artifact has no per-entry boxes to crop (backlog).
  - Stage-3 metric (2026-11-01, user): on NEVIS-1, NURSERY-1 and 26-993, per-family billable recall = labelled designators found as a detection of the same family linked to that tag; on 6199-2-50, per-family detection counts against the labelled rows. Plus duplicates left (measured in code), the share reaching the disambiguation call, and cost. Precision waits for symbol-box labels (backlog).
  - Live recording (2026-11-01, user): the local `ANTHROPIC_API_KEY`, $10 ceiling (`EVAL_MAX_USD=10`). Stop and ask before passing it.
  - Made while building (2026-11-01, Claude; for the user's review at close):
    - **Contract** (03 §6.2, snapshot rewritten): `method` gains `llm_vision` (found and classed by the interim model alone); `Detection.flags` (`no_tag`). Confidence for `llm_vision` is the model's one rating (sure 0.9, unsure 0.7), standing for both `detector_score` and `class_score`; 0.7 rather than 0.6 so that an unsure symbol a disambiguation confirms at 0.8–0.9 lands yellow, not red.
    - **No `labeled_box` family in the search.** The model reports a box with text as the family its text means and copies the text; the dictionary in code wins. A box whose text is a tag (R1, NVR) gives the tag too.
    - **Junction dots are not searched**: not a quote line, no help to stage 4, many output tokens.
    - **De-duplication beyond 03 §3.5:** one family and 70% of the smaller box covered; IoU above 0.5 whatever the families (6199-2-50's main breaker came back as two families in two tiles), the loser's class kept as a candidate; the same tag end to end on one wire whatever the families, with the union box (NEVIS-1's breaker crosses drawn above the blade).
    - **Designators only from spans** (00 §5.3); the model's tag is a hint that wins at twice the radius. Letters-only tags only when the model read them or they are inside the box. An auxiliary contact takes only the model's tag. Front-view ranges and the dashed aux link: backlog.
    - **Disambiguation:** only billable symbols; candidates from a `CONFUSABLE` table (widened after the first recording: overload relay ↔ breaker, terminal ↔ current transformer, contactor ↔ time switch); the first look's role is in the prompt, since a relay's contact doesn't look like its coil.
    - **Orphan search:** device tags only (not cables, voltage, power); orphans grouped within the radius, one crop each, at most 12 searches a page; a hint replaces 03 §3.6's lower threshold.
    - **Library from the database, ordered by the module**: the global rows come from `library.py` through `seed_global`; `build()` sorts them, so the prompt and its cassette keys don't depend on row order.
    - **Reference drawings with the default PIL font**: no Hebrew or Greek glyphs, so no "מ.פ." image (the dictionary covers it in text) and "30mA" instead of ΔI.
    - **Migration 0008:** `pages.symbol_count`, `symbol_llm_count` for the run step's line, which reads "N סימנים · X בזיהוי ישיר, Y בהכרעת מודל" (the prototype's "מהספרייה" is the phase-4 index).
    - **Stage-1 privacy test:** besides page images, the model may get images keyed `lib-…`: our own reference sheets.
  - De-duplication (2026-11-01, user; known inconsistency): stage 3 removes tile duplicates and picks the owner tile (03 §3.5, 00 §12). 02 §2.6 is fixed and the item leaves CLAUDE.md's list.
- **Eval / metrics:**
  - Live recording (2026-11-01) on `claude-sonnet-5-5` at effort `low`: 267 detection calls and 97 disambiguation calls in the committed cassettes, **$3.94** at list prices (1.65M tokens in, 62k out). With the prompt probes and one re-recording of the disambiguation calls, about **$5.10** for the session, against the $10 ceiling. S08's and S10's cassettes were not touched (`EVAL_RECORD=missing`); 13 stale probe cassettes were deleted.
  - Two replays gave identical reports, equal to the live run; `eval/baseline.json` rewritten with `make eval-baseline`, every earlier metric unchanged (137 new metrics, 0 regressions).

  | Drawing | Detections (accepted / uncertain / unknown) | Designator recall | Family accuracy | Family count recall | Duplicates left | LLM share |
  | --- | --- | --- | --- | --- | --- | --- |
  | NEVIS-1 | 108 (84 / 17 / 7) | 100% (42/42) | 100% | n/a | 0 | 16.7% |
  | NURSERY-1 | 115 (96 / 16 / 3) | 100% (41/41) | 100% | n/a | 0 | 15.7% |
  | 26-993 | 62 (44 / 16 / 2) | 89.2% (33/37) | 93.9% | n/a | 0 | 14.5% |
  | 6199-2-50 | 207 (146 / 42 / 19) | n/a | n/a | 90.4% (94/104) | 0 | 25.1% |
  | **Total** | 492 | **96.7% (116/120)** | **98.3%** | 90.4% | **0** | **19.7%** |

  - **Under target (03 §10: 98% recall per family, 10% LLM share), with causes:**
    - 26-993: MS1–MS3, the current-transformer block, are detected once without a tag (2 of 5 current transformers over the set); RF is not written on the plan (its label says so), as in S10.
    - 6199-2-50: time switches 0/5 and impulse relays 0/3: the first look calls the designer's clock and step boxes contactor coils or unknown; fuses 4/6, changeover switches 1/2 over the set.
    - LLM share 19.7%: the interim model rates many symbols unsure.
  - Orphan texts: 5 on 6199-2-50, none elsewhere; no orphan search found a new symbol on the golden set.
- **Bugs logged:** BUG-024 (P1, the screenshot image lost corepack when the amd64 tag was re-published with Node 26), fixed in S12. BUG-025 (P2, open: a local-services test reads the dev queue, which a running `make dev` worker empties first), for the gate. BUG-018 (open, S17) failed once in an integration run and passed on three reruns.
- **Follow-ups:** in the roadmap backlog: symbol-box labels for the golden set; time switches and impulse relays (redraw two references, re-record about $3.60); disambiguation share above target; an auxiliary contact's device and front-view ranges (S21); legend crops; neutral poles and output terminals as symbols (S13, S20).
