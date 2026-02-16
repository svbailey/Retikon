# Cost Estimates (Staging Baseline)

This document records compute envelopes per request/object. Multiply the
vCPU-seconds and GiB-seconds by current Cloud Run pricing to obtain USD.

## Assumptions

- Staging project: `simitor`, region `us-central1`.
- Query service resources: 4 vCPU, 8 GiB memory, timeout 120s.
- Ingestion service resources: 1 vCPU, 4 GiB memory, concurrency 1.
- Baseline latencies collected on 2026-02-03 (see Production-Readiness-Checklist).

## Query cost per request (compute envelope)

Baseline (gateway, 5 qps, 60s, timeout=60s):

- p50 0.824s → 3.30 vCPU-s, 6.59 GiB-s
- p95 1.050s → 4.20 vCPU-s, 8.40 GiB-s
- p99 1.127s → 4.51 vCPU-s, 9.02 GiB-s

Latest eval latency check (staging): eval-20260216-114441
- docs p95 602.04ms, images p95 823.49ms, audio p95 613.24ms, video p95 627.73ms

## Ingest cost per object (completion envelope)

Ingestion completion (20–40 object runs):

- p50 14.12s → 14.12 vCPU-s, 56.48 GiB-s
- p95 58.56s → 58.56 vCPU-s, 234.24 GiB-s

Notes:
- These are end-to-end completion times, not pure CPU time. Use them as a
  conservative envelope when estimating costs and capacity.

## Doc/Image ingest baseline (staging, 2026-02-11)

Run id: `sla-20260211-131546`

Docs:
- cpu_s p50 0.965, p95 1.307
- memory_peak_kb p50 1,209,172 (~1.15 GiB), p95 1,216,244 (~1.16 GiB)
- bytes_derived p50 20,455, p95 20,462

Images:
- cpu_s p50 9.62, p95 10.106
- memory_peak_kb p50 1,769,574 (~1.69 GiB), p95 1,789,883 (~1.71 GiB)
- bytes_derived p50 20,015, p95 20,018

Source:
- `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id sla-20260211-131546 --modalities docs,images`

Follow-up (queue isolation check, 2026-02-11, --unique uploads):
- Run id: queue-baseline-20260211-203152
- Docs: cpu_s p50 0.65, p95 1.355; memory_peak_kb p50 1,594,096 (~1.52 GiB), p95 2,029,294 (~1.94 GiB)
- Images: cpu_s p50 0.705, p95 8.8555; memory_peak_kb p50 1,967,396 (~1.88 GiB), p95 2,035,860 (~1.94 GiB)
- Source: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id queue-baseline-20260211-203152 --modalities docs,images`

Latest SLA run (staging, 2026-02-13, doc-minimal/typical/multipage fixtures):
- Run id: sla-20260213-113957
- Docs: cpu_s p50 0.63, p95 0.883; memory_peak_kb p50 1,887,768 (~1.80 GiB), p95 1,973,760 (~1.88 GiB); bytes_derived p50 21,067, p95 21,225.3
- Images: cpu_s p50 0.67, p95 0.87; memory_peak_kb p50 1,887,768 (~1.80 GiB), p95 1,973,760 (~1.88 GiB); bytes_derived p50 22,099, p95 22,117
- Source: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id sla-20260213-113957 --modalities docs,images`

Embed-only baseline (staging, 2026-02-13, doc/image only):
- Run id: embed-baseline-20260213-103820
- Docs: cpu_s p50 12.45, p95 64.6155; memory_peak_kb p50 2,215,528 (~2.11 GiB), p95 2,283,992 (~2.18 GiB); bytes_derived p50 31,498, p95 35,132.5
- Images: cpu_s p50 0.695, p95 0.988; memory_peak_kb p50 2,179,424 (~2.08 GiB), p95 2,240,308.8 (~2.14 GiB); bytes_derived p50 20,199, p95 20,214.4
- Source: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id embed-baseline-20260213-103820 --modalities docs,images`

Latest embed-only run (staging, 2026-02-16, doc/image only):
- Run id: `embed-only-20260216-101846`
- Docs: cpu_s p50 0.13, p95 0.59; memory_peak_kb p50 1,195,168 (~1.14 GiB), p95 1,204,395 (~1.15 GiB); bytes_derived p50 21,063, p95 21,251
- Images: cpu_s p50 0.115, p95 0.704; memory_peak_kb p50 1,183,300 (~1.13 GiB), p95 1,205,028 (~1.15 GiB); bytes_derived p50 22,318, p95 22,347
- Source: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id embed-only-20260216-101846 --modalities docs,images`

## Guardrails that cap cost growth

- `MAX_RAW_BYTES=500000000` (per object)
- `MAX_VIDEO_SECONDS=300`
- `MAX_AUDIO_SECONDS=1200`
- `MAX_FRAMES_PER_VIDEO=600`
- `MAX_QUERY_BYTES=4000000`
- `MAX_IMAGE_BASE64_BYTES=2000000`
- Per-tenant rate limits (`RATE_LIMIT_*_PER_MIN`)
- Optional global limits (`RATE_LIMIT_GLOBAL_*_PER_MIN`)

## Derived bytes breakdown baseline (staging)

Populate using `scripts/derived_bytes_guardrails.py` and record p95 per component.

- Run id: canary4-20260216-114401
- manifest_b p95: 2906.5
- parquet_b p95: 21675.2
- thumbnails_b p95: 12560.0
- frames_b p95: not emitted (current pipeline metrics)
- transcript_b p95: not emitted (current pipeline metrics)
- embeddings_b p95: not emitted (current pipeline metrics)
- other_b p95: 0.0
- derived_b_total p95: 31869.6
- Baseline file: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/derived-bytes/baseline.json`
- Latest guardrails output: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/derived-bytes/latest.json`

## Per-asset cost rollup (daily)

Generate daily JSONL with `scripts/cost_aggregator.py` and load into analytics.

Latest rollup (staging, 2026-02-16):
- Run id: canary4-20260216-114401
- cpu_seconds p50 0.83, p95 9.1370
- model_seconds p50 0.3930, p95 8.1008
- derived_bytes p50 21346, p95 31868.9
- Output: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/cost-rollups/canary4-20260216-114401.jsonl`
- Latest pointer: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/cost-rollups/latest.jsonl`

## Pricing formula (plug in current rates)

- Query: `(vCPU-s * price_vcpu) + (GiB-s * price_mem)`
- Ingest: `(vCPU-s * price_vcpu) + (GiB-s * price_mem)`
