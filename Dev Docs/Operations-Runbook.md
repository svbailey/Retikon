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
