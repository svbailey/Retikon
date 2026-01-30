# Tier-3 GCP Smoke (Pro)

Purpose: verify real GCP ingestion + query flow end-to-end with cleanup.

## Prerequisites

- GCP project: simitor (or set `GOOGLE_CLOUD_PROJECT`)
- Region: us-central1 (or set `GOOGLE_CLOUD_REGION`)
- ADC configured: `gcloud auth application-default login`
- Required buckets and services already exist
- JWT issuer/audience/JWKS configured for the environment
- `RETIKON_AUTH_TOKEN` exported for the query call

### CI (Workload Identity Federation)

If running from GitHub Actions, configure these secrets:

- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

These must match the Workload Identity Pool provider and service account
with permissions to GCS, Firestore, Secret Manager, and Cloud Run.

## Run

```bash
python scripts/gcp_smoke_test.py
```

## What it does

1) Uploads a sample file to `RAW_BUCKET`.
2) Waits for Firestore idempotency record to reach `COMPLETED`.
3) Verifies the GraphAr manifest exists in `GRAPH_BUCKET`.
4) Runs a query against `retikon-query-dev`.
5) Cleans up test artifacts unless `KEEP_SMOKE_ARTIFACTS=1`.

## Expected output

- A summary JSON with:
  - uploaded object URI
  - Firestore document ID + status
  - manifest URI
  - query status + result count

## Failure hints

- If ingestion HTTP endpoints return 404, check ingress policy (internal-only).
- If Firestore status stays `PROCESSING`, check ingestion logs and Eventarc.
- If manifest missing, check graph bucket permissions and index writes.
- If query fails, check `retikon-query-dev` logs and JWT configuration.

## Cleanup

By default, the script deletes:
- Raw object uploaded
- Manifest JSON
- Graph data files listed by the manifest

Set `KEEP_SMOKE_ARTIFACTS=1` to keep outputs for inspection.
