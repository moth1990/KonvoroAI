# S06: Golden eval harness

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s06-golden-eval` |
| **Depends on** | S05 |
| **Status** | todo |
| **PR** | |

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
- [ ] `eval/canonical.py`: canonical schema. For each drawing:
  - `pages[{no, kind, route}]` and `input_kind`;
  - `panels[{name, components[{family, attributes, designators, qty}]}]`;
  - `audit{matched, differences[{type, item, designators, value_at_risk}]}`;
  - `quote_total`.
- [ ] `eval/normalizers/`: one per label shape. Map the known quirks, e.g. `single_line` → `single_line_diagram`. Unit-test each normalizer against its file: product counts, unit counts, and the `summary` checksums where present.
- [ ] `eval/metrics/`:
  - stage 1: page kind accuracy, route accuracy, missed process pages, `input_kind`;
  - stage 4: component precision and recall per panel, by family + designators, with attribute accuracy for `current_a` and poles, and quantity accuracy;
  - audit: difference precision and recall against the factory-confirmed `differences[]`;
  - pricing backtest: total within ±5%.

  Stages without labels yet (2, 3) report `n/a`.
- [ ] `eval/run.py`:
  - runs the real pipeline in-process (no queue) per drawing on a throwaway tenant;
  - collects stage outputs and scores them;
  - writes `eval/reports/<ts>.json` and `.md`.
- [ ] `eval/compare.py`: compares a report with a baseline (the last `main` artifact, or a committed `eval/baseline.json`). Prints the deltas. Exits non-zero on any regression unless `--allow-regression`.

### Backend (`konboro_llm`)
- [ ] `CassetteProvider`:
  - key = hash of (stage, model, system, user_text, image hashes, schema);
  - `replay` mode: a missing key raises a clear error;
  - `record` mode: calls the wrapped provider and stores the JSON in `eval/cassettes/<stage>/<hash>.json`.
- [ ] `EVAL_MODE=replay|live`, `EVAL_RECORD=1`.
- [ ] Cost logging: every live call writes to `llm_calls` (stage, tenant, model, tokens, latency, attempts), not just to `logging`.

### Unit tests
- [ ] Normalizers (5 files), every metric function on hand-made small cases, and the comparison logic.
- [ ] `CassetteProvider`: record, then replay gives an identical result; a missing key raises.

### Integration tests
- [ ] `make eval` in replay mode completes on all 5 drawings and produces both report files.

### CI
- [ ] An `eval` job runs on PRs touching `backend/konboro/pipeline`, `contracts`, `konboro_llm`, `eval` or `golden`. It posts the markdown summary as a PR comment (or job summary) and fails on regression.

## Acceptance criteria

- [ ] Replay is deterministic: two runs give byte-identical metrics.
- [ ] The normalizers reproduce the documented counts. NEVIS-1: 21 components. 6199-2-50: 84 products and 184 units. 26-993: 22 products and 47 units. NURSERY-1: 13 products. BOM-HW-1: 19 products.
- [ ] The report is readable on its own: per-drawing and per-stage tables, plus totals by input kind.

## Out of scope

- Span and box labeling tooling for stages 2–3. Planned as part of S10/S12 or the backlog, once labels are needed.
- Injected-error sets (06 §10.1, 11 §10). Added in S15 and S21.

## Open questions

- Should the baseline be committed (`eval/baseline.json`), or taken from the last `main` CI artifact? Default: committed, updated deliberately in PRs.

## Outcome

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
