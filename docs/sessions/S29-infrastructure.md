# S29: Infrastructure as code

| | |
| --- | --- |
| **Track** | X |
| **Branch** | `s29-infrastructure` |
| **Depends on** | S28 |
| **Status** | todo |
| **PR** | (link) |

## Goal

The whole of 12 §2 exists as code in one AWS account, in eu-central-1: a staging environment the API and the pipeline workers run in, with Cognito instead of dev auth, Claude through Bedrock, Transcribe for voice, and a pipeline concurrency limit per tenant (00 §4.3). Nothing is deployed by CI yet (S30).

## References

- Specs: 12 §2 (the picture), §3 (server side), §4 (Bedrock), §7 (infrastructure and operations), §9 items 2–4 (Terraform or CDK, the region, Bedrock quotas); 00 §4.3 (per-tenant limits), §8 (isolation), §14.1 (one owner per factory); 13 §4.2 (Transcribe for `voice_input`).
- Prototype: none (no screen).
- Golden: none. The live eval runs on Bedrock once the provider is in (12 §4: changing the provider route needs a golden-set run, non-negotiable 2).
- Earlier sessions: S03 (dev JWT, `current_actor`), S05 (queues, `StageMessage`), S27 (`services/transcribe.py`, the stand-in), S28 (gate 2).
- Bugs: BUG-008 (no per-tenant concurrency limit).
- External: B8 (Bedrock model access and quota in the AWS account, owner: user).

## Tasks

### Infrastructure
- [ ] Terraform or CDK (open question 1): VPC with private subnets, RDS PostgreSQL with pgvector, S3 with KMS and a bucket per environment, SQS (a queue per stage, `konboro-audit`, the DLQ after 3 receives), ECS Fargate (an API service and a workers service, scaled by queue depth), ALB, CloudFront with the app's static files, Secrets Manager, Cognito.
- [ ] The app's roles: `konboro_app` and the NOLOGIN `konboro_promoter` created by the migration step, never the owner at run time (non-negotiable 7).
- [ ] RDS backups and S3 versioning (12 §7), for S32's restore test.

### Backend
- [ ] Cognito tokens in `current_actor`, `tenant_id` from the token, the DB role still the one that counts; dev auth only in `make dev` and tests.
- [ ] `AnthropicProvider.for_bedrock()` behind the settings, the model names with Bedrock's prefix (12 §4).
- [ ] Transcribe behind `services/transcribe.py`'s interface, `he-IL`, never stored (13 §4.2).
- [ ] BUG-008: a per-tenant limit on drawings in the pipeline at once (00 §4.3).

### Unit tests
- [ ] The token verification for Cognito's keys; the provider's model names; the concurrency limit's decision.

### Integration tests
- [ ] A Cognito-shaped token through `require(...)` on the local stack; the limit holds with two tenants' uploads.

### Eval
- [ ] A live eval run through Bedrock, side by side with the direct API (capped).

### Docs
- [ ] CLAUDE.md commands, `.env.example`, a short runbook in `docs/` for the infrastructure code.
- [ ] 12 §9 items 2–4 answered in the spec.

## Acceptance criteria

- [ ] `terraform plan` (or `cdk diff`) is clean against the created staging environment.
- [ ] The API and one worker run in ECS staging, reach RDS, S3 and SQS, and a drawing goes through the 7 stages there.
- [ ] Login on staging is Cognito's; a token for one tenant never reads another's rows (the RLS suite's cases, by hand on staging).
- [ ] A live eval through Bedrock is recorded under Outcome.

## Out of scope

- CI deploys, Sentry, OpenTelemetry, CloudWatch dashboards, the per-tenant cost table (S30).
- The OCR engine (S31).
- The security review, the restore test, the staging E2E (S32).

## Open questions

1. Terraform or CDK (12 §9 item 2).
2. eu-central-1, or il-central-1 after checking every service of 12 §2 there (12 §9 item 3).
3. Bedrock quotas: tokens per minute for a typical drawing, and the increase to ask for before the pilot (12 §9 item 4, B8).
4. The per-tenant limit's number, and whether a waiting drawing shows as queued on the run step.

## Outcome

Filled in at `/session-close`.

- **Done:**
- **Decisions made:**
- **Eval / metrics:**
- **Bugs logged:**
- **Follow-ups:**
