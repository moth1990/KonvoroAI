# S15: Quote audit backend

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s15-quote-audit` |
| **Depends on** | S13, S14 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#16](https://github.com/moth1990/KonvoroAI/pull/16) |

## Goal

A factory uploads a drawing with the quote it already made for it, and gets back a list of differences with evidence on both sides: what the quote leaves out, counts twice, or reads differently from the drawing, and how much money that is at the quote's own prices. The quote is read on S14's table path with its prices kept, checked arithmetically, each line signed by stage 4's grammar, and matched to the drawing's components by code. The API serves the audit, takes the user's verdict on each difference, and turns an audit into a corrected quote in the system (11 §8). On the golden set, the audit finds the differences the factory confirmed on NEVIS-1, 26-993 and NURSERY-1.

## References

- Specs:
  - 11 §1 (principles: neither side is the truth, a person decides, no made-up prices, few wrong differences), §3 (terms), §4 (inputs, quota, read like a BOM with prices kept), §5.1 (stages 1–4 only), §5.2 (read the quote: columns, sum and VAT rows out, arithmetic check, signature by the grammar, ranges "עד 4X100A", "כולל" items), §5.3 (matching rules, assignment that maximises matched components and prefers exact over range, included items), §5.4 (the 8 difference types, severity, confidence = min(component, match), < 0.6 shown apart), §5.5 (price search order, two numbers, `qty_over` apart), §6 (output), §8 (corrected quote), §11 (no customer contact details), §12.4 (one panel or the whole drawing).
  - 01 §5.8 (the BOM path the quote is read on), §4.5 (an audit counts in the quote quota unless the plan has `monthly_audit_limit`), §6.1 `quota.reason` = `audit`.
  - 00 §7.1 (`table_transcription` serves stages 1 and 11; the customer's contact details are not kept from its answer), §7.2 (closed answers, checked in code), §2 principle 9, §6 (IDs, money as strings).
  - 04 §5.1 (the spelling grammar), §6.3 (the component contract, `instance_ids` for evidence).
  - 05 §5.5.1 (an untyped "מפסק" decided by its current: the audit matches it as a breaker of either class).
  - 07 (money is `Decimal`), 13 §2–3 (a new feature behind a server-side flag).
- Prototype: none for this session's backend. The audit screen (`vAudit`, 1066–1096) and its mock `AUDIT` (521) are S16's, but suggest the API's fields: matched lines with qty, unit price and the drawing's designators; per difference "what", drawing qty, quote qty, money at risk, designators; a "not a difference" row (auxiliary material).
- Golden: NEVIS-1 (quote 10288: 12 missing — F11, C1–C5, six relays — and FP1 counted twice; 140 ₪ at risk, 11 without a price, 42 ₪ over-charged; FNV a drawing conflict the quote settles; PT100 included in the controller line), 26-993 (quote 10271: QG2 short, 1,250 ₪; TC-G1/TC-G2 and MS1–MS3 missing, no price; the CT test terminals are not a difference; lines 5 and 15 cover several devices), NURSERY-1 (quote 10285: FNV missing at 185 ₪, RNV missing with no price). All three quote PDFs are scans with no text layer.
- Earlier sessions:
  - S02: `audits` and `audit_differences` tables, `drawings.purpose` = `audit`; S03/S05: the `audit` quota counter.
  - S04: the home screen's `audit_omissions` card reads `audit_differences`.
  - S06: the eval's audit metrics (`difference_precision`, `difference_recall`, `type_agreement`), n/a until now; `eval/predict.py` sets `audit=None`.
  - S13: the grammar and `components` with instances and pages.
  - S14: the table reader (`pipeline/bom/`: sheets, mapping, `table_transcription`, row rules), BOM words (`bom/terms.py`), decision 2 (no number from a spreadsheet to a model).

## Tasks

### Backend
- [x] Upload: `POST /audits` (drawing files + one `quote` file), behind a new flag `quote_audit`; the drawing gets `purpose` = `audit`, reserves on the audit counter (the quote counter when the plan has none) and always counts once stage 1 succeeds; the quote is a `drawing_files` row with `role` = `audited_quote`, checked as any file is (no ZIP: `quote_not_one_file`), which stage 1 skips.
- [x] Reading the quote (`pipeline/audit/quote.py`): a spreadsheet through `bom/sheets` and `bom/mapping` (money columns told apart by header, else by quantity × unit = total on rows with a quantity other than 1); a picture or a scanned PDF page through `table_transcription.transcribe_quote` (decision 1); a PDF with a text layer through pdfplumber in code. Number, date and total before VAT (less a discount) to `quote_ref`; total rows are not lines; a line on two rows of a picture is joined; no customer field.
- [x] Arithmetic check: qty × unit price = line total to half an agora a unit, and the lines' sum = the subtotal, in `Decimal`; an `arithmetic` difference for each break.
- [x] Line signatures (`pipeline/audit/signature.py`): family from the BOM words (new words in `bom/terms.py`: הגנת מנוע, מנורה, מגע עזר, בקר טמפרטורה, מנתק נתיך, פסי צבירה…; the cabinet in `signature.py`, since it is no library symbol), values from stage 4's grammar, "עד" ranges, motor ranges, CT ratios, cabinet sides, "כולל" and "+" items, "N+16" as 1P+N.
- [x] Matching (`pipeline/audit/match.py`), code only: family equivalents as data, the neutral rule, positions as a set, a motor protection never a breaker and its range bounding the current, the assignment best tier first, then most values agreed.
- [x] Differences (`pipeline/audit/differences.py`): the 8 types and `not_a_difference`, severity, confidence, evidence (pages and instance ids), `suggested_line`, Hebrew messages; the attribute mismatch one value apart and before a short quantity; the double count by drawings on process pages.
- [x] Auxiliary families per tenant (decision 4): `tenant_settings.auxiliary_families`, default `{terminal}`, in `GET`/`PATCH /settings`.
- [x] Money (11 §5.5): same signature, then same family and poles (nearest current), else none (decision 5: no price-list search yet); value at risk on shown differences, missing without a price, over-charged apart; all `Decimal`.
- [x] The audit step (`pipeline/audit/step.py`): stage 8 on `konboro-audit`, after stage 4 of an audit drawing; stages 5–7 skipped; writes `audits`, `audit_quote_lines`, `audit_differences` and the `AuditResult` contract; a rerun keeps the user's decisions; a failed, cancelled or blocked drawing fails its audit.
- [x] API (`api/routes/audits.py`): `POST /audits`, `GET /audits/{id}`, `PATCH /audits/{id}/differences/{dif_id}`, `POST /audits/{id}/corrected-quote` (decision 6), each with `require(...)` and `require_flag("quote_audit")`; `make gen-client`.
- [x] Migration 0011: `audit_quote_lines` (RLS forced), the differences' new columns and checks, `drawing_files.role`, `audits.issues`, stage 8, `tenant_settings.auxiliary_families`; `docs/db-schema.md`; a row in `tests/integration/factory.py`; the `aql_` prefix.
- [x] The stand-in model answers the quote transcription (`fake_llm.quote_table`, with one wrong total on purpose).

### Frontend
- [x] None: the screen is S16. The regenerated client is committed; `tsc` passes.

### Unit tests
- [x] `tests/unit/test_audit.py`: amounts, total rows, money headers, the heading; a spreadsheet, a mapping model that sees no digit, a text table, a picture checked in code, pages joined, no customer field; arithmetic; signatures of every golden quote line; matching rules; each type on a hand-made case; prices; stage 4's components as the audit sees them.
- [x] The oracle (the golden labels as the drawing side, `actual_quote.json` as the quote): every factory-confirmed difference found and nothing else, value at risk 140 / 1,250 / 185 ₪, 12 / 6 / 2 units missing, NEVIS-1's 42 ₪ over-charged, 26-993's test terminals not a difference and its bundled lines 5 and 15 matched. The labels have no conflicting values, so `drawing_conflict` is tested on a hand-made case.
- [x] 100% branch coverage on `differences.py` (the money code).
- [x] The 11 §6 example validates as `AuditResult`; the stage-8 schema snapshot; the eval's audit metric accepts a split difference.

### Integration tests
- [x] `tests/integration/test_audit.py`: a spreadsheet quote audited with no model call (stages 5–7 skipped, 8 done, the contract in S3, the quota, RLS, another tenant's 404); decisions (a rejection needs a reason) and the corrected quote on `GET /quotes/{id}`, made once; a photographed quote (one `table_transcription` call, line boxes, the arithmetic difference); the audit counter; a ZIP quote refused with nothing kept; the flag off on every route. Settings: the auxiliary list.

### UI tests (Playwright)
- [x] None: no screen in this session (S16 adds the E2E on 26-993).

### Eval (pipeline sessions)
- [x] `eval/predict.py` maps the audit's differences (`qty_short`, `qty_over`, `possible_double_count` → `quantity_mismatch`); `eval/run.py` audits each golden quote on the run's own stages 1 and 4; the three quote pages recorded live (`EVAL_RECORD=missing`, capped); `make eval` replays; baseline updated. Numbers under Outcome.

### Docs
- [x] 11: decisions in §5.1, §5.2, §5.3, §5.4 (`not_a_difference`), §5.5, §6, §8, §10.
- [x] 00 §7.1: only the audited quote's page carries prices.
- [x] 13 §4.6: `quote_audit`. CLAUDE.md: non-negotiable 6, the pipeline paragraph, the queues, the screens line.
- [x] `docs/db-schema.md`, `eval/README.md`.

## Acceptance criteria

- [x] Oracle (golden labels as the drawing side, golden quote lines as the quote): difference recall 1.0 on the three goldens with nothing wrong shown, value at risk 140 ₪ (NEVIS-1), 1,250 ₪ (26-993), 185 ₪ (NURSERY-1). `tests/unit/test_audit.py::test_the_golden_quotes_against_their_labels`.
- [x] Pipeline (replay): `difference_precision`, `difference_recall` and `type_agreement` are no longer n/a: 87.5%, 66.7% and 100% over the three drawings. The stage 1–4 numbers of all five goldens do not change. The 80% precision target on the pipeline's own output is phase 1's exit criterion (roadmap, phase 1 "Exit"), checked at the gate (S17); today's 87.5% is above it.
- [x] No price or customer detail reaches a model outside the quote transcription (unit tests on the mapping request; the integration test of a spreadsheet quote makes no model call); the transcription answer has no customer field.
- [x] Money is `Decimal` everywhere in the audit and a string in JSON.

## Out of scope

- The audit screen, its upload flow and the "create corrected quote" button: S16.
- The learning loop (11 §9): prices into the price list, confirmed differences into the golden set, rejected ones as negative examples. S15 stores the verdicts and the reasons only.
- Labour in the value at risk (11 §12.5), an audit with no account (§12.1), a quote that is a single total (§12.3).
- A model fallback for quote lines code can't sign (decision 3): in the backlog.

## Open questions

All four were answered at kickoff; see "Decisions made" under Outcome.

1. ~~Prices from a picture of a quote?~~ Decision 1.
2. ~~Where the audit runs, and where the quote lines live?~~ Decision 2.
3. ~~Matching by code only?~~ Decision 3.
4. ~~"Not a difference" (auxiliary material)?~~ Decision 4.

## Outcome

Filled in at `/session-close`.

- **Done:** The quote audit's backend. `POST /audits` takes a drawing and the factory's own quote; the drawing runs stages 1–4 and then the audit step (stage 8, its own queue, stages 5–7 skipped). The step reads the quote (a spreadsheet or a text PDF in code, a picture or a scan through `table_transcription`'s quote mode, which copies the quote's prices), checks its arithmetic, signs each line by stage 4's grammar, matches lines to components in code, and writes the nine difference types with evidence, a suggested line and their money. The API reads the audit, takes "נכון / לא נכון" with a reason on each difference, and turns it into a corrected quote that opens on the review screen. Everything behind `quote_audit`. The eval scores the audit on the three golden quotes for the first time.
- **Decisions made:**
  1. **The audited quote's prices may be read by `table_transcription`** (user, at kickoff). In its quote mode the route copies the audited quote's own selling prices (unit price and line total) from a picture or a scanned PDF page; 00 §7.1 already lists the route for 11. Code checks every amount with the arithmetic check (11 §5.2 step 3) and keeps it as `Decimal`. Those amounts never go into any other model request, and a test enforces it; costs, margins and the price list still never reach a model. A spreadsheet's or a text-layer PDF's quote is read in code, with no number sent (S14 decision 2). CLAUDE.md non-negotiable 6 is reworded to say this.
  2. **The audit runs after stage 4** (user, at kickoff). For a drawing with `purpose` = `audit`, the coordinator sends stage 4's output to an audit step on a queue of its own instead of stage 5; stages 5–7 are skipped (11 §5.1) and the audit step marks the drawing `ready`. The quote's lines get a table of their own (`audit_quote_lines`).
  3. **Matching is code only** (user, at kickoff): the 11 §5.3 rules and a family-equivalence table as data, measured on the three goldens. A line code can't sign is an `extra_in_quote` at low confidence. A model fallback is in the backlog.
  4. **A tenant's auxiliary list** (user, at kickoff; prototype over spec). Each tenant has a list of auxiliary families, seeded with test terminals and plain terminals. A drawing component on the list with no quote line is reported in a separate `not_a_difference` group: no money, never counted as a difference. 11 §5.4 gets a line for it.
  5. **No price-list search yet** (in session). 11 §5.5's third source, the factory's price list, needs a component matched to a product (stage 5, S20). Until then a price comes from the quote itself or not at all.
  6. **The corrected quote's lines** (in session, 11 §8). Manual lines; the quote's own green with a price, red without; a suggested line yellow with a price, red without. A confirmed missing item or short quantity adds its suggested line; an over-count or double count lowers its line to the drawing's quantity; an attribute mismatch takes the drawn product's description. Made once per audit.
  7. **The eval's audit match** (in session). A shown difference is right when it shares a designator with a confirmed one, not one to one: the factory confirmed NEVIS-1's C1–C5 as one omission, and 11 §6 reports one difference per component.
- **Eval / metrics:** the three quote pages recorded live (`EVAL_RECORD=missing`, 3 `table_transcription` calls on Opus, well under the $3 cap); every line, amount and total of quotes 10271, 10288 and 10285 read exactly. Replay, on the pipeline's own components: 26-993 precision 50% (1/2), recall 33% (1/3); NEVIS-1 100% (4/4), 75% (3/4); NURSERY-1 100% (2/2), 100% (2/2); all 87.5% (7/8), 66.7% (6/9), type agreement 100%. Value at risk found: 1,250 ₪ (26-993), 140 ₪ (NEVIS-1), 185 ₪ (NURSERY-1), each the factory's figure. What is missed comes from stages 3–4: on 26-993 EMS is not detected, SG comes out as 4 terminals, MS1–MS3 as one untagged CT (found missing, but with no designator to show), and the shunt trips at 0.49; on NEVIS-1 the relays are one component at 0.50, so their omission is in "לבדוק". One audit fix came from the recording: a "פחת" line now matches an RCBO (stage 4 read 26-993's FB2 as one). Baseline updated; only the audit metrics moved.
- **Bugs logged:** BUG-031 (open, P2, for S17: stages 3–4 lose what 26-993's audit needs), BUG-032 (fixed: a new queue missing from an older ElasticMQ container).
- **Follow-ups:** in the roadmap backlog: a model for quote lines code can't sign; the price list in the audit's money (S20); the audit's learning loop (11 §9); what the home card counts as an omission (S16); the audit's progress for the screen (S16). Settings: `auxiliary_families` is in `GET`/`PATCH /settings`, with no screen yet. Not done: nothing in the task list. Not run: none of S15's code has a screen, so no Playwright test is new; `make check` runs the existing E2E and screenshots.
