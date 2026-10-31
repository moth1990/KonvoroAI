# S08: Stage 1, intake and page classification

| | |
| --- | --- |
| **Track** | P |
| **Branch** | `s08-stage1-intake` |
| **Depends on** | S07 |
| **Status** | todo |
| **PR** | |

## Goal

Stage 1 is real. Each drawing gets these from code:
- pages rendered and normalized;
- rotation and quality;
- geometry and text source;
- reuse of earlier results by hash, within the tenant.

The `page_classification` agent gives each page a kind and a route, with confidence. The drawing gets its `input_kind`, panel count and title-block context. The user can confirm the pages, or change a page's kind, on the done step. The first model calls are recorded as cassettes, so `make eval` replays them.

## References

- Specs:
  - 01 (all), especially §5.1–5.8 (process), §6 (output contract), §7 (routing), §8 (errors) and §10 (metrics);
  - 00 §3 and §7.2 (an LLM decides only inside a stage, from a closed list, checked by code);
  - 12 §8 (licenses: pypdfium2, never PyMuPDF).
- Prototype: `prototype/konboro-app.html` lines 840–855 (the done step's page strip and page-kind select).
- Golden: all five drawings for stage 1 (`page_kind`, `route`, `input_kind`, panel count). BOM-HW-1 has no pages to classify.
- Earlier sessions:
  - S05 left the stage-1 stub, its thumbnail key and the read-only page-kind select. Its follow-ups are listed under Tasks.
  - S06 built the eval harness and the empty `eval/cassettes/`.
  - S07 added `stage_runs.sent_at` and the re-queue sweep.

## Tasks

### Backend
- [ ] Replace `pipeline/stages/s1_intake.py`. Keep the `run(ctx) -> Contract` shape and the S05 thumbnail key.
- [ ] Normalize (01 §5.1): render with pypdfium2, and read EXIF rotation for images. HEIC thumbnails, and a real DPI for image page sizes (S05 follow-ups).
- [ ] Geometry and text source (01 §5.2), and quality and rotation (01 §5.3), in code.
- [ ] Reuse by sha256 within the tenant only (01 §11).
- [ ] The `page_classification` agent (01 §5.4): one route in `config.py`, a closed list of page kinds, and code that checks the answer. Only the reduced image and a text excerpt go to the model (01 §11).
- [ ] Routing (01 §7). Add the missing `technical_data` and `factory_template` rows. This is the known inconsistency due in this session; the S06 normalizer's mapping is the starting proposal.
- [ ] Context extraction: the title block, panel notes and the feed schema (01 §5.5).
- [ ] The confirmation step when it is needed (01 §5.6), and the endpoint to change a page's kind.
- [ ] The revision check (01 §4.5): same drawing number, or ≥50% identical pages, plus the `revision_counted_as_new` notice (S05 follow-up).
- [ ] A visibility heartbeat while a stage runs, so a long stage is never delivered twice (BUG-009).
- [ ] The stage-1 summary on the run step stays correct with real data.

### Frontend
- [ ] The done step's page-kind select becomes editable (S05 follow-up), plus the confirmation flow when stage 1 asks for it.

### Unit tests
- [ ] Routing table, quality and rotation rules, the agent-answer check, and the revision rule.

### Integration tests
- [ ] Stage 1 on each golden PDF through the queue. `FakeProvider` or cassettes only; never a real model in tests.
- [ ] Hash reuse never crosses tenants.
- [ ] Changing a page kind is checked against the actor and the tenant.

### UI tests (Playwright)
- [ ] Desktop and mobile: change a page kind on the done step, and confirm pages when asked.
- [ ] Fidelity report for the done step reviewed by the user.

### Eval (pipeline sessions)
- [ ] Record the first cassettes: `EVAL_MODE=live EVAL_RECORD=1 make eval`. Commit the cassettes and the new baseline (`make eval-baseline`).
- [ ] `make eval` in replay; numbers recorded under Outcome.

### Docs
- [ ] 01 §7 routing table completed. Remove the item from CLAUDE.md's inconsistency list.
- [ ] `docs/db-schema.md` for any new column.

## Acceptance criteria

From 01 §10, measured on the golden set. They are starting values, calibrated after this first run (01 §12 item 5):

- [ ] Missed `process` pages: **0**.
- [ ] `page_kind` accuracy ≥ 97%.
- [ ] Panel count accuracy ≥ 95%.
- [ ] Title-block field accuracy ≥ 90% per field.
- [ ] The eval baseline is updated on purpose, and the cassettes replay deterministically.

## Out of scope

- Text extraction and tiling: S10.
- Symbols: S12.
- The BOM-only path's table import: S14.
- DWG and DXF (01 §12 item 1, version 2.0).

## Open questions

1. 01 §7 lacks `technical_data` and `factory_template`. Do the S06 normalizer's routes apply (`context` and `skip`)?
2. Which model does the `page_classification` route use, and what is the image size budget per page?
3. A live run is needed once to record cassettes. Is the local `ANTHROPIC_API_KEY` the right key, and is there a cost ceiling for the run?
4. When the revision check finds a match by page hashes only, with a different drawing number, which wins?

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
