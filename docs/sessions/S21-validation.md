# S21: Stage 6, validation

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s21-validation` |
| **Depends on** | S20 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#24](https://github.com/moth1990/KonvoroAI/pull/24) |

## Goal

Stage 6 is real. For each panel, code builds one panel model (final attributes from the chosen catalog item or else as read, the hierarchy when the wire graph is built, the main device, structural elements) and runs a versioned rule pack stored as data, with factory overrides. It cross-checks the designer's BOM when the drawing has one, and the `validator_review` agent adds at most 5 warnings per panel that rules don't cover. The validator flags and never fixes: each issue has a Hebrew message, its values, the components and instances it points to, and the cap it puts on the rows' colour. The rules alone re-run on one panel in under 1 s, ready for the review screen's edits (S23).

## References

- Specs:
  - 06, all of it: §1 (flag, don't fix; independent; rules first; false findings are costly; not an engineering check), §4 (input from stages 1–5, the rule pack, factory overrides, dismissal stats), §5 / 6.1 (the panel model, the main device with and without a graph), 6.2 (rules as data; categories A–D and every rule in their tables; `requires` → `checks_skipped`; category D as a bug net), 6.3 (the BOM cross-check, four outcomes), 6.4 (the agent: input, output schema, its rules), 6.5 (de-duplication, overrides, row caps, panel-level issues), §6 (contract, issue fields, after a user action), §7 (decision rules), §8 (stage issues), §9 (performance), §10 (the injected-error set, targets), §11 (learning loop, tenant tuning), §12 (no price to the model), §13 (open points).
  - 04 §5.1.1 (ranges and multiplicity), §5.1.2 (`supply_scope`), §6.3 (the component contract, `circuit_context`, `multiplicity_inherited`).
  - 05 §5.5.1 (inferred attributes), §6 (the match: `defaulted_attributes`, `substitution`, `has_cost_price`, `conflict`), `DATA_MODEL_TEXT_CONFLICT` and `POLES_CABLE_CONFLICT` left for stage 6 (S20).
  - 01 §5.5.1 (per-panel notes blocks, e.g. 10 kA), §5.8 (the designer's BOM table).
  - 02 §7–8 (`wire_graph.status`), 03 §4.5 (detection roles, `front_view`).
  - 07 §7.4 (the enclosure by modules, for `BOM_NO_ENCLOSURE`), 09 §6 (how findings show on the review screen).
  - 00 §5.3, §6 (ids, `iss_`, colours), §7.1–7.2 (routes; `validator_review`), §10.1 (measure on labelled input).
- Prototype: lines 460–472 (`makeFindings`: `FRONT_VIEW_DESIGNATOR_MISSING`, `MISSING_PRICE`, `DATA_INFERRED_ATTRIBUTE`, `DATA_MODEL_TEXT_CONFLICT`, each with a title, a body, a box or a line, and actions). The findings panel is built since S09/S11; its actions are S23's.
- Golden:
  - 26-993: `findings` (FC1 16A with INC=20A → `DATA_LOAD_CURRENT_GT_RATED`; SE in the front view vs SG in the plan → `FRONT_VIEW_DESIGNATOR_NEAR_MATCH`; GIC-1 ↔ RF; partial text layer; remote emergency button as a supply scope).
  - NURSERY-1: `front_view_only` F26–F29 → `FRONT_VIEW_DESIGNATOR_MISSING`, resolved as leftovers.
  - 6199-2-50: `referenced_not_drawn` ("לוח מבנה משרדים" from circuit 28) → `PANEL_REFERENCED_NOT_DRAWN`; circuits 67–70 with one MCB → `QTY_RANGE_MISMATCH`.
  - BOM-HW-1: 5 shunt trips and 2 breakers → `BOM_ACCESSORY_HOST_COUNT`; no enclosure → `BOM_NO_ENCLOSURE`.
  - NEVIS-1: front view "R1-R7" vs R1, R3, R5, R6, R7 in the control plan → `FRONT_VIEW_DESIGNATOR_MISSING`; FNV → `DATA_MODEL_TEXT_CONFLICT`.
- Earlier sessions:
  - S02: `validator_rules` (global), `tenant_rule_overrides`, `findings` (on `quote_version_id`).
  - S09/S11: the review screen reads `findings` (`FindingOut`) and shows them with "בשרטוט"; only the NURSERY-1 fixture writes rows today.
  - S10: `wire_graph` per page. S13: `circuit_context.upstream_component_id`, `missing[]`, `context_elements`, `multiplicity_inherited`.
  - S14: the `bom_table` artifact. S20: the stage-5 match per component, `defaulted_attributes`, inferred values, `conflict` / `attribute_conflict`.
  - Backlog: "A drawing's BOM SKUs and a CT's count" (S20), "An auxiliary contact's device and front-view ranges" (S12), BUG-036 (26-993's SG and EMS).

## Tasks

### Backend
- [x] Replace `pipeline/stages/s6_validation.py` (`run(ctx) -> ValidationResult`), its parts in `pipeline/validation/`.
- [x] Panel model (06 §6.1): final attributes (catalog item, else as read, each with its source), the hierarchy from `circuit_context` when the page's `wire_graph` is `built`, the main device (top of the tree, or the highest current among `circuit_breaker` / `switch_disconnector`), busbars, meters and CTs from `context_elements`.
- [x] Rule pack as data (06 §6.2): `pipeline/validation/rules.json` (id, version, category, `applies_to`, `requires`, severity, params, `message_he`, `enabled`), seeded into `validator_rules` by `seed_global`; `rules_version`. Each rule's check is a pure function keyed by `rule_id`. Factory overrides from `tenant_rule_overrides` (off, params); `tenant_rules_version`.
- [x] Category A: the four `HIER_*` rules (graph only) and the two `PANEL_*` rules (no graph needed).
- [x] Category B: main device, empty panel, overload without contactor, contactor without coil circuit, missing rows, referenced not drawn, BOM accessory host count, BOM without an enclosure, supply scope not in panel; the three `FRONT_VIEW_*` rules from stage 1's front-view tags (decisions 2, 8).
- [x] Category C: multiplicity outlier (24), more than one main device, range vs multiplicity, inherited multiplicity, text coverage below 90%.
- [x] Category D: SKU vs read `exact` value, same signature with different SKUs, general note not applied, many defaults (30%), designator in two families, model vs text, load current above rated, inferred attribute, poles vs cable cores, panel requirement not met, no cost price. A D rule that fires adds `internal_consistency_violation` (06 §8).
- [x] BOM cross-check (06 §6.3): BOM rows signed by stage 4's grammar, matched per panel or for the drawing, the four outcomes (`BOM_MISSING_IN_QUOTE`, `BOM_EXTRA_IN_QUOTE`, `BOM_QTY_DIFF`, `BOM_SKU_DIFF`), `bom_crosscheck` summary; `bom_parse_failed` when it can't read.
- [x] Agent (06 §6.4) on `validator_review`: one call per panel with ≥ 5 billable components; the panel's component table (no price, no cost), the panel crop (long side 1568 px), the indented tree, the BOM summary, the rule findings. Code drops answers with no existing component or a bbox outside the panel, caps severity at `warning`, hides confidence < 0.5, keeps at most 5. `agent_unavailable` when it fails. Stand-in model answer.
- [x] Merge and caps (06 §6.5): agent issue dropped when a rule issue covers the same components and subject; `row_status_caps` (error → red, warning → yellow, info → tag); panel-level issues on the panel summary; `panel_summaries`.
- [x] Findings rows: stage 6 writes them on the drawing, stage 7 attaches them to the quote version (decisions 1, 12).
- [x] Re-run after an edit (06 §6.3, §9): `engine.revalidate` and `services/validation.revalidate_panel`, rules only, one panel, under 1 s, findings rows synced (decision 5).
- [x] Stage issues (06 §8): `rule_execution_failed` (the rule is skipped and logged), `agent_unavailable`, `internal_consistency_violation`, `bom_parse_failed`.
- [x] The run step's stage-6 summary line (errors, warnings, info, skipped checks, agent calls) and the done step's `findings` count.

### Frontend
- [x] The run step's stage-6 line through the existing per-stage line, and the done step's findings count. Re-check the accepted `new-run` / `new-done` shots.

### Unit tests
- [x] Panel model: main device with and without a graph, attributes from the catalog item over the read ones, tree from `circuit_context`.
- [x] Every rule: fires on a minimal case, stays silent on the near miss, respects its params and a tenant override; `requires` missing → `checks_skipped` with the reason.
- [x] A rule that raises → `rule_execution_failed`, the other rules still run.
- [x] BOM cross-check: each of the four outcomes, per panel and for the drawing.
- [x] Agent check: unknown component, bbox outside the panel, `error` downgraded, confidence < 0.5 hidden, more than 5 cut, duplicate of a rule issue dropped; the request holds no price, cost or customer detail.
- [x] Row caps and panel-level issues; issue ids stable across a rerun.
- [x] Rule pack schema check (every rule has a function, every function a rule, messages fill without a missing value).
- [x] Contract snapshot and the 06 §6.1 example (`test_contracts.py`).

### Integration tests
- [x] Stage 6 through the queue on a golden drawing with the stand-in model: the result in S3 under the tenant, `llm_calls` for agent calls only, a rerun gives the same issues.
- [x] Tenant overrides read under RLS; another tenant's override never applies.
- [x] The agent's request holds no price, cost, margin or customer detail (non-negotiable 6, 06 §12).
- [x] Rule pack seeded into `validator_rules`; `make seed` safe to rerun.
- [x] Findings reach the review API for a pipeline quote (per question 1); the progress endpoint returns the stage-6 summary and the findings count.
- [x] Performance: the rules on a whole drawing under 1 s, and on one panel's re-run under 1 s (06 §9).

### UI tests (Playwright)
- [x] Desktop and mobile: the run step shows the stage-6 summary, and the done step's findings count (stand-in model). `new-quote.spec.ts`; the whole suite passes on both projects (151).
- [x] `new-run` / `new-done` screenshots re-checked (`make check-screenshots`): 66 of 66 passed, no baseline changed.

### Eval (pipeline sessions)
- [x] Stage-6 metrics end to end (`s6`) and on the labelled quote with the injected-error set (`s6_labelled`; `eval/validation.py`, `eval/metrics/stage6.py`).
- [x] `validator_review` cassettes recorded live (8 calls, about $0.17 of the $5 ceiling); `make eval` in replay twice, identical; numbers under Outcome; `make eval-baseline`.

### Also
- [x] Stage 5 marks a model-code conflict that memory settled (`attribute_conflict_resolved`), for decision 4.
- [x] Migration 0016: `validator_rules.title_he` and `approval`; `requires` takes `front_view` and `text_layer`.
- [x] The eval's report: an `average` kind for per-drawing counts; each drawing's findings and injected errors.

### Docs
- [x] 06 with this session's decisions (and any spec fix from the questions).
- [x] `docs/db-schema.md` (any column or table), CLAUDE.md "Stages" line (stage 6 is real), `eval/README.md`.

## Acceptance criteria

From 06 §9–10:

- [x] Injected errors caught by rules (categories A–E): **≥ 95%**. **98.2% (56/57)** of those a rule can see; 5 of 62 had nothing to see them (decision 15).
- [x] `error` findings on correct (labelled) input: **≤ 1 per 10 drawings**. **0 in 5 drawings.**
- [x] `warning` findings on correct input: **≤ 3 per drawing**. **0.8 per drawing (4 in 5).**
- [x] Category D safety nets that fired on correct input: **0**. **0.**
- [x] Rules on a whole drawing: **≤ 1 s**; a rules-only re-run on one panel: **< 1 s**. Unit (150 components) and integration (`revalidate_panel`).
- [x] At most one agent call per panel with ≥ 5 components; no agent `error`; no agent issue without a component or a box in the panel. Unit tests; 8 calls on the golden set.
- [x] No price, cost or customer detail in any model request. Unit and integration.
- [ ] Injected errors caught by the agent: measured, no target (06 §10.2). **Not measured**: the labelled quote has no picture (backlog).

## Out of scope

- Findings actions on the review screen (ignore with a reason, add rows, "open the line"), dismissals and their stats, the edit that triggers the re-run: S23.
- Whether an open `error` blocks sending (06 §13 item 3): S23.
- The final row colour (worst source with all reasons): stage 7, S22. Stage 6 only gives the caps.
- Proposing to turn a rule off after 5 dismissals in a row (06 §11): with the approval queue, S24.
- An Israeli electrical-regulations rule pack (06 §13 item 1).
- Counting modules on the front view against the components (06 §13 item 4).
- The electrical expert's approval of category A wording and thresholds (06 §13 item 2, roadmap B2).

## Open questions

1. **Where findings rows are written.** `findings` hangs on `quote_version_id`, which stage 7 creates after stage 6. Proposal: stage 6 writes its result to S3 only; the stage-7 stub writes one `findings` row per issue now, so the review screen and the done step show real findings before S22. S22 adds pricing findings and the row colours.
2. **Front-view rules.** Stage 3 doesn't read front-view pages, so nothing reads their designators (NURSERY-1's F26–F29, NEVIS-1's "R1-R7", 26-993's SE). Options: (a) read the designators from a front-view page's text in code (vector text; a raster page through the existing OCR), with the stage-4 grammar for ranges; (b) leave the three `FRONT_VIEW_*` rules skipped with `front_view_unavailable` until a later session.
3. **The injected-error set (06 §10.1, open point 6).** Proposal: built in code in `eval/`, from the labelled input of each golden drawing, with the four mutations the spec lists (an MCB set to 63 A under a 40 A main, a quantity cut by 2, a SKU swapped for one with other poles, a component deleted) plus one per rule family where a mutation is natural. Golden files don't change.
4. **Re-run after an edit.** No edit endpoint exists until S23. Proposal: a `revalidate` service (rules only, one panel, < 1 s, tested), and S23 calls it from the edit routes. No new route in S21.
5. **Agent cassettes.** Recording `validator_review` (Sonnet, one image per panel, about 12 panels across the golden set) live. Ceiling proposal: $5.
6. **Spec vs prototype: `DATA_MODEL_TEXT_CONFLICT`'s severity.** 06 §6.2 says `warning`; the prototype's FNV finding (line 468) is `info` ("נפתר לפי זיכרון ההתאמות"). Proposal: `warning` when stage 5 left the conflict open, `info` when memory or the user resolved it; written into 06.
7. **Category A before the expert's review (06 §13 item 2, B2).** Proposal: ship the six rules on, with the spec's thresholds, marked in the pack as awaiting the expert's approval; the UI line "this is not an engineering check" is already S23's.

## Outcome

Filled in at `/session-close`.

- **Done:** Stage 6 is real (`pipeline/validation/`, `stages/s6_validation.py`): the panel model, 38 rules as data (34 checks, 4 of the BOM cross-check), the `validator_review` agent, caps, panel summaries, stable ids. Findings are rows on the drawing that stage 7 attaches to the quote version, so the review screen and the done step show them. The rules-only re-run for S23 (`services/validation.py`). The run step's stage-6 line. The eval's `s6` and `s6_labelled` sections with the injected-error set.
- **Decisions made:** (with who decided, and why)
  1. **Findings rows written by the stage-7 stub** (user, at kickoff; question 1). Stage 6 writes its result to S3; stage 7 turns each issue into a `findings` row on the quote version, so the review screen and the done step show real findings before S22.
  2. **Front-view designators read from the page's text** (user, at kickoff; question 2). In code: vector text, a raster page through the existing OCR, ranges ("R1-R7") through stage 4's grammar. The three `FRONT_VIEW_*` rules run on NURSERY-1, NEVIS-1 and 26-993.
  3. **The injected-error set is generated in `eval/`** (user, at kickoff; question 3), by mutating each golden drawing's labelled input: the four mutations of 06 §10.1 plus one per rule family where natural. Golden files are untouched.
  4. **`DATA_MODEL_TEXT_CONFLICT`: `warning` while open, `info` once resolved** (user, at kickoff; question 6, spec vs prototype line 468). Resolved means memory or the user settled it. Written into 06.
  5. **Re-run as a service only** (user, at kickoff; question 4). `revalidate(panel)`, rules only, < 1 s; S23's edit routes call it. No route in S21.
  6. **Live recording ceiling: $5** (user, at kickoff; question 5) for the `validator_review` cassettes.
  7. **Category A on, marked as awaiting the expert** (user, at kickoff; question 7). The six rules run with the spec's thresholds; the pack marks them pending B2's approval.
  8. **The front view's tags come from stage 1** (Claude, in session; refines decision 2). Stage 1 already reads every front-view page into a `panel_front_view` artifact with its tags, ranges kept; stage 6 spreads the ranges in code. No second reading of the page.
  9. **The main device** (Claude, in session; 06 §6.1): with a graph, the highest current among the feeders nothing feeds (a graph that missed a link leaves lower ones parentless too: on NURSERY-1 the contactors' breakers became "the top"); without one, a device called "ראשי" or MAIN, then the feed classes (switch-disconnector, MCCB, changeover), then any breaker. A highest current shared by more than one unit among all breakers names no main.
  10. **Poles compared as phases; outgoing-current rules on breakers and fuses only** (Claude, in session). A 4P RCD under a 3P main, or a 40 A RCD after a 25 A main (6199-2-50's guard booth), is normal.
  11. **Contract** (Claude, in session; written into 06): `Issue.page_id` and `Issue.title` (the review screen shows a headline and a body, prototype lines 460–472), `ValidationResult.stage_issues` (06 §8). Migration 0016 for the rule table's `title_he` and `approval`.
  12. **Stage 6 writes the findings rows itself** (Claude, in session; refines decision 1). On the drawing, with no quote version, so the run step counts them when stage 6 is done; stage 7 attaches them to its version. The review screen sees the same.
  13. **The agent's findings** (Claude, in session; 06 §6.4): confidence 0.5–0.7 is an info, 0.7 and above a warning. It never sees `DATA_NO_COST_PRICE`, not even that a price is missing (06 §12). Rows are shown as `c01`, so a request replays the same.
  14. **Category D's safety nets are two** (Claude, in session): `DATA_SKU_ATTR_MISMATCH` and `DATA_SAME_SIGNATURE_DIFF_SKU`. An inferred value or a missing cost is a normal finding. Findings with one cause are grouped, one finding naming every row, as the prototype's are.
  15. **Injected errors count only where a rule can see them** (Claude, in session; 06 §10.1): a quantity cut or a deleted component needs a front view that shows its tags or a designer's BOM; a current needs a main device. Without them no rule can catch it, by design; those are reported apart (`injected_not_applicable`).
  16. **The eval's factory turns `DATA_NO_COST_PRICE` off** (Claude, in session): it has no price list, so every SKU would lack a cost.
- **Checks:** `make check` under Node 22, all green: lint, types, licenses, secrets, client, unit (959 + 225 Vitest), integration (565), eval (no regression), E2E (151, desktop and mobile), screenshots (66 of 66, no baseline changed).
- **Eval / metrics:** replay, after one live recording of `validator_review` (8 cassettes). On the labelled quote: false errors 0 in 5 drawings, false warnings 0.8 per drawing, safety nets 0, injected errors caught 98.2% (56/57; the miss is NEVIS-1's L1–L3 cut to one, whose tags L2 and L3 the drawing also uses elsewhere), 5 of 62 not applicable. End to end: golden findings 85.7% (6/7; 26-993's SE/SG cannot fire, BUG-046), errors 0, warnings 4.2 per drawing (6199-2-50: 13, mostly stage 4's ranges with no count). No other metric moved. Two replays identical; `make eval-baseline` written.
- **Bugs logged:** BUG-046 (26-993's front view read without SE).
- **Follow-ups:** in the roadmap backlog: findings actions and the dismissal loop (S23, S24); `QTY_RANGE_MISMATCH` reads stage 4's own flag; the agent's catch rate on injected errors. Updated: the aux contact's device (front-view ranges done), a drawing's BOM SKUs and a CT's count.
