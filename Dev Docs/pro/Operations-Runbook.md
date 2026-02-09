# Operations Runbook

Pro only. This runbook applies to Retikon Pro (GCP).

This runbook covers routine checks and incident response for Retikon services.

## Nightly GCP smoke

- Run `python scripts/gcp_smoke_test.py` from CI or a trusted workstation.
- Keep artifacts by setting `KEEP_SMOKE_ARTIFACTS=1` when debugging.

## Daily checks

- Cloud Run health:
  - Query `/health` endpoints (ingest, query, audit).
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
    - Terraform: `index_schedule_enabled=true`, `index_schedule`, `index_schedule_timezone`.
  - Manual on-demand trigger via Dev Console `/dev/index-build`.
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
- OCR-specific checks:
  - Confirm `ENABLE_OCR=1` on the ingestion service.
  - Ensure at least one OCR connector is enabled
    (`/data-factory/ocr/connectors`).
  - If multiple are enabled, verify `OCR_CONNECTOR_ID` is set.
  - Verify the token env var named by `token_env` is present on ingestion.

## Office conversion incidents

- Confirm `OFFICE_CONVERSION_MODE` is set appropriately (inline vs queue).
- Inline mode:
  - Verify LibreOffice is installed (`soffice` on PATH or `LIBREOFFICE_BIN` set).
- Queue mode:
  - Confirm Pub/Sub push subscription targets
    `/data-factory/convert-office/worker`.
  - Check DLQ topic (`OFFICE_CONVERSION_DLQ_TOPIC`) for failures.

## Cost controls

- Validate raw bucket lifecycle rule is active (7-day delete).
- Verify `MAX_RAW_BYTES` and `MAX_FRAMES_PER_VIDEO` remain enforced.
- Graph bucket retention: no lifecycle delete; cleanup requires approval.

## Cost spike response

- Check Cloud Billing budget alert details (threshold + overage).
- Review Ops dashboard CPU/memory/tmpfs and request rate panels to identify the driver.
- Confirm rate limits are still enforced (`RATE_LIMIT_*_PER_MIN`, optional global limits).
- If ingestion is the driver:
  - Temporarily disable the Eventarc trigger or set `INGESTION_DRY_RUN=1`.
  - Reduce `ingestion_max_scale` until costs stabilize.
- If query is the driver:
  - Reduce `query_max_scale` and tighten rate limits.
  - Validate snapshot size and query payload guardrails.
- Re-run Tier-3 smoke to validate recovery before re-enabling normal limits.

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

## JWT key rotation

- Rotate signing keys at your IdP and publish updated JWKS.
- Roll Cloud Run services if JWKS caching needs refresh (or shorten cache TTLs).
- Validate:
  - `curl -X POST "$QUERY_URL/query" -H "Authorization: Bearer $RETIKON_AUTH_TOKEN" -H "Content-Type: application/json" -d '{"top_k":1,"query_text":"demo"}'`
- Update any local tooling (Dev Console, load tests) with a fresh JWT.
