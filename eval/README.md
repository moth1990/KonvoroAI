# Golden-set evaluation

`make eval` runs the pipeline on every drawing in `golden/`, scores each stage against the labels, writes a report, and compares it with `baseline.json`. The method is in [dev-strategy.md §6](../docs/dev-strategy.md#6-golden-evaluation). The decisions are in [S06](../docs/sessions/S06-golden-eval.md).

## Running it

| Command | What it does |
| --- | --- |
| `make eval` | Replay mode: the model's answers come from `cassettes/`. Deterministic and free. CI runs it |
| `EVAL_MODE=live make eval` | Real Claude (`ANTHROPIC_API_KEY`) |
| `EVAL_MODE=live EVAL_RECORD=1 make eval` | Real Claude, saving every answer as a cassette. Commit the new cassettes |
| `EVAL_MODE=live EVAL_RECORD=missing make eval` | Replays what is recorded and sends only the calls with no cassette to Claude, saving them. For a new stage or prompt, so the stages before it keep their recorded answers |
| `EVAL_MAX_USD=20` (with `EVAL_MODE=live`) | Stops the run once its calls cost this much at list prices. The call that crosses the line finishes; the next one fails the run |
| `make eval-baseline` | Make this run's metrics the new `baseline.json`, after a change that moves a score on purpose |

Every run needs `make up`. It recreates the `konboro_eval` database, uploads each drawing to one throwaway tenant, and runs the 7 stages in-process, without the queue (`Pipeline.run_inline`).

A missing cassette fails the run with "no cassette for stage …". This happens when a prompt, a schema, an input or a model changed. To fix it, record again in live mode.

## Layout

| Path | What |
| --- | --- |
| `canonical.py` | One shape for every label file and for the pipeline's output |
| `normalizers/` | One normalizer per label shape. The shape is recognised from the file's keys. Known quirks (`single_line`, missing routes, designator ranges) are mapped in `common.py` |
| `predict.py` | Stage contracts → the canonical shape |
| `metrics/` | Stage 1 (01 §10), stage 4 (04 §10), audit (11 §10), pricing backtest (07 §10.2). Stages 2–3 are n/a until span and box labels exist |
| `report.py`, `compare.py` | The JSON and markdown report, and the comparison with the baseline |
| `cassettes/<stage>/<hash>.json` | Recorded model answers (`konboro_llm.providers.CassetteProvider`) |
| `reports/` | `<timestamp>.json` and `.md` (git-ignored) |

## Reading the scores

- **`n/a`** means there was nothing to score: no label for it, or nothing produced yet (the audit flow). It is never 0%.
- **Stage 4 matching.** On factory drawings, components match by family + designators. With no designators (designer plans, BOM-only), they match by family + `current_a` + poles, with quantities added up. So merged and unmerged rows score the same. `current_a` and poles accuracy are measured on designator matches only.
- **Backtest.** The real quotes left out items the factory confirmed. The report shows the confirmed value at risk next to each total.
- **Regressions.** A metric that is lower than the baseline, or that had a value and now is n/a, fails `make eval` and the CI job. For "lower is better" metrics (`missed_process_pages`, `backtest_deviation`), a higher value fails.

## Adding a drawing

Put it in `golden/<id>/` with a `README.md`, `labels.json` and, if there is one, `actual_quote.json`. If the labels use a known shape, nothing else is needed. Otherwise add a normalizer to `normalizers/shapes.py` and a case to `normalizer_for`. Then run `make eval-baseline` and commit the new baseline with the drawing.
