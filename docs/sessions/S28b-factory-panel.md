# S28b: A factory drawing is one panel; the common products in the demo

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s28b-factory-panel` |
| **Depends on** | S28 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#40](https://github.com/moth1990/KonvoroAI/pull/40) |

## Goal

A factory drawing comes out as one panel, whatever cells or parts the classifier reads in it: 25/886's kitchen panel is one panel, "לוח מטבח", not five. Whether a drawing is a factory's is decided by the factory's own pages, so a designer's plan keeps its panels as named. In `make dev`, the demo factory has `catalog_lines` on and S27b's 15 common products in its price list.

## References

- Specs: 01 §4.4 (the input kind), §5.4 (the classifier's panels and regions), §5.5.1 (a panel's notes block), §5.6 (the confirm step), §5.7 (the factory's template pages), §12 item 2 (a panel over several pages); 07 §7.1 (one chapter per panel), §7.2 (the price list is the factory's prices); 13 §4.10 (`catalog_lines`).
- Prototype: none. No screen changes.
- Golden: every drawing through `make eval`. The factory drawings: NURSERY-1, NEVIS-1, MINHAROT-1, 26-993 (BUG-035: three panels where the label has one). The designer's plans: 25.26.100 (two panels, read as a factory drawing by the eval's cassette), 6199-2-50 (three).
- The user's report (2026-11-07):
  1. The catalog from S27b looks not updated.
  2. A designer's plan may have several panels and the app handles it well. In a factory drawing the app takes every cell as a panel of its own, which is wrong: a panel can be made of more than one cell.
- The drawing that showed both: `drw_01M6RMRPVB1FX4W03MH65ED7NR` (לוח מטבח.pdf, 25/886), in the dev database.

## What was found

1. **The catalog is there.** `common.csv`'s 15 products are in the dev database's master catalog (seeded 2026-11-05), and the kitchen quote matched some of them: XT2N160 Ekip LS/I In=63, 100 and 160, and F204A-100/0.03.
   - **Why it looked missing:** the price list screen shows the factory's own products only, and none of the 15 is one.
   - **Also:** `catalog_lines` was off for the demo factory, so the kitchen quote had none of S27b's behaviour (one line per product, waiting lines with their nearest products, "מוצר חדש"). The seed turns every flag on only when it creates the demo factory, and the dev database's demo factory is from before S27b (BUG-105).
2. **Five panels.**
   - Stage 1 took every name the classifier read on a page as a panel: "לוח מטבח", "לוח מטבח-חלק א", "חלק ב", "חלק ג".
   - The pages with no name went to "לוח 1": no title-block name was read, and with four names there was no single panel to give them to.
   - The drawing's title block has "שם הלוח: לוח מטבח", but the title-block read returned null.
   - Page 5's front view shows the three parts over six cells of one panel (600, 1000, 600, 600, 600, 800 mm).
3. **The input kind.** It was decided by the classifier's `component_labels` alone (most diagram pages with tags and models). The eval's cassette reads 25.26.100's one sheet that way, so it came out a factory drawing (`s1/input_kind_accuracy` 0 in the baseline). A "factory drawing = one panel" rule on that input kind would have made 25.26.100's two panels one.
4. **The kitchen quote's other gaps**, logged and not fixed here (BUG-107–110). They are about reading and matching, not about the catalog's content.

## Tasks

### Specs
- [x] 01 §4.4: the input kind by the factory's pages; a correction on the confirm step decides it again
- [x] 01 §5.4: the panels of a drawing, a factory drawing's one panel and its name; §12 item 2 closed
- [x] 01 §5.4: `component_labels` no longer decides the input kind

### Backend
- [x] `pipeline/intake/drawing.py`: `input_kind` by `FACTORY_PAGE_KINDS`; `merge_panels(one_panel=True)` with its name rule and `aliases`; `panel_resolver`
- [x] `pipeline/stages/s1_intake.py`: the input kind before the panels; notes blocks, reused notes and regions resolved through the panel's parts
- [x] `pipeline/intake/corrections.py`: the confirm step decides the input kind again, builds the one panel, repoints regions and notes blocks, and writes the input kind to stage 1's output
- [x] `db/seed.py`: `demo_flags` (every flag for an existing demo factory, one set off stays off), `demo_common_products` (the 15 in the demo price list, linked, no supplier, no cost)

### Unit tests
- [x] A factory drawing's parts are one panel, named by the title block, else the base name, else the most pages; aliases; as a designer's plan the five panels stand
- [x] Every name resolves to a factory drawing's one panel; a designer's plan by name only
- [x] The input kind: the factory's pages decide; 25.26.100's shape is a designer's plan

### Integration tests
- [x] Stage 1 on a drawing with parts: one panel, its pages, the notes block of a part on it (`test_stage1.py`)
- [x] A designer's plan keeps its five panels; marking a page as the factory's template on the confirm step makes it one panel, with the notes block and stage 1's output following
- [x] The seed: an existing demo factory gets `catalog_lines`, a flag turned off stays off; the 15 products in the price list once, linked, with no cost (`test_seed.py`)

### UI tests (Playwright)
- No screen changed; `make e2e` (desktop and mobile) and the screenshot check ran in `make check`.

### Eval (pipeline sessions)
- [x] `make eval`: 26-993 one panel (BUG-035), 25.26.100 a designer's plan; the moves explained; the baseline written

### Docs
- [x] `docs/bugs.md`: BUG-104, 105, 106 fixed, BUG-035 fixed, BUG-107–110 logged
- [x] CLAUDE.md: what S28b changed in stage 1 and the seed
- [x] Roadmap row

## Acceptance criteria

- [x] A factory drawing with parts ("לוח מטבח-חלק א/ב/ג" and unnamed pages) comes out as one panel named "לוח מטבח" (integration test). The user's rerun of 25/886: not yet.
- [x] 26-993 comes out as one panel, "MAIN ELECTRICAL BOARD" (eval).
- [x] 25.26.100 and 6199-2-50 keep their two and three panels, and are designer's plans (eval: input kind and panel count 7/7).
- [x] After `make seed`, the demo factory has `catalog_lines` on and the 15 products in its price list under "בלי עלות" (integration test). In the dev database: not yet.
- [x] `make check` passes (2026-11-07): lint, licenses, secrets, the client, unit (1,294 backend, 279 Vitest), integration (822), the eval, E2E (251). The screenshots: 85 passed and one timed out (light prices › prices-editor, desktop: BUG-102 again); rerun alone, 8 of 8 passed.

## Out of scope

- The kitchen quote's reading and matching gaps (BUG-107–110), and the astronomical clock typed as a Shabbat clock (BUG-082).
- Sections inside a panel's chapter of the quote (a cell's lines apart): the panel is one chapter, as 07 §7.1.
- The enclosure of a panel of several cells: stage 7 sizes one enclosure from the modules, as before (07 §7.4).
- A screen for the master catalog: the price list stays the factory's.

## Open questions

None open. Answered 2026-11-07: decisions 1–4 below.

## Outcome

Filled in at `/session-close`.

- **Done:**
  - **Spec 01:** §4.4 (the input kind by the factory's pages, decided again on the confirm step), §5.4 (the panels of a drawing, a factory drawing's one panel and its name), §12 item 2 closed.
  - **Stage 1:** `intake/drawing.py` (`input_kind` by `FACTORY_PAGE_KINDS`, `merge_panels(one_panel=True)`, `aliases`, `panel_resolver`); `stages/s1_intake.py` (the input kind before the panels; notes blocks, reused notes and regions resolved through the parts); `intake/corrections.py` (the confirm step decides the input kind again, builds the one panel, repoints regions and notes blocks, writes the input kind to stage 1's output). No contract and no prompt changed.
  - **Seed:** `demo_flags` (every flag for an existing demo factory, one already set kept), `demo_common_products` (the 15 in the demo price list).
  - **Tests:** unit (`test_stage1.py`: the one panel and its name, the resolver, the input kind), integration (`test_stage1.py`: a drawing with parts is one panel with its notes block; a designer's plan keeps five panels and a correction makes it one; `test_seed.py`: an existing demo factory gets `catalog_lines` and keeps a flag turned off, the 15 products once with no cost).
  - **Docs:** the bug log, the roadmap, CLAUDE.md.
- **Decisions made:**
  1. **A factory drawing is one panel** (the user, 2026-11-07). A factory draws one panel per drawing set; the names the classifier reads in it are its cells or parts. A designer's plan keeps its panels as named. The user chose this over joining parts by a name pattern (חלק/תא/שדה).
  2. **The factory's pages decide the input kind** (the user). A drawing with a technical-data page or a factory template page is a factory drawing, otherwise a designer's plan. Every factory drawing we have has one; neither designer's plan has. A factory whose drawings lack those pages gets the panels as named, as before S28b.
  3. **The one panel's name** (Claude). The title block's "שם הלוח"; else the name every other name extends by a word or a mark; else the name on the most process pages, the first on a tie; else "לוח 1".
  4. **The 15 products in the demo price list, with no cost** (the user). Demo only: a real factory's price list is never filled from the shared catalog. They are `manual_entry` products linked to their catalog item, named as stage 5 names the item.
  5. **A new branch after S28's merge** (the user).
- **Eval / metrics:** replay, twice, the same numbers; the second run is the baseline (`make eval-baseline`).
  - **Better (35 metrics):**
    - Stage 1: input kind 6/7 → 7/7 (25.26.100 is a designer's plan) and panel count 6/7 → 7/7 (26-993 is one panel).
    - 26-993, stage 4: component recall 11/22 → 17/22, precision 0.42 → 0.85, unit recall 0.47 → 0.81.
    - 26-993, the backtest: from 46% over the real quote to 12% under. One enclosure instead of three: derived items 12,600 → 4,200, the quote's own 4,200.
    - 26-993, stage 6: its labelled SE/SG near match fires (`golden_findings` 1/2 → 2/2).
    - All drawings: rows that need no edit 51.4% → 52.8%.
  - **Worse (19 metrics), all on 26-993 or in totals that hold it.** They come from the components stage 4 put in the two feed-board panels. Nothing paired those before; now they are scored, with their own errors:
    - `s4/poles_accuracy` 7/7 → 8/10: three more components with labelled poles, two of them read wrong.
    - `s5/sku_value_accuracy` 7/7 → 8/9.
    - `s5/llm_share` 1/20 → 1/19: one model call, over fewer signatures once the panels are one.
    - `s6/warnings` 3 → 5: the labelled near match, and `QTY_SINGLE_INSTANCE_FAMILY` on QG1, QG2.
    - `audit/difference_recall` 3/3 → 2/3: G1, a shunt trip read on the feed boards, now merges with TC-G1 and TC-G2 into one component of 3. The confirmed missing shunt trips are found at confidence 0.56, under the 0.6 shown (BUG-111).
    - The factory-drawing totals also move because 25.26.100 left them for the designer's plans.
  - `catalog_lines` on (`EVAL_CATALOG_LINES=1`): not run; it is reported, not the baseline.
- **Bugs logged:** BUG-104 (a factory drawing's parts as panels, P1, fixed), BUG-105 (the demo's flags, P2, fixed), BUG-106 (25.26.100's input kind, P2, fixed), BUG-035 fixed; open: BUG-107 (F204s typed `rcbo`), BUG-108 (C3, AC-1 or AC-3), BUG-109 (a shunt trip without its breaker's series), BUG-110 (AM530D, PM135E, SW3's positions), BUG-111 (26-993's G1 merged with the shunt trips).
- **Follow-ups:**
  - A `mixed` drawing (a factory drawing with a BOM page) keeps its panels as named: the one-panel rule is for `factory_drawing` only.
  - 25/886's title block has "שם הלוח: לוח מטבח", and the title-block read returned no panel name. The base-name rule covers it here.
  - The user reruns `make seed` and uploads 25/886 again.
