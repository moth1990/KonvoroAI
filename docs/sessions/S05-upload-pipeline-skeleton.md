# S05: Upload and pipeline skeleton

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s05-upload-pipeline` |
| **Depends on** | S04 |
| **Status** | todo |
| **PR** | |

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
- [ ] `konboro/contracts/`: Pydantic models for every stage boundary in 00 §5.1 and the side flows in §5.2, field for field from the specs, starting with the minimum each stub needs. Each model gets a JSON-schema snapshot test.
- [ ] `services/storage.py` (S3 via boto3, against S3Mock locally): tenant prefix, server-side encryption flag, presigned GET.
- [ ] `services/queue.py` (SQS via boto3, against ElasticMQ): one queue per stage plus a DLQ, messages `{drawing_id, tenant_id, stage, trace_id}`.
- [ ] `POST /drawings` (multipart). Checks run in the order of 01 §4.3:
  1. quota;
  2. size (20 MB per file);
  3. format by magic bytes (DWG/DXF rejected with the v2.0 message);
  4. page count against the plan.

  Any failure rejects the whole upload with per-file Hebrew errors (01 §8). Then: sha256, store, create drawing and files, reserve quota, enqueue stage 1.
- [ ] New-version mode: `revision_of` an existing quote does not consume quota (01 §4.5).
- [ ] `pipeline/coordinator.py` and the worker loop. Each stage:
  - reads the previous stage's output;
  - runs;
  - writes its output (DB row or S3 JSON);
  - updates `drawings.stage` / `progress`;
  - enqueues the next stage.

  Retries go to the DLQ. On failure, the quota is released.
- [ ] `pipeline/stages/s1…s7`: stubs returning deterministic contract objects (e.g. page count from the PDF, everything else minimal). The stub for stage 7 creates a quote with zero lines.
- [ ] `GET /drawings/{id}/progress` (polling; SSE later if needed) and `POST /drawings/{id}/cancel` (stops the pipeline and releases the quota).
- [ ] The quota is confirmed when the pipeline succeeds.

### Frontend
- [ ] New-quote screen, faithful to the prototype:
  - Mode toggle: new quote or new version.
  - Customer and project fields, or the revision picker.
  - Drop zone and file input, with client-side checks that mirror the server's (size, type).
  - Per-file error chips and remove buttons; clear all; samples.
  - Start is disabled when invalid or when the quota is full.
- [ ] Run step: meter and the 7 stages, from polling `/progress`. Cancel.
- [ ] Done step: summary grid and page thumbnails. The page-kind select is visible but read-only until S08.
- [ ] "To review" navigates to `/review/:quoteId` (placeholder).

### Unit tests
- [ ] Magic-byte detection for pdf, png, jpg, xlsx, csv, zip, dwg and dxf.
- [ ] Check order: the first failing rule wins.
- [ ] Contract schema snapshots.

### Integration tests
- [ ] Upload a golden PDF. The worker runs all 7 stubs through ElasticMQ, a quote exists, and the quota is confirmed.
- [ ] Upload over the size limit, or a DWG: rejected, no quota used.
- [ ] Cancel mid-run: the pipeline stops and the quota is released.
- [ ] A stage that crashes: the message lands in the DLQ, the drawing is marked failed, and the quota is released.
- [ ] Tenant B cannot read A's progress or files.

### UI tests (Playwright)
- [ ] Happy path: upload `golden/NURSERY-1/NURSERY-1.pdf` → progress → done → navigate to review.
- [ ] A DWG file and a 25 MB file show the right chips, and Start stays disabled.
- [ ] Cancel during the run.
- [ ] New-version mode does not change the quota meter.
- [ ] Mobile project for the whole flow.
- [ ] Fidelity report for the new-quote screen (pick, run, done), reviewed by the user.

## Acceptance criteria

- [ ] All tests green in CI. The worker runs inside the CI job against the compose services.
- [ ] Every stage message carries IDs only. No payloads in the queue.
- [ ] The fidelity report has been reviewed.

## Out of scope

- Real stage logic (S08 onward).
- ZIP extraction and multi-file drawings beyond the basic case: keep the limits, implement fully in S08.

## Open questions

- Polling or SSE for progress? Default: polling every 1 s.

## Outcome

- **Done:**
- **Decisions made:**
- **Bugs logged:**
- **Follow-ups:**
