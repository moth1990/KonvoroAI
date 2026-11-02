# S16: Audit screen

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s16-audit-screen` |
| **Depends on** | S15 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#17](https://github.com/moth1990/KonvoroAI/pull/17) |

## Goal

A factory uploads a drawing with the quote it already made, follows the run, and lands on the audit's results: the headline, the KPIs, the differences with their evidence on the drawing, a "נכון / לא נכון" decision on each one, the matched lines, and "צור הצעה מתוקנת", which opens the corrected quote on the review screen. Everything on S15's API, behind `quote_audit`, and E2E-tested on 26-993.

## References

- Specs:
  - 11 §7 (the results screen: headline, quote lines with status, the "חסר בהצעה" group, the drawing, the decision with its four reasons, "צור הצעה מתוקנת" and "הורד דוח"), §8 (the corrected quote opens on the review screen), §5.4 (confidence < 0.6 in a "לבדוק" group; `not_a_difference`), §5.5 (two numbers: priced value at risk and items without a price; `qty_over` apart), §6 (the output and its S15 decisions: `lines`, `to_check`, `not_differences`, the reject reasons), §1 principles.
  - 09 §5 (layout, phone from 860px), §6.5 (the drawing pane), §7.11 (toast and undo).
  - 13 §3 (a flag that is off answers 404), §4.6 (`quote_audit`).
  - 01 §5.6 (an audit drawing can stop for page confirmation like any upload).
- Prototype: `prototype/konboro-app.html` 1066–1096 (`vAudit`), 521–528 (`AUDIT` mock), 722 and 747 (home's "בדיקת הצעה קיימת" button and omissions card), 476 (the audit in recent work), 692 (rail item). No prototype screen for the audit upload; the new-quote flow (754–869) is the nearest.
- Golden: 26-993 (quote 10271; the factory confirmed QG2 short at 1,250 ₪, TC-G1/TC-G2 and MS1–MS3 missing without a price; the CT test terminals are not a difference). The pipeline's own output finds 1 of the 3 today (BUG-031).
- Earlier sessions: S04 (home card, `/audit` placeholder), S05/S08/S14 (new-quote pick, run, confirm and BOM mapping steps), S09/S11 (review layout, `DrawingPane`, `Viewer`, toast and undo), S15 (the audit API, the stand-in model's `quote_table`, backlog items "what the home card counts as an omission" and "the audit's progress for the screen").

## Tasks

### Backend
- [x] Progress for an audit drawing: `GET /drawings/{id}/progress` lists stages 1–4 and the audit step (stage 8), stages 5–7 left out (backlog item from S15).
- [x] The drawing side of the audit for the screen: the audit drawing's pages (viewer pyramid, size, kind) and the boxes of every evidence instance, on `GET /audits/{id}` or a sibling route.
- [x] Home card count: shown `missing_in_quote` and `qty_short` differences (decision 3, `services/home.py`).
- [x] A seeded 26-993 audit fixture for E2E and fidelity (decision 2): `make fixture-audit` (`eval/audit_fixture.py`) runs 26-993 and quote 10271 as an audit through stages 1–4 and the audit step on replay cassettes and writes `devtools/fixtures/audit_993.json` and `audit_993_pages/` (title block and the front view's factory label blanked: they name people and the factory); `fixtures/audit_993.py` seeds it under fresh ids (a fixed audit id for the three E2E audit tenants), for `make seed` and the E2E seed.
- [x] `GET /audits/{id}` also carries the drawing's file name and number, and each line's matched designators.
- [x] `make gen-client`.

### Frontend
- [x] Route `/audit` (the upload steps, decision 4) and `/audit/:auditId` (results), behind `quote_audit`; off, the placeholder stays.
- [x] Audit upload: pick (drawing + existing quote), run (stages 1–4 + audit), page confirmation and BOM mapping reused from the new-quote flow, then the results.
- [x] Results: header cards (drawing, quote, "בדיקה חדשה"), KPIs, headline (11 §7), differences table with chips, money and designators, the "לבדוק" group, "לא הבדל" rows, matched lines with "מכסה כמה מכשירים".
- [x] Decision per difference: "נכון, זה הבדל" / "לא נכון" with a reason (כלול במחיר אחר · הלקוח מספק · טעות של המערכת · אחר), undo through the toast.
- [x] Evidence on the drawing: "הצג בשרטוט" on a difference opens the drawing pane with its instances on every page they are on (decision 1). `DrawingPane` now takes pages and an overlay function instead of a quote, and can hide the panel veils.
- [x] "צור הצעה מתוקנת" → `POST /audits/{id}/corrected-quote` → `/review/:quoteId`.
- [x] Home: the omissions card opens `/audit/:auditId`; the chat-home route for "בדוק הצעה" stays `/audit`. Recent work lists quotes only: audits there are in the backlog.
- [x] CSS ported from the prototype into `theme/app.css` (`.kpis`, `.kpi`, `.diff-row`, `.chip`…), phone layout from 860px.

### Unit tests
- [x] Vitest: the headline text, KPI numbers, grouping (shown / לבדוק / not a difference), chips per type, money formatting ("אין מחיר דומה"), the decision state machine.
- [x] pytest: progress rows for an audit drawing; the evidence boxes; the home count.

### Integration tests
- [x] Progress of an audit drawing through the API; the audit's pages and boxes, another tenant's 404, flag off 404 on any new route; the fixture seeds idempotently.

### UI tests (Playwright)
- [x] `e2e/audit.spec.ts`, desktop and mobile: 26-993 results (headline, KPIs, rows), confirm and reject with a reason, undo, show on drawing, the corrected quote opens on review; an upload through the stand-in model (drawing + spreadsheet quote) reaches its results; flag off keeps the placeholder.
- [x] Home → audit links.
- [x] Prototype-fidelity report for `#audit`, the evidence dialog and the new-audit pick step (`e2e/fidelity/capture.ts`)
- [x] Reviewed and accepted by the user; the 12 shots added to `visual.spec.ts` (`audit-results`, `audit-evidence`, `audit-new`)

### Eval (pipeline sessions)
- [x] Not a pipeline session. `make eval` (replay): no change against the baseline.

### Docs
- [x] Spec 11 §7 updated with decisions 1 and 4; 11 §6 with decision 3.
- [x] CLAUDE.md prototype map ("Built so far"), `make seed` and `make fixture-audit`; no schema change, so `docs/db-schema.md` stays.
- [x] Roadmap backlog: the two S15 items for S16 resolved; added "הורד דוח", audits in recent work, the summary counting the ones to check.

## Acceptance criteria

- [x] On the 26-993 fixture the screen shows the audit's own numbers: lines matched, omissions and units, value at risk with "+" when items have no price, not-a-difference count, every difference with its designators and pages.
- [x] A decision persists across a reload; a rejection cannot be sent without a reason; undo restores the previous status.
- [x] "צור הצעה מתוקנת" opens the review screen on the corrected quote, with the confirmed differences' lines; asked again, the same quote.
- [x] A fresh audit uploaded through the app reaches its results screen on desktop and mobile with the stand-in model.
- [x] RTL throughout, numbers and designators in `dir="ltr"`, no horizontal scroll at 375px.
- [x] `quote_audit` off: `/audit` stays the placeholder and the API answers 404.

## Out of scope

- "הורד דוח" (11 §7): decision 1; a report export goes to the backlog, next to `export_doc`.
- The learning loop (11 §9), the price list in the audit's money (S20), a model for lines code can't sign: backlog from S15.
- Fixing what stages 3–4 lose on 26-993 (BUG-031): S17.

## Open questions

All four were answered at kickoff; see "Decisions made" under Outcome.

1. **Layout: spec or prototype?** 11 §7 says the results are the review screen in an "audit" mode: quote lines on the right with a status, a "חסר בהצעה" group above them, the drawing on the left, a decision per difference, and "הורד דוח". The prototype's `vAudit` is a single column: header cards, KPIs, a differences table and a matched-lines table, no drawing, no decisions, no download.
2. **The 26-993 fixture: the pipeline's output or the golden labels?** The pipeline's replayed output finds QG2 only (BUG-031); the labels find all three omissions, as the prototype shows.
3. **What counts as an omission** (home card and the KPI): `missing_in_quote` only (today's home card), or also short quantities (the prototype counts QG2 among 3)?
4. **The audit upload and `/audit` with no id.** No prototype screen: reuse the new-quote steps with a second file, and what `/audit` shows when audits already exist.

## Outcome

Filled in at `/session-close`.

- **Done:** The audit's screen, on S15's API, behind `quote_audit`. `/audit` takes a drawing and the existing quote and runs them through the new-quote screen's run, confirmation and BOM-mapping steps (5 rows: stages 1–4 and the audit step), then opens `/audit/:auditId`: the drawing and quote cards, 11 §7's headline, the prototype's four KPIs, the differences with their chips, money, tags and pages, a decision on each ("נכון, זה הבדל" / "לא נכון" with one of four reasons, undone from the toast or "שנה"), the "לבדוק" group, the matched lines, "הצג בשרטוט" in the review screen's drawing pane, and "צור הצעה מתוקנת" to the review screen. The API gained the audit drawing's progress rows, its pages, each difference's boxes, each line's tags, and the drawing's file name and number; the home card counts short quantities as omissions. The 26-993 audit is a seeded fixture written from a replay run (`make fixture-audit`), in the demo tenant and three E2E tenants.
- **Decisions made:**
  1. **Layout: the prototype, with the spec's actions in its style** (user, at kickoff; spec vs prototype). The results screen is `vAudit`'s single column: header cards, KPIs, the differences table and the matched lines. From 11 §7 it adds a decision per difference ("נכון, זה הבדל" / "לא נכון" with a reason), the "לבדוק" group (< 0.6) and "הצג בשרטוט", which opens the evidence in the review screen's drawing pane. No "הורד דוח" in this session. 11 §7 is updated.
  2. **The 26-993 fixture is the pipeline's own output on replay** (user, at kickoff). It shows what the product finds today (BUG-031), not the golden labels; the fidelity report's numbers differ from the prototype's, and that is listed as a deliberate difference.
  3. **An omission is a shown `missing_in_quote` or `qty_short`** (user, at kickoff; S15 backlog item). The home card and the audit's KPI count both, as the prototype counts 10271's 3 omissions; units come from the shown differences (decision 5).
  4. **The audit upload reuses the new-quote steps** (user, at kickoff; no prototype screen). `/audit` is a pick step with the drawing and the existing quote, then the new-quote run, page-confirmation and BOM-mapping steps for stages 1–4 and the audit, then `/audit/:auditId`. Home's omissions card links to `/audit/:auditId`; recent work lists quotes only (backlog).
  5. **The screen counts from the shown differences** (in session). S15's `summary.missing_items` and `missing_items_without_price` include the differences below 0.6, while `value_at_risk` and `over_charged` don't. The KPIs, the headline and the run step's "N הבדלים" count only the differences shown (≥ 0.6); money still comes from the server's sums, never added up in the browser. The summary's own counts are in the backlog.
  6. **Anything below 0.6 goes to "לבדוק", whatever its type** (in session). 26-993's SG comes out as a not-a-difference at 0.49 (BUG-031): shown as auxiliary material it would hide a missed changeover.
  7. **The fixture carries no person or factory name** (in session, as NURSERY-1's). The generator keeps only the title block's drawing number, panel, date and revision, renames the files as the prototype does, and blanks the pages' title-block strip and the front view's factory label (name and phone numbers). Neither uploaded file is stored.
  8. **On the phone the difference's sentence is hidden** (in session, from the fidelity review). The table is six columns; the sentence made each row a column of single words, and the columns already say the same.
  9. **Screenshots accepted** (user, at close): the audit's results, its evidence dialog and the new-audit pick step, light and dark, desktop and mobile, are `visual.spec.ts` baselines.
- **Eval / metrics:** not a pipeline session. `make eval` (replay): no change against the baseline. On the fixture, the screen shows what the pipeline finds on 26-993: 13 of 17 lines matched, 2 omissions (QG2 short at ₪1,250, an untagged CT with no price), 6 to check, 1 not a difference.
- **Bugs logged:** BUG-034 (fixed: the new audit shots, run first, starved the review screenshots under emulation; they now run last). The other failure on the way, `test_e2e_seed.py` not knowing the new E2E tenants, was this session's own and fixed before close.
- **Follow-ups:** in the roadmap backlog: "הורד דוח" for an audit; audits in home's recent work; the audit summary counting the ones to check. Still open from S15: BUG-031 (stages 3–4 on 26-993) for S17.
