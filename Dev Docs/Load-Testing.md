# Load Testing

This doc captures the minimal load test procedure for the query and ingestion
services, plus the results record to fill before release.

## Prerequisites

- Cloud Run query URL (`QUERY_URL`).
- Query API key (`QUERY_API_KEY`).
- Raw bucket (`RAW_BUCKET`) and ADC credentials for uploads.
- Python dependencies installed:
  - `pip install -r requirements-dev.txt`

## Query load test

Command (example):

```bash
QUERY_URL="https://<query-service>/query" \
QUERY_API_KEY="<key>" \
python scripts/load_test_query.py \
  --qps 5 \
  --duration 60 \
  --concurrency 10 \
  --query-text "retikon demo query" \
  --top-k 5
```

Optional image query:

```bash
python scripts/load_test_query.py \
  --url "$QUERY_URL" \
  --api-key "$QUERY_API_KEY" \
  --qps 2 \
  --duration 30 \
  --image-path tests/fixtures/sample.jpg
```

Capture output JSON and record the latencies below.

## Ingestion throughput test

Command (example):

```bash
RAW_BUCKET="<raw-bucket>" \
GOOGLE_CLOUD_PROJECT="<project>" \
python scripts/load_test_ingest.py \
  --source tests/fixtures \
  --count 20 \
  --concurrency 4 \
  --poll \
  --timeout 900
```

This uploads test fixtures to `raw/<modality>/<run-id>/` and (optionally)
waits for Firestore ingestion completion.

## Results record (fill before release)

### Query

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 554.52
- p95 latency (ms): 902.92
- p99 latency (ms): 1396.88
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query`.
  - Timeout set to 60s; query service tuned to concurrency=4, maxScale=50, cpu=2, memory=4Gi.
  - Throughput was 4.93 rps for 300 requests.

### Ingestion

- Target RPS: 1 (count 20, concurrency 4)
- Upload throughput (rps): 18.41
- Completion p50 (s): 37.44
- Completion p95 (s): 97.21
- Notes:
  - Fixtures: `/tmp/retikon_load_fixtures` (10 files, repeated to 20).
  - Status ended as `COMPLETED` for 20/20 (polling).
