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
- p50 latency (ms): 361.28
- p95 latency (ms): 1333.93
- p99 latency (ms): 34811.39
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-27.
  - Client timeout set to 60s; API key sourced from Secret Manager (`retikon-query-api-key`).
  - Query service tuned: minScale=2, maxScale=40, concurrency=4, cpu=2, memory=4Gi, timeout=120s.
  - Throughput was 4.98 rps for 300 requests; p99 reflects slow tail latency.

### Query (headroom)

- Target QPS: 6 (60s, concurrency 12)
- p50 latency (ms): 314.99
- p95 latency (ms): 443.95
- p99 latency (ms): 13205.73
- Error rate: 0% (0/360)
- Notes:
  - Same service config as above.
  - Throughput was 5.64 rps for 360 requests.

### Query (mode=text baseline)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 321.98
- p95 latency (ms): 499.04
- p99 latency (ms): 773.82
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-27.
  - Payload used `mode=text` (document + transcript only) to skip image/audio embeddings.
  - Query service tuned: minScale=2, maxScale=40, concurrency=4, cpu=2, memory=4Gi, timeout=120s.
  - Warmup enabled: `QUERY_WARMUP=1`, `QUERY_WARMUP_TEXT="retikon warmup"`.
  - Throughput was 4.96 rps for 300 requests.

### Query (default multimodal baseline)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 320.49
- p95 latency (ms): 454.45
- p99 latency (ms): 590.70
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-27.
  - Default query path (no mode/modality filter), so text queries compute text + image-text + audio-text embeddings.
  - Query service tuned: minScale=2, maxScale=40, concurrency=4, cpu=2, memory=4Gi, timeout=120s.
  - Warmup enabled: `QUERY_WARMUP=1`, `QUERY_WARMUP_TEXT="retikon warmup"`.
  - Throughput was 4.97 rps for 300 requests.

### Ingestion

- Target RPS: 1 (count 20, concurrency 4)
- Upload throughput (rps): 14.10
- Completion p50 (s): 6.94
- Completion p95 (s): 61.11
- Notes:
  - Fixtures: `/tmp/retikon_load_fixtures_3SfBDg` (10 files, repeated to 20).
  - Status ended as `COMPLETED` for 20/20 (polling).
