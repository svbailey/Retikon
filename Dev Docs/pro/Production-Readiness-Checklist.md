# Production Readiness Checklist (Pro)

Project: simitor
Region: us-central1
Date: 2026-02-03

## 1) Core/Pro boundary
- [x] Core has no GCP imports (CI enforced)
- [x] Core tests green (`pytest tests/core -m core`)
- [x] Pro tests green (`pytest tests/pro -m pro`)

## 2) GCP resources present
- [x] Cloud Run services exist (ingest/query/stream/edge/dev-console)
- [x] Buckets exist (raw/graph/dev-console)
- [x] Firestore default DB enabled
- [x] Pub/Sub topics/subscriptions exist
- [x] JWT issuer/audience/JWKS configured

## 3) Security posture
- [x] Ingestion ingress internal-only in prod
- [x] Query API requires JWT (gateway + in-service validation)

## 4) Tier-3 GCP smoke
- [x] Upload → ingest → Firestore COMPLETED
- [x] Manifest exists
- [x] Query returns results
- [x] Cleanup removes artifacts

## 5) Load testing baseline
- [x] Query baseline recorded (p50/p95/p99)
- [x] Ingest baseline recorded (throughput/latency)

## 6) Ops & monitoring
- [x] Runbooks updated
- [x] Alerts/monitors configured (error rate, latency, DLQ)

## 7) Release sign-off
- [ ] Stakeholder approval
- [ ] Rollback plan verified

## Evidence (latest run)

- Tier-3 smoke (2026-01-28): ingestion COMPLETED, manifest present, query ok, cleanup ok.
- Query load test (2026-02-03): p50 681 ms, p95 973 ms, p99 2526 ms @ ~1 rps (60 reqs, 0 errors) via gateway.
- Query load test (2026-02-03): p50 824 ms, p95 1050 ms, p99 1127 ms @ ~5 rps (300 reqs, 0 errors, timeout=60s). Rate limit temporarily raised to 600/min for baseline, then restored to 60/min.
- Query rate-limit check (2026-02-03): 5 rps for 60s produced 429s after 60 req/min (expected).
- Guardrails (2026-02-03): MAX_QUERY_BYTES=4,000,000 enforced (413 Request too large), MAX_IMAGE_BASE64_BYTES=2,000,000 enforced (413 Image payload too large), top_k>50 rejected (422).
- Ingest sustained load (2026-02-03): 20 objects, p50 14.12s, p95 58.56s, ~20 rps upload, 0 failures.
- Ingest burst load (2026-02-03): 40 objects, p50 11.7s, p95 49.12s, ~36.5 rps upload, 0 failures.
- Cost estimates (2026-02-03): query + ingest compute envelopes documented in `Dev Docs/pro/Cost-Estimates.md`.
- Timeout tests (2026-02-03): Query timeout set to 1s produced 504s under 5 qps image load (image rate limit still at 60/min caused 429s as expected); index-builder job executed with 5s task timeout failed with "configured timeout was reached".
- Global rate-limit (2026-02-03): RATE_LIMIT_GLOBAL_DOC_PER_MIN=5 yielded 6x 429 / 15 requests (keyword) via gateway; restored to 0.
- Inference timeout (2026-02-03): MODEL_INFERENCE_TIMEOUT_S=0.01 produced 504 (image inference timed out after 0.01s) via gateway; restored to 30s.
- Monitoring policies enabled: Retikon Query p95 latency, Retikon Ingest 5xx rate, Retikon DLQ backlog.
- Monitoring dashboard updated via Terraform (2026-02-03): ops dashboard tiles for latency, request rates, CPU/memory, tmpfs, and workflow backlog.
- Synthetic alert test (2026-02-03): temporary policy on query request_count opened/closed alerts; notification channel validated; policy removed.
