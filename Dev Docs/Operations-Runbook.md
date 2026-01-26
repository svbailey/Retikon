# Operations Runbook

This runbook covers routine checks and incident response for Retikon services.

## Daily checks

- Cloud Run health:
  - Query `/health` or `/healthz` endpoints.
- Error rates:
  - Ingestion 5xx and query p95 alerts.
- DLQ backlog:
  - Ensure DLQ subscription is near zero.
- Snapshot freshness:
  - Review snapshot sidecar timestamp logged on query startup.

## DLQ handling

- Use `scripts/dlq_tool.py` to list, inspect, and replay messages.
- Follow the detailed steps in `Dev Docs/DLQ-Runbook.md`.

## Query incidents

- Check logs for snapshot load errors.
- Confirm `SNAPSHOT_URI` is reachable.
- If needed, roll back snapshot or reload via `/admin/reload-snapshot`.

## Ingestion incidents

- Check ingestion logs for `PermanentError` vs `RecoverableError`.
- Verify raw bucket object size and extension allowlists.
- Confirm Firestore idempotency records.

## Cost controls

- Validate raw bucket lifecycle rule is active (7-day delete).
- Verify `MAX_RAW_BYTES` and `MAX_FRAMES_PER_VIDEO` remain enforced.
- Graph bucket retention: no lifecycle delete; cleanup requires approval.

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
