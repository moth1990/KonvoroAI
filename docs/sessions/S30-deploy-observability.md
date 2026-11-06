# S30: Deploy and observability

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s30-deploy-observability` |
| **Depends on** | S29 |
| **Status** | todo |
| **PR** | (link) |

## Goal

A merge to `main` deploys to staging through GitHub Actions after `make check`, and what runs there can be seen: errors in Sentry, one OpenTelemetry trace per drawing across the 7 stages, logs and alarms in CloudWatch, and the model's cost per factory and per flag in a table.

## References

- Specs: 12 §7 (CI/CD, Sentry, CloudWatch and OpenTelemetry, the cost per factory), 01 (`trace_id`), 00 §7.2 (`konboro_llm`'s log per call), 13 §3 rule 4 (every flag measured: users, uses, model cost per factory), 07 §4.3 and §8 (exchange rates from a configured source, `fx_rate_missing`).
- Prototype: none.
- Earlier sessions: S29 (the environment), S01 (CI), S26 decision 6 (the export downloads' log).
- Backlog items scheduled here at Gate 2 (S28): a usage table for every flag (S26 decision 6), exchange rates in production (S18), cassettes that replay the same on every platform (S24b decision 15, BUG-073).

## Tasks

### Backend
- [ ] OpenTelemetry: the drawing's `trace_id` on every stage's spans and every `llm_calls` row.
- [ ] Sentry in the API and the workers, with the tenant as a tag and no customer data in events.
- [ ] The cost table per factory: `llm_calls` and the OCR cost per page (12 §7).
- [ ] `flag_usage`: who used which flag how many times, written by `require_flag`, with the model's cost (13 §3 rule 4).
- [ ] A daily exchange-rate feed into `fx_rates`, and `fx_rate_missing` alerting operations (07 §8).

### CI
- [ ] GitHub Actions: deploy to staging after `make check` on `main`, migrations first, the workers drained before a new version.
- [ ] Cassettes recorded or checked in CI's Linux image, and a tile agent's cassette miss failing the eval in replay (BUG-073).

### Unit tests
- [ ] The cost roll-up, the flag usage counter, the feed's parsing and the alert's decision.

### Integration tests
- [ ] `flag_usage` rows from flagged routes; a trace id from upload to stage 7 on the local stack.

### Docs
- [ ] CLAUDE.md (deploy, where to look), the runbook from S29.

## Acceptance criteria

- [ ] A merge deploys to staging with no manual step, and a failed check stops it.
- [ ] One drawing on staging shows as one trace across the 7 stages, and a forced error reaches Sentry with its tenant.
- [ ] The cost table shows a staging drawing's model cost; the flag table shows a flagged route's use.

## Out of scope

- Production (after Gate 3 and the pilot's go-ahead).
- The OCR engine (S31), the security review and the restore test (S32).

## Open questions

1. The exchange-rate source (07 §4.3 "ממקור מוגדר"): Bank of Israel's representative rate, or another.
2. Who gets the alarms, and where (email, Slack).
3. Staging's data: the demo seed, or empty factories only.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
