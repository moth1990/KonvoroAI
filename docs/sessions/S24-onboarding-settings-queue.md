# S24: Onboarding, settings, approval queue

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s24-onboarding-settings-queue` |
| **Depends on** | S22 |
| **Status** | done |
| **PR** | [moth1990/KonvoroAI#30](https://github.com/moth1990/KonvoroAI/pull/30) |

## Goal

A new factory answers two questions and accepts the data terms before its first drawing, and gets a quote on day one with an empty price list. The owner sees and changes the factory's settings on the settings screen (flags shown read-only). The pilot engineer approves or rejects candidates for the shared layer in the approval queue, and only an explicit approval there copies a record into the global layer, stamped `pilot_engineer`, with no price, supplier, customer or factory name.

## References

- Specs:
  - 10 §1 (principles 1, 4, 5), §5.1 (question 1, markup with a live example; question 2, brands for breakers and RCDs, skippable; the data terms before the first upload), §5.2 (the first-quote banner, coverage in the header), §5.3 (the banner gives way to coverage), §5.4 (what stays with the factory and what may go to the shared layer), §9.1 (the new factory's settings), §11 (a promoted product carries no price, supplier or factory name).
  - 00 §9 (what improves from each correction; promotion: two factories, a knowledge owner, or the pilot engineer; what never moves), §14.1 (one `owner` user), §14.2 (the pilot queue: candidates are a new symbol, abbreviation, spelling pattern, catalog item or item attribute; only an explicit approval promotes; every global record keeps `pilot_engineer`, the factory, the date; what never moves even in the pilot).
  - Also cited by the above: 07 §7.3 (the `default` `markup` rule), 05 §5.4 (brand preference, priority 4), 00 §11 (the data terms), 13 §2–3 (flags resolved on the server; read-only to the owner per S03).
- Prototype: lines 1210–1226 (`vQueue`: the pilot banner, pending and handled cards, "אשר לשכבה המשותפת" / "דחה", the chips "אושר · pilot_engineer" / "נדחה · נשאר במפעל"), 1228–1251 (`vPrefs`: plan and limits, pricing, enclosure includes, defaults, flags, account), 512–519 (`QUEUE` mock data), 552 (`S.prefs`), 1506 (`qok` / `qno` toasts), 1548 (`pref`). **The prototype has no onboarding screen** (no two questions, no data terms).
- Golden: none.
- Earlier sessions: S03 (`GET/PATCH /settings`, flags read-only), S04 (shell, the queue count on the rail and home), S18–S19 (margin rules, brand discounts), S20 (`tenant_settings.matching`, brand preferences in stage 5), S22 (derived rules, `enclosure_includes_default`), S23b (`tenant_reference_crops`, products from "מוצר אחר…").
- Backlog items naming S24: matching settings on the settings screen (S20), the factory tunes an inference rule (S20), findings dismissal loop (S21), pricing's learning loop (S22), labor and derived-rule settings (S22).

## Tasks

Written at kickoff, refined as they landed.

### Backend
- [x] Flags `onboarding`, `settings_screen`, `approval_queue` (seed, spec 13 §4.7–4.9), on for the demo tenant (`seed_demo_fixtures`) and every E2E tenant but `s24-off`.
- [x] Migration 0020: `knowledge_candidates.dedupe_key` (unique per tenant and kind) and `promoted_id`; the global `spelling_patterns` (`spl_`); `catalog_items.attribute_provenance`; the NOLOGIN `konboro_promoter` and its SECURITY DEFINER `konboro_promote(candidate_id, record_id)`.
- [x] Onboarding (`services/onboarding.py`, `GET/POST /onboarding`): the markup is the `default` `markup` margin rule (created or changed, logged in `price_history`), the brands the preference per family ("אחר" and a skip set none), the terms `{version, by, at}`. `POST /drawings` and `POST /audits` answer 409 `data_terms_required` until then. `/me` has `onboarding_required`.
- [x] The counters of 10 §9.1: `first_drawing_at` at the first upload, `first_quote_sent_at`, `quotes_sent` and `price_coverage_last` at each send. `QuoteOut.first_quote` for the banner.
- [x] Settings: `default_markup` in `GET/PATCH /settings` (through the margin rule); the rest of the screen's rows already were there (S03). Flags stay out of the patch.
- [x] Approval queue (`services/knowledge.py`, `GET /knowledge-candidates`, `POST …/{id}/approve`, `…/reject`): the payload whitelist per kind, de-duplication, `propose_product` from the price list's create and update, approval and promotion in one savepoint (a refused promotion leaves it pending, 409 `global_conflict`), the product linked to its new catalog item. Permissions `knowledge.read`, `knowledge.decide`.
- [x] Seed: the prototype's six queue items (`devtools/fixtures/queue.py`) for the demo tenant; the demo tenant has accepted the terms and sent the two quotes its price list came from. E2E tenants 25–32.

### Frontend
- [x] `/welcome` (`screens/welcome/`): the two questions, the live example, the terms; every page sends a factory there until it has answered (`OnboardingGate`).
- [x] `/prefs` (`screens/prefs/`), ported from `vPrefs`: plan and limits, markup, two brand selects, enclosure includes, 30 mA, flags read-only, account.
- [x] `/queue` (`screens/queue/`), ported from `vQueue`, with line 1506's toasts; the rail and home counts refresh.
- [x] The first-quote banner on the review screen.
- [x] `make gen-client`.

### Unit tests
- [x] `tests/unit/test_knowledge.py`: every kind drops private fields, attributes too; required fields; the dedupe key; the card's title.
- [x] `tests/unit/test_onboarding.py`: markup bounds, brands from the closed list, skip and "אחר".
- [x] Vitest: `welcome/model.test.ts` (rate as a string, the example), `prefs/model.test.ts` (the 30 mA default), `queue/model.test.ts` (the source line's date).

### Integration tests
- [x] `test_onboarding.py`: the gate on both uploads, what the answers write, validation, an existing default rule changed, the flag off, the banner and the counters through send and N+1.
- [x] `test_approval_queue.py`: a product proposed once (not when in the catalog, without a SKU or brand, or again), approval with `pilot_engineer` and no price, rejection, the prototype's kinds in their tables, an attribute that fills a gap and one that would overwrite (409, stays pending), a payload that smuggles money, RLS across tenants, the function on a pending candidate and the app role's write refused, the flag off.
- [x] `test_api_settings_screen.py`: the markup as the default rule, every row round trips, flags and unknown fields refused, current and poles still refused.
- [x] The new routes pass `test_api_routes.py`; `spelling_patterns` passes the global read-only check in `test_rls.py`.

### UI tests (Playwright)
- [x] `welcome.spec.ts`: a new factory is sent to /welcome, an upload is refused, the example, the brands, the terms, on to /new; the first quote's banner after a real upload; the flags off.
- [x] `prefs.spec.ts`: plan and limits; markup, brands, a toggle and 30 mA saved across a reload; a bad markup not saved; flags disabled.
- [x] `queue.spec.ts`: approve one, reject one, the chips, the counts after a reload.
- [x] Desktop and mobile projects (16 tests)
- [x] Prototype-fidelity report reviewed by the user (settings and queue; onboarding has no prototype; accepted 2026-11-04)

### Eval (pipeline sessions)
- [x] Not a pipeline session. `make eval` ran: no change against the baseline.

### Docs
- [x] Spec 13 §4.7–4.9: the three flags.
- [x] `docs/db-schema.md`: the promoter role, the new columns and table, `spl_`.
- [x] CLAUDE.md "Built so far", the prototype map and the services paragraph.

## Acceptance criteria

- [x] A tenant with no terms accepted cannot upload a drawing, and is taken to the onboarding screen; answering takes two questions plus the terms (10 §5.1). `test_onboarding.py`, `welcome.spec.ts`.
- [x] The markup answer is the factory's `default` `markup` margin rule (07 §7.3). `test_onboarding.py`, `test_api_settings_screen.py`. That stage 7 prices from the `default` rule is S22's (`pipeline/pricing/` tests); S24 has no test that prices a quote after answering.
- [x] A skipped brand question sets no preference (10 §5.1). `test_onboarding.py`, `tests/unit/test_onboarding.py`.
- [x] Only an explicit approval in the queue writes the global layer; every record written carries `pilot_engineer`, the tenant and the date (00 §14.2). `test_approval_queue.py`.
- [x] No promoted record carries a price, a cost, a supplier, a customer, a project or a designer name (10 §11, 00 §9). `test_approval_queue.py` (including a payload that smuggles money past the service), `tests/unit/test_knowledge.py`.
- [x] Flags are visible on the settings screen and cannot be changed by the owner (S03). `prefs.spec.ts`, `test_api_settings_screen.py`.
- [x] RLS: no tenant reads or decides another tenant's candidates. `test_approval_queue.py`, `test_rls.py`.

## Out of scope

- Inviting users and roles (00 §14.1, not in 1.0).
- The accelerators of 10 §6 beyond what exists (price-list upload is later; the brand discount is S19/S23b).
- Onboarding metrics dashboards and the funnel (10 §7.2–7.3): only the counters are written.
- Re-review of `pilot_engineer` records when a second factory joins (00 §14.2): later, with a second tenant.
- Signup and tenant creation (S29, Cognito).

## Open questions

All six answered at kickoff (Outcome → Decisions made).

1. Where does the onboarding screen go, given the prototype has none?
2. Brands: the onboarding question asks breakers and RCDs separately with "אחר" and skip (10 §5.1); the settings screen has one select for both (prototype line 1239). Which wins on the settings screen?
3. Which corrections feed the queue in S24? Nothing writes tenant abbreviations or spellings yet; factory products with no catalog item exist. And are the tenant-level proposals the backlog assigns to S24 (dismissal loop, pricing loop, inference tuning) in this session?
4. How does the promotion write the global layer, given the app connects only as `konboro_app`?
5. Flag keys for the three features.
6. Is the first-quote banner (10 §5.2) in this session?

## Outcome

- **Done:** a new factory's entry (`/welcome`, the two questions and the data terms, the upload gate, the counters of 10 §9.1, the first-quote banner), the settings screen (ported from `vPrefs`, two brand selects, flags read-only), and the pilot approval queue (ported from `vQueue`; candidates from factory products; approval promoted through the SECURITY DEFINER `konboro_promote`, migration 0020). Three flags, `onboarding`, `settings_screen`, `approval_queue` (spec 13 §4.7–4.9). Every task above is done; the tenant-level proposals were moved out at kickoff (decision 3).
- **Decisions made:** (2026-11-04, user, at kickoff)
  1. **Onboarding placement:** a full page (`/welcome`) on first login, in the prototype's card classes, shown until the data terms are accepted; the brand question can be skipped. The server refuses an upload until the terms are accepted (10 §5.1). The prototype has no screen for it.
  2. **Brands on the settings screen, spec vs prototype:** **the spec wins.** Two selects, breakers and RCDs, each with "no preference", the same `brand_preferences` per family that onboarding writes. The prototype's single select (line 1239) is not followed.
  3. **What feeds the queue:** the queue, approve / reject and promotion are built for all five kinds. Only factory products with no catalog item create real candidates in S24 (`catalog_item`). The other kinds come from the seed now and from their own sources later. The tenant-level proposals (findings dismissal loop, pricing learning loop, inference-rule tuning) move to the backlog.
  4. **Promotion mechanism:** a `SECURITY DEFINER` function, the `konboro_sweeper` pattern of migration 0004. A NOLOGIN role owns `konboro_promote(candidate_id)`, which promotes only an approved candidate of the caller's tenant, strips the identifying fields, and writes the record with `pilot_engineer` provenance. Only `konboro_app` may execute it. It runs at once on approval. The app role keeps `SELECT`-only on global tables.
  5. **Flags:** three keys added to spec 13: `onboarding`, `settings_screen`, `approval_queue`. Each is on for the demo and E2E tenants; off answers 404 and shows the placeholder.
  6. **First-quote banner (10 §5.2):** in S24. It shows on the review screen until the factory's first quote is sent, from the onboarding counters, using the existing banner classes (no prototype design).
  7. **"אחר" in the brand question** (Claude, while building, from 05 §5.4): it sets no preference, like a skip, because stage 5 cannot prefer a brand with no name. The answer itself is kept in `tenant_settings.onboarding.brands`, so `GET /onboarding` shows it again.
  8. **The demo and the established E2E tenants** (Claude): they have accepted the terms and have `quotes_sent: 2`, the two quotes the demo price list came from (10288, 10271), so the gate and the banner show only for a new factory.
- **Eval / metrics:** `make eval` (replay): no change against `eval/baseline.json`. Checks run at close: lint, types, licenses, secrets; `make test-unit` (1,049 Python, 253 Vitest); `make test-int` (676, after `test_e2e_seed.py` learned the eight new E2E tenants); `make e2e` (195 on desktop and mobile, 16 of them new); `make check-client` after the commit. `make check-screenshots`: 82 passed, 4 failed twice in a row, the four dark review shots of BUG-038, each a timeout taking the screenshot, not a pixel difference; not compared with a run on `main`.
- **Bugs logged:** BUG-062 (settings: two quick changes to one dict lost the first) and BUG-063 (onboarding went home instead of to the new quote), both found and fixed here. BUG-038 recurred (noted on its row).
- **Follow-ups:** in the roadmap backlog: tenant-level proposals; more sources for the approval queue; stage 4 reading `spelling_patterns`; re-review of `pilot_engineer` records; the data terms' wording; a product deleted after it was queued. Notes added to the S20–S22 backlog items that named S24.
