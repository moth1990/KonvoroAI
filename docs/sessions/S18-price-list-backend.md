# S18: Price list backend

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s18-price-list` |
| **Depends on** | S17 |
| **Status** | todo |
| **PR** | (link) |

## Goal

A tenant's price list is real behind an API: products with several suppliers, the cost that goes into a quote (the line's supplier, then the product's preferred one, then the brand's or family's, then the cheapest in force), margin rules by priority, fixed sale prices, brand discounts, history, consumables and a cabinet's "includes". Stage 7 (S22) and the price list screen (S19) build on it.

## References

- Specs: 07 §7.2 (cost lookup order, `price_status`, identical product only, manual entry, brand discount), §7.2.1 (product record, `sale_mode`), §7.2.2 (several suppliers, which cost enters the quote), §7.2.3 (a price change from a quote, what other quotes do), §7.3 (margin rules, formulas, priority, margin floor), §10.1 (100% branch coverage for pricing code); 10 §9.2 (a record from manual entry, `sanity`).
- Data model: [docs/db-schema.md §6.2](../db-schema.md#62-price-list-07-721-73). The tables exist since S02 (`products`, `suppliers`, `product_suppliers`, `price_history`, `brand_discounts`, `margin_rules`).
- Prototype: `prototype/konboro-app.html` lines 484–511 (`SUP`, `CATALOG`: the demo price list's fields and values, already in `make seed`).
- External: B3, the master catalog of 3–5 brands (open). Until then, a small sample seed.

## Tasks

### Backend
- [ ] `konboro/domain/pricing/`: pure functions, `Decimal` only. `unit_cost(product, line_supplier, tenant_prefs, on_date)` by 07 §7.2.2's order; `price_status` (`ok`, `stale` after `stale_days`, `discount_based`, `missing`); brand discount as priority 2; currency conversion with the rate and its date kept for the trace.
- [ ] Margin rules: the most specific rule in force (`customer_sku` > `customer` > `sku` > `family` > `brand` > `default`), `markup` / `margin` / `fixed` formulas, `margin` < 100% enforced, the line and quote margin floors as findings only.
- [ ] `services/price_list.py`: create, read, update and list products with their suppliers, inside `tenant_session`; every change writes `price_history` (what, from, to, who, from which quote). One preferred supplier per product.
- [ ] A price change from a quote (07 §7.2.3): "רק בהצעה הזו" vs "גם במחירון" (the product becomes `fixed` with the new price, history with the quote id). Draft quotes are not changed (they get "מחיר חדש במחירון" in S22/S23).
- [ ] Bulk brand discount ("כל המוצרים של שניידר: מחירון יצרן פחות 32%") into `brand_discounts`.
- [ ] Master-catalog import format: a documented file layout and a loader into the shared layer, with a small sample seed (B3).
- [ ] API: `/price-list` routes with `require(Permission.X)` and a new flag if the route is new to users (13). Money as strings in JSON. `make gen-client`.

### Frontend
- None (S19).

### Unit tests
- [ ] 100% branch coverage of `domain/pricing/` (07 §10.1), enforced in `make test-unit`.
- [ ] The cost order, `stale`, brand discount, the identical-product rule (NURSERY-1's 3X20A gets no price from 3X16A or 3X25A), each formula with `Decimal`, rule priority and validity dates.

### Integration tests
- [ ] The price-list API across two tenants (RLS), history rows, one preferred supplier, a price change from a quote with each choice.
- [ ] A new tenant table, if any, gets a row in `tests/integration/factory.py`.

### UI tests (Playwright)
- None (S19).

### Eval (pipeline sessions)
- [ ] `make eval` replay unchanged (no stage changes).

### Docs
- [ ] `docs/db-schema.md` for any migration; 07 for any rule settled here.

## Acceptance criteria

- [ ] Every 07 §7.2.2 cost case and every 07 §7.3 priority case has a test; pricing code at 100% branch coverage.
- [ ] No float anywhere in pricing code or its JSON (a test checks the API's money fields are strings).
- [ ] A product's history shows every change with who, when and from which quote.

## Out of scope

- The price list screen and the product editor (S19).
- Stage 5 matching against the price list (S20) and stage 7's line pricing (S22).
- Supplier price-list upload parsing beyond the master-catalog format (later).

## Open questions

1. The master catalog's import format: which columns, and is a sample of one brand enough until B3 arrives?
2. `stale_days`: keep 90 by default, per tenant setting?
3. The brand or family preferred supplier (07 §7.2.2 item 3): stored in tenant settings, or a table of its own?
4. Currency rates: where do they come from locally, a fixed table in the seed?

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
