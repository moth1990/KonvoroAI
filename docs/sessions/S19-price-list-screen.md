# S19: Price list screen

| | |
| --- | --- |
| **Track** | R |
| **Branch** | `s19-price-list-screen` |
| **Depends on** | S18 |
| **Status** | todo |
| **PR** | (link) |

## Goal

A factory sees and edits its price list in the app, as in the prototype: the products table with search and filters, the product editor with several suppliers, a fixed price or a margin rule, consumables, and the bulk brand discount. A manually typed price goes through the sanity checks before it is saved.

## References

- Specs: 07 §7.2.1 (the product record the editor shows), §7.2.2 (several suppliers, the preferred one), §7.2.3 (what changes elsewhere when the price list changes); 10 §8 (sanity checks on a typed price: against the maker's list price, against similar products, a jump from the previous price; never against other tenants).
- Prototype: `prototype/konboro-app.html` lines 1098–1208 (`vPrices`, `openEditor`: `pricef`, `prod`, `prod-new`, `cons`, `ed-addsup`, `ed-rmsup`, `ed-save`, the search "חיפוש: מוצר, מק"ט, ספק", "הנחת מותג גורפת", "כשלאותו מוצר יש כמה ספקים"); mock data 484–511 (`CATALOG`, `SUP`).
- S18's API. The shell's `#prices` entry from S04.

## Tasks

### Backend
- [ ] The 10 §8 sanity checks as a pure function and an endpoint the editor calls before saving: maker's list price (when the catalog has one), similar products of the same family, brand and current (3× or more), a jump of over 50% from the previous price. Warnings only; the user can save anyway.
- [ ] Anything the screen needs that S18's API lacks (filters, counts), with `make gen-client`.

### Frontend
- [ ] `/prices` route behind its flag: the prototype's CSS moved to `frontend/src/theme/app.css` with the same class names; MUI for behaviour only.
- [ ] Products table: search by product, SKU and supplier; filters (`pricef`); sale mode, source ("הצעה 10271"), suppliers; RTL, `.mono` for SKUs and money.
- [ ] Product editor modal (`openEditor`): name, SKU, brand, family, unit, sale mode with a fixed price or the rule, suppliers added and removed with one preferred, consumable, includes; the sanity warnings beside the field; save writes history.
- [ ] "הנחת מותג גורפת": the bulk brand discount.
- [ ] Phone layout from 860px (`MOBILE_MAX_PX`).

### Unit tests
- [ ] The sanity checks (each rule and its threshold, no cross-tenant comparison).
- [ ] Vitest for the screen's model: filtering, search, editor validation, money as strings.

### Integration tests
- [ ] The sanity endpoint and any new route, across two tenants.

### UI tests (Playwright)
- [ ] Desktop and mobile projects: search, filter, open a product, add and remove a supplier, change the preferred one, save, see the history; a typed price that trips a sanity warning; the bulk discount.
- [ ] `visual.spec.ts` shots for the price list and the editor, light and dark.
- [ ] Prototype-fidelity report reviewed by the user.

### Docs
- [ ] CLAUDE.md's prototype map and "Built so far" line.

## Acceptance criteria

- [ ] Every prototype action on the price list (1098–1208) works against the real API.
- [ ] A typed price that trips a 10 §8 check shows its warning, and saving anyway is recorded.
- [ ] Fidelity screenshots accepted by the user.

## Out of scope

- "Update the price list too?" from the review screen (S23).
- Supplier price-list upload (later).
- Stage 5's matching against the price list (S20).

## Open questions

1. The flag key for the price list screen (13).
2. The prototype's filter chips: which filters ship (sale mode, missing supplier, consumables, brand)?
3. Does "includes" get its own editor field in this session, or a read-only list?

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
