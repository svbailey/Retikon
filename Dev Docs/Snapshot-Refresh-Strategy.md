# Snapshot Refresh Strategy

This strategy keeps the query service fast and safe while updating HNSW
snapshots.

## Cadence

- Default cadence: daily or on-demand after ingestion backfills.
- Build via Cloud Run Job `index-builder`.

## Build workflow

1. Run the index builder to create a versioned snapshot:
   - `gs://<graph-bucket>/retikon_v2/snapshots/retikon-YYYYMMDD-HHMM.duckdb`
   - Sidecar: `.../retikon-YYYYMMDD-HHMM.duckdb.json`
2. Validate the build:
   - Inspect the report JSON for row counts and index sizes.
   - Optionally run a local query against the new snapshot to confirm index use.
3. Promote to `retikon.duckdb`:
   - Copy the versioned snapshot to `retikon.duckdb` (and the JSON sidecar).
   - Keep at least N previous snapshots (N >= 3) for rollback.

## Rollback

- If queries regress, repoint `SNAPSHOT_URI` to the prior versioned snapshot, or
  copy the prior snapshot back to `retikon.duckdb`.
- Reload snapshot via `/admin/reload-snapshot` (protected) after update.

## Backfill behavior

- During large backfills, build a snapshot only after ingestion completes.
- Avoid partial updates by gating promotion on manifest completeness.

## Validation checklist

- Query service loads snapshot successfully at startup.
- Sample queries return results without errors.
- p95 latency within target bounds.
