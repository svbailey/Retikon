# Load Testing

Pro only. This runbook applies to Retikon Pro (GCP).

This doc captures the minimal load test procedure for the query and ingestion
services, plus the results record to fill before release.

## Prerequisites

- Cloud Run query URL (`QUERY_URL`).
- JWT token (`RETIKON_AUTH_TOKEN`).
- Raw bucket (`RAW_BUCKET`) and ADC credentials for uploads.
- Python dependencies installed:
  - `pip install -r requirements-dev.txt`
- Optional (ONNX/quantized backends):
  - `pip install onnxruntime`

## Query load test

Command (example):

```bash
QUERY_URL="https://<query-service>/query" \
RETIKON_AUTH_TOKEN="<jwt>" \
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
  --auth-token "$RETIKON_AUTH_TOKEN" \
  --qps 2 \
  --duration 30 \
  --image-path tests/fixtures/sample.jpg
```

Capture output JSON and record the latencies below.

### Optional ONNX/quantized setup

Export ONNX artifacts and enable the backend before running benchmarks:

```bash
EXPORT_ONNX=1 MODEL_DIR=/app/models python scripts/download_models.py
QUANTIZE_ONNX=1 MODEL_DIR=/app/models python scripts/download_models.py
```

Then set `EMBEDDING_BACKEND=onnx` or `EMBEDDING_BACKEND=quantized` on the query
service and re-run the load tests for comparison.

### SLO split: text-only vs multimodal

Run two baselines and record each separately:

- Text-only: send `mode=text` and confirm only text embeddings run.
- Multimodal: default mode (text + image-text + audio-text).

If you run a GPU tier, repeat the same two baselines against the GPU query URL
and record the deltas (p50/p95/p99). This is the release SLO for Sprint 9.

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
  - Client timeout set to 60s; JWT sourced from the configured IdP.
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

### Query (mode=text ONNX)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 803.77
- p95 latency (ms): 1047.22
- p99 latency (ms): 42777.79
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-29.
  - Embedding backend: `EMBEDDING_BACKEND=onnx`.
  - Query image: `dev-20260129-080400-onnx`.
  - Payload used `mode=text`.
  - Throughput was 4.94 rps for 300 requests.
  - Re-test on 2026-01-29: p50 819.68 ms, p95 990.93 ms, p99 1111.70 ms, errors 0/300.
  - Cloud Run logs show 42-45s requests at 2026-01-29T08:58:45Z and startup probes at 08:57-08:59Z; no >10s requests in the last 5 minutes after re-test.

### Query (default multimodal ONNX)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 869.97
- p95 latency (ms): 1095.20
- p99 latency (ms): 1269.78
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-29.
  - Embedding backend: `EMBEDDING_BACKEND=onnx`.
  - Query image: `dev-20260129-080400-onnx`.
  - Default query path (no mode/modality filter).
  - Throughput was 4.93 rps for 300 requests.

### Query (mode=text quantized)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 653.51
- p95 latency (ms): 882.37
- p99 latency (ms): 39912.46
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-29.
  - Embedding backend: `EMBEDDING_BACKEND=quantized`.
  - Query image: `dev-20260129-080400-onnx`.
  - Payload used `mode=text`.
  - Throughput was 4.93 rps for 300 requests.
  - Cloud Run logs show two 39-40s requests at 2026-01-29T09:06:35Z.
  - Re-test on 2026-01-29: p50 615.45 ms, p95 852.01 ms, p99 911.85 ms, errors 0/300.
  - No >10s requests in the last 10 minutes after re-test.

### Query (default multimodal quantized)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 789.86
- p95 latency (ms): 959.55
- p99 latency (ms): 1081.45
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-29.
  - Embedding backend: `EMBEDDING_BACKEND=quantized`.
  - Query image: `dev-20260129-080400-onnx`.
  - Default query path (no mode/modality filter).
  - Throughput was 4.94 rps for 300 requests.

### Decision (backend default)

- Date: 2026-01-29
- Decision: keep HF (default) as the production backend; ONNX/quantized remain optional.
- Rationale:
  - HF baseline (2026-01-27) shows lower p50/p95/p99 than ONNX/quantized.
  - ONNX/quantized runs showed intermittent long-tail spikes during some tests.
  - No cost/CPU utilization data yet to justify higher latency.
- Action taken:
  - `query_embedding_backend` reverted to empty string (HF default) via Terraform apply.

### Query (HF sanity re-test after revert)

- Target QPS: 5 (60s, concurrency 10)
- p50 latency (ms): 784.29
- p95 latency (ms): 2045.90
- p99 latency (ms): 39761.85
- Error rate: 0% (0/300)
- Notes:
  - Test ran against `https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query` on 2026-01-29.

### Query (CPU vs GPU, low-load comparison)

- Date: 2026-01-29
- Parameters: qps=2, duration=60s, concurrency=2, top_k=5, timeout=60s.
- GPU config: minScale=1, concurrency=1, region=us-east4.
- Note: GPU uses the same us-central1 graph bucket (cross-region reads).

| Modality | CPU p50/p95/p99 (ms) | GPU p50/p95/p99 (ms) | Errors (CPU/GPU) |
| --- | --- | --- | --- |
| text | 508 / 614 / 671 | 507 / 580 / 681 | 0 / 0 |
| image_text | 503 / 542 / 591 | 501 / 514 / 532 | 0 / 0 |
| audio_text | 480 / 518 / 554 | 489 / 509 / 510 | 0 / 0 |
| multimodal | 571 / 640 / 741 | 522 / 559 / 589 | 0 / 0 |
| image_base64 | 641 / 803 / 855 | 507 / 800 / 1706 | 0 / 0 |

### Query (CPU vs GPU, QPS=5, opt2 build)

- Date: 2026-01-29
- Parameters: qps=5, duration=60s, concurrency=10, top_k=5, timeout=60s.
- Images: CPU `dev-20260129-123607-opt2`, GPU `dev-20260129-123607-opt2`.
- GPU config: minScale=1, concurrency=1, region=us-east4; graph bucket in us-central1.

| Modality | CPU p50/p95/p99 (ms) | GPU p50/p95/p99 (ms) | Errors (CPU/GPU) |
| --- | --- | --- | --- |
| text | 425.34 / 689.64 / 1026.98 | 3479.66 / 3631.08 / 3666.97 | 0 / 0 |
| image_text | 363.59 / 490.53 / 613.61 | 3260.94 / 3394.01 / 3420.74 | 0 / 0 |
| audio_text | 340.76 / 423.67 / 570.87 | 3136.70 / 3273.37 / 3288.65 | 0 / 0 |
| multimodal | 470.75 / 741.68 / 845.81 | 3742.24 / 3881.45 / 3909.84 | 0 / 0 |
| image_base64 | 713.81 / 1491.75 / 4984.22 | 4105.78 / 4244.40 / 4349.84 | 0 / 0 |

- Notes:
  - CPU throughput ~4.95 rps; GPU throughput ~2.4–3.2 rps (single concurrency).
  - GPU slower across all modalities at QPS=5; likely cross-region reads + low concurrency.

### Ingestion (fixture sweep)

- Date: 2026-01-29
- Parameters: 10 fixtures, concurrency=4, poll enabled.
- Results: throughput 13.18 rps; completion p50=26.64s, p95=64.38s.
  - Backend set to default (HF).
  - Cloud Run logs show 38–45s requests at 2026-01-29T09:15:53Z and 09:15:59Z.
- Re-run 2026-01-29 (20 fixtures, concurrency=4, poll enabled):
  - Throughput 13.81 rps; completion p50=37.58s, p95=85.17s.
  - Uploads 20, bytes_total 95,700.

### Investigation notes (cold starts)

- Service config at 2026-01-29: minScale=2, maxScale=40, containerConcurrency=2, cpu=4, memory=8Gi, timeout=120s, QUERY_WARMUP=1.
- Load tests used concurrency=10, so Cloud Run needed to scale beyond minScale (new instances warm up).
- Cloud Run logs show repeated STARTUP probe events around the test windows, and >10s requests align with those windows.
- Warmup logs show repeated warnings: "Query model warmup failed" with error "mean must have 1 elements if it is an iterable, got 3".
- Warmup timings (examples): text_embed_ms ~12–33s; image_text_embed_ms ~2–5s; audio_text_embed_ms ~5–9s.
- Likely root cause of 40s p99 tail: cold-start + long warmup on new instances.
- Mitigation applied: `query_min_scale=5` and `QUERY_WARMUP_STEPS=text` (config) to reduce cold-start tail.
- Re-test after mitigation (2026-01-29):
  - mode=text: p50 496.46 ms, p95 793.92 ms, p99 1101.07 ms, errors 0/300.
  - default: p50 541.03 ms, p95 822.52 ms, p99 931.50 ms, errors 0/300.
  - No >10s requests in the last 15 minutes.
- Warmup fix deployed (image `dev-20260129-094559-warmup`), warmup completed (text-only) with `text_embed_ms` ~20–24s.
- Re-test after warmup fix + minScale=5 (2026-01-29):
  - mode=text: p50 601.23 ms, p95 852.75 ms, p99 1038.39 ms, errors 0/300.
  - default: p50 622.56 ms, p95 1987.39 ms, p99 11672.58 ms, errors 0/300.
  - Logs show 10–12s requests at 2026-01-29T10:07:44Z during default (multimodal) run.
- Warmup expanded to `text,image_text,audio_text` (2026-01-29):
  - Warmup completed with timings: text ~24–25s, image_text ~3–4s, audio_text ~4.8–6.8s.
  - mode=text: p50 531.28 ms, p95 828.19 ms, p99 905.14 ms, errors 0/300.
  - default: p50 712.68 ms, p95 1070.06 ms, p99 1322.76 ms, errors 0/300.
  - No new >10s requests since warmup expansion; last >10s entries were at 10:07:44Z (before re-test).

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
