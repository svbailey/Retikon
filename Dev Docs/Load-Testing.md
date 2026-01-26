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

- Target QPS: 5 (30s, concurrency 10)
- p50 latency (ms): 458.56
- p95 latency (ms): 2769.45
- p99 latency (ms): 4424.48
- Error rate: 0% (150/150)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query`.

### Ingestion

- Target RPS: 1 (single file, concurrency 1)
- Upload throughput (rps): 3.24
- Completion p50 (s): 6.03
- Completion p95 (s): 6.03
- Notes:
  - Fixture: `tests/fixtures/sample.csv` (18 bytes).
  - Status ended as `COMPLETED`.
