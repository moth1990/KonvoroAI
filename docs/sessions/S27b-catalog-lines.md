# S27b: Quote lines from the catalog, one line per product

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s27b-catalog-lines` |
| **Depends on** | S27 (and S22, S23, S23b, S24) |
| **Status** | in progress |
| **PR** | (link) |

## Goal

With `catalog_lines` on, every product line in a quote points to a product the app knows (a master catalog item, or a factory product made in "מוצר חדש"), and a product appears once per panel: components that resolve to the same product are one line, with their quantities added and their tags together. A component with no product is a line waiting for a decision: it has its family, an alert, and up to 3 nearest products with their difference ("20A במקום 16A"), no price, and the quote can't be sent while one is left. The user picks the nearest product, another one, "מוצר חדש" (a product in the app's own format, with the family's attributes, saved for the factory and offered to the master catalog through the approval queue), or "אין כאן רכיב". The flag off leaves the app as it is today. The session also brings in the 15 products the user prepared from 25/886 and 2240-P-001 (`backend/konboro/db/catalog/common.csv`), and fixes four names the app writes wrong today.

## References

- Specs:
  - 05 §1 (principles 2 and 3: never invent a SKU, never change an electrical value without approval), §4.4 (attribute schemas), §5.6 (candidate query, relaxation, ranking), §5.7, §5.9 (alternatives with their difference), §5.9.1 (kits and accessories as child lines), §6.2, §7 (statuses), §8 (`no_catalog_match`, `catalog_gap`, `high_unmatched_ratio`), S20 decisions.
  - 04 §5.8 (stage 4's merge: identical instances in one panel are one component; what is not merged), §6.3.
  - 06 (the rule pack as data; S21 decision 14, findings grouped per cause).
  - 07 §6.2 (the line, the description of a line with no catalog item, BUG-071), §7.1 (lines by panel, one chapter per panel), §7.2 (nearby prices only as a hint), §7.2.1 (the product record), §7.5 (final colour), §8, S22 decisions 5 (`line_key`, what a rerun keeps) and 8 (kit parts), S23 decisions.
  - 09 §6.3 (row, title of a missing or unmatched line), §6.4 (line detail, missing line, unmatched line), §7.2–7.8, §7.12 (send, "שלח בכל זאת"), §7.13, §10 (correction events), S23b decisions 1–4 and 8.
  - 10 §5.4 (a product not in the catalog is saved for the factory and is a candidate for the master), §9.2, §11 (it goes to the master without price, supplier or the factory's name).
  - 13 §2, §3 (rule 6: the eval runs both states of a flag that moves the pipeline), §4.9 (`approval_queue`).
  - 00 §9, §14.2 (only an explicit approval in the queue changes the shared layer).
  - 03 (the symbol library: `time_switch`), 04 §5.1 (the spelling grammar: `trip_unit`).
- Prototype: `prototype/konboro-app.html`
  - 409–460 (`makeLines`: one line per product, with `qty`, `des[]` and a joined `note`; F18's line with no product has `price:null` and `hint` "קרובים במחירון: 3X16A ₪185 · 3X25A ₪195").
  - 872–1004 (`vReview`: the rows, the "אין מחיר" chip, the line detail).
  - The waiting line's decisions and the "מוצר חדש" form have no prototype screen (as S23b decision 1).
- Golden: every drawing through `make eval`, with `catalog_lines` off and on (13 §3 rule 6).
- Earlier sessions and the planning conversation:
  - S20 (stage 5), S22 (stage 7, `line_key`), S23 (review actions, `pipeline/pricing/edits.py`), S23b (product picker, stage 5 for one line in code), S24 (approval queue, `konboro_promote`).
  - The design and the user's decisions: `/Users/mothanaa/.claude/plans/users-mothanaa-downloads-pdf-soft-fox.md` (2026-11-06).
  - The product list: `backend/konboro/db/catalog/common.csv` (15 products, no prices) and the review workbook `boq/common-products.xlsx` (74 products of 25/886, 2240-P-001 and 25/823, what went in and why the rest didn't; kept out of git).
  - BUG-084 (one product, two lines) is fixed by the merge.

## Design

1. **A product line points to a product.** `component`, `manual` and kit lines carry a `catalog_item_id` or a factory `product_id`. Labor, a service from the notes and consumables are not product lines and stay as they are. Derived items (enclosure, rails, busbars, terminals, labels) stay as stage 7's rules make them.
2. **A line waiting for a decision.** A component stage 5 leaves with no SKU (`unmatched`, `conflict`, `ambiguous` with no SKU), and a stage-4 `missing` row, is a waiting line: red, no price, counted at the top of the screen ("N מוצרים חדשים בשרטוט"). Sending is refused while one is left; red lines of other causes keep "שלח בכל זאת" (09 §7.12).
3. **The alert.** A stage 6 rule, `PRODUCT_NOT_IN_CATALOG`, grouped as one finding with every waiting line of the panel (S21 decision 14).
4. **The nearest products.** A new search in stage 5, in code, only when the candidate query finds nothing: same family and class, ranked by the attributes that differ, weighted (poles, current, curve, kA, residual mA, RCD type, then brand and series by the factory's preferences). A product with another pole count may be suggested, after every product with the drawing's poles (decision 6). Up to 3, each with its difference in 05 §5.9's wording. It is a suggestion, never a choice (05 §1): the match stays `unmatched`. No suggestion when the current or the poles were not read (05 §5.5; the user picks the value, as today). The suggested products' prices are shown as a hint only (07 §7.2).
5. **The decisions.** "זה המוצר" (one of the suggestions), "מוצר אחר…" (the picker, filtered to the line's family), "מוצר חדש", "אין כאן רכיב". Each is a correction event with undo. Choosing a product whose values differ from the drawing's records the change as approved by the user (05 §1 principle 3).
6. **"מוצר חדש".** A form opened from the line: the family is fixed, the attributes are the family's schema (`association/schemas.py`), filled from the drawing's values and editable, then brand, series, model and SKU. The name is not typed: it is `text.describe` of those values, shown as the user fills the form. It is saved as a factory product with its attributes (`products.attributes`, new), so stage 5 finds it on the next drawing; with a brand and a SKU it is also a `catalog_item` candidate in the approval queue, with its attributes in the payload. Only an approval puts it in the master catalog (00 §9). Required: the family's required attributes (current and poles where the schema has them), brand and model; the SKU is optional, and without it the product stays the factory's (decision 8).
7. **One line per product in a panel.** Stage 7 merges the lines of components that resolve to the same product in the same panel: quantities added, designators and boxes joined, circuit notes joined. The key becomes the product's: `p:{panel}:{catalog_item_id}`, or `p:{panel}:prd:{product_id}`. A rerun moves what the user set on a `c:` line to the product's line through its components. A waiting line stays one line per component until it is decided; deciding it on a product that already has a line joins that line. A kit part priced as included stays under its device; any other occurrence of the product joins its line. A manual line of a product already in the panel adds to its quantity. An edit on a merged line applies to the whole line, or to the designators the user picks in the line detail: those move to the other product's line (a split), and undo brings them back (decision 7).
8. **The product list.** `catalog.load_sample` loads `common.csv` after `sample.csv`, so it is in `make seed`, E2E and the eval. `sample.csv` doesn't change.
9. **The names.**
   - "שעון שבת" and "שעון אסטרונומי" are two classes of `time_switch`, each with its name (today both are "שעון שבת / שעון פיקוד"). DWA1 is astronomical, D1 PLUS a Shabbat clock.
   - A contactor's utilization category is an attribute, `utilization` (`AC-1` / `AC-3`, default `AC-3`), and `text.describe` writes it (today "(AC-3)" is fixed after the current). ESB25-30N-06 is `AC-1`: "מגען ABB ESB25 3P 25A (AC-1) סליל 230V".
   - The grammar's `trip_unit` reads "LS/I", as the catalog writes it.
   - No U+200F in the DIN rail's name (`pricing/load.py`) or in `text.py`.

## Tasks

### Specs (first: the line key and the product record are contracts)
- [ ] 05: the nearest-products search (§5.9 or a new §5.10), a suggestion is not a choice, `nearest[]` in §6.2's output
- [ ] 06: `PRODUCT_NOT_IN_CATALOG`
- [ ] 07 §7.1, §6.2: one line per product per panel, waiting lines, `line_key` `p:` (and S22 decision 5)
- [ ] 09 §6.3, §6.4, §7.8, §7.12: the waiting line, its decisions, "מוצר חדש", send refused while one is left
- [ ] 10 §5.4, §9.2: a factory product with attributes, its name in the app's format
- [ ] 13: `catalog_lines` (what it does, depends on nothing, removed when on for everyone)
- [ ] 03, 04, 07: the clock classes, `utilization`, "LS/I"

### Backend
- [ ] Migration: `products.attributes` (jsonb), the `catalog_lines` flag; `docs/db-schema.md`
- [ ] Contracts: `nearest` on a match (`contracts/matching.py`), a line's `pending` reason (`contracts/pricing.py`); `tests/unit/test_contracts.py` pins
- [ ] Stage 5: the nearest search (`pipeline/matching/query.py`, `match.py`); factory products with attributes as candidates (`pipeline/matching/catalog.py`)
- [ ] Stage 7: the merge by product per panel and the `p:` key (`pipeline/pricing/lines.py`, `engine.py`), the rerun moving `c:` state to `p:` (`run.py`, `load.py`), edits on merged lines (`edits.py`, `stored.py`)
- [ ] Stage 6: `PRODUCT_NOT_IN_CATALOG` in `validation/rules.json` and `checks.py`
- [ ] Review: decide a waiting line (nearest, picker, new product, delete), join on decide, undo (`services/review.py`, `review_picker.py`); a manual line of a product already there adds quantity
- [ ] New product: `services/price_list.py` creates it with attributes and the standard name; `services/knowledge.py` puts its attributes in the candidate's payload (whitelist), `konboro_promote` writes them
- [ ] Send refused while a waiting line is left (`services/quote_versions.py`), behind the flag
- [ ] Quote API: waiting lines, their nearest products with the difference and the price hint, the count (`services/quotes.py`); `make gen-client`
- [ ] Flag gate on every new route and every path that changes behaviour
- [ ] `common.csv` loaded by `catalog.load_sample` (`db/catalog/__init__.py`)
- [ ] Names: the clock classes (`detection/library.py`, `matching/text.py` `LINE_NAMES`), `utilization` (`association/schemas.py`, `text.py`, `sample.csv`'s contactors, `common.csv`'s ESB25), "LS/I" (`association/grammar.json`), U+200F (`pricing/load.py`, `text.py`)

### Frontend
- [ ] The waiting line: its chip, the count at the top, the nearest products with the difference and the price hint, keys 1–3 (`screens/review/LineDetail.tsx`, `model.ts`)
- [ ] "מוצר אחר…" on a waiting component line too, filtered to the family (`ProductPicker.tsx`: pass `family`)
- [ ] The "מוצר חדש" form: fixed family, the schema's attributes, brand, series, model, SKU, the name as it is built
- [ ] Merged lines: every designator in the sub line, the joined notes; in the line detail, pick designators for a change of product (the split)
- [ ] Send: the summary says why it is refused while a waiting line is left
- [ ] Everything behind `catalog_lines` from the server's flags

### Unit tests
- [ ] Two components resolving to one product in one panel are one line with the quantities added; in two panels, two lines
- [ ] A kit part priced as included doesn't join the direct line; one that isn't does
- [ ] The nearest search: up to 3 with their difference, weighted order, nothing when the current or the poles are missing, the match stays `unmatched`
- [ ] `PRODUCT_NOT_IN_CATALOG` fires once per panel with its lines
- [ ] `text.describe`: the two clocks, `utilization`, no U+200F/U+200E in any catalog item's description (`sample.csv` and `common.csv`)
- [ ] The grammar reads "LS/I"
- [ ] `common.csv` parses, has no price, no (brand, SKU) also in `sample.csv`
- [ ] With the flag off, stage 7's lines are today's (the existing tests pass unchanged)

### Integration tests
- [ ] A drawing with a product not in the catalog: the waiting line, the finding, the nearest products, send refused
- [ ] Each decision, its event and its undo; deciding on a product that has a line joins it; undo splits it again
- [ ] "מוצר חדש": the product with its attributes and the standard name, the candidate with the attributes; stage 5 finds it on the next drawing; an approval promotes it with its attributes
- [ ] A rerun of a draft keeps a deleted line, a typed price and a manual line across the `c:` → `p:` change
- [ ] The flag off answers 404 on the new routes, and the quote is today's

### UI tests (Playwright)
- [ ] Desktop and mobile: a waiting line, choosing a nearest product, "מוצר חדש" end to end, "אין כאן רכיב", send refused then allowed
- [ ] Desktop and mobile: a merged line shows every designator
- [ ] Prototype-fidelity screenshots of the waiting line and the form reviewed by the user (no prototype screen: as S23b)

### Eval (pipeline sessions)
- [ ] `make eval` with `catalog_lines` off and on; the line counts' drop, `common.csv` and the names explained; the baseline accepted once

### Docs
- [ ] `docs/catalog-import.md`: `common.csv`, why it is apart from the sample
- [ ] `docs/db-schema.md`: `products.attributes`, `line_key` `p:`
- [ ] CLAUDE.md: what S27b built
- [ ] `docs/bugs.md`: BUG-084 fixed

## Acceptance criteria

- [ ] With `catalog_lines` on, no golden quote has two lines of the same product in one panel (checked in code over every eval drawing).
- [ ] With `catalog_lines` on, every product line has a `catalog_item_id` or a `product_id`, or is a waiting line.
- [ ] A quote with a waiting line can't be sent; with none left it can.
- [ ] A product made in "מוצר חדש" is matched by stage 5 on the next drawing that has it.
- [ ] No value the user didn't approve changes: a nearest product is never priced or chosen on its own.
- [ ] With the flag off, the eval's metrics move only by `common.csv` and the names.
- [ ] `make check` passes.

## Out of scope

- Derived items' "not found" (an enclosure that doesn't fit stays a red derived line, as today).
- Stage 3 typing the astronomical clock as a time relay (BUG-082): this session names the class, the detector's prompt is BUG-082's live re-record.
- The products the user's list left out (XT1C or XT1N, XT2 125A and 40A, CTs 630/5A and 160/5A, F202 10mA, the SPDs, the meters with no model): they reach a quote as waiting lines, and the user decides there.
- A factory product's delete or archive (backlog, S18).

## Open questions

None open. Answered 2026-11-06: decisions 6–9 below.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
  1. **One line per product in each panel** (the user, 2026-11-06). The quote keeps a chapter per panel (07 §7.1); inside a panel a product appears once.
  2. **No price before the decision** (the user). A waiting line has no price and isn't in the total; the nearest products' prices are a hint; the quote can't be sent while one is left.
  3. **A new product is the factory's, and a candidate** (the user). Usable at once in the factory's quotes and by stage 5; it reaches the master catalog only through an approval in the queue (00 §9, 10 §1).
  4. **Its own session before Gate 2** (the user): S27b, after S27.
  5. **The product list and the name fixes in this session** (the user): `common.csv`, and the clocks, AC-1, "LS/I" and U+200F, so the list's products reach a quote with the right name.
  6. **A nearest product may have other poles, ranked last** (the user). Every product with the drawing's pole count comes first.
  7. **A split by designators** (the user). On a merged line, a change of product can apply to the designators the user picks; they move to the other product's line, and undo brings them back.
  8. **"מוצר חדש" requires the family's attributes, a brand and a model** (the user). The SKU is optional: without it the product stays the factory's and doesn't reach the approval queue.
  9. **One flag, `catalog_lines`** (the user). Off by default, on for the demo tenant; the eval runs both states (13 §3 rule 6).
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
