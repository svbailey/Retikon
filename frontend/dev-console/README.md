# Retikon Dev Console

Minimal React console for testing Retikon multimodal query APIs.

## Setup

```bash
cd frontend/dev-console
npm install
```

## Run locally

```bash
npm run dev
```

Set the query API URL with:

```bash
export VITE_QUERY_URL="http://localhost:8080/query"
```

Optional helpers for the guided pipeline UI:

```bash
export VITE_RELOAD_URL="http://localhost:8080/admin/reload-snapshot"
export VITE_UPLOAD_URL="https://your-upload-endpoint"
export VITE_RAW_BUCKET="retikon-raw-simitor-dev"
export VITE_RAW_PREFIX="raw"
export VITE_INDEX_URL="https://your-index-trigger-endpoint"
export VITE_INDEX_JOB="retikon-index-builder-dev"
export VITE_INDEX_COMMAND="gcloud run jobs execute retikon-index-builder-dev --region us-central1"
export VITE_REGION="us-central1"
```

## Smoke test

1. Start the query service locally or deploy it to Cloud Run.
2. Open the Dev Console and paste the API key.
3. Upload an asset and trigger the index build (or run the CLI commands).
4. Reload the snapshot, then run a query.
5. Confirm results render with modality icons and scores.

## Deployment (GCS static)

```bash
npm run build
```

Upload `dist/` to a GCS bucket configured for static hosting.
