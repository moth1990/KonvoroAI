# S22: Stage 7, pricing and versions

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s22-pricing-versions` |
| **Depends on** | S21 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#25](https://github.com/moth1990/KonvoroAI/pull/25) |

## Goal

Stage 7 is real. In code only, with no model, it turns stage 5's matches, stage 4's missing rows and stage 6's caps into a priced quote version. Each line gets a cost from the factory's price list (07 §7.2), a sale price from the most specific margin rule (§7.3), and the factory's rounding (§7.6). It adds derived items and labor by rules stored as data (§7.4), gives each row its final colour as the worst of all sources with every reason (§7.5), and works out panel and quote totals with discount and VAT. A version is a frozen snapshot of what it was priced from. Once sent it never changes, and a recalculation makes a new version with a diff (§7.7). The golden backtest compares our total before VAT with the factory's real quote (§10.2).

## References

- Specs:
  - 07, all of it: §1 (code only, every number explained, never invent a price, costs never leave, a sent quote is frozen), §4 (inputs), §7.1 (line types), §7.2 (cost order, identical product only, the price list built from use, FX, `price_status`), 7.2.1–7.2.3 (product record, several suppliers, a price change from a quote and what happens to drafts), §7.3 (rule levels, formulas, floors), §7.4 (derived items: enclosure by modules or by the data page or notes' dimensions, `includes`, consumables, supply scope, labor, `is_derived`, a deleted derived line stays deleted), §7.5 (final colour), §7.6 (order of computation, rounding, totals), §7.7 (versions, when a new one is made), §6 (contract), §7 (decision rules), §8 (issues), §9 (performance), §10 (acceptance, backtest), §11 (learning loop: proposals only), §12 (security).
  - 05 §5.9.1 (kits and accessories, `parent_line_id`, "included"), §6 (the match: `status`, `has_cost_price`, `auxiliary`).
  - 06 §6.5 (`row_status_caps`, panel-level issues), §6 (issue fields).
  - 04 §5.1.2 (`supply_scope`: `other_location`, `prepare_only`, `by_others`), §6.3 (`missing[]`, `context_elements`).
  - 01 §5.5 (data page with the enclosure's dimensions), §5.5.1 (per-panel notes: dimensions, IP, spare 30%, "heat calculation").
  - 09 §6.3 (line row, groups, chips), §7.13–7.15 (typing a cost, a price change, a supplier switch: S23's UI), §11 (revision).
  - 10 §5.1 (the default markup rule from the onboarding question), §8 (sanity of a typed cost).
  - 11 §9 (prices from an audited quote, `quote_import`).
  - 00 §6 (ids, colours: only stage 7 sets a row's final colour), §10.1.
- Prototype: lines 582–619 (`status`, `totals`, `prefSup`, `catSale`, `lineCost`, `margin`, `profit`, `coverage`). Also lines 878–906 (row and detail price cells: "כלול", "אין מחיר", "מחיר חדש במחירון", "רווח נמוך"), 978 (the "פריטים נלווים" footnote), 955–963 (version, draft/sent, lock).
- Golden: the backtest on the three drawings with a real quote: NURSERY-1 (10285), 26-993 (10271), NEVIS-1 (10288). `actual_quote.json`: totals before VAT, bundles in the enclosure line, consumables (26-993's CT test terminals), "no labor or terminal lines, probably in the prices" (NEVIS-1).
- Earlier sessions:
  - S18: `domain/pricing/` (`cost`, `margin`, `fx`, `sanity`), `domain/totals.py`, `services/price_list.py`, `price_history`. S19: the price list screen.
  - S09: `services/quotes.write_lines` and the read model; the NURSERY-1 fixture writes lines through it.
  - S20: the stage-5 match per component, kits and accessories (`catalog_kits`, `catalog_accessories`), `MatchingResult.auxiliary`.
  - S21: stage 6 writes findings on the drawing; the stage-7 stub attaches them to version 1 (S21 decisions 1, 12). `row_status_caps`.
  - Backlog for S22: terminals as derived material (S12, S20 decision 3); a rerun of stages 2–7 under existing lines (S13); the done step's product count (S05, S14); the editor's toast count of "מחיר חדש" (S19); the price list's rounded sale price (S19); review pricing details (S09).

## Tasks

### Backend
- [x] Replace `pipeline/stages/s7_pricing.py` (`run(ctx) -> QuoteVersionResult`), its parts in `pipeline/pricing/` (`book`, `lines`, `derived` + `derived.json`, `status`, `engine`, `diff`, `load`, `run`).
- [x] 7.1 Line building: a `component` line per match with a SKU, an unpriced red `component` line per match without one, a `missing` line per `missing[]` row, kit add-ons and accessories under their parent (`parent_line_id`, "included" at 0.00), `line_group` (feed, outputs, control, enclosure) and panel chapters. `supply_scope`: `other_location` in a separate "מחוץ ללוח" group outside the enclosure count, `prepare_only` / `by_others` as notes, not priced.
- [x] 7.2 Cost through `domain/pricing/cost.py`: the product by `catalog_item_id` or `manufacturer_sku`, identical product only; `price_status`; `missing_cost`, `stale_price`, `fx_rate_missing`, `empty_price_list`.
- [x] 7.3 Sale price through `domain/pricing/margin.py`: the quote's customer, the product's `sale_mode`; line floor (`below_margin_floor`) and quote floor (`quote_below_margin_floor`); `no_margin_rule`.
- [x] 7.6 Rounding: a pure `domain/pricing/rounding.py` (`agora`, `shekel`, `five`, `ten`), the unit price only; VAT to the agora; no rounding of subtotals. 100% branch coverage.
- [x] 7.4 Derived items as data: a starter rule pack (`pipeline/pricing/derived.json`, seeded into each tenant's `derived_item_rules`; version). Enclosure (modules × qty + spare, or the data page's or notes' dimensions and IP; the smallest that fits; `includes`; `enclosure_not_found` as a red row), DIN rails, busbars, terminals (stage 5's `auxiliary`), labels, consumables as a percentage, "heat calculation" as a yellow service row. A tenant can turn a rule off. Each derived line points to its rule and its components. `derived_rule_failed`.
- [x] 7.4 Labor: hours per family and an hourly rate from `tenant_settings.labor`, a `labor` margin rule (`family` = `labor`), one line per panel with the breakdown.
- [x] 7.5 Final colour: the worst of confidence, match status, stage 6's caps, price status and line type; derived lines by price and query status; manual lines green unless unpriced; every reason kept in `status_reasons`; `issue_ids`. Pricing issues written as `findings` (`source` = `pricing`) next to stage 6's.
- [x] 7.6 Totals through `domain/totals.py`: per panel and per quote, customer discount, VAT by date, `line_counts`, `unpriced_count`.
- [x] 7.7 Versions (`services/quote_versions.py`): the snapshot (price-list rows, margin rules and versions, derived rules version, FX, VAT id); `send` locks a version (the existing trigger); `recalculate` makes a new version from the current price list with `diff_from_previous` (lines added, removed, changed, by how much and why); a deleted derived line stays deleted; an override is kept and never overwritten by rules.
- [x] A rerun of stages 2–7 on a drawing with a draft: replace the draft's lines in place, keeping what the user did (decision below). A sent version is never touched; a rerun after sending makes a new version.
- [x] The done step's product count from stage 7's lines (backlog, S05/S14).

### Frontend
- [x] Nothing new on screen (decision 4). The review screen renders stage 7's lines, colours and `status_reasons` chips from the quote API; the "מחוץ ללוח" group label for `outside` (07 §7.4); the done step says "מוצר אחד" (BUG-048).

### Unit tests
- [x] Rounding: each mode, half-up at the edge, VAT to the agora, subtotals not rounded (100% branch coverage).
- [x] Line building: each line type, kits and accessories under the parent, supply scope, groups.
- [x] Cost and sale on stage 7's path: identical product only (NURSERY-1's 3X20A stays empty), stale, discount-based, FX missing, fixed product beats a family rule, customer rule beats a fixed price, floors only tag.
- [x] Derived rules: enclosure by modules with spare, by dimensions, from the notes' spare percentage, none fits → red, `includes` suppresses a busbar line, consumables as a percentage, a disabled rule, a failing rule → `derived_rule_failed`, terminals from `auxiliary`, labor hours and rate.
- [x] Final colour: each source on its own, the worst wins, all reasons kept, derived and manual lines.
- [x] Reproducibility: the same input and snapshot give the same quote to the agora (07 §10.1).
- [x] Diff between two versions: added, removed, changed price, changed qty, the reason.
- [x] Contract snapshot and the 07 §6.1 example (`test_contracts.py`).

### Integration tests
- [x] Stage 7 through the queue on a golden drawing with the stand-in model: lines and totals in the DB, the result in S3 under the tenant, findings attached, no `llm_calls` row for stage 7.
- [x] Price lists, rules and settings read under RLS; another tenant's price never applies (07 §12).
- [x] Send locks the version (the trigger rejects a change); recalculate makes version 2 with a diff; a sent version is untouched by a rerun.
- [x] A rerun of stages 2–7 replaces the draft's lines with no FK error (backlog S13), keeping a deleted derived line deleted.
- [x] The review API returns the real lines, colours and reasons for a pipeline quote; the progress endpoint's product count.
- [x] Performance (07 §9): 150 lines priced in under 1 s; a full recalculation with the diff in under 2 s.
- [x] Derived rules seeded per tenant; `make seed` safe to rerun.

### UI tests (Playwright)
- [x] Desktop and mobile: a drawing through all 7 stages opens for review with priced lines and totals (stand-in model, the E2E tenant's price list).
- [x] `make check-screenshots`: 66 of 66 passed, no baseline changed (the review shots use the NURSERY-1 fixture, not stage 7).

### Eval (pipeline sessions)
- [x] The backtest (07 §10.2) on NURSERY-1, 26-993 and NEVIS-1: total before VAT within ±5%, the derived-items-and-labor gap within ±10%, with the confirmed value at risk beside it.
- [x] `make eval` in replay twice, identical; numbers under Outcome; `make eval-baseline`.

### Docs
- [x] 07 with this session's decisions and any spec fix from the questions.
- [x] `docs/db-schema.md` (any column or table), CLAUDE.md "Stages" and "Pricing" lines (stage 7 is real), `eval/README.md`.

## Acceptance criteria

From 07 §9–10:

- [x] Arithmetic correctness on known cases (markup, margin, rounding, discount, VAT, FX): **100%**.
- [x] Reproduction: the same input and snapshot give the same quote to the agora: **100%**.
- [x] A full price trace on every priced line: **100%**.
- [x] Cost or margin in anything meant for the customer: **0**. No model call in stage 7.
- [x] 150 lines priced in **≤ 1 s** (unit, the engine with every derived rule and labor); a full recalculation with the diff in **≤ 2 s** (integration, `recalculate`). A recalculation after one line's change in **< 200 ms** is S23's, with the edit routes.
- [ ] Backtest: total before VAT within **±5%** of the factory's quote: **not met, 0 of 3** (NURSERY-1 −6.2%, NEVIS-1 −8.2%, 26-993 +45.7%). Derived items and labor within **±10%**: **2 of 3** (NURSERY-1 and NEVIS-1 exact; 26-993 200% over, BUG-035). Measured and reported per drawing, with the confirmed value at risk beside it; see Outcome. Left to stage 4–5 work and BUG-035, checked again at Gate 2 (S28, roadmap backlog).
- [x] A sent version never changes; a recalculation makes a new version with a diff.

## Out of scope

- The review screen's editing actions: typing a cost, a price change with "update the price list too?", a supplier switch, approve, delete, send and lock buttons, "open version N+1": S23. S22 gives them the services.
- The learning loop's proposals (repeated manual changes in a family, repeated derived additions or deletions, 07 §11): with the approval queue, S24.
- Labor and derived-rule settings on the settings screen: S24.
- The customer document (PDF, Excel): `export_doc`, S26.
- Quantity-tiered supplier prices, a quote in a foreign currency, VAT-exempt customers, a quote's validity date (07 §13 items 1, 4, 5, 6).

## Open questions

1. **The backtest's price list.** The eval factory has no price list (S21 decision 16), so stage 7 prices nothing and the backtest stays at 100% off. Options: (a) each drawing priced from its own real quote's prices, imported as `quote_import` fixed prices by the audit's signature, so the backtest measures our quantities, derived items and rounding against the factory's total; (b) leave one out: each drawing priced from the other two quotes, as a new factory would be; (c) both, (a) gated and (b) reported as a coverage number. The eval factory's settings follow these three quotes' factory: the enclosure includes busbars, N, PE, panels and doors; CT test terminals are consumables; no labor or terminal lines (NEVIS-1's note).
2. **Spec vs prototype: rounding.** 07 §7.6 rounds the unit price by the factory's setting (default agora), VAT to the agora, and no subtotal. The prototype rounds the sale price to a whole shekel (`catSale`, `Math.round`) and VAT and the total to whole shekels (`totals`). Proposal: the spec's rules; the demo tenant's setting is `shekel`, so the price list shows ₪23 as the prototype does (S19 backlog); VAT stays to the agora.
3. **Derived items: where enclosures come from, and which starter rules are on.** The sample catalog has no enclosures and the demo price list has one "ארון" product. Proposal: add a few enclosures to the sample catalog (modules, dimensions, IP, rows) and query it, through the factory's price list for the cost; no fit → a red "ארון: לא נמצא מתאים ל-X מודולים". Starter rules on for a new tenant: enclosure, DIN rails, busbars (off when the enclosure includes them), terminals and labels; consumables at 0% until the factory sets it; marked as awaiting the expert (B2), like S21's category A. Labor: a line only when the factory set an hourly rate.
4. **What S22 ships beyond stage 7.** The roadmap's S23 owns the review screen's actions. Proposal: versions as services only (send, recalculate with a diff, new version), with S23's routes calling them, as S21 did with the re-run. The read-only pricing details go out in S22: in the quote API and on the review row and detail ("מחיר חדש במחירון", "רווח נמוך X%", "קרובים במחירון: …", the "פריטים נלווים" footnote), the editor's toast count and the price list's rounded sale price.

## Outcome

Filled in at `/session-close`.

- **Done:** Stage 7 is real (`pipeline/pricing/`, `stages/s7_pricing.py`), in code only: lines from the matches, kits, accessories and missing rows; cost and sale price through `domain/pricing` on the identical product only; rounding (`domain/pricing/rounding.py`); derived items as rules stored as data (enclosure by the drawing's dimensions or by modules, rails, busbars, terminals, labels, consumables, a required service) and labor; the final colour as the worst source with every reason; totals with discount and VAT; grouped pricing findings; the version's snapshot. Versions as services (`services/quote_versions.py`): send and lock, recalculate with a preview and a diff, open N+1. A rerun keeps the user's deletions, price overrides and manual lines (`quote_lines.line_key`), and stage 4's rewrite no longer breaks under quote lines. The done step's product and price counts and the run step's stage-7 line. The eval's backtest on two price lists (`eval/backtest.py`). Migration 0017.
- **Decisions made:** (with who decided, and why)
  1. **Backtest on two price lists** (user, at kickoff; question 1). Gated: each drawing priced from its own real quote's prices, imported as `quote_import` fixed prices by the audit's signature, which measures quantities, derived items and rounding against the factory's total. Reported, not gated: leave one out, each drawing priced from the other two quotes, as a coverage number. The eval factory's settings follow these quotes' factory: the enclosure includes busbars, N, PE, panels and doors; CT test terminals are consumables; no labor or terminal lines.
  2. **Rounding by the spec; the demo tenant rounds to the shekel** (user, at kickoff; question 2, spec vs prototype lines 582–619). Unit price by the factory's setting (default `agora`), VAT to the agora, no subtotal rounded. The demo tenant's setting is `shekel`, so its price list shows ₪23 as the prototype does. 07 §7.6 unchanged; the prototype's whole-shekel VAT and total are not followed.
  3. **Enclosures from the catalog; the starter rules on** (user, at kickoff; question 3). A few enclosures (modules, dimensions, IP, rows) join the sample catalog and the enclosure rule queries it, the cost through the factory's price list; no fit is a red row. On for a new tenant: enclosure, DIN rails, busbars (none when the enclosure includes them), terminals, labels. Consumables at 0% until the factory sets it. Labor only with an hourly rate. The pack marks them as awaiting the expert (B2).
  4. **Versions as services only** (user, at kickoff; question 4). Send and lock, recalculate with a diff, a new version, as tested services that S23's routes and buttons call. The read-only review pricing details (new-price tag, low margin, price hints, the derived footnote), the editor's toast count and the price list's rounded price stay in the backlog for S23.
  5. **What a rerun keeps** (Claude, in session; written into 07). Every line has a stable `line_key` (`c:<component>`, `d:<panel>:<rule>`, `l:<panel>`…, migration 0017). Pricing a draft again, or a rerun of stages 2–7, keeps the lines the user deleted deleted (a derived line is not made again), a price the user set on a line, and the lines they added. A deleted line stays as a soft-deleted row, for undo, and the version's snapshot carries the deleted keys into the versions that follow.
  6. **Which version is priced** (Claude, in session; 07 §7.2.3, §7.7). A draft is priced again in place, and `preview_recalculation` shows the comparison first, writing nothing (a savepoint). After a sent version, a recalculation or a rerun makes N+1 with `diff_from_previous`. "Open version N+1" copies the sent version as it is, unpriced again. Stage 6's findings follow the current version; pricing's belong to their version and are made anew.
  7. **A fixed price is `ok`** (Claude, in session; written into 07). The price status follows the cost only when the sale price is worked out from it.
  8. **A kit's part** (Claude, in session; 05 §5.9.1). Priced on its own; "included" (0.00, green) when the device's product lists the part's SKU in `includes`.
  9. **Pricing findings grouped by cause** (Claude, in session; as S21 decision 14): one each for `missing_cost`, `stale_price`, `fx_rate_missing`, `no_margin_rule`, naming every line; one per line below the margin floor. They never change a line's colour.
  10. **The enclosure's requirements** (Claude, in session; 07 §7.4). A panel's notes block, else the drawing's data page when the drawing has one panel. The notes' `spare_space_pct` beats the rule's spare.
  11. **The contract** (Claude, in session; written into 07 §6.2): `cost_source` gets `supplier_id`, `via`, `original_cost`, `fx_date`, `list_price`, `discount_pct`; `margin_rule` takes `fixed` with `fixed_price`; `derived` gets `rule_key`, labor's `hours` and a service's `service`.
  12. **Stage 5's frequency counts sent versions only** (Claude, in session; BUG-047). Stage 7's own drafts would otherwise vote for themselves.
  13. **Derived items' catalog families** (Claude, in session): `enclosure`, `din_rail`, `busbar`, `label` join the attribute schemas (no drawing has them as components), and `terminal`'s cross-section is queried. The labelled stage-5 run now matches the golden labels' enclosures too, so `s5_labelled` counts one more signature on three drawings.
- **Eval / metrics:** `make eval` in replay, twice, identical; `make eval-baseline`. The backtest, priced from each drawing's own quote:

  | Drawing | Real quote, before VAT | Ours | Gap | Component lines priced | Derived: quote / ours | Leave one out | Lines priced |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | NURSERY-1 | 14,109 | 13,229 | −6.2% | 60% | 3,800 / 3,800 | 4,619 | 53% |
  | NEVIS-1 | 11,603 | 10,656 | −8.2% | 67% | 4,200 / 4,200 | 2,336 | 38% |
  | 26-993 | 14,022 | 20,427 | +45.7% | 71% | 4,200 / 12,600 | 1,457 | 25% |

  The ±5% target is met on none (07 §10.2's "a big gap is not always ours"): the lines with no price are the 30–40% of component lines stage 5 gave no SKU, so no price list can find them; 26-993's three panels (BUG-035) each get an enclosure. The derived items match the quote exactly where the drawing has one panel. No other metric moved, except `s5_labelled`'s model share, one more signature on three drawings (decision 13).
- **Checks:** under Node 22: lint, licenses, secrets, unit (1003, pricing at 100% branch coverage, + 227 Vitest), integration (570), eval (no change against the new baseline), E2E (151, desktop and mobile), screenshots (66 of 66, no baseline changed). `check-client` fails only until the regenerated client is committed.
- **Bugs logged:** BUG-047 (P1, stage 5's frequency counted stage 7's drafts; fixed), BUG-048 (P3, "1 מוצרים"; fixed). BUG-035 noted: it triples 26-993's enclosure.
- **Follow-ups:** in the roadmap's backlog: the backtest's unpriced lines (stage 4–5, BUG-035); version routes and buttons (S23); what a rerun keeps beyond prices and deletions (S23); pricing's learning loop (S24); labor and derived-rule settings (S24); the review pricing details, the editor's toast count and the rounded price in the price list moved to S23 (decision 4). Done and struck: terminals as derived material, a rerun of stage 4 under quote lines, the done step's product count.
