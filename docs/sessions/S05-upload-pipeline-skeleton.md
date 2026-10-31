# S05: Upload and pipeline skeleton

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s05-upload-pipeline` |
| **Depends on** | S04 |
| **Status** | done |
| **PR** | [#6](https://github.com/moth1990/KonvoroAI/pull/6) |

## Goal

The thin end-to-end slice works:
1. The user uploads a drawing.
2. Every intake check runs and the quota is reserved.
3. A coordinator drives 7 **stub** stages through the queue, and each stub emits a valid contract object.
4. The UI shows live progress, supports cancel, and ends on the summary step.

Later sessions replace the stubs one at a time without touching the plumbing.

## References

- Specs:
  - 00 §4 (pipeline run, concurrency, failure behavior), §5.1–5.2 (stage contracts and side flows), §6.1 (IDs).
  - 01 §4.1–4.6: request, formats, limits, check order, `input_kind`, quota, new-quote screen.
  - 12 §3 (SQS per stage, messages carry IDs only).
- Prototype: 754–869:
  - `SAMPLES`, `STAGES`, `REV_OPTIONS`, `validateFile`, `vNew`, `runPipeline`;
  - phases `pick`, `run` and `done`;
  - cancel releases the quota;
  - a version does not count against the quota.

## Tasks

### Backend
- [x] `konboro/contracts/`: Pydantic models for every stage boundary in 00 §5.1 (01 §6 → 07 §6) and the side flows of §5.2, field for field from the specs. Each stub fills the minimum, and every model gets a JSON-schema snapshot test.
- [x] `services/storage.py` (boto3; S3Mock locally):
  - Keys under `tenants/{tenant_id}/…`, with the server-side encryption flag set.
  - Put, get and a presigned GET.
- [x] `services/queue.py` (boto3; ElasticMQ locally):
  - One queue per stage (`konboro-s1-intake` … `konboro-s7-pricing`, from S01's `infra/elasticmq.conf`), each sending to `konboro-dlq` after 3 failed receives. Tests and E2E use their own prefixed copies.
  - Messages carry IDs only: `{drawing_id, tenant_id, stage, trace_id}` (12 §3).
- [x] `services/intake.py`:
  - Format by magic bytes: pdf, png, jpg, webp, heic, xlsx, csv, zip; dwg and dxf → `cad_not_supported`.
  - Page counts without rendering: PDF via pypdfium2, an image = 1, CSV = 1, XLSX = its worksheets. ZIP is one level deep, within 200 MB uncompressed, and each inner file gets the same checks.
  - Checks in the order of 01 §4.3: quota, size (20 MB), format, pages (plan's `max_pages_per_file`; 200 per drawing). One failing file rejects the whole upload, with every file's Hebrew error (01 §8).
- [x] `POST /drawings` (multipart; files plus customer, project, or `revision_of`):
  - quota reserve (atomic, S03) → checks → sha256 → S3 → `drawings` + `drawing_files` + `stage_runs` → enqueue stage 1.
  - Any failure after the reserve releases it.
  - A new version of an existing drawing reserves nothing (decision below).
- [x] Quota: a new `refund` event kind (migration 0003). It gives a confirmed upload back after a later system failure or a cancel. One refund per reservation.
- [x] `pipeline/coordinator.py` + `pipeline/worker.py` (`python -m konboro.pipeline.worker`). For each message:
  1. Skip if the drawing is cancelled or failed.
  2. Mark the stage `running`.
  3. Run it, write its contract JSON to S3 (`stage_runs.output_key`), set `drawings.current_stage` and `progress`.
  4. Enqueue the next stage.
  - Stage 1 succeeding confirms the quota.
  - After the queue's retries the message goes to the DLQ: the drawing becomes `failed`, and its quota is released or refunded.
- [x] `pipeline/stages/s1…s7` stubs with deterministic contract output:
  - s1 creates the pages (size from the PDF), a ~300 px thumbnail per page in S3, and one panel.
  - s2–s6 return empty but valid outputs.
  - s7 creates a quote with zero lines (version 1, draft), linked to the drawing.
- [x] `GET /drawings/{id}/progress`: status, current stage, the 7 stages with their states, `quote_id` when done, and the pages and summary for the done step (with presigned thumbnail URLs).
- [x] `POST /drawings/{id}/cancel`: stops at the next stage boundary, releases or refunds the quota. The files stay.
- [x] `GET /drawings/revisable`: the tenant's finished quote drawings, for the "new version" picker.
- [x] Every route checks a permission (`drawings.write`, `drawings.read`) and a tenant (RLS). `make gen-client`.
- [x] Dependencies: pypdfium2 (Apache-2.0/BSD-3), python-multipart (Apache-2.0), Pillow (MIT-CMU, for thumbnails); the license gate passes.

### Frontend
- [x] New-quote screen (754–869), phase `pick`:
  - The mode toggle (new quote / new version); customer and project fields, or the revision picker.
  - Drop zone and file input, with client checks mirroring the server's (size; type by extension, the server decides by content).
  - File rows with size, pages, ok/rejected chips and the server's reason, and a remove button; the start bar with the quota sentence; clear all.
  - Start is disabled on any rejected file, with no revision chosen, or with the quota full.
  - The chat-builder card when `chat_quote_builder` is on.
- [x] Phase `run`: meter, the 7 stages (done / working / waiting) from polling `/progress` every second, and cancel.
- [x] Phase `done`: the summary grid, a card per page with thumbnail, route and kind (the kind select is read-only until S08), and "המשך לבדיקה" → `/review/:quoteId`.
- [x] A finished or running upload survives a reload: `/new?drawing=drw_…` resumes the right phase.
- [x] After a run, home's recent work and the quota meter refresh.

### Unit tests
- [x] Magic bytes: pdf, png, jpg, webp, heic, xlsx (zip with `xl/`), csv, zip, dwg, dxf, and unknown.
- [x] Check order: the first failing rule wins, and one bad file rejects all.
- [x] Contract schema snapshots.
- [x] Vitest: client-side file checks; progress → stage rows.

### Integration tests
- [x] Upload `golden/NURSERY-1/NURSERY-1.pdf`: the worker runs all 7 stubs through ElasticMQ, a quote exists, pages and thumbnails are stored, and the quota is confirmed once.
- [x] Over 20 MB, a DWG, too many pages, or the quota full: rejected with the right code, nothing stored, no quota used.
- [x] Cancel before and after stage 1: the pipeline stops; the quota is released or refunded.
- [x] A stage that keeps crashing: the message lands in the DLQ, the drawing is `failed`, and the quota is refunded.
- [x] Messages carry IDs only.
- [x] Tenant B cannot read A's progress, files or thumbnails, and cannot cancel A's drawing.
- [x] A new version reserves nothing.

### UI tests (Playwright, desktop + mobile)
- [x] Happy path: upload NURSERY-1 → progress → done → review placeholder; the quota meter goes up by one.
- [x] A DWG and an oversized file show their chips, and Start stays disabled.
- [x] Cancel during the run.
- [x] New-version mode leaves the quota meter unchanged.
- [x] **Fidelity:** pick, run and done, from the prototype and the app, reviewed by the user. Accepted screens become baselines.

### CI and docs
- [x] The E2E API also runs the worker. CI starts S3Mock and ElasticMQ next to Postgres for E2E.
- [x] `make dev` runs the worker too.
- [x] `docs/db-schema.md` (the `refund` event), and CLAUDE.md (worker, commands).

## Acceptance criteria

- [ ] All tests green in CI. The worker runs inside the CI job against the compose services.
- [x] Every stage message carries IDs only. No payloads in the queue (`StageMessage` refuses extra fields; `test_storage_queue.py` reads the raw body).
- [x] The fidelity report has been reviewed (pick, run, done; accepted as is).

## Out of scope

- Real stage logic (S08 onward).
- ZIP beyond one level and the system limits: S05 unpacks one level and checks each file; the rest is S08.

## Open questions

- Polling or SSE for progress? Default: polling every 1 s. Kept, see decisions.

## Outcome

- **Done:** The thin end-to-end slice:
  - **Upload.** `POST /drawings` runs the 01 §4.3 checks in order, all or nothing: format by content, pages without rendering, one-level ZIPs. It then reserves the quota, stores the files under the tenant's S3 prefix, and queues stage 1 after the commit.
  - **Pipeline.** A coordinator and worker drive 7 stub stages through ElasticMQ. Each writes its contract (`konboro/contracts/`, all seven validated against their spec examples) to S3. Stage 1 renders a real thumbnail per page, and stage 7 creates an empty quote.
  - **Quota.** Counted at stage 1, and refunded (migration 0003) on a later failure or a cancel.
  - **Endpoints.** Progress, cancel, and the "new version" picker.
  - **Screen.** Pick, run (polling every second), done, resumable at `/new?drawing=…`.
  - **Running it.** `make dev` and the E2E API run the worker; CI starts S3Mock and ElasticMQ for E2E. The new screens are screenshot baselines.
- **Decisions made:**
  - When an upload counts, spec vs prototype (2026-10-31, user): **01 §4.5 wins.**
    - The reservation is confirmed when stage 1 succeeds, not at the end of the pipeline as in the prototype and the first draft of this file.
    - A later system failure, or a cancel, gives it back through a new `refund` quota event. So the quota never charges for work that did not finish.
    - Before stage 1 succeeds, cancel or failure releases the reservation.
  - New versions (2026-10-31, user): until S08 reads title blocks and page hashes, a new version of an existing drawing is trusted and reserves nothing. S08 adds the 01 §4.5 check and the `revision_counted_as_new` notice.
  - Thumbnails (2026-10-31, user): the stage-1 stub renders a small real thumbnail per page with pypdfium2 and stores it in S3. S08 keeps the same storage key.
  - Progress is polled every second; SSE only if it proves needed.
  - The prototype's "sample files" section is left out: 01 §4.6 item 5 shows it in the demo only.
  - Fidelity report for pick, run and done (2026-10-31, user): **accepted as is**, with these differences:
    - The page count appears once the server has checked a file; the browser checks only type and size.
    - Stage summaries exist for stage 1 only.
    - Results read 0 until stages 4–7 are real, and every page is routed to processing by the stub.
    - Page kinds are read-only until S08.
  - A rejected upload leaves no quota trace: the reservation is in the same transaction as the checks and rolls back with them. Only uploads that pass the checks are ever reserved.
  - Stage 1 is queued after the commit (a background task), so the worker never sees a drawing that isn't there yet.
  - The coordinator locks the drawing with `FOR NO KEY UPDATE`, so a cancel never waits on a running stage. A cancel that lands mid-stage wins: the stage's rows roll back.
  - Three error codes are new to 01 §8 (`too_many_files`, `zip_too_large`, `zip_nested`), and 01 §4.5 now describes the refund. Both spec changes are in this PR.
  - `qty` in the stage 7 contract accepts a JSON number, as in 07 §6.1's example, and is written back as an exact decimal string. Money stays string-only.
  - E2E: the desktop and mobile projects each get their own upload tenant, and the new-quote tests run in order. The E2E worker runs a project named "E2E איטי" slowly, so a test can cancel mid-run. The hook lives in `devtools/e2e.py`, not in the product code.
  - Tests and E2E use their own prefixed SQS queues, so a running `make dev` worker never takes their messages.
- **Bugs logged:** BUG-004 (P3, the rail email wrapped onto two lines; fixed).
- **Follow-ups:**
  - S08:
    - Replace the stage-1 stub: classification, page hashes, `title_block`.
    - The 01 §4.5 revision check (same drawing number, or ≥50% identical pages) and the `revision_counted_as_new` notice.
    - HEIC thumbnails, EXIF rotation, and a real DPI for image page sizes.
    - Make the done step's page-kind select editable.
  - S06: the eval harness can drive this pipeline (`Worker.run_until_idle`, as the integration tests do).
  - S07 gate:
    - A per-tenant concurrency limit for the pipeline (00 §4.3).
    - Re-queue a drawing whose stage-1 message was never sent because SQS failed after the commit; today it would stay `uploaded`.
    - Stage summaries for stages 2–7 once they are real.
  - S29: KMS encryption with the tenant key (`s3_sse=aws:kms`), and the queues and bucket from infrastructure instead of `Queue.ensure`.
