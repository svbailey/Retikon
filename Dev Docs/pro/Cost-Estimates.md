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

## Ingest cost per object (completion envelope)

Ingestion completion (20–40 object runs):

- p50 14.12s → 14.12 vCPU-s, 56.48 GiB-s
- p95 58.56s → 58.56 vCPU-s, 234.24 GiB-s

Notes:
- These are end-to-end completion times, not pure CPU time. Use them as a
  conservative envelope when estimating costs and capacity.

## Guardrails that cap cost growth

- `MAX_RAW_BYTES=500000000` (per object)
- `MAX_VIDEO_SECONDS=300`
- `MAX_AUDIO_SECONDS=1200`
- `MAX_FRAMES_PER_VIDEO=600`
- `MAX_QUERY_BYTES=4000000`
- `MAX_IMAGE_BASE64_BYTES=2000000`
- Per-tenant rate limits (`RATE_LIMIT_*_PER_MIN`)
- Optional global limits (`RATE_LIMIT_GLOBAL_*_PER_MIN`)

## Pricing formula (plug in current rates)

- Query: `(vCPU-s * price_vcpu) + (GiB-s * price_mem)`
- Ingest: `(vCPU-s * price_vcpu) + (GiB-s * price_mem)`
