# S24b: Reading a designer's plan (25.26.100)

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s24b-designer-plan-reading` |
| **Depends on** | S22 |
| **Status** | in progress |
| **PR** | (link) |

## Goal

A designer's single-sheet plan in the style of 25.26.100 (בית כנסת מקווה, לוח ראשי-בית כנסת) reads as the factory reads it. Its main panel has both RCDs, 23 16A breakers, 3 current transformers and none made up from a breaker's end circles. Q0 is a switching device or an MCCB, not an MCB. The 10A 1P breakers are one line. Every quote line is described in one format.

## References

- Specs: 03 §3.5–3.7 (dedup, orphan texts, the designator link), §4.4–4.6 (families, roles, the abbreviation dictionary and its three levels); 04 §5.1.1 (multiplicity, circuit ranges, chains), §5.6–5.8 (instances and the merge); 05 §4.4 (current and poles never get a default), §5.5.1 (circuit inference: the cable cores, the class by current); 07 §7.4–7.5 (the lines and their description).
- Prototype: none (pipeline only).
- Golden: no golden file for 25.26.100 yet: the user checked the main panel only. Measured on a unit fixture built from the dev run's stage 2–4 outputs (`drw_01M6JTD6P888QR919B5KM52EWX`), and on `make eval` for no drop on the golden set.
- Bugs: BUG-066 to BUG-072 (the user's seven findings on the main panel), and BUG-051 / BUG-036 (checked for the same cause as BUG-066).

## Tasks

### Backend
- [x] BUG-066: `association/merge.py::devices`: a tag merges symbols of one family, or a parent with its coil, contacts and accessories. Another family under the same tag is a conflict, never a terminal that swallows breakers and RCDs.
- [x] BUG-067: `detection/designators.py`: `x2` / `X11` beside a protective device's rating is a count, not a tag; stage 4's circuit range confirms it.
- [x] BUG-069: `designators.tags()` expands a range of one prefix ("T1-T3" → T1, T2, T3).
- [x] BUG-070: a designator-prefix table as data (Q a switching device or MCCB, F an MCB), overridable per factory, that weighs the class in stage 3. A breaker above the catalog's MCB range is not an MCB. Breakers on one field's busbar with the same rating and the same drawn symbol are one class.
- [x] BUG-068: a small circle touching a device's box on its wire is part of that device. A residual-current reading beside a protective symbol is evidence for `rcd`.
- [x] BUG-072: the cable written along a circuit's outgoing line reaches its breaker (`poles_from_cable_cores`).
- [x] BUG-071: stage 7 describes an unmatched line with `matching/text.py::describe`; the audit keeps its own short form.

### Unit tests
- [x] A failing test first for each bug, then the fix.
- [x] A fixture of 25.26.100's main panel from the dev run's stage 2–4 outputs (`tests/unit/fixtures/`), with the whole-panel counts.

### Integration tests
- [x] The factory's prefix override reaches only that factory (`tests/integration/test_stage3.py`).

### Eval (pipeline sessions)
- [ ] `make eval` run; numbers recorded under Outcome. Cassettes re-recorded where the change moves a request.

### Docs
- [x] Spec notes for the rules added (03 §3.7, 04 §5.8, 05 §5.5.1)
- [ ] `docs/bugs.md`: BUG-066 to BUG-072 closed, BUG-051 / BUG-036 updated
- [x] CLAUDE.md if a rule or a data file is added

## Acceptance criteria

- [ ] The main panel's re-run: both RCDs (4P 40A 30 mA type A), 23 16A breakers, 3 current transformers (T1–T3), no phantom CTs, Q0 a switch or MCCB, one 10A 1P line.
- [ ] `make check` and `make eval` pass with no metric drop.

## Out of scope

- The sub-panel (לוח משנה-מקווה): the user has not checked it.
- A golden file for 25.26.100: only once the user verifies the labels (then `golden/25.26.100/`).

## Open questions

- None blocking. The rules below are the user's (findings 1–7); their exact thresholds are recorded as decisions.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
