# S18: Price list backend

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s18-price-list` |
| **Depends on** | S17 |
| **Status** | in review |
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
- [x] `konboro/domain/pricing/`: pure functions, `Decimal` only. `unit_cost(product, line_supplier, tenant_prefs, on_date)` by 07 §7.2.2's order; `price_status` (`ok`, `stale` after `stale_days`, `discount_based`, `missing`); brand discount as priority 2; currency conversion with the rate and its date kept for the trace.
- [x] Margin rules: the most specific rule in force (`customer_sku` > `customer` > `sku` > `family` > `brand` > `default`), `markup` / `margin` / `fixed` formulas, `margin` < 100% enforced, the line and quote margin floors as findings only.
- [x] `services/price_list.py`: create, read, update and list products with their suppliers, inside `tenant_session`; every change writes `price_history` (what, from, to, who, from which quote). One preferred supplier per product.
- [x] A price change from a quote (07 §7.2.3): "רק בהצעה הזו" vs "גם במחירון" (the product becomes `fixed` with the new price, history with the quote id). Draft quotes are not changed (they get "מחיר חדש במחירון" in S22/S23).
- [x] Bulk brand discount ("כל המוצרים של שניידר: מחירון יצרן פחות 32%") into `brand_discounts`.
- [x] Master-catalog import format (decision 1): a documented CSV layout, a loader into `catalog_items` (upsert on `(brand, sku)`, `source` = `import`), and a sample of about 20 ABB items loaded by `make seed`; demo products link to their catalog item.
- [x] Migration 0012: `supplier_preferences` (decision 3), `product_suppliers.supplier_id` nullable with at most one supplier-less row per product (decision 7), `price_history.subject` (decision 10). The `price_list` flag in `seed.FLAGS` (decision 5), and `Permission.PRICE_LIST_READ` / `PRICE_LIST_WRITE` / `QUOTES_WRITE`.
- [x] FX: seeded USD and EUR rates in `fx_rates`; the latest rate on or before the quote date, at most 7 days old, else `fx_rate_missing` (decision 4).
- [x] Manual-entry sanity checks (10 §8) as pure functions, their result kept in `products.sanity` and returned as warnings.
- [x] API: `/price-list` routes (products, suppliers, brand discounts, margin rules, supplier preferences) with `require(Permission.X)` and `require_flag("price_list")`. Money as strings in JSON. `make gen-client`.
- [x] `POST /quotes/{id}/lines/{line_id}/price` with `scope` `quote` | `catalog` (decision 8): refuses a `sent` version (409), recomputes the line's amounts with `domain/totals.py`, writes a `price_changed` correction event.

### Frontend
- None (S19).

### Unit tests
- [x] 100% branch coverage of `domain/pricing/` (07 §10.1), enforced in `make test-unit`.
- [x] The cost order, `stale`, brand discount, the identical-product rule (NURSERY-1's 3X20A gets no price from 3X16A or 3X25A), each formula with `Decimal`, rule priority and validity dates.

### Integration tests
- [x] The price-list API across two tenants (RLS), history rows, one preferred supplier, a price change from a quote with each choice.
- [x] `supplier_preferences` gets a row in `tests/integration/factory.py`.
- [x] The catalog loader against the DB (idempotent rerun), the flag off answers 404, and the line price endpoint on the NURSERY-1 fixture (both scopes, a sent version refused).

### UI tests (Playwright)
- None (S19).

### Eval (pipeline sessions)
- [x] `make eval` replay unchanged (no stage changes).

### Docs
- [x] `docs/db-schema.md` for any migration; 07 for any rule settled here.

## Acceptance criteria

- [x] Every 07 §7.2.2 cost case and every 07 §7.3 priority case has a test; pricing code at 100% branch coverage.
- [x] No float anywhere in pricing code or its JSON (a test checks the API's money fields are strings).
- [x] A product's history shows every change with who, when and from which quote.

## Out of scope

- The price list screen and the product editor (S19).
- Stage 5 matching against the price list (S20) and stage 7's line pricing (S22).
- Supplier price-list upload parsing beyond the master-catalog format (later).

## Open questions

Answered at kickoff; see "Decisions made".

1. The master catalog's import format: which columns, and is a sample of one brand enough until B3 arrives?
2. `stale_days`: keep 90 by default, per tenant setting? (Already `tenant_settings.stale_days`, default 90, since S02.)
3. The brand or family preferred supplier (07 §7.2.2 item 3): stored in tenant settings, or a table of its own?
4. Currency rates: where do they come from locally, a fixed table in the seed?

## Outcome

Filled in at `/session-close`.

- **Done:** A tenant's price list behind an API. The pricing rules are pure `Decimal` functions in `domain/pricing/`. Which cost enters a quote follows 07 §7.2.2's order (the line's supplier, the product's preferred one, the family's, the brand's, the cheapest in force), then the brand discount, then `missing`. An expired price is skipped, a later supplier price list supersedes an older hand-typed cost, and a foreign price is converted at the latest rate up to 7 days old. The rules also give `price_status`, the most specific margin rule in force, its formula, the margin floors (which only report) and 10 §8's checks on a cost typed by hand. They and `domain/totals.py` are at 100% branch coverage, which `make test-unit` and CI now enforce.

  Migration 0012 adds `supplier_preferences`, allows a cost with no supplier, and adds `price_history.subject`. `services/price_list.py` and the `/price-list` routes (behind `price_list`) cover products with their suppliers, suppliers, brand discounts, margin rules and supplier preferences, with every change in the history: who, when and from which quote. `POST /quotes/{id}/lines/{line_id}/price` changes a line's price for the quote only, or in the price list too. The master catalog has a CSV format ([docs/catalog-import.md](../catalog-import.md)) and a loader, and `make seed` loads a 20-item ABB sample, weekly USD and EUR rates, and links the demo products to the catalog.
- **Decisions made:** (with the user at kickoff, 2026-11-02)
  1. **Master catalog format:** CSV, one row per item: `brand`, `sku`, `series`, `model_code`, `family`, `module_width`, `list_price`, `list_currency`, `status`, `replaced_by_sku`, and one `attr.<name>` column per attribute. Upsert on `(brand, sku)`, `source` = `import`. The sample until B3 is about 20 ABB items (the demo price list's products and a few more), with made-up list prices.
  2. **An expired supplier price is skipped.** A price past `valid_until` on the quote date is not in force (07 §7.2, priority 1) at any step of 07 §7.2.2's order; the lookup moves to the next supplier, then the brand discount, then `missing`.
  3. **Brand or family preferred supplier:** a tenant table `supplier_preferences` (`scope` `brand` | `family`, `key`, `supplier_id`), RLS and a composite FK to `suppliers`. Family beats brand, the margin rules' order (07 §7.3).
  4. **FX rates:** fixed USD and EUR rates seeded into the global `fx_rates` (`source` = `seed`). A quote uses the latest rate on or before its date, at most 7 days old; otherwise `fx_rate_missing` and no price. The rate and its date go into the trace.
  5. **A `price_list` flag** gates the `/price-list` routes (non-negotiable 8): off by default, on for the demo and E2E tenants, 404 when off. Removed once S19's screen is complete.
  6. **A fixed price lives in `products.fixed_price` only** (spec conflict: 07 §7.2.1 says it is stored as an `sku` rule). The rule picker treats a fixed product as the `sku`-level rule, so `customer_sku` and `customer` rules still beat it. 07 §7.2.1 is reworded in this PR.
  7. **A manual cost with no supplier:** `product_suppliers.supplier_id` becomes nullable, with at most one supplier-less row per product. A newer supplier price-list row for the product supersedes an older manual one in the lookup (07 §7.2).
  8. **The line price change has its endpoint now:** `POST /quotes/{id}/lines/{line_id}/price`, scope `quote` or `catalog`, tested on the NURSERY-1 fixture.
  9. **A margin rule's `target`** (made while building, not asked): the product's id for `sku` and `customer_sku` (a product may have no manufacturer sku), the family or the brand for those levels, empty for `customer` and `default`. 07 §7.3's table says so now.
  10. **Changes that are not to a product are logged too** (07 §12, made while building): `price_history.product_id` is nullable and `subject` names a brand discount, a margin rule or a supplier preference. A changed margin rule gets the next `version`.
  11. **`price_date` doesn't limit "in force"** (made while building): only `valid_until` does (decision 2). A price dated after the quote date still applies, so a cost typed today prices a draft dated yesterday; `price_date` only ages a price (`stale`).
  12. **The line price route is behind `review_screen`**, like `GET /quotes/{id}`; the `catalog` scope writes the price list whatever `price_list` says. For `catalog` the line's override is cleared (it now has the price list's price), so a later price-list change can still tag it in a draft (07 §7.2.3).
  13. **The last `default` margin rule can't be deleted** (409 `default_rule_required`): without it a line with a cost has no price (07 §8 `no_margin_rule`).
- **Eval / metrics:** `make eval` replay: no change against the baseline (no stage changed).
- **Verification:** `make check` under Node 22 (the shell defaults to Node 20, where Vitest's workers don't start). Lint, licenses, secrets, the client check, unit tests (789 backend with pricing at 100% branch coverage, 201 Vitest), integration (536), eval (no change) and E2E (131 passed, 71 skipped) all passed. `check-screenshots` timed out on 2 dark review shots, then on 5 in a rerun, with no pixel difference. All 7 passed alone: BUG-038's load flake, at load average 18–27.
- **Bugs logged:** BUG-039 (P2, fixed): the demo price list's families were symbol classes, so rules by family would never meet a drawing's component. The bug log's two tables also had their separator row in the wrong place and didn't render; fixed.
- **Follow-ups:** in the roadmap backlog:
  - Undo of a line's price change, including the price-list change (09 §7.14), with the review screen's editing (S23).
  - A product's delete or archive, and the prototype's "a margin rule needs a supplier" check, for S19's editor.
  - 10 §8's similar-products check without a catalog link.
  - A real source of exchange rates before the pilot.

  Draft quotes' "מחיר חדש במחירון" and the floors as findings stay with stage 7 (S22).
