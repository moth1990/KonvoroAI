# S20: Stage 5, catalog matching

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s20-catalog-matching` |
| **Depends on** | S18 |
| **Status** | in review |
| **PR** | (link) |

## Goal

Stage 5 is real. Every component from stage 4 comes out with a SKU that exists in the master catalog, or with `null` and a reason. Code decides almost every match: an explicit SKU or series written in the drawing, the factory's match memory, the brand and series by 05 §5.4's order, missing attributes filled in only where the schema allows it and always marked, circuit inference, a filtered and ranked candidate query that never relaxes an `exact` attribute. The `catalog_disambiguation` model picks only between the candidates code left, and code checks its answer. Each match carries its alternatives, its kit and accessory lines, and a Hebrew reason, ready for stage 7 (S22) and the review screen (S23).

## References

- Specs:
  - 05, all of it: §4 (input: the stage-4 component, general notes and the designer's BOM, catalog and factory data, attribute schemas and `match_mode`), §5 (the flow and the signature cache), §5.1 (normalize and sign), §5.2 (explicit SKU, the consistency check, the factory's own-brand policy), §5.2.1 (series or partial model, `model_tokens`, series-fixed attributes, FNV's conflict), §5.3 (memory, customer before factory), §5.4 (brand and series order, "או ש"ע"), §5.5 (fill-in order: panel notes, drawing notes, tenant default, system default; penalties; the model is not required), §5.5.1 (circuit inference rules as data), §5.6 (filter, staged relaxation, ranking), §5.7 (decision rules, "clear advantage"), §5.8 (the agent: input, output schema, the check), §5.9 (alternatives with their difference), §5.9.1 (kits and accessories), §6 (contract), §6.3 (confidence), §7 (statuses), §8 (issues), §9 (performance), §10 (metrics), §11 (memory and what it learns), §12 (privacy: no price to the model), §13 (open points 1–2).
  - 04 §6.3 (the component contract stage 5 reads, `circuit_context`, `parent_designators`, `supply_scope`).
  - 01 §5.5, §5.5.1 (technical data: control voltage; per-panel notes blocks), §5.8 (the designer's BOM table).
  - 07 §7.2.1–7.2.2 (what counts as an active cost price for `has_cost_price`), §7.4 (derived items: where terminals and the enclosure are counted).
  - 06 `DATA_MODEL_TEXT_CONFLICT`, `POLES_CABLE_CONFLICT` (what stage 5 leaves for stage 6, S21).
  - 11 §5.5 priority 3 (the audit's price-list search, backlog from S15).
  - 00 §5.3 (evidence), §6 (ids, confidence colours), §7.1–7.2 (routes, LLM rules), §10.1 (measure a stage on labelled input).
- Prototype: no screen for the stage. The run step's per-stage summary line already exists. The FNV line (lines 434–436, 470) shows how a memory match reads ("זיכרון התאמות", "נבחר 3P לפי זיכרון ההתאמות").
- Golden: NEVIS-1 (S204M with "3X6A", `ABB-XT1C` "משולב פחת" as a kit, 5 aux contacts on F1–F4 and F7, contactors with no current), NURSERY-1 (the same FNV case through memory; contactors sized above the breaker), 26-993 (BUG-036: SG and the line for EMS), 6199-2-50 (per-panel notes, `PKZM 1-2.4A`, `500A/630A`), BOM-HW-1 (the untyped "מפסק 3X40", the 30 mA default). No golden file holds a SKU.
- Earlier sessions:
  - S02: `catalog_items`, `attribute_schemas`, `match_memory`, `tenant_settings.brand_preferences` / `attribute_defaults`, `customers.brand_preferences`.
  - S13: `components` rows, `association/schemas.py` (05 §4.4 as data), `model_token` in `explicit_texts`, `circuit_context`.
  - S14: BOM rows become components (`association/bom.py`).
  - S18: the catalog CSV loader and the 20-item ABB sample, products linked to catalog items, `domain/pricing/cost.py`.
  - S15: the audit reads stage 4 and skips stage 5 (`differences.py` notes the missing price-list search).

## Tasks

### Backend
- [x] Replace `pipeline/stages/s5_matching.py` (`run(ctx) -> MatchingResult`), its parts in `pipeline/matching/`. One pass per drawing; the signature cache per panel and brand context (05 §5).
- [x] Catalog data for matching (migration, global layer): the catalog's own symbol class to narrow a family (`mcb` / `mccb` / `motor_protection`, `rcd` / `rcbo`), `model_tokens` as written in drawings (05 §5.2.1; today one `model_code`), and kits and accessory compatibility (05 §5.9.1). CSV loader and `docs/catalog-import.md` updated.
- [x] Sample catalog extended to cover the golden drawings (question 1).
- [x] Normalize and sign (05 §5.1): units, family and class to the catalog category, the signature string of 05 §6.1.
- [x] Explicit SKU (05 §5.2): SKU-like strings in `explicit_texts` and the designer's BOM, normalized; the attribute consistency check → `conflict` / `attribute_conflict`; the factory's own-brand alternative.
- [x] Explicit series (05 §5.2.1): `model_tokens` narrow the candidates; attributes the series fixes get `source` = `series`; a code that contradicts the text → `attribute_conflict` (FNV); an unknown code goes to `catalog_gap` for the catalog team.
- [x] Memory (05 §5.3, §11): customer, then factory; not when the drawing names another SKU or brand. A `remember()` service for the review screen's swap (S23) and the `approved_count` bump on approval (S22/S23).
- [x] Brand and series (05 §5.4): `brand_hint`, general notes (panel notes before drawing notes), the customer's preference, the factory's per family, any brand with a cost; "או ש"ע". Notes read in code with a phrase list, no model.
- [x] Fill-in (05 §5.5): notes → tenant default → system default (30 mA), only where `default_allowed`; `defaulted_attributes`; `current_a` and poles never.
- [x] Circuit inference (05 §5.5.1) as data, global with tenant overrides: contactor current from the upstream device, coil voltage from technical data, overload range from `load_current_a`, aux NO/NC from contact numbers, breaker poles from cable cores (only without text or graphic poles; `POLES_CABLE_CONFLICT`), untyped "מפסק" by current, MCCB setting in range. `source` = `inferred`, the explanation, × 0.85. **CT quantity not done**: a quantity is stage 4's (decision 8).
- [x] Candidate query and ranking (05 §5.6): the filter, staged relaxation (series → allowed brands → any brand with a cost) never touching `exact`, discontinued → replacement (`discontinued_replaced`), the five ranking keys; `has_cost_price` from the tenant's products (a boolean only, 05 §12).
- [x] Decision rules (05 §5.7) and the tie-break setting (05 §13 item 1); `gte` upgrades chosen automatically with a tag (05 §13 item 2).
- [x] The agent (05 §5.8) on `catalog_disambiguation`: 3–5 candidates with no price, the component, the relevant notes and preferences in short; the answer checked against the list, one retry with the error; `ambiguous` on `null` or low confidence. Stand-in model answer and a test that no price, cost or customer detail is in the request.
- [x] Alternatives (05 §5.9) with their Hebrew difference; kit lines and accessories by compatibility (05 §5.9.1), an accessory ambiguous when its device is.
- [x] Confidence (05 §6.3), statuses (05 §7), issues (05 §8, including `high_unmatched_ratio`), Hebrew `reason` per match; stats for the run step.
- [x] Contract (05 §6) brought to the spec (question 4).
- [x] The run step's stage-5 summary line (matched, ambiguous, unmatched, model calls).
- [x] Settings: thresholds, the tie-break, inference rules on/off per tenant.

### Frontend
- [x] Only the run step's stage-5 summary line, through the existing per-stage line. Re-check the accepted `new-run` / `new-done` shots.

### Unit tests
- [x] Signature and normalization: units, class narrowing, order-independence.
- [x] Explicit SKU: normalization (spaces, hyphens, dots, case), consistent and conflicting attributes, own-brand alternative.
- [x] Series: S203M narrowing, series-fixed poles, FNV ("3X6A" with S204M → `conflict`), unknown code → `catalog_gap`.
- [x] Memory: customer before factory, the drawing's explicit brand or SKU wins over memory, brand context.
- [x] Brand order: each of 05 §5.4's five levels, "או ש"ע", panel notes over drawing notes.
- [x] Fill-in: each source, `default_allowed` respected, `current_a` and poles never defaulted (property test over the schemas), `system_default` without the penalty.
- [x] Inference: every rule in 05 §5.5.1, no rule without a known upstream device, cable vs graphic poles.
- [x] Query: each filter, each relaxation step and its mark, `exact` never relaxed, discontinued replacement, ranking order, "clear advantage" and the tie-break.
- [x] Agent check: a SKU outside the list refused and retried, `null` → `ambiguous`, confidence capped at 0.85.
- [x] Confidence formula, statuses, alternatives' difference text, kit and accessory lines.
- [x] Contract snapshot and the 05 §6.1 example validated (`test_contracts.py`).

### Integration tests
- [x] Stage 5 through the queue on a golden drawing with the stand-in model: matches in S3 under the tenant, `llm_calls` rows for agent calls only, a rerun gives the same SKUs (consistency).
- [x] Tenant data stays the tenant's: memory, customer preferences, defaults and `has_cost_price` read under RLS; another tenant's memory never applies.
- [x] The agent's request holds no price, cost, margin or customer detail (non-negotiable 6, 05 §12).
- [x] Migration for the catalog columns and tables; the CSV loader with the new columns; `make seed` loads the extended sample.
- [x] The drawing still reaches stage 7 and opens for review; the progress endpoint returns the stage-5 summary.
- [x] Performance: 150 components without the model in under 2 s (05 §9).

### UI tests (Playwright)
- [x] Desktop and mobile: the run step shows the stage-5 summary once stage 5 is done (stand-in model). `new-quote.spec.ts`; the whole suite passes on both projects (149).
- [x] `new-run` / `new-done` screenshots re-checked (`make check-screenshots`): 65 of 66 passed, no pixel difference. `new-pick` (dark, desktop) crashed the page under load (BUG-038) and passed with all six new-quote shots on a rerun. No baseline changed.

### Eval (pipeline sessions)
- [x] Stage-5 metrics (question 2), end to end and on labelled input (00 §10.1, 05 §10): `eval/metrics/stage5.py`, `eval/labelled.py`.
- [x] Record `catalog_disambiguation` cassettes live within an agreed ceiling ($3; two recordings, 14 cassettes kept); `make eval` in replay twice, identical; numbers under Outcome; `make eval-baseline`.

### Docs
- [x] 05 with this session's decisions (contract fields, open points 1–2, output terminals).
- [x] `docs/db-schema.md` (catalog columns and tables, any tenant setting), `docs/catalog-import.md`, CLAUDE.md "Stages" line (stage 5 is real), `eval/README.md`.

## Acceptance criteria

From 05 §9–10, as far as the sample catalog and the golden set can measure them:

- [x] Wrong electrical value (`exact`) in a chosen SKU: **0**, on every drawing, end to end and on labelled input. **0: 24/24 end to end, 105/105 labelled.**
- [x] Every SKU in the output exists in the catalog; every `null` has a reason. `test_every_chosen_sku_is_in_the_catalog`.
- [x] `current_a` and poles never come from a default (a test over every schema family; `fill` never offers them).
- [x] Consistency: the same signature in a drawing gets the same SKU, 100%. **100% (93/93 end to end, 103/103 labelled).**
- [x] `unmatched` when the catalog has the item: ≤ 1% on labelled input. **0% (0/152).**
- [x] Signatures sent to the model: ≤ 15%. **4.4% end to end (6/137), 7.8% labelled (9/115); at most 10.5% on one drawing (BOM-HW-1).**
- [x] No price, cost or customer detail in any model request (unit and integration tests).
- [x] 150 components in under 2 s without the model (about 0.03 s).
- Top-1 SKU accuracy (≥ 95%) and top 3 (≥ 99%) are not measured: the golden set holds no SKU (decision 2).

## Out of scope

- The review screen's SKU swap, approval and the memory writes they trigger: S23 (S20 provides `remember()`).
- Prices, margins and derived items (enclosure, busbars, terminals by count): S22.
- Validator rules, including `DATA_MODEL_TEXT_CONFLICT` and `POLES_CABLE_CONFLICT` as findings: S21. Stage 5 leaves the data they need.
- The settings screen for brand preferences and defaults: S24.
- Tenant proposals to tune an inference rule from the estimator's choices (05 §5.5.1, last bullet): needs the approval flow (06 §11, S24).
- The audit's price-list search (11 §5.5 priority 3): stays in the backlog unless question 3 brings it in.
- A real master catalog (roadmap B3) and the electrical expert's review of schemas and inference rules (B2).

## Open questions

1. **Sample catalog.** The 20-item ABB sample covers few golden components (no contactors, lamps, selectors, relays, S204M). Extend it?
2. **Eval without SKU labels.** No golden file holds a SKU, and golden files can't change without you. What does the eval measure?
3. **Output terminals and auxiliary families.** Are output terminals (26 on NEVIS-1, 42 on NURSERY-1) matched as quote lines?
4. **Kits and accessories (05 §5.9.1).** They need a compatibility table nobody has delivered. Build with sample data now, or defer?
5. **Contract vs spec (found at kickoff).** The contract's `UsedSource` has `circuit` where 05 §5.2.1 and §5.5.1 say `series` and `inferred`, and it has no `bundle_lines` (05 §5.9.1). The catalog has one `model_code` where 05 §5.2.1 says `model_tokens`. Proposal: the spec wins; the contract gains `series`, `inferred` (replacing `circuit`) and `bundle_lines`; the catalog gains `model_tokens`.

## Outcome

Filled in at `/session-close`.

- **Done:** Stage 5 is real (`pipeline/matching/`, `stages/s5_matching.py`): normalize and sign, explicit SKU and series (with series-fixed values and conflicts), match memory (customer, then factory), brand and series by 05 §5.4, fill-in from notes, factory and system defaults, circuit inference as data (`inference.json`), the candidate query with staged relaxation that never relaxes `exact`, the ranking and decision rules, the `catalog_disambiguation` agent (Haiku, no prices, checked, one retry), alternatives with their difference, kit lines and accessories by series. Migration 0015 (catalog `symbol_class`, `model_tokens`, `catalog_kits`, `catalog_accessories`; `components.match_status`, `catalog_item_id`; `tenant_settings.matching`). The catalog loader takes kit and accessory files; the sample is 156 items (ABB, Schneider, one SATEC). `services/match_memory.py` (`remember`, `approve`) for S23. The run step's stage-5 line. The eval's `s5` and `s5_labelled` sections. Not done: a CT's count of 3 (decision 8).
- **Decisions made:** (with who decided, and why)
  1. **Sample catalog: about 100 items, ABB and Schneider** (user, at kickoff; question 1). Every family in the golden drawings, including S204M, the XT1C kit and aux contacts, so brand relaxation and substitution run end to end. Made-up list prices, marked as a sample, replaced when B3 arrives.
  2. **Eval: label-free metrics** (user, at kickoff; question 2). Wrong `exact` value (must be 0), `unmatched` when the catalog has an item, consistency, the model's share, the method mix; end to end and on the labelled attributes (05 §10, 00 §10.1). Top-1 and top-3 wait for SKU labels.
  3. **Auxiliary families get no SKU** (user, at kickoff; question 3). Components whose family is in the tenant's `auxiliary_families` (`terminal` by default) are listed apart by stage 5; stage 7 counts them as derived material (07 §7.4, S22). Closes the backlog item "Output terminals as symbols".
  4. **Kits and accessories built on a sample compatibility table** (user, at kickoff; question 4). A global table with a few rows (XT1C + RCD module, S2C aux contacts on S200M), so NEVIS-1's Q0 and its five aux contacts work end to end.
  5. **The spec wins over the contract** (kickoff, question 5, in the plan the user approves): `UsedSource` gains `series` and `inferred` (replacing `circuit`), the match gains `bundle_lines`, the catalog gains `model_tokens`.
  6. **Rules found while building** (Claude, in session; all written in 05's "החלטות ב-S20", items 4–12): a filled-in value applies only to items that state the attribute; a value the drawing left out that tells candidates apart goes to the estimator, never to a price, a habit or the model; an `ambiguous` match keeps a provisional, yellow choice; NO/NC is read from contact numbers; a stated preference is part of the signature; the cache keys on what the text found; the agent only when something beside the component can be read (a tag that is a word, like EMS, counts); a motor-protection breaker is its range; an "electronic" trip unit accepts LSI/LI. The demo and eval factories default an RCD to type A (factory policy, 05 §4.4).
  7. **Stage 5's result on the component row** (Claude, in session): `components.match_status` and `catalog_item_id` (migration 0015), for the run step's line; the full match stays in S3.
  8. **Not done: a current transformer's count of 3** (05 §5.5.1): a quantity is stage 4's; it waits for stage 6's cross-check (S21).
- **Checks:** `make check` under Node 22: lint, types, licenses, secrets, client, unit (896 + 224 Vitest), integration (562), eval (no regression), E2E (149, desktop and mobile) all green; screenshots 61 of 66, the 5 timeouts passing rerun alone (BUG-038).
- **Eval / metrics:** replay, after the two live recordings (14 `catalog_disambiguation` cassettes, under $3 in all). Stage 5 end to end: SKU values right 100% (24/24), components with a SKU 69.3% (113/163; 6199-2-50 55.4%: sockets, fuse bases and PKZM have nothing in the sample catalog or no current), consistency 100% (93/93), model share 4.4% (6/137). On the labelled attributes: exact values 100% (105/105), unmatched though in the catalog 0% (0/152), consistency 100% (103/103), model share 7.8% (9/115). Top-1 and top-3 are not measured (decision 2). No other metric moved. Two replays identical; `make eval-baseline` written.
- **Bugs logged:** none new. BUG-038 seen twice: `new-pick` crashed the page in a standalone `make check-screenshots`, and five shots timed out in `make check` after the E2E suite; each passed when rerun alone, no pixel difference.
- **Follow-ups:** in the roadmap backlog: matching settings on the settings screen (S24); a drawing's BOM SKUs linked to its components and a CT's count (S21); the factory tuning an inference rule from its choices (S24); the audit's price-list search can now use stage 5 (backlog item updated). The electrical expert's review of the inference rules joins B2.
