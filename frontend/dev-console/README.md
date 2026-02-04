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

The visual test mini page is available at:

```
http://localhost:5173/visual-test.html
```

Set the query API URL with:

```bash
export VITE_QUERY_URL="http://localhost:8082/query"
```

Set the dev console API URL (upload/status/manifest preview):

```bash
export VITE_DEV_API_URL="http://localhost:8082"
```

For local ingestion (path-based ingest service):

```bash
export VITE_INGEST_URL="http://localhost:8081/ingest"
```

Optional helpers for the guided workflow UI:

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
2. Open the Dev Console, switch to the Settings tab, and paste the JWT.
3. (Optional) override the Dev API URL, Local Ingest URL, and Query API URL in Settings.
4. Upload an asset and check ingest status.
5. Load the manifest and keyframes preview.
6. Trigger the index build (or run the CLI command).
7. Reload the snapshot, then run a query.
8. Confirm results render with thumbnails, video segments, and scores.

## Deployment (GCS static)

```bash
npm run build
```

Upload `dist/` to a GCS bucket configured for static hosting.

The visual test page is published as `visual-test.html` alongside the main
console.
