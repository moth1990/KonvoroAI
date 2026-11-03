# S19: Price list screen

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s19-price-list-screen` |
| **Depends on** | S18 |
| **Status** | in review |
| **PR** | (link) |

## Goal

A factory sees and edits its price list in the app, as in the prototype: the products table with search and filters, the product editor with several suppliers, a fixed price or a margin rule, consumables, and the bulk brand discount. A manually typed price goes through the sanity checks before it is saved.

## References

- Specs: 07 §7.2.1 (the product record the editor shows), §7.2.2 (several suppliers, the preferred one), §7.2.3 (what changes elsewhere when the price list changes); 10 §8 (sanity checks on a typed price: against the maker's list price, against similar products, a jump from the previous price; never against other tenants).
- Prototype: `prototype/konboro-app.html` lines 1098–1208 (`vPrices`, `openEditor`: `pricef`, `prod`, `prod-new`, `cons`, `ed-addsup`, `ed-rmsup`, `ed-save`, the search "חיפוש: מוצר, מק"ט, ספק", "הנחת מותג גורפת", "כשלאותו מוצר יש כמה ספקים"); mock data 484–511 (`CATALOG`, `SUP`).
- S18's API. The shell's `#prices` entry from S04.

## Tasks

### Backend
- [x] The 10 §8 sanity checks as a pure function (S18: `domain/pricing/sanity.py`, run on save into `products.sanity`).
- [x] `POST /price-list/products/check-cost`: the same checks on a cost that hasn't been saved yet (product id or family, brand and catalog item; cost, currency), for the editor's on-blur warning (decision 4). Warnings only; nothing is written.
- [x] The open drafts that use a product (`ProductOut.used_in_drafts`: the quote's name and each line's designators), for the editor's "בשימוש בטיוטה הפתוחה" note.
- [x] Anything else the screen needs that S18's API lacks (the source quote's name and the last change, `GET /price-list/brands`; the E2E price-list tenants and `seed_price_list`), the brand list for the bulk discount), with `make gen-client`.

### Frontend
- [x] `/prices` route behind its flag: the prototype's CSS moved to `frontend/src/theme/app.css` with the same class names; MUI for behaviour only.
- [x] Products table: search by product, SKU and supplier; filters (`pricef`); sale mode, source ("הצעה 10271"), suppliers; RTL, `.mono` for SKUs and money.
- [x] Product editor modal (`openEditor`): name, SKU, brand, family, unit, sale mode with a fixed price or the rule, suppliers added and removed with one preferred, consumable, includes; the sanity warnings beside the field; save writes history.
- [x] "הנחת מותג גורפת": the bulk brand discount.
- [x] Phone layout from 860px (`MOBILE_MAX_PX`).

### Unit tests
- [x] The sanity checks (each rule and its threshold: S18's `tests/unit/test_pricing.py`; no cross-tenant comparison: the integration test below).
- [x] Vitest for the screen's model: filtering, search, editor validation, money as strings.

### Integration tests
- [x] The sanity endpoint and any new route, across two tenants (`test_api_price_list_screen.py`), and the E2E price-list tenants (`test_e2e_seed.py`).

### UI tests (Playwright)
- [x] Desktop and mobile projects (`e2e/prices.spec.ts`): search, filter, open a product, add and remove a supplier, change the preferred one, save, see the history; a typed price that trips a sanity warning; the bulk discount.
- [x] `visual.spec.ts` shots for the price list and the editor, light and dark (baselines written after the fidelity review; `make check-screenshots`: 66 passed).
- [x] Prototype-fidelity report reviewed by the user (accepted 2026-11-03).

### Docs
- [x] CLAUDE.md's prototype map and "Built so far" line.

## Acceptance criteria

- [x] Every prototype action on the price list (1098–1208) works against the real API.
- [x] A typed price that trips a 10 §8 check shows its warning, and saving anyway is recorded.
- [x] Fidelity screenshots accepted by the user (2026-11-03).

## Out of scope

- "Update the price list too?" from the review screen (S23).
- Supplier price-list upload (later).
- Stage 5's matching against the price list (S20).

## Open questions

Answered at kickoff; see "Decisions made" below.

## Outcome

Filled in at `/session-close`.

- **Done:** The price list at `/prices`, behind `price_list`, as in the prototype (`vPrices`, `openEditor`, lines 1098–1208). The four cards, the table with search (name, sku, brand, supplier name and sku) and the four chips, the consumable switch, the note on several suppliers, and the bulk brand discount. The product editor: name, skus, brand, family, unit, suppliers added and removed with one preferred, a fixed price or the margin rule, "כלול בארון" on a cabinet, consumable, the open drafts that use the product, and its history. A typed cost is checked when the field loses focus (10 §8) and the warning sits under its row; saving anyway is kept in `products.sanity`.

  Backend: `POST /price-list/products/check-cost` runs 10 §8's checks on a cost that is not saved (the row's previous cost, or the product's cost today and its date; nothing is written). `ProductOut` adds `used_in_drafts` (on GET of one product), `entered_in_quote_name` and `last_changed_at`. `GET /price-list/brands` lists the catalog brands with a list price and the brands already discounted. The demo price list is `seed_price_list`, and four E2E tenants use it (desktop, mobile, shots, and one with the flag off). The prototype's CSS for the cards, the switch, the supplier table and clickable rows is in `app.css`.
- **Decisions made:** (with the user at kickoff, 2026-11-02)
  1. **A margin-rule product with no supplier is allowed** (spec over prototype). 07 §7.2.1 allows it: no cost means no price. The editor saves it with a hint ("בלי ספק אין עלות, ולכן אין מחיר"), and it shows under "בלי עלות". The prototype's refusal is not ported; the spec stays.
  2. **"כלול בארון" is five checkboxes**: `busbar`, `n`, `pe`, `panels`, `doors`, the keys of the tenant's `enclosure_includes_default`, saved in `products.includes` so stage 7's rule (07 §7.4) can read them. Shown for cabinet products; a new cabinet starts from the tenant's defaults. The prototype's free-text field is not ported.
  3. **No product delete or archive this session.** The prototype has no control for it; it goes to the roadmap backlog.
  4. **10 §8's warnings show on blur, before saving.** A check endpoint runs when a cost field loses focus; the warning sits under the field, and Save always stays available. Saving anyway is recorded in `products.sanity` (`warning_shown`).
  5. **The flag is S18's `price_list`** (spec 13 has no key for the screen): it gates the `/prices` route (off, it is the placeholder; the rail keeps its entry, as for `quote_audit`) and the API, and is removed once the screen is accepted.
  6. **The filter chips are the prototype's four**: הכול, כמה ספקים, בלי עלות, רווח נמוך (below the tenant's `min_line_margin`). S18's `filter` query already serves them.
  7. **The table filters in memory** (made while building): the screen loads the whole price list once and searches and filters it on every key, as the prototype does, and the cards count the whole list. S18's `q` and `filter` query parameters stay for other callers.
  8. **Families are a list with Hebrew names** (made while building): the attribute schemas' codes (BUG-039), which margin rules and supplier preferences match on, named in `screens/prices/model.ts`. 'מא"ז', 'מפסק' and 'מגן מנוע' are one family, `circuit_breaker`, shown as 'מא"ז / מפסק'. The prototype has a free-text field.
  9. **A consumable with no sale price is saved on the rule** (made while building): `fixed` needs its price (07 §7.2.1, and the database checks it), and a consumable is never a line of its own.
  10. **A cost typed in the editor is a manual entry** (made while building): a new row, or a saved row whose cost changed, is sent as `manual_entry` dated today, so the save runs 10 §8 too; an untouched row keeps its source and dates.
  11. **The fidelity report was accepted by the user** (2026-11-03), with the differences in its notes: the price before 07 §7.6's rounding (₪22.50, not ₪23), money with agorot, the family names, the source column without quote numbers, the discount field empty until one is saved, rows in family order.
- **Eval / metrics:** `make eval` replay: no change against the baseline (no stage changed).
- **Verification:** see the PR. Unit tests (801 backend, pricing at 100% branch coverage; 224 Vitest, 23 of them the screen's model), integration (554, `test_api_price_list_screen.py` new), E2E (147 passed; `prices.spec.ts`, 8 tests on both projects) and `check-screenshots` (66 passed standalone, the 8 new price-list baselines among them). In the final `make check`, lint, licenses, secrets, the client check, unit, integration, eval and E2E passed; `check-screenshots` timed out on two dark review shots waiting for the viewer, BUG-038's flake, and both passed when rerun alone.
- **Bugs logged:** BUG-045 (P3, fixed): the app's `.modal.wide` missed the prototype's second, 640px rule.
- **Follow-ups:** in the roadmap backlog:
  - A product's delete or archive (decision 3).
  - The editor's check has no catalog link on a new product: link by exact brand and manufacturer sku on save.
  - The save toast's count of draft lines marked "מחיר חדש", with S22's tag.
  - The sale price after 07 §7.6's rounding, with S22.

  - Remove `price_list` (decision 5): the screen is accepted, so the flag, its 404 tests and the flag-off E2E tenant can go. Not done in this PR, to keep it to the screen; scheduled for Gate 2 (S28).
