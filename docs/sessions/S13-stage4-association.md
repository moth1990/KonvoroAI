# S13: Stage 4, association and merge

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s13-stage4-association` |
| **Depends on** | S12 |
| **Status** | in review |
| **PR** | (link) |

## Goal

Stage 4 is real. Every billable detection from stage 3 gets the text that belongs to it, read into the attributes its family needs, each value pointing at the span it was read from and checked in code. Multiplicity marks, circuit numbers and supply scope are read. A tile agent decides only the tiles code could not resolve, and its answers are checked against the spans. Instances merge by designator across pages and representations, then by signature, into the `components[]` that stage 5 (S20) reads.

## References

- Specs:
  - 04, all of it: §4 (input, billable only, the rest as `context_elements`), §5.1 (the spelling grammar as data, `INC=` as load current, ambiguous readings), §5.1.1 (multiplicity by position, chains, circuit-number ranges), §5.1.2 (supply scope, dashed frames, the English phrases), §5.2 (geometric association, page-wide search, the resolved test), §5.3 (when a tile needs the agent), §5.4 (the tile agent: numbered boxes, input, output schema, evidence kinds), §5.5 (citation check, retries, fallback model, `fallback_geometric`), §5.6–5.7 (instances, missed symbols), §5.8 (merge by designator, then by signature; what never merges), §6 (contract), §6.4 (confidence), §7–8 (decision rules, issues), §10 (metrics), §12 (privacy), §13 (open points).
  - 05 §4.1, §4.4 (the contract stage 5 reads; attribute schemas, required attributes, `default_allowed`), §5.5.1 (what stage 5 needs in `circuit_context`).
  - 03 §3.7, §4.5–4.6 (designators, representations and roles, the abbreviation dictionary), §6 (the detection contract stage 4 reads).
  - 02 §2.4–2.5, §6 (span tags, the wire graph, the stage-2 contract).
  - 00 §5.3 (evidence), §6 (`ins_` / `cmp_` ids, PDF points, colours), §7.1–7.2 (routes, LLM rules), §10.1 (measurement per stage).
  - 06 (`DATA_LOAD_CURRENT_GT_RATED`, `QTY_RANGE_MISMATCH`: stage 4 leaves what stage 6 needs; the rules themselves are S21).
- Prototype: none for the stage itself. The run step already shows a stage's summary line.
- Golden: all four drawings. NEVIS-1 (OCR text, `INC=`, 1P+N breakers with the neutral drawn on its own line, FP1 on two pages, C1 as power contact and coil), NURSERY-1 (`SAVE` spare circuits), 26-993 (`INC=` ≈ 0.8 × rated, FC1's exception, "Preparation for a Remote Emergency Push Button"), 6199-2-50 (13 multiplicity marks, chains, dashed frame "תוספת מפסק חדש בפילר חשמל קיים", generator "הכנה בלבד", graphic poles, `500A/630A`, `800/5A`, `PKZM 1-2.4A`). The eval's stage-4 metrics exist since S06 and are 0 today.
- Earlier sessions:
  - S02: `components` table, `attribute_schemas`, `symbol_classes.attribute_schema`.
  - S06: `eval/metrics/stage4.py` (component precision and recall per panel, `current_a` and poles accuracy, quantity accuracy, unit recall), `eval/predict.py` reads `MergeResult.components`.
  - S10: spans with `tags` (`pipeline/extraction/normalize.py`), the wire graph on vector pages (`wires.json.gz`).
  - S12: detections with `owner_tile_id`, `designator`, `role`, `flags`; `orphan_texts`; the library (`detection/library.py`); backlog item "neutral poles and terminals as symbols" asks S13 to decide on the N-line contact.

## Tasks

### Backend
- [x] Replace `pipeline/stages/s4_association.py` (`run(ctx) -> MergeResult`), its parts in `pipeline/association/`. Tiles in parallel (8 calls at a time, as in stages 2–3); the merge once per drawing.
- [x] Attribute schemas as data (05 §4.4) for every billable family in the library: required or not, `match_mode`, `default_allowed` (never for `current_a`, poles). Seeded into `attribute_schemas` by `seed_global`, as S12 did the library.
- [x] Spelling grammar as a data file (04 §5.1, every row of the table), versioned, loaded and checked at start: each pattern gives values with a parse confidence, every reading kept, the family picks. `INC=`/`Ib=` → `load_current_a`, never `current_a`; an unknown prefix kept as text. Model tokens to `explicit_texts`. Cables to `circuit_context.cable`, circuit numbers and ranges to `circuit_numbers`.
- [x] Multiplicity (04 §5.1.1): on the device's text, on a line or cable, at the top of a chain; chain inheritance through the wire graph with × 0.8 and `multiplicity_inherited`; the range cross-check, leaving what stage 6 needs for `QTY_RANGE_MISMATCH`.
- [x] Supply scope (04 §5.1.2): the phrase dictionary as data (Hebrew and English), every non-`in_panel` component kept with its reason. **Dashed frames not done**: stage 2's paths keep no line style (roadmap backlog, "Dashed frames for supply scope").
- [x] Geometric association (04 §5.2): candidates within 3 × symbol height on the whole page, the score (distance, alignment, direction, family fit, competition), one global assignment per tile, the "resolved" test.
- [x] The tile decision (04 §5.3) and the tile agent (04 §5.4) on the `text_association` route: the tile image with numbered boxes drawn per call and not stored, owned and context symbols, spans in tile pixels, the proposed assignment, the attributes to read, the legend entries. The output schema of 04 §5.4.
- [x] The answer check (04 §5.5): schema and one answer per owned symbol (retry with the error), span ids that exist and are within the radius, the citation check through the grammar (`citation_mismatch`), graphic evidence only for poles, text beats graphic (`attribute_conflict`), a span on several symbols only through `shared_labels`. Two failures → the fallback model; then `fallback_geometric`, `uncertain`.
- [x] Instances (04 §5.6), missed symbols (04 §5.7: `possible_missed` and unassigned `orphan_texts` → `missing`, confidence ≤ 0.4), `context_elements` for non-billable detections.
- [x] Merge (04 §5.8): by designator within a panel across pages and roles (attributes joined, conflicts flagged), auxiliary contacts as accessories with `parent_designators`, `circuit_context` from the wire graph (upstream device, `load_current_a`), then by signature; quantity = distinct designators, or the sum of multiplicities; what never merges.
- [x] Confidence and status (04 §6.4), issues (04 §8), stats (04 §6.1), `ins_` / `cmp_` ids by place so reruns keep cassettes replaying.
- [x] Components written to the `components` table (replaced on a rerun) and the stage-5 stub passes them through instead of raising (question 4).
- [x] The run step's stage-4 summary line (components and instances, how many went to the agent).
- [x] Settings: radius factor, the resolved thresholds, concurrency, retries.

### Frontend
- [x] Only the run step's stage-4 summary line, through the existing per-stage line. Re-check the accepted `new-run` / `new-done` shots.

### Unit tests
- [x] Grammar: every row of 04 §5.1, ambiguous readings ("6000" by family), `INC=12.8A` never `current_a`, unknown prefixes kept as text, `16+N`, `500A/630A`, `5/800A`, `4x63A/0,03A`, cables, `SAVE`/"שמור".
- [x] Multiplicity by position, chain inheritance and its × 0.8, range equal, missing, different.
- [x] Supply scope: phrases in Hebrew and English, `prepare_only` keeping the in-panel switch `in_panel` (the dashed frame waits, with the backend task).
- [x] Geometric score and assignment: the nearer symbol wins, competition, the page-wide search across a tile edge, the resolved test.
- [x] Answer check: each row of 04 §5.5, including 04 §5.5's own example (`current_a=16` cited from "C20" is refused).
- [x] Merge: NEVIS-1's examples (FP1 on two pages → 1; C1 contact + coil → 1; F1, F2, F12 → quantity 3), conflicting attributes, never-merge cases, panels apart, `brand_conflict`.
- [x] Confidence formula and status; issue thresholds.
- [x] Contract snapshot updated if the contract changes.

### Integration tests
- [x] Stage 4 through the queue on a golden drawing with the stand-in model (or cassettes): `llm_calls` rows per agent call, `components` rows under the tenant (RLS), a rerun replaces them.
- [x] The tile agent's prompt holds no prices, customer details or title block (04 §12, non-negotiable 6).
- [x] The progress endpoint returns the stage-4 summary; the drawing still reaches stage 7 and opens for review.

### UI tests (Playwright)
- [x] Desktop and mobile: the run step shows the stage-4 summary once stage 4 is done (stand-in model).
- [x] `new-run` / `new-done` screenshots re-checked (`make check-screenshots`): all four `new-done` and both `new-run` pass in `make check`, no pixel difference; the one failure there (`review-red`, dark desktop, a 5 s screenshot timeout waiting for fonts) passed on its own rerun. Earlier local runs timed out under load (BUG-028).

### Eval (pipeline sessions)
- [x] The stage-4 metrics on stage 3's output (question 1), per drawing and panel: component precision and recall, `current_a` and poles accuracy, quantity accuracy, unit recall; plus values without evidence (must be 0), the share of tiles needing the agent, the `citation_mismatch` rate, cost per drawing.
- [x] Record cassettes live within the agreed ceiling; `make eval` in replay twice, identical; numbers under Outcome; `make eval-baseline`.

### Docs
- [x] 04 with this session's decisions (and 00 §7.1, 12 if a route changes).
- [x] `docs/db-schema.md` for the seeded schemas, the `supply_scope` values and any new column; CLAUDE.md "Stages" line (stage 4 is real); `eval/README.md`.

## Acceptance criteria

From 04 §10, as far as the golden set can measure them now (on stage 3's output, question 1):

- [x] Values without evidence in the output: **0**, enforced by the check and asserted by the eval. **0 on every drawing.**
- [ ] `current_a` accuracy on matched components: vector ≥ 99.5%, OCR ≥ 97% (NEVIS-1 is OCR); a miss is named with its cause. **100% (26/26)** on the factory drawings; 6199-2-50 has no designator pairs to measure it on.
- [ ] Poles accuracy ≥ 97%; multiplicity and quantity per component per panel ≥ 97–98% on 6199-2-50; a miss named with its cause, separating stage-3 misses from stage-4 ones. **Poles 92.9% (26/28), quantity 67.5% (56/83): under target; see Outcome.**
- [ ] `citation_mismatch` rate in agent answers ≤ 2%. **4.4% (8/181): over target; see Outcome.**
- [x] Two replays give identical reports, equal to the live run; no stage failure on the golden set.

## Out of scope

- General notes ("all breakers 10kA") and factory defaults: stage 5 (S20).
- Stage 6 rules (`DATA_LOAD_CURRENT_GT_RATED`, `QTY_RANGE_MISMATCH`): S21. Stage 4 only leaves the data.
- Retrieval of corrected examples for the agent (04 §11): nothing is corrected yet; with the review actions (S23).
- Quote lines from components: stage 7 (S22).
- `cad_attrib` spans and CAD blocks: 2.0.

## Open questions

1. **How to measure stage 4.** 04 §10 and 00 §10.1 say feed stage 4 hand-labelled detections; there are no symbol-box labels (backlog). Score end to end on stage 3's output for now, and split each miss into a stage-3 or a stage-4 cause?
2. **Tile agent route and live recording.** 04 §5.4: a mid-size model with a stronger fallback on `text_association`. Sonnet 5.5 with Opus 5.5 as the fallback? A ceiling for the live recording (S12 used $10 and spent about $5)?
3. **Where the grammar and the scope phrases live.** 04 §5.1 says a data file, not code. A versioned JSON file in the package (`pipeline/association/grammar.json`), read at start and covered by tests; the DB and learned patterns later (04 §11)? Stage 2's own `tags` stay as they are, and stage 4 parses every span itself.
4. **Components and the stage-5 stub.** Today stage 5 raises `NotImplementedError` when there are components. Stage 4 writes the `components` rows, and stage 5's stub returns no matches without raising until S20. The quote stays at zero lines until S22?
5. **`supply_scope` values.** The DB check constraint and `docs/db-schema.md` say `outside_panel`, `prep_only`, `not_in_scope`; 04 §5.1.2, 07 and the contract say `other_location`, `prepare_only`, `by_others`. The spec wins: a migration renames the allowed values?
6. **The neutral contact on its own line** (S12 backlog). NEVIS-1's 1P+N breakers (F3–F5) come out of stage 3 with an untagged `switch_disconnector` on the N line. Absorb it into the tagged breaker next to it (no component of its own; the label already says `poles=1, neutral=true`)?
7. **Shared labels across tiles** (04 §13 item 1). Find them in code on the whole page before the agent (one label over a row of same-family symbols with no text of their own), and join the agent's per-tile `shared_labels` by span id at the merge, rather than enlarging tiles?

## Outcome

Filled in at `/session-close`.

- **Done:**
  - Stage 4 is real (`pipeline/stages/s4_association.py`, its parts in `pipeline/association/`):
    - the spelling grammar and the scope phrases as data (`grammar.json`, version g2) and its reader (`grammar.py`): every row of 04 §5.1, readings per family, `INC=` as load current;
    - the attribute schemas (`schemas.py`, 05 §4.4), seeded into `attribute_schemas` and read back;
    - geometric association on the whole page, the resolved test, shared labels over a row, the neutral pole on its own line (`assign.py`);
    - multiplicity by position, ranges of circuit numbers, supply scope from phrases (`quantity.py`); chains and the upstream device from the wire graph (`circuits.py`);
    - the tile agent on `text_association` with numbered frames, its check (citation, distance, graphic poles, shared spans, refusal and retry, the fallback model, code alone) (`agent.py`, `konboro_llm/stages/text_association.py`, `LLMRequest.start_at_fallback`);
    - instances, missed symbols, the merge by tag then by signature, confidence and status (`merge.py`); the `components` rows (replaced on a rerun); the stage-5 stub passes components through; the run step's stage-4 line.
  - Migration 0009: `components.supply_scope` takes the spec's values.
  - Eval: `values_without_evidence`, `citation_mismatch_rate`, `agent_tile_share` (lower is better) and the stage-4 counts in the report; 51 `text_association` cassettes; new baseline.
  - Tests: `tests/unit/test_association.py` (97), stage-4 eval metric tests, `tests/unit/llm/test_client.py` on the new call, `tests/integration/test_stage4.py` (4), the run step's stage-4 line in `new-quote.spec.ts` (desktop and mobile).
  - Docs: spec 04 (§5.1, §5.1.1, §5.1.2, §5.2, §5.4, §5.5, §5.6, §5.8, §10, §13), `docs/db-schema.md`, CLAUDE.md (stages line), `eval/README.md`, roadmap backlog, BUG-027.
- **Decisions made:** (with who decided, and why)
  - Measuring stage 4 (2026-11-01, user; question 1): end to end on stage 3's output with the existing stage-4 metrics; each miss named as a stage-3 or stage-4 cause. Feeding labelled detections (04 §10, 00 §10.1) waits for the symbol-box labels in the backlog.
  - Tile agent route and recording (2026-11-01, user; question 2): `text_association` on Claude Sonnet 5.5, falling back to Opus 5.5 after two failed checks (04 §5.5). Live recording with the local key, `EVAL_MAX_USD=10`; stop and ask before passing it.
  - The neutral contact (2026-11-01, user; question 6, S12 backlog): an untagged contact on the N line next to a tagged breaker is absorbed into that breaker, with no component of its own; it supports `neutral=true`.
  - Shared labels across tiles (2026-11-01, user; question 7, 04 §13 item 1): code finds them on the whole page before the agent, and the merge joins the agents' per-tile `shared_labels` by span id. Tiles are not enlarged.
  - Defaults approved with the plan (2026-11-01, user; questions 3–5):
    - The grammar and the scope phrases are a versioned JSON file in the package (`pipeline/association/grammar.json`); stage 4 parses every span itself and stage 2's `tags` stay as they are.
    - Stage 4 writes the `components` rows; the stage-5 stub passes them through without raising until S20; the quote stays at zero lines until S22.
    - `supply_scope` takes the spec's values (`other_location`, `prepare_only`, `by_others`): migration 0009 and `docs/db-schema.md`.
  - Made while building (2026-11-01, Claude; for the user's review at close):
    - **"Resolved" needs current and poles only** (04 §5.2 item 4): required attributes with no default. Curve and breaking capacity may come from the factory's defaults (stage 5), so they don't send every breaker to the agent. Spec 04 says so.
    - **A tag on the page reads as nothing**: "C1" beside a breaker on NEVIS-1 is the contactor's tag, not curve C at 1 A.
    - **Assignment on the whole page**: each span to the symbol that scores it highest; with no capacity limit that is the assignment that maximizes the total (04 §5.2 item 3).
    - **The tile agent's output**: attributes as a list (strict JSON output has no free keys), only the values found, `explicit_texts` as span ids; code keeps its own value where the agent gave none, and where the agent says null only when code was sure (association ≥ 0.9). The answer is refused and asked again with the reason (a symbol missed, answered twice, not shown), then the fallback model (`LLMRequest.start_at_fallback`, new in `konboro_llm`), then code alone.
    - **Merge**: the device's family from its device drawing, then its coil, then its contacts; an untagged contact or coil of a family with tagged devices in the panel joins the nearest one (no quantity of its own); an aux contact's tag is its parent. `unknown_symbol` takes its family's default class.
    - **Chains and circuits from the wire graph**: forward along the line until a junction; only a device of another family inherits, and the walk stops at the next protective device. Ranges of circuit numbers go to the protective device in their column. Dashed frames wait for line styles from stage 2 (backlog).
    - **Component ids** `cmp_<drawing ulid>_<n>`: unique in the tenant, stable on a rerun.
    - **Eval**: three lower-is-better stage-4 metrics, `values_without_evidence` (04 §10: 0), `citation_mismatch_rate` (≤ 2%) and `agent_tile_share`; stage-4 counts in the report.
- **Eval / metrics:**
  - Live recording (2026-11-01) on `claude-sonnet-5-5` at effort `low`, `EVAL_RECORD=missing`: 51 tile-agent calls in the committed cassettes, 306k tokens in and 32k out, **about $0.93** at list prices; no answer was refused, so no fallback call. With the two probes and the first two recordings (52 calls each, a prompt fixed in between), about **$2.10** for the session, against the $10 ceiling. Stages 1–3's cassettes were not touched.
  - Two replays gave identical reports, equal to the live run; `eval/baseline.json` rewritten with `make eval-baseline`: 20 metrics up from 0, none down, stages 1–3 unchanged.

  | Drawing | Component precision | Component recall | `current_a` | Poles | Quantity | Unit recall | No evidence | Citation mismatch | Agent tiles |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | NEVIS-1 | 85.7% (18/21) | 85.7% (18/21) | 100% (11/11) | 91.7% (11/12) | 72.2% (13/18) | 76.6% | 0 | 5.0% (1/20) | 15.0% (9/60) |
  | NURSERY-1 | 80.0% (12/15) | 92.3% (12/13) | 100% (8/8) | 88.9% (8/9) | 91.7% (11/12) | 92.9% | 0 | 0% (0/25) | 11.9% (7/59) |
  | 26-993 | 42.3% (11/26) | 50.0% (11/22) | 100% (7/7) | 100% (7/7) | 72.7% (8/11) | 46.8% | 0 | 7.7% (1/13) | 19.4% (7/36) |
  | 6199-2-50 | 50.6% (42/83) | 57.5% (42/73) | n/a | n/a | 57.1% (24/42) | 52.2% | 0 | 4.9% (6/123) | 26.2% (28/107) |
  | **All** | **57.2%** | **56.5%** | **100% (26/26)** | **92.9% (26/28)** | **67.5%** | 47.0% | **0** | **4.4% (8/181)** | 19.5% |

  - Code alone (the agent's calls missing) gave factory drawings 71.9% precision and 73.2% recall; with the agent, 66.1% and 73.2%, and the designer plan's poles come from the drawing's marks.
  - **Under target, with causes:**
    - Stage 1 and 3, not stage 4: 26-993's feed boards counted as panels (backlog, S08) split identical devices across panels; MS1–MS3 and RF untagged or missing (S12); 6199-2-50's time switches and impulse relays not detected (S12); output terminals counted as components (26 on NEVIS-1, 42 on NURSERY-1; S20 decides). BOM-HW-1 has no pipeline path yet (S14).
    - Stage 4: poles read from drawn contacts vary between recordings (NURSERY-1's C1–C4 came out as three components in the last one); aux contacts drawn twice on NEVIS-1 are counted twice (backlog); on 6199-2-50 some breakers still get no poles, and a fuse's "3×100A" is not always read as three fuses.
    - Citation mismatches 4.4% against 2%: what remains is mostly the agent citing a value the text doesn't say in that sense (a socket's pins as poles, a load's "3×208V" as a contactor's poles, a lone "500A" as a setting). The check refuses them, as it should; the prompt was tightened once.
- **Bugs logged:** BUG-027 (P3, open: stage 2's span tags read `INC=` as a setting; stage 4 doesn't use them). BUG-028 (P2, fixed: the `new-done` screenshot's wait for a whole pipeline run was too short under emulation once stage 4 became real; longer wait, faster tile encoding).
- **Verification:** `make check` under Node 22: lint, licenses, secrets, client freshness, unit (572 backend, 179 frontend), integration (440), eval (no change against the new baseline), E2E (111 passed, desktop and mobile), screenshots (45 of 46, the 46th passed on rerun).
- **Follow-ups:** in the roadmap backlog: output terminals as symbols (S20); dashed frames for supply scope; an auxiliary contact drawn twice; re-running stage 4 under existing quote lines (S22).
