# S06: Golden eval harness

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s06-golden-eval` |
| **Depends on** | S05 |
| **Status** | in review |
| **PR** | [#7](https://github.com/moth1990/KonvoroAI/pull/7) |

## Goal

`make eval` runs the pipeline on every golden drawing and scores each stage against the labels. It writes a report and compares it with the last one on `main`. Replay mode makes this deterministic and free, so CI runs it on every pipeline PR. The scores will be near zero with stub stages. What matters is that the measurement is real.

## References

- Specs:
  - 00 §10: the three test sets; the most important metric per stage.
  - Acceptance sections: 01 §10, 04 §10, 07 §10.2, 11 §10.
  - README §6.2 #1: the golden set's purpose and target size.
- Golden: all 5 folders. Label shapes:
  - 26-993: `bom[]` + `outside_scope[]`.
  - NEVIS-1: `components[]` + `derived_expected[]`; page kind `single_line`.
  - 6199-2-50: `panels[].components[]`.
  - BOM-HW-1: `rows[]` with `transcription_confidence`.
  - NURSERY-1: `rows[]` with prices.
  - `actual_quote.json` exists for 26-993, NEVIS-1 and NURSERY-1, with differing key names (`text` / `description`, `subtotal` / `total_before_vat`).
- [dev-strategy.md §6](../dev-strategy.md#6-golden-evaluation).

## Tasks

### Eval
- [x] `eval/canonical.py`: canonical schema. For each drawing:
  - `pages[{no, kind, route}]` and `input_kind`;
  - `panels[{name, components[{family, attributes, designators, qty}]}]`;
  - `audit{matched, differences[{type, item, designators, value_at_risk}]}`;
  - `quote_total`.
- [x] `eval/normalizers/`: one per label shape. Map the known quirks, e.g. `single_line` → `single_line_diagram`. Unit-test each normalizer against its file: product counts, unit counts, and the `summary` checksums where present.
- [x] `eval/metrics/`:
  - stage 1: page kind accuracy, route accuracy, missed process pages, `input_kind`;
  - stage 4: component precision and recall per panel, by family + designators, with attribute accuracy for `current_a` and poles, and quantity accuracy;
  - audit: difference precision and recall against the factory-confirmed `differences[]`;
  - pricing backtest: total within ±5%.

  Stages without labels yet (2, 3) report `n/a`.
- [x] `eval/run.py`:
  - runs the real pipeline in-process (no queue) per drawing on a throwaway tenant;
  - collects stage outputs and scores them;
  - writes `eval/reports/<ts>.json` and `.md`.
- [x] `eval/compare.py`: compares a report with a baseline (the last `main` artifact, or a committed `eval/baseline.json`). Prints the deltas. Exits non-zero on any regression unless `--allow-regression`.

### Backend (`konboro_llm`)
- [x] `CassetteProvider`:
  - key = hash of (stage, model, system, user_text, image hashes, schema);
  - `replay` mode: a missing key raises a clear error;
  - `record` mode: calls the wrapped provider and stores the JSON in `eval/cassettes/<stage>/<hash>.json`.
- [x] `EVAL_MODE=replay|live`, `EVAL_RECORD=1`.
- [x] `StageContext.llm`: one `LLMClient` per pipeline, built in the worker (live) or by eval (cassette). The stubs don't call it yet.
- [x] `make eval` and `make eval-baseline` replace the placeholder target. Recording is `EVAL_MODE=live EVAL_RECORD=1 make eval`.
- [x] Cost logging: every live call writes to `llm_calls` (stage, tenant, model, tokens, latency, attempts), not just to `logging`.

### Unit tests
- [x] Normalizers (5 files), every metric function on hand-made small cases, and the comparison logic.
- [x] `CassetteProvider`: record, then replay gives an identical result; a missing key raises.

### Integration tests
- [x] `make eval` in replay mode completes on all 5 drawings and produces both report files.

### CI
- [ ] An `eval` job runs on PRs touching `backend/konboro/pipeline`, `contracts`, `konboro_llm`, `eval` or `golden`. It posts the markdown summary as a PR comment (or job summary) and fails on regression. Built: job summary plus report artifact. Not ticked until CI is green on the PR.

## Acceptance criteria

- [x] Replay is deterministic: two runs give byte-identical metrics.
- [x] The normalizers reproduce the documented counts. NEVIS-1: 21 components. 6199-2-50: 84 products and 184 units. 26-993: 22 products and 47 units. NURSERY-1: 13 products. BOM-HW-1: 19 products.
- [x] The report is readable on its own: per-drawing and per-stage tables, plus totals by input kind.

## Out of scope

- Span and box labeling tooling for stages 2–3. Planned as part of S10/S12 or the backlog, once labels are needed.
- Injected-error sets (06 §10.1, 11 §10). Added in S15 and S21.

## Open questions

- ~~Should the baseline be committed, or taken from the last `main` CI artifact?~~ Answered below.

## Outcome

- **Done:** The golden-set harness, end to end:
  - **Normalizers.** `eval/normalizers/` reads the five label shapes into one canonical schema (`eval/canonical.py`): page kinds and routes, `input_kind`, components per panel, confirmed audit differences, and the real quote's pre-VAT total. Shapes are recognised from the file's keys. Quirks mapped in `common.py`: `single_line`, missing routes, designator ranges (`F1–F17`), NEVIS-1's `resolved` poles, and NURSERY-1's current and poles taken from the product names. Every documented count is reproduced.
  - **Metrics.** `eval/metrics/` covers stage 1 (01 §10), stage 4 (04 §10, three-pass matching), the audit (11 §10) and the pricing backtest (07 §10.2). Stages 2–3 report n/a with the reason.
  - **Runner.** `eval/run.py` recreates `konboro_eval`, uploads each drawing to a throwaway tenant, and runs the coordinator's stages in-process (`Pipeline.run_inline`). It writes `eval/reports/<ts>.json` and `.md` (per drawing, per stage, per panel, totals by input kind), compares with `eval/baseline.json` (`eval/compare.py`), and writes the job summary in CI.
  - **Model gateway.** `CassetteProvider` (replay and record), `EVAL_MODE` / `EVAL_RECORD`, `LLMClient.on_call`, and `StageContext.llm`. Every answered call writes an `llm_calls` row in its own transaction (`konboro/services/llm.py`).
  - **Tooling.** `make eval`, `make eval-baseline`, and `eval` in `make check`. A CI `eval` job runs on pipeline paths and on main, with the job summary and the report artifact. Lint covers `../eval`.
- **Decisions made:**
  - **Baseline** (user, session start): committed `eval/baseline.json`. A PR that moves a metric updates it on purpose, so the change is reviewed.
  - **6199-2-50 ground truth** (user): stage 4 is scored against `panels[].components[]`. With no designators, components match on family + `current_a` + poles, with quantities added up on both sides, so merged and unmerged output score the same. `bom[]` is used only for the 84-product / 184-unit checksum.
  - **Matching key in general**: family + designators when the label has designators (factory drawings). Otherwise family + `current_a` + poles (designer plans, BOM-only).
  - **Pricing backtest reference** (user): the real quote's pre-VAT total (`subtotal` / `total_before_vat`), as 07 §10.2 says. The report shows the factory-confirmed value at risk next to it, so a gap can be explained.
  - **Missing routes** (user): the normalizer fills a missing route from the route the other golden files give the same page kind (`technical_data` → `context`, `single_line_diagram` → `process`, `factory_template` → `skip`). The mapping is one table in the normalizer. Fixing 01 §7 stays in S08.
  - **Audit ground truth**: only differences the factory confirmed. 26-993's `not_a_difference` is excluded. NEVIS-1's `in_drawing_not_in_quote` / `quantity_differences` map to `missing_in_quote` / `quantity_mismatch`. Predicted and labelled differences match by designator overlap. Type agreement is reported separately. The audit flow (11) isn't built yet, so the run reports `n/a`. The metric is unit-tested on hand-made cases.
  - **The LLM client reaches stages through `StageContext.llm`.** The worker passes the live client, and eval passes one wrapped in `CassetteProvider`. The coordinator's logic doesn't change. It only hands the client through.
  - **Stage 4 recall's denominator is fixed** (Claude, during the build). A labelled component with designators always counts as one item. It can match by designators, or one to one by key, but it is never grouped with others. The first version grouped the unmatched ones, so NEVIS-1's denominator moved between 17 and 21 with the prediction.
  - **NURSERY-1 attributes come from the product names** (Claude). The label has no attribute block. `3P ‏20A` gives poles and current; a minimum ("‏16A לפחות") is not taken as a rating.
  - **Eval needs `make up`.** Stages use a DB session and S3, so `eval/run.py` runs the coordinator's stage functions in order, without the queue, on its own `konboro_eval` database, with a throwaway tenant per run. The CI eval job reuses the backend job's services.
- **Eval / metrics:** The first baseline, with stub stages. All numbers are expected to be low; what matters is that the measurement is real.
  - Stage 1: page kind 0% (0/24), route 58.3% (14/24), missed process pages 0 of 14, `input_kind` 20% (1/5), panel count 80% (4/5).
  - Stage 4: component recall 0% (0/143), unit recall 0% (0/411). Precision and attribute accuracy are n/a (nothing predicted).
  - Audit: n/a (the audit flow arrives in S15). Backtest: 0 of 3 within ±5% (the stub prices nothing).
  - Replay is deterministic: `test_replay_is_deterministic` compares two runs byte for byte.
- **Bugs logged:** BUG-005 (P2, open): local E2E failed in 2 of 10 runs on this branch, against 0 of 5 on `main`. It could not be reproduced on demand and is left for the Gate 0 session (S07). The stage-4 denominator flaw was found and fixed in this session's own new code before anything shipped (see Decisions).
- **Tests run:** `make check` (lint, types, licenses, client, unit, integration and eval all green; e2e 64/66 in that run, see BUG-005), then `make e2e` alone 10 times (8 green) and on `main` 5 times (5 green), and `make check-screenshots` (24/24). Eval: no change against the baseline.
- **Follow-ups:** in the [roadmap backlog](../roadmap.md#backlog): eval each stage on labelled input (00 §10.1, with the stage 2–3 labels); S15 feeds the audit output into `Prediction.audit`; the first model-calling stage (S08) records cassettes and updates the baseline.
