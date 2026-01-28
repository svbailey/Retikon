# Production Readiness Checklist (Pro)

Project: simitor
Region: us-central1
Date: 2026-01-28

## 1) Core/Pro boundary
- [x] Core has no GCP imports (CI enforced)
- [x] Core tests green (`pytest tests/core -m core`)
- [x] Pro tests green (`pytest tests/pro -m pro`)

## 2) GCP resources present
- [x] Cloud Run services exist (ingest/query/stream/edge/dev-console)
- [x] Buckets exist (raw/graph/dev-console)
- [x] Firestore default DB enabled
- [x] Pub/Sub topics/subscriptions exist
- [x] Secret Manager API key exists

## 3) Security posture
- [x] Ingestion ingress internal-only in prod
- [x] Query API requires key (Secret Manager wired)

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
- Query load test (2026-01-28): p50 402 ms, p95 438 ms, p99 445 ms @ 1 rps.
- Ingest load test (2026-01-28): 3 objects completed in 1.5s (~2.0 rps), cleanup ok.
- Monitoring policies enabled: Retikon Query p95 latency, Retikon Ingest 5xx rate, Retikon DLQ backlog.
