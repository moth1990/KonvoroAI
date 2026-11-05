# S24b: Reading a designer's plan (25.26.100)

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s24b-designer-plan-reading` |
| **Depends on** | S22 |
| **Status** | in review |
| **PR** | [moth1990/KonvoroAI#32](https://github.com/moth1990/KonvoroAI/pull/32) |

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
- [x] `make eval` run; numbers recorded under Outcome. Cassettes re-recorded where the change moves a request.

### Docs
- [x] Spec notes for the rules added (03 §3.7, 04 §5.8, 05 §5.5.1)
- [x] `docs/bugs.md`: BUG-066 to BUG-072 closed, BUG-051 / BUG-036 updated
- [x] CLAUDE.md if a rule or a data file is added

## Acceptance criteria

- [x] The main panel's re-run: both RCDs (4P 40A 30 mA type A), 23 16A breakers, 3 current transformers (T1–T3), no phantom CTs, Q0 a switch or MCCB, one 10A 1P line.
- [x] In replay, `make eval` shows 25.26.100's main panel with both RCDs, 23 16A breakers (S201M × 22, S203M × 1 by stage 5), 3 CTs and no other, Q0 an MCCB, and one 10A 1P line (× 12; two more breakers with no current read are a line of their own).
- [x] `make check` passes (the four dark review shots of BUG-038 passed rerun alone; gitleaks run with the main repository's `.git` mounted, since the worktree's `.git` is a pointer). `make eval` passes against the rewritten baseline; the metric drops against the old one are explained above.

## Out of scope

- The sub-panel (לוח משנה-מקווה): the user has not checked it.
- The sub-panel's labels (not checked by the user yet).

## Open questions

- None blocking. The rules are the user's (findings 1–7 on 25.26.100); their thresholds are recorded as decisions below.

## Outcome

- **Done:** BUG-066 to BUG-072. **Live run** of the PDF through all seven stages (real Claude, on the eval's throwaway database, `drw_01M6K2FJSWAT0S955BX6DMHEHZ` there): the main panel has Q0 as an MCCB (ABB XT1C160 TMD80 3P), three current transformers 100/5A, no phantom one, two RCDs (ABB F204 4P 40A 30mA type A), 23 16A breakers (S201M-C16 × 22 and S203M-C16 × 1), and one 10A line (S201M-C10 × 13), each line in one format. Left on it: the breaker marked X2 beside `C130,131` (circuits 130–131) is read as a contactor × 2, the five 40A field breakers are MCCBs after the one the model was sure of (the user to say whether they are MCBs), and a red missing line "מא"ז 4P 40A". On the unit fixture, 25.26.100's main panel replayed from the dev run's stage 2–3 outputs (`tests/unit/test_plan_25_26_100.py`, stage 4 without the tile agent), the panel now has both RCDs (4P 40A 30 mA), 23 16A breakers (22 on 3×2.5 → 1P, the kitchen's on 5×2.5 → 3P), three current transformers T1–T3, no current transformer made of an end circle, Q0 an MCCB (XT1 on the sample catalog), and the 10A lighting breakers as one 1P line on their 3×1.5 cables.
- **Decisions made:**
  1. **Where the factory overrides the prefix table** (Claude): `tenant_settings.matching.designator_prefixes`, a key in an existing JSON column, so no migration (S25's open branch adds 0021). The table is not part of the library's version: the model never sees it, so it moves no cassette.
  2. **The prefix only weighs** (Claude, from the user's "weighs the class"): it changes an unsure reading only, picks among the classes the model saw, else the one class of the symbol's own family the prefix allows, and never brings in a family the model did not see. A sure reading stands.
  3. **"Above the catalog's MCB range"** (the user's rule, finding 2): stage 5 types a breaker the drawing did not call an MCB in words again by its current, as an MCCB, when the current is above the largest MCB in the catalog (63A in the sample). An MCB written as such ("MCB") still narrows to MCBs (05 §5.1 item 2), so `test_the_class_narrows_the_family` now writes "MCB". 05 §5.5.1's row is amended.
  4. **A tag conflict** (Claude, BUG-066): a sure device of another family under a tag, or one drawn away from the tag's device, stays its own device, untagged and yellow (`tag_conflict`). An unsure one within the length of one of the tag's device's drawings is a misread part of it and joins, as before (NEVIS-1's Q0 ring, 26-993's QLG1 thermal release): treating those as conflicts made phantom current transformers on two golden drawings.
  5. **End circles after the disambiguation call** (Claude): absorbing them before the call would save a few calls, but it moves the page's budget and so every disambiguation cassette. After the call, the eval's stage 3 changes come from the new rules only. Follow-up below.
  6. **Thresholds** (Claude, starting values): an end circle is ≤ 35% of its device and within 6 pt or 30% of its size; peers share a top within 3 pt, a width within 15% and a height within 60%; a count is beside a rating or a range within 1.5 line heights; a wire that starts within 3 pt of where the walk passed carries it on; a dead end of 4 pt or less is a tick.
  7. **No golden file for 25.26.100** (brief): the user checked the main panel only. A unit fixture from the dev run instead, with the title block, notes and file name left out.
  8. **One line for breakers whose cable gives the poles the others read** (Claude, from the user's "one 10A 1P line"): on the live run the agent read the pole mark on 10 of the 13 10A breakers. A protective device with no poles written joins the identical component whose poles are what its own cable's cores give (05 §5.5.1's table, read from `matching/inference.json`), when that component's cables agree. Its instance keeps the poles unread: no value without evidence (00 §5.3), and stage 5 does the filling in. A known value against a null still never merges otherwise.
  9. **An uncited count of 1 from the tile agent is no reading** (Claude, BUG-067): on the live run it hid every "x2" and "X11". Code's mark stands then; a count the agent cites wins.
  10. **The rewritten eval baseline is kept** (the user, after review): NEVIS-1's poles accuracy and SKU share drops and stage 3's `llm_share` rise are accepted as explained below.
  11. **25.26.100 joins the golden set, main panel only** (the user, after the PR opened): `golden/25.26.100/` with the PDF, a README and labels in 6199-2-50's shape, no quote. The sub-panel is listed with `verified: false` and no components; stage 4 skips a panel nobody verified (`eval/metrics/stage4.py`), stage 1 still counts it. Labels read from the drawing and the user's corrections; what is not read is in `to_verify`, and two rows are interpretations marked as such: the 25A feeder's 3P (from its 5X6 cable, no pole mark drawn) and 1X10AC as an MCB 1P 10A curve C. Its cassettes were recorded live (`EVAL_RECORD=missing`, 316 calls kept), and the baseline rewritten with it.
  12. **A breaker's own copy is not the next breaker** (Claude, from the new drawing's eval run): a breaker found twice, the second box inside the first, stopped the walk to its cable. The walk goes through a protective symbol that overlaps the start's box.
  13. **25.26.100's 25A feeder (circuit 300) is 3P** (the user, asked "3P or 1P?"): no pole mark is drawn; the label had it 3P from its 5X6 cable, and it leaves `to_verify` (`poles_source: user`).
  14. **Every label on 25.26.100's main panel is user-verified** (the user, answering the five open points): 1X10AC is an MCB 1P 10A curve C; the control selector is one selector; X11 counts 11 as marked (the written count wins over the 12 circuit numbers listed under it, and the user corrects it in review if needed); the five 40A field breakers are MCBs (no 40A MCCB exists); the photocell and light sensor are outside the panel. `to_verify` is empty. The sub-panel stays `verified: false`.
  15. **A cassette recorded under two keys for one platform difference** (Claude; the user chose it over re-recording on Linux, BUG-073): CI's replay of 25.26.100 gave 51 cited values against 53 on macOS. Cause: pdfium renders the plan 37 corner pixels differently on Linux amd64; one moves a sub-panel busbar's ink-shrunk box by a pixel (161 → 160) in one tile's prompt and frames, so that tile's `text_association` cassette missed and the agent fell back to code. No threshold or render option makes the raster identical, so the tile's macOS answer is also stored under the Linux request's key (`eval/cassettes/text_association/5124260f…`, a copy of `5dd6ba3f…`; the requests differ in that box line only). Both platforms then replay the same answers, and the baseline does not change. Re-recording on Linux instead would have let the two platforms replay different answers.
- **Eval / metrics:** cassettes re-recorded for the calls the change moved (`EVAL_RECORD=missing`, three live runs, about 60 calls), then the baseline rewritten (`make eval-baseline`, its own commit). Better: 6199-2-50 component recall 0.575 → 0.644, precision 0.506 → 0.560, unit recall 0.522 → 0.576, with SKU 0.554 → 0.616 (guard-booth panel recall 0.357 → 0.643); NEVIS-1 component recall 0.857 → 0.905, unit recall 0.766 → 0.787. 6199-2-50 unit recall then 0.576 → 0.620 with decisions 8–9 (its with-SKU share 0.616 → 0.612: two components joined). Worse, explained: NEVIS-1 poles accuracy 0.917 → 0.846 and with SKU 0.810 → 0.773, from the re-recorded tile's answer, which reads C4's power contacts as one pole (graphic); the tile's prompt moved because F4's unsure cross is now an `mcb` by its letter, which stage 4 defaulted it to before. Stage 3's `llm_share` rises by up to 1.7 points on the designer's plans: the same disambiguation calls over fewer detections, the circles absorbed after their call. 6199-2-50's `s5_labelled` `llm_share` 0.0870 → 0.0889: one signature fewer once an MCB above the catalog's range is an MCCB.
- **Bugs logged:** BUG-066 to BUG-072 closed. BUG-051 and BUG-036 checked: not BUG-066's cause (stage 3 detects only terminals there).
- **Follow-ups:** see the roadmap backlog.

## Follow-up: what a live run on S24b's code still got wrong (BUG-077 to BUG-081)

Branch `fix-25-26-100-main-panel`, started from the bugs session after a live run of 25.26.100 (dev `drw_01M6M5S1RS05GXXD6XK2HAQNXE`), and checked again on a live run of the branch (`drw_01M6M9BJXK4H757VWBGAXXJPWN`).

- **Decisions made:**
  1. **An MCCB within the catalog's MCB range is typed by its current** (the user, BUG-077): the converse of decision 3. A breaker typed `mccb`, rated at or below the catalog's largest MCB and under 100A, becomes an MCB, yellow, unless "MCCB" or "בתיבה יצוקה" is written beside it, a series or SKU is written, or a designator prefix names an MCCB (Q, the factory's table on top). 05 §5.5.1 amended. The grammar reads "בתיבה יצוקה" as `mccb`, so 6199-2-50's factory-verified 25A and 63A MCCBs stay MCCBs.
  2. **No "a peer must not overturn the model's `choose`"** (Claude, against the brief): MCBs and MCCBs are drawn alike, so a peer that unifies a row's class keeps the row one line, and decision 1 types the class by current. Blocking it would have split the five 40A breakers into two lines.
  3. **An unsure pole mark the cable contradicts is a conflict** (the user, BUG-079): below 0.85, nothing is chosen, both readings are offered, nothing is filled in. A sure mark is still matched, yellow. 05 §5.5.1 amended.
  4. **One written tag names one device, in stage 4** (Claude, BUG-081): a span nearest a coil or a contact is not another family's tag (`merge.one_name_per_tag`). Done in stage 3 first, it moved the tile agent's prompt on every golden drawing (81 calls), and a version for spans nearest a device drawing made NEVIS-1's and MINHAROT-1's rings phantom current transformers again (decision 4).
  5. **The clock's class and the selector's two decks are deferred** (the user): BUG-082 needs the timer and time-switch descriptions reworded in the detection prompt, which moves every stage 3 cassette; BUG-083 needs a mechanical link told from a wire.
  6. **A rated push button is a breaker** (the user, an exception to decision 2, after the branch's live run): a symbol read as a push button, however sure, with a current rating beside it and drawn like the breakers in its row with the same rating (whatever their confidence), is a breaker, yellow (`evidence.py` rule 3b). On the live run the model was sure of two 16A socket breakers as push buttons (`det_001_0017` with X11, `det_001_0020`), "לחצן" × 12.
  7. **An unmatched line is described by stage 5's class** (Claude): the 40A breaker typed `mccb` in stage 3 and an MCB in stage 5 read "מפסק בתיבה יצוקה 40A" on its unmatched line; the line takes the class from stage 5's signature.
  8. **Rows with no sure symbol vote, and alike peers give their poles** (the user on a later live run, "they're all the same", BUG-087, BUG-088, BUG-090): rule 3c in stage 3, rule 3b widened to unsure contactors, a row lined up by middles too, and `merge._join_by_peers` in stage 4, which joins like decision 8 and fills no value (00 §5.3). A device's own cable stays `_join_by_cable`'s evidence.
  9. **A curve on the rating means a breaker** (the user, BUG-091): "1×10AC" beside a disconnector makes it an MCB, a written reading over the model's class.
  10. **Professional quote-line names** (the user, overriding the prototype's "מגן מנוע", line 501): a motor-protection breaker is "מפסק מגן מנוע … טווח 2.5–4A", a switch-disconnector "מנתק" (the prototype's own word, lines 500 and 518), a contactor's current "(AC-3)" and its coil "סליל 230V" (the prototype's line 443), in `matching/text.describe` for every line, and the demo price list's MS116 row. The detection library's names stay, since they are the model's words in the disambiguation prompt; the BOM reader knows both; the audit keeps the factory's short form.
- **Eval / metrics:** eight cassettes recorded live (`EVAL_RECORD=missing`, for the calls the new grammar patterns moved), then the baseline rewritten (accepted by the user). 25.26.100: citation mismatch 0.132 → 0.091, with SKU 0.609 → 0.640, stage 6 warnings 4 → 3; main-panel component precision 0.579 → 0.524, from the clock (a timer, BUG-082) and C130,131's coil (a relay), no longer swallowed into the selector tagged T1. The other drawings replay as before.
- **Bugs:** BUG-077 to BUG-081 closed; BUG-082 to BUG-084 open.
