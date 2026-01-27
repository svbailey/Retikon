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

### Streaming ingest (dev baseline)

- Target EPS: 10 (60s, concurrency 4)
- p50 ingest latency (ms): 121.97
- p95 ingest latency (ms): 2145.11
- p99 ingest latency (ms): 13166.79
- Error rate: 0% (0/600)
- Notes:
  - Test ran against `https://retikon-stream-ingest-dev-yt27ougp4q-uc.a.run.app/ingest/stream` on 2026-01-27.
  - Throughput achieved: 6.42 eps (600 requests over 93.46s).
  - Payload rotated existing objects: `raw/docs/sample.csv`, `raw/images/sample.jpg`, `raw/audio/sample.wav`.
  - Generation fixed to `1` to avoid duplicate downstream ingestion; dispatch path still exercised.

### Streaming ingest (dev knee sweep)

- Date: 2026-01-27
- Endpoint: `https://retikon-stream-ingest-dev-yt27ougp4q-uc.a.run.app/ingest/stream`
- Payload: `raw/docs/sample.csv`, `raw/images/sample.jpg`, `raw/audio/sample.wav` (generation from GCS metadata)
- Results:
  - 15 EPS (60s, concurrency 6): achieved 14.98 EPS, p50 121.66 ms, p95 1478.12 ms, p99 2462.34 ms, errors 0/900
  - 25 EPS (60s, concurrency 10): achieved 24.75 EPS, p50 127.00 ms, p95 1277.05 ms, p99 1446.53 ms, errors 0/1500
  - 35 EPS (60s, concurrency 14): achieved 34.47 EPS, p50 126.90 ms, p95 1333.61 ms, p99 1796.52 ms, errors 0/2100
- Notes:
  - All requests returned 202; no 429 backpressure observed.
  - stream_id set to `loadtest-<qps>qps` per run.

### Compaction (dev baseline)

- Run ID: `compaction-20260127-160530-c6f46f04-0bf3-4ba9-8cf4-1201df67821d`
- Job: `retikon-compaction-dev` (Cloud Run Jobs) on 2026-01-27
- MediaAsset core: rows_in/out 41, bytes_in 304,868, bytes_out 231,617
- DocChunk core/text/vector: rows_in/out 110, bytes_in 217,314 / 115,724 / 484,176, bytes_out 161,810 / 103,315 / 465,368
- ImageAsset core/vector: rows_in/out 36, bytes_in 117,084 / 114,110, bytes_out 85,899 / 102,102
- AudioClip core/vector: rows_in/out 13, bytes_in 50,336 / 42,281, bytes_out 38,194 / 37,284
- Transcript core/text/vector: rows_in/out 3, bytes_in 11,446 / 2,775 / 13,756, bytes_out 9,308 / 2,239 / 12,916
- DerivedFrom adj_list: rows_in/out 93, bytes_in 52,459, bytes_out 38,620
- NextKeyframe adj_list: rows_in/out 5, bytes_in 1,434, bytes_out 1,434
