# Operations Runbook

Pro only. This runbook applies to Retikon Pro (GCP).

This runbook covers routine checks and incident response for Retikon services.

## Nightly GCP smoke

- Run `python scripts/gcp_smoke_test.py` from CI or a trusted workstation.
- Keep artifacts by setting `KEEP_SMOKE_ARTIFACTS=1` when debugging.

## Daily checks

- Cloud Run health:
  - Query `/health` or `/healthz` endpoints (ingest, query, audit).
- Error rates:
  - Ingestion 5xx and query p95 alerts.
- DLQ backlog:
  - Ensure DLQ subscription is near zero.
- Snapshot freshness:
  - Review snapshot sidecar timestamp logged on query startup.

## DLQ handling

- Use `scripts/dlq_tool.py` to list, inspect, and replay messages.
- Follow the detailed steps in `Dev Docs/pro/DLQ-Runbook.md`.

## Query incidents

- Check logs for snapshot load errors.
- Confirm `SNAPSHOT_URI` is reachable.
- If needed, roll back snapshot or reload via `/admin/reload-snapshot`.
- Warmup tuning (tail latency):
  - `QUERY_WARMUP=1` enables model warmup at startup.
  - `QUERY_WARMUP_STEPS` controls which warmup steps run.
    - Recommended default for production: `text,image_text,audio_text`.
  - If p99 spikes appear, consider raising `query_min_scale` and ensuring warmup steps complete.

## Snapshot refresh strategy

- Cadence:
  - Dev: rebuild snapshot every 2 hours.
  - Prod: rebuild snapshot every 1 hour.
- Trigger:
  - Scheduled Cloud Run Job (index builder) via Cloud Scheduler.
  - Manual on-demand trigger via Dev Console `/dev/index-build` or CLI.
- Validation:
  - After build, call `/admin/reload-snapshot` on the query service.
  - Run one smoke query to confirm results and response time.
- Rollback:
  - Keep the previous snapshot file for 24 hours.
  - If validation fails, revert `SNAPSHOT_URI` to the previous file and reload.
- SLA:
  - Target freshness: 1–2 hours (worst case).

## Ingestion incidents

- Check ingestion logs for `PermanentError` vs `RecoverableError`.
- Verify raw bucket object size and extension allowlists.
- Confirm Firestore idempotency records.

## Cost controls

- Validate raw bucket lifecycle rule is active (7-day delete).
- Verify `MAX_RAW_BYTES` and `MAX_FRAMES_PER_VIDEO` remain enforced.
- Graph bucket retention: no lifecycle delete; cleanup requires approval.

## Chaos testing (safe defaults)

- Chaos is disabled by default, even in dev. Enable explicitly with:
  - `CHAOS_ENABLED=1`
- Only safe steps are allowed by default:
  - `delay`, `drop_percent`, `retry_jitter`, `rate_limit`
- Guardrails:
  - `CHAOS_MAX_PERCENT_IMPACT` (default 10)
  - `CHAOS_MAX_DURATION_MINUTES` (default 30)
- Admin gating:
  - `CHAOS_REQUIRE_ADMIN=1` in prod (default behavior).

## Secret rotation (query API key)

- Generate a new API key (example):
  - `python - <<'PY'`
  - `import secrets; print(secrets.token_urlsafe(32))`
  - `PY`
- Add a new secret version:
  - `printf '%s' "$NEW_KEY" | gcloud secrets versions add retikon-query-api-key --data-file=- --project $PROJECT_ID`
- Roll the query service to a new revision so it picks up the latest secret:
  - `gcloud run services update retikon-query-dev --region $REGION --project $PROJECT_ID --update-env-vars RETIKON_VERSION=$(date +%Y%m%d%H%M%S)`
- Validate:
  - `curl -X POST "$QUERY_URL/query" -H "X-API-Key: $NEW_KEY" -H "Content-Type: application/json" -d '{"top_k":1,"query_text":"demo"}'`
- Update any local tooling (Dev Console, load tests) with the new key.

## Secret rotation (audit API key)

- By default, audit uses the same Secret Manager key as `QUERY_API_KEY`.
- If you split keys later, rotate the audit key the same way and roll the audit
  service to pick up the new secret.
