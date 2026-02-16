# Retikon Ingest + Index Optimization Plan (Execution Ready)

Status: P0/P1 complete in staging; prod rollout pending
Owner: Product + Eng
Last Updated: 2026-02-14

## Goals (what "better" means)

Primary outcomes:
- Audio/video ingest p95 latency drops (mostly by avoiding unnecessary transcription and queueing).
- Docs/images are never blocked by video (queue isolation + scaling).
- Indexing is explainable and predictable (stage breakdown, queue metric, tunable micro-batching).
- Unit economics are measurable (per-asset cost summary and storage guardrails).
- Operational safety (SLOs, alerts, lifecycle enforcement, regression suite).

## Target SLOs (staging defaults)

Use these as acceptance thresholds so "done" is unambiguous.

Ingest SLOs (per modality):
- Docs: wall_ms p95 <= 2000
- Images: wall_ms p95 <= 10000
- Audio: wall_ms p95 <= 30000 for speech clips; silent/no-speech assets p95 <= 2000
- Video: queue_wait_ms p95 <= 5000; wall_ms p95 <= 60000 for short clips; no-speech/no-audio p95 <= 5000

Index SLOs:
- Index build: duration_s p95 <= 60s for micro-batch size N=25
- Freshness: index_queue_length p95 <= 100 pending manifests

Index quality gates (staging):
- Eval set: frozen query + relevance labels per modality (docs/images/audio/video).
- Metrics: recall@10, recall@50, MRR@10; record baseline per modality.
- Gate: no regression > 1.0pp (recall@10), > 0.5pp (recall@50), > 0.5pp (MRR@10) vs baseline.
- Query latency (warm): metadata <= 500ms, text <= 1500ms, audio <= 4000ms, image <= 5000ms, video <= 6000ms.
- Promotion: only promote new snapshots if quality + latency gates pass; otherwise rollback.

Index quality baseline (staging):
- Record baseline after the first eval run and update on model or index changes.

| Modality | recall@10 | recall@50 | MRR@10 | query_p95_ms | eval_run_id |
| --- | --- | --- | --- | --- | --- |
| docs | 1.0 | 1.0 | 1.0 | 777.20 | eval-20260214-171409 |
| images | 1.0 | 1.0 | 1.0 | 918.19 | eval-20260214-171409 |
| audio | 1.0 | 1.0 | 1.0 | 568.87 | eval-20260214-171409 |
| video | 1.0 | 1.0 | 1.0 | 762.21 | eval-20260214-171409 |

- Note: warm run is eval-20260214-171409 (min_scale=1 on query service). Cold-start outlier eval-20260214-164126 had video p95 22329.18ms.
- Latest eval run: eval-20260216-114441 (docs p95 602.04ms, images p95 823.49ms, audio p95 613.24ms, video p95 627.73ms). All modalities are within warm targets.

HNSW sweep plan (staging):
- Fix dataset + eval set + query mix for all runs.
- Build-time params: m in {8, 12, 16, 24}, ef_construction in {100, 150, 200, 300}.
- Query-time params: ef_search in {32, 64, 96, 128}.
- Keep best quality under latency gate; record size delta and build time per run.
- Automation: `scripts/hnsw_sweep.py` (updates HNSW_EF_CONSTRUCTION/HNSW_M and query HNSW_EF_SEARCH).

HNSW sweep results (staging, 200-manifest sample):
- Results file: `tests/fixtures/eval/hnsw_sweep_fast.json`.
- All runs reported recall@10/50 and MRR@10 as 0.0 on this small sample, so the best pick is the lowest mean latency.

| eval_run_id | ef_construction | m | ef_search | recall@10 | recall@50 | MRR@10 | mean_latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hnsw-100-m16-efs64-1771231235 | 100 | 16 | 64 | 0.0 | 0.0 | 0.0 | 637.96 |

## Phase 0 baseline pack (staging)

Baseline run (staging): 2026-02-11
- Run id: sla-20260211-131546
- Bucket/prefix: retikon-raw-simitor-staging / raw_clean

Docs p95 (baseline):
- wall_ms: 2624
- queue_wait_ms: 4600
- pipe_ms: 1852
- stage p95: embed_text_ms 751, write_parquet_ms 756, write_manifest_ms 171, finalize_ms 272

Images p95 (baseline):
- wall_ms: 11453
- queue_wait_ms: 12756
- pipe_ms: 10887
- stage p95: embed_image_ms 9998, write_parquet_ms 559, write_blobs_ms 152, write_manifest_ms 144, decode_ms 78

Latest SLA run (staging): 2026-02-14
- Run id: sla-20260214-123316 (15 min loop, 28 batches x 60 uploads; quality checks passed)

Docs p95 (latest):
- wall_ms: 1496.15
- queue_wait_ms: 16387.87
- pipe_ms: 904.74
- stage p95: embed_text_ms 451.36, write_parquet_ms 350.61, write_manifest_ms 144.69, finalize_ms 1.0, decode_ms 21.0

Images p95 (latest):
- wall_ms: 1460.9
- queue_wait_ms: 17488.81
- pipe_ms: 881.38
- stage p95: embed_image_ms 437.57, write_parquet_ms 232.84, write_blobs_ms 164.19, write_manifest_ms 142.84, decode_ms 2.92

Audio p95 (latest):
- wall_ms: 3697.8
- queue_wait_ms: 17153.08
- pipe_ms: 2264.62
- stage p95: decode_ms 1134.92, embed_audio_ms 526.01, write_parquet_ms 569.64, write_manifest_ms 155.57

Videos p95 (latest):
- wall_ms: 13320.0
- queue_wait_ms: 6494.68
- pipe_ms: 3007.95
- stage p95: decode_ms 935.21, extract_frames_ms 571.32, embed_image_ms 880.16, write_parquet_ms 584.47, write_manifest_ms 145.59

Stage SLO targets (p95, staging)
Docs:
- download_ms <= 150
- decode_ms <= 100
- embed_text_ms <= 600
- write_parquet_ms <= 300
- write_manifest_ms <= 120
- write_blobs_ms <= 100
- finalize_ms <= 120

Images:
- download_ms <= 300
- decode_ms <= 150
- embed_image_ms <= 7000
- write_parquet_ms <= 400
- write_blobs_ms <= 200
- write_manifest_ms <= 120
- finalize_ms <= 150

Accuracy regression suite (docs/images)
- Spec: Dev Docs/pro/Doc-Image-Accuracy-Regression.md
- Run: `python scripts/load_test_ingest.py --source tests/fixtures --count 5 --poll`
- Validate: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id <run-id> --quality-check`
- Latest run (staging): sla-20260214-123316 (quality checks passed)

Cost baseline capture + guardrails
- Tooling: `python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id <run-id>`
- Record baselines in Dev Docs/pro/Cost-Estimates.md (doc/image cpu_s, memory_peak_kb, bytes_derived).
- Guardrails: p95 cpu_s <= 1.5x baseline, p95 bytes_derived <= 2.0x baseline.

## Canonical status taxonomy

transcript_status enum:
- ok | no_speech | no_audio_track | skipped_too_long | skipped_by_policy | failed

Required companion fields (always present, even if skipped/failed):
- transcript_model_tier: fast | accurate | off
- transcript_error_reason: string (empty if not failed)
- transcript_word_count: int (0 if none)
- transcript_language: string (or unknown)
- transcript_confidence: float (0-1, optional if model supports)

## Metrics schema (field names + where to write)

Emit the same schema to:
- Firestore ingest record (source of truth for per-asset metrics)
- Manifest JSON (subset for lineage + debugging)
- Structured logs (for debugging and quick queries)

### Firestore ingest record fields (metrics.* unless noted)

Note: metric fields below are stored under `metrics` in Firestore (e.g., `metrics.queue_wait_ms`).
Identity fields remain top-level.

Identity (top-level):
- ingest_id (string)
- org_id (string)
- asset_uri (string)
- asset_type (docs|images|audio|videos)
- content_hash_sha256 (string)
- audio_track_hash_sha256 (string, nullable)
- cache_hit (bool) and cache_source (none|transcript|embeddings|both)

Timing:
- queue_enqueued_at, queue_dequeued_at (timestamps)
- queue_wait_ms (float)
- started_at, updated_at (timestamps)
- wall_ms (float)
- pipe_ms (float) (compute-only time; excludes queue wait)
- system.cpu_user_s (float)
- system.cpu_sys_s (float)
- system.memory_peak_kb (int)
- system.cold_start (bool, best-effort)
- system.instance_id (string, best-effort)

Bytes:
- raw_b (int)
- derived_b_total (int)
- derived_b_breakdown (map<string,int>):
  - manifest_b, parquet_b, thumbnails_b, frames_b, transcript_b, embeddings_b, other_b
- graph_b_written (int, optional if available per ingest)

Stage timings:
- stage_timings_ms (map<string,int>) with consistent keys:
  - download_ms
  - decode_ms
  - extract_audio_ms
  - extract_frames_ms
  - vad_ms
  - transcribe_ms
  - embed_text_ms
  - embed_image_ms
  - embed_audio_ms
  - write_manifest_ms
  - write_parquet_ms
  - write_blobs_ms
  - finalize_ms

Transcript block (always present on audio/video):
- transcript_status
- transcript_model_tier
- audio_duration_ms
- extracted_audio_duration_ms
- trimmed_silence_ms
- transcribed_ms
- transcript_word_count
- transcript_language
- transcript_confidence
- transcript_error_reason

Embeddings + evidence:
- embeddings (object):
  - text: { count, dim, seconds, bytes }
  - image: { count, dim, seconds, bytes }
  - audio: { count, dim, seconds, bytes }
- evidence (object):
  - frames_count, segments_count, snippets_count
  - evidence_bytes_total (optional)

Model calls (list, one per external/ML call):
- model_calls[] objects:
  - name (transcribe, image_embed, audio_embed, text_embed)
  - model_id (string)
  - tier (fast|accurate)
  - duration_ms (int)
  - success (bool)
  - error (string, nullable)

### Manifest JSON (subset)

Keep it lightweight but include:
- hashes
- transcript_status/tier + durations
- evidence counts
- embedding dims/counts
- derived bytes breakdown
- stage_timings_ms (optional but helpful)

## Work plan (priorities + dependencies + acceptance)

P0 (biggest wins, lowest ambiguity)
Dependencies: A -> (B,D), E -> (G), K -> (L,M), S supports all timing claims.

A) VAD / no-speech / no-audio early exit  
Where: audio.py, video.py  
Adds: vad_ms, transcript_status=no_speech|no_audio_track, transcribe_ms=0, transcript_word_count=0  
Acceptance: silent audio/video completes with pipe_ms <= 2000 p95 and no transcribe model call.

C) Log audio duration + coverage fields  
Where: media.py + pipeline wrappers  
Adds: audio_duration_ms, extracted_audio_duration_ms, trimmed_silence_ms, transcribed_ms  
Acceptance: 0 <= transcribed_ms <= extracted_audio_duration_ms <= audio_duration_ms for 100% of runs.

E) Split modality queues/services  
Where: main.tf (Pub/Sub topics + Cloud Run services), ingestion_service.py routing  
Acceptance: docs/images ingest continues normally while a video backlog exists (no correlated increase in docs/images queue_wait_ms).
Verification: run a video-heavy load test (`python scripts/load_test_ingest.py --mix videos=0.6,images=0.2,docs=0.2 ...`)
and compare docs/images `queue_wait_ms` p95 to a baseline run via `scripts/report_ingest_baseline.py`.
Latest run (staging, 2026-02-11, --unique uploads to avoid dedupe):
- Baseline run id: queue-baseline-20260211-203152
  - docs queue_wait_ms p95: 59082.48 ms (n=30)
  - images queue_wait_ms p95: 58723.69 ms (n=30)
- Video-heavy run id: queue-video-20260211-203326
  - docs queue_wait_ms p95: 3372.88 ms (n=16)
  - images queue_wait_ms p95: 3823.18 ms (n=16)
Notes: docs/images queue_wait_ms did not increase under video backlog; sample sizes improved.

F) Queue depth + wait time metrics per modality  
Where: ingestion_service.py (emit queue wait per message + periodic queue depth poll)  
Acceptance: dashboard shows queue_depth and queue_wait_ms p50/p95 by modality.
Verification: Ops dashboard panels show `retikon_ingest_queue_wait_ms` and `retikon_ingest_queue_depth_backlog`.

H) Lazy-load models by modality  
Where: ingestion_service.py (or model registry)  
Acceptance: docs/images workers do not load transcribe/CLAP dependencies; peak_mb drops materially on doc/image traffic.
Verification: capture docs/images `memory_peak_kb` via `scripts/report_ingest_baseline.py --modalities docs,images`
and record deltas in Dev Docs/pro/Cost-Estimates.md.
Latest run (staging, 2026-02-11, --unique uploads): queue-baseline-20260211-203152
- docs memory_peak_kb p50 1,594,096 (~1.52 GiB), p95 2,029,294 (~1.94 GiB)
- images memory_peak_kb p50 1,967,396 (~1.88 GiB), p95 2,035,860 (~1.94 GiB)

K) Indexer timing breakdown  
Where: index_builder.py  
New fields in snapshot report: snapshot_download_seconds, load_snapshot_seconds, apply_deltas_seconds, build_vectors_seconds, write_snapshot_seconds, upload_seconds, duration_seconds  
Acceptance: snapshot report includes timings and sums ~ duration.

S) Standard stage timing map + cold_start flag  
Where: all pipelines  
Acceptance: 100% of ingests have stage_timings_ms; cold start flagged best-effort; stage sum matches pipe_ms.

P1 (cost control + tail latency + scalability)
Dependencies: A before B/D; E before G; K before L/M.

B) Transcription tiering (fast vs accurate)  
Where: config.py env + audio.py, video.py selection logic  
Adds: transcript_model_tier, model_calls[].tier  
Acceptance: staging defaults to fast and audio/video transcribe_ms p95 improves vs baseline.
Latest run (staging, fast): transcribe-fast-20260213-124252 (audio n=10, videos n=10).
- Audio p95: wall_ms 48884.55, queue_wait_ms 67711.73, transcribe_ms 43739.42.
- Video p95: wall_ms 60841.70, queue_wait_ms 66560.00, transcribe_ms 41006.18.
Latest run (staging, accurate): transcribe-accurate-20260213-125050 (audio n=10, videos n=10).
- Audio p95: wall_ms 54106.20, queue_wait_ms 61836.89, transcribe_ms 48201.91.
- Video p95: wall_ms 67063.70, queue_wait_ms 35141.83, transcribe_ms 45981.81.
Notes: fast transcribe_ms p95 is ~4-5s faster; queue_wait_ms elevated with cold starts (see I).

D) Hard transcription caps (asset + org plan)  
Where: config.py, audio.py, video.py  
Status: skipped_too_long or skipped_by_policy  
Acceptance: assets over limit do not call transcribe; fields still emitted; user-visible behavior defined.
Status: per-org limit set via TRANSCRIBE_MAX_MS_BY_ORG (simitor=20000).
Latest verification (staging): transcribe-cap-20260213-125322 (audio n=2, videos n=2).
- transcript_status=skipped_by_policy, transcript_error_reason=transcribe_org_limit_exceeded, transcribe_ms=0, transcribed_ms=0.

G) Increase concurrency/autoscale on heavy services  
Where: main.tf (Cloud Run concurrency, max instances, CPU/mem)  
Acceptance: video queue_wait_ms p95 <= target under load test.
Latest run (staging): video-queue-20260213-125811 (videos n=10).
- queue_wait_ms p95 2530.45 (meets target).
- wall_ms p95 20905.75.
Notes: run used video-only fixtures; transcribe_ms p95 0 (no audio track).

I) Keep-warm instances for heavy services  
Where: main.tf min instances; app caches  
Acceptance: cold_start contribution to wall_ms p95 decreases for audio/video.
Latest cold_start_rate (staging, sla-20260214-123316): audio 0.11, video 0.10.
Notes: ingestion_media concurrency=2 with min_scale=4; cold_start rates dropped, but video queue_wait_ms p95 is 6494.68 in the mixed SLA run.

J) Split embed-only vs transcribe-capable services (if needed)  
Note: optional if E already isolates modalities  
Acceptance: embed-only service has lower memory footprint and can scale differently.
Embed-only baseline (staging): embed-baseline-20260213-103820.
- Docs memory_peak_kb p95 2,283,992 (~2.18 GiB).
- Images memory_peak_kb p95 2,240,309 (~2.14 GiB).
Latest embed-only run (staging): embed-only-20260216-101846.
- Docs memory_peak_kb p95 1,204,395 (~1.15 GiB); cpu_s p95 0.59.
- Images memory_peak_kb p95 1,205,028 (~1.15 GiB); cpu_s p95 0.704.

L) Micro-batch indexing schedule + queue metric  
Where: scheduler + index_builder.py output + query readiness metric  
Acceptance: index_queue_length is tracked; schedule configurable by N manifests or T minutes.
Defaults (staging): N=25 manifests, T=10 minutes (index_schedule=*/10 * * * *), max_new_manifests=200.

M) Track HNSW build time + index size delta  
Where: index_builder.py  
New fields: hnsw_build_seconds, index_size_delta_bytes, vectors_added, total_vectors, dim, ef_construction, m  
Acceptance: fields present; can correlate build time to vectors added.
Latest index build (staging): retikon-index-builder-staging-vpwt4.
- duration_seconds 1086.0; apply_deltas_seconds 7.64; build_vectors_seconds 19.97; hnsw_build_seconds 19.97.
- index_size_delta_bytes 20,709,376; vectors_added 7; total_vectors 7,603; index_queue_length 0.
Notes: incremental enabled; new_manifest_count=7; snapshot_manifest_count=5,513; manifest_count=5,513.

T) Dedupe/caching via hashes  
Where: ingest pipeline store (hash lookup table)  
Acceptance: re-ingesting same asset yields cache_hit=true and cuts pipe_ms by >80%.
Latest verification (staging, docs-heavy): dedupe-docs-base-20260216-104703 -> dedupe-docs-repeat-20260216-105109.
- cache_hit_rate 1.0 on repeat; pipe_ms p95 drop 99.03% for docs.

P2 (ops + economics + lifecycle + quality safety net)

N) Derived-bytes guardrails (by component)  
Where: `scripts/derived_bytes_guardrails.py` + scheduled job + alerting  
Acceptance: alert if component bytes spike beyond thresholds.  
Verification: run `python scripts/derived_bytes_guardrails.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id <run-id>`.
Latest outputs (staging):
- Baseline: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/derived-bytes/baseline.json` (run id canary4-20260216-114401).
- Latest guardrails: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/derived-bytes/latest.json`.

O) TTL/GC audit script + retention reporting  
Where: `scripts/graph_gc.py` + `scripts/gc_audit_report.py`  
Acceptance: monthly report proves lifecycle rules executed (counts removed, bytes reclaimed).  
Verification: run `python scripts/graph_gc.py --graph-root <graph-root> --include-sizes` (dry run) and `python scripts/gc_audit_report.py --graph-root <graph-root> --limit 1` after an `--execute` run.
Latest audit summary (staging):
- `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/gc-audit/latest.json` (source `gc-20260216-113036.json`, candidate_count=61,848, candidate_bytes=322,922,714, deleted_count=61,848, dry_run=false).

P) Downsample policy with quality checks  
Where: image.py, video.py (preprocess)  
Acceptance: derived bytes drop while retrieval quality remains acceptable on regression suite.  
Defaults (staging): IMAGE_EMBED_MAX_DIM=1024, VIDEO_EMBED_MAX_DIM=640, MAX_FRAMES_PER_VIDEO=300, VIDEO_THUMBNAIL_WIDTH=640, THUMBNAIL_JPEG_QUALITY=80.

Q) Per-asset cost summary aggregator  
Where: `scripts/cost_aggregator.py` + Metrics-Reference.md  
Fields: cost_cpu_seconds, cost_model_seconds, cost_raw_bytes, cost_derived_bytes, cost_index_seconds_est  
Acceptance: report generated daily and used for pricing inputs.  
Verification: run `python scripts/cost_aggregator.py --project simitor --bucket retikon-raw-simitor-staging --raw-prefix raw_clean --run-id <run-id> --output gs://<bucket>/cost-rollups/<run-id>.jsonl`.
Latest outputs (staging):
- `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/cost-rollups/canary4-20260216-114401.jsonl`
- Latest pointer: `gs://retikon-graph-simitor-staging/retikon_v2_demo_20260209_clean/audit/ops/cost-rollups/latest.jsonl`

R) Publish SLAs + alerts per modality  
Acceptance: SLO doc + alert rules live (see next section).
Staging dashboard: `https://console.cloud.google.com/monitoring/dashboards/builder/6ac49812-be84-4c53-957e-353c6f13b72d?project=simitor`
Alert policy IDs (staging):
- Retikon Ingest 5xx rate: `projects/simitor/alertPolicies/10875073443325579203` (duplicate exists at `projects/simitor/alertPolicies/6748294807146535239`)
- Retikon Query 5xx rate: `projects/simitor/alertPolicies/2956657331862272263`
- Retikon Query p95 latency: `projects/simitor/alertPolicies/9792662545742451410`
- Retikon Ingest p95 latency: `projects/simitor/alertPolicies/12781580063648637627`
- Retikon ingest queue wait p95: `projects/simitor/alertPolicies/8307282649155648809`
- Retikon ingest embed_image_ms p95: `projects/simitor/alertPolicies/5163745058832829445`
- Retikon ingest decode_ms p95: `projects/simitor/alertPolicies/13703068267927889981`
- Retikon ingest embed_text_ms p95: `projects/simitor/alertPolicies/10251698153299086884`
- Retikon ingest embed_audio_ms p95: `projects/simitor/alertPolicies/10136383650975844519`
- Retikon ingest transcribe_ms p95: `projects/simitor/alertPolicies/13290920868300759395`
- Retikon ingest write_parquet_ms p95: `projects/simitor/alertPolicies/8780289570620758125`
- Retikon ingest write_manifest_ms p95: `projects/simitor/alertPolicies/4660847698023695515`
- Retikon index queue length: `projects/simitor/alertPolicies/1782690081396754189`
- Retikon DLQ backlog: `projects/simitor/alertPolicies/8198575263140174886`
Latest eval latency check (staging): eval-20260216-114441
- docs p95 602.04ms (<=1500), images p95 823.49ms (<=5000), audio p95 613.24ms (<=4000), video p95 627.73ms (<=6000).

## Test plan

Regression asset suite (staging bucket):
- Audio: silence-only (10s), music/noise (10s), speech (10s, 60s), noisy speech (10s)
- Video: with speech (10s), with silence (10s), no audio track, longer clip (2-5 minutes)
- Images: 256^2, 1024^2, large
- Docs: tiny, typical paragraph, multi-page text

Load test definition (minimum):
- 10 minutes
- Mix: 40% images, 30% docs, 20% audio, 10% video
- Concurrency: 20 in-flight ingests (increase to 50 for stress)
- Collect: queue_wait_ms, wall_ms, pipe_ms, stage timings, error rates
  - Use `--mix` on `scripts/load_test_ingest.py` to enforce the ratio.

Acceptance harness output:
- p50/p95 by modality
- p95 by stage (transcribe_ms, embed_image_ms, etc.)
- cache hit rate (once T implemented)
- index queue length trend + index duration trend

SLA verification workflow (staging):
1. Preflight
   - Confirm metrics coverage for API/GCS/stream paths (queue/wall/pipe + stage_timings_ms).
   - Confirm target run bucket/prefix and baseline run id are set.
   - Ensure fixtures include docs and images (and any modalities under test).
2. Load test run (records run id)
   ```bash
   RUN_ID="sla-$(date +%Y%m%d-%H%M%S)"
   python scripts/load_test_ingest.py --project simitor --bucket retikon-raw-simitor-staging \
     --prefix raw_clean --source tests/fixtures --count 40 --poll --run-id "$RUN_ID"
   ```
3. Generate SLA report + quality checks
   ```bash
   python scripts/report_ingest_baseline.py --project simitor --bucket retikon-raw-simitor-staging \
     --raw-prefix raw_clean --run-id "$RUN_ID" --quality-check
   ```
4. Evaluate deltas vs baseline and stage SLO targets
   - Compare wall_ms/queue_wait_ms/pipe_ms p95 to baseline and SLOs.
   - Compare stage p95 to stage SLO targets (embed_* and write_*).
   - Verify cache_hit metrics when dedupe is enabled.
5. Index SLO check (staging)
   - Trigger the scheduled index build (or manual run if needed).
   - Capture snapshot report fields (snapshot_download_seconds/load_snapshot_seconds/apply_deltas_seconds/build_vectors_seconds/write_snapshot_seconds/upload_seconds/duration_seconds).
   - Verify index build duration p95 and index_queue_length p95 are within targets.
6. Record artifacts
   - Update this doc with the new run id + deltas summary.
   - Update Dev Docs/pro/Cost-Estimates.md if cost guardrails were re-baselined.

Pass/Fail checks:
- Any modality with count=0 is a fail (re-run with the correct fixtures).
- Docs/images wall_ms p95 meet SLOs; stage p95 meets stage targets.
- queue_wait_ms p95 does not regress beyond baseline unless explained (e.g., known backlog).
- Accuracy regression suite passes (no quality_check failures).
- Cost guardrails pass (p95 cpu_s <= 1.5x baseline, p95 bytes_derived <= 2.0x baseline).

Latest canary acceptance runs (staging):
- canary-20260216-112452 (n=40, mixed load): completed all modalities, but queue_wait_ms p95 failed for docs/images/audio/video due concurrent backlog.
- canary2-20260216-112912 (n=12, quick canary): docs wall_ms p95 1766 (pass), images wall_ms p95 10816 (slight fail vs 10000), audio wall_ms p95 33624 (fail vs 30000), video queue_wait_ms p95 1852 (pass).
- canary3-20260216-114015 (n=24, after routing to fast tier revision): docs/images/video passed; audio still failed due fast tier mapping to `small`.
- canary4-20260216-114401 (n=24, fast tier mapped to `tiny` on media service revision `retikon-ingestion-media-staging-00020-bbl`): all ingest SLO checks passed; service later promoted to latest traffic (current latest ready revision `retikon-ingestion-media-staging-00021-ppx`).
- quality_check failures: none across canary1-canary4.

## Dashboards + alerts

Dashboards (by modality):
- queue_depth + queue_wait_ms p50/p95
- wall_ms p50/p95, pipe_ms p50/p95
- stage p95s (especially transcribe_ms, embed_image_ms)
- error rate + transcript_status distribution
- memory peak (if available) and cold_start rate

Alerts (examples):
- video queue_wait_ms p95 > 10000 for 5m
- embed_image_ms p95 > 12000 for 5m
- audio/video failed rate > 1% for 10m
- index_queue_length > 200 for 15m
- derived bytes spike: embeddings_b or thumbnails_b > 2x 7-day baseline

## Rollout mechanics (safe deployment)

Gate A/B/D/P/T behind env flags:
- TRANSCRIBE_ENABLED=1|0
- TRANSCRIBE_TIER=fast|accurate|off
- TRANSCRIBE_MAX_MS=...
- ENABLE_VAD=true|false
- ENABLE_DOWNSAMPLE=true|false
- ENABLE_DEDUPE_CACHE=true|false

Rollout: staging -> canary orgs -> full rollout  
Track: p95 improvements + any drop in transcript availability quality.

## Dependency map (quick)

- S (stage timing map) unlocks trustworthy measurements for everything.
- A + C before B/D (need accurate duration/coverage + no-speech handling first).
- E before G/I/J (scale the right isolated service).
- K before L/M (cannot tune indexing without timing breakdown).
- T benefits from hash fields; implement hashes early.
