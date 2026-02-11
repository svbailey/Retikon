# Retikon Ingest + Index Optimization Plan (Execution Ready)

Status: Draft
Owner: Product + Eng
Last Updated: 2026-02-10

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
- Docs: wall_s p95 <= 2s
- Images: wall_s p95 <= 10s
- Audio: wall_s p95 <= 30s for speech clips; silent/no-speech assets p95 <= 2s
- Video: queue_s p95 <= 5s; wall_s p95 <= 60s for short clips; no-speech/no-audio p95 <= 5s

Index SLOs:
- Index build: duration_s p95 <= 60s for micro-batch size N (define N)
- Freshness: index_queue_length p95 <= threshold (e.g., <= 50 pending manifests)

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

### Firestore ingest record fields (top-level)

Identity:
- ingest_id (string)
- org_id (string)
- asset_uri (string)
- asset_type (docs|images|audio|videos)
- content_hash_sha256 (string)
- audio_track_hash_sha256 (string, nullable)
- cache_hit (bool) and cache_source (none|transcript|embeddings|both)

Timing:
- queue_enqueued_at, queue_dequeued_at (timestamps)
- queue_s (float)
- started_at, updated_at (timestamps)
- wall_s (float)
- pipe_s (float) (compute-only time; excludes queue wait)
- cpu_s (float)
- cold_start (bool, best-effort)
- instance_id (string, best-effort)

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
Acceptance: silent audio/video completes with pipe_s <= 2s p95 and no transcribe model call.

C) Log audio duration + coverage fields  
Where: media.py + pipeline wrappers  
Adds: audio_duration_ms, extracted_audio_duration_ms, trimmed_silence_ms, transcribed_ms  
Acceptance: 0 <= transcribed_ms <= extracted_audio_duration_ms <= audio_duration_ms for 100% of runs.

E) Split modality queues/services  
Where: main.tf (Pub/Sub topics + Cloud Run services), ingestion_service.py routing  
Acceptance: docs/images ingest continues normally while a video backlog exists (no correlated increase in docs/images queue_s).

F) Queue depth + wait time metrics per modality  
Where: ingestion_service.py (emit queue wait per message + periodic queue depth poll)  
Acceptance: dashboard shows queue_depth and queue_s p50/p95 by modality.

H) Lazy-load models by modality  
Where: ingestion_service.py (or model registry)  
Acceptance: docs/images workers do not load transcribe/CLAP dependencies; peak_mb drops materially on doc/image traffic.

K) Indexer timing breakdown  
Where: index_builder.py  
New fields in snapshot report: load_snapshot_s, apply_deltas_s, build_vectors_s, write_snapshot_s, upload_s, total_s  
Acceptance: snapshot report includes timings and sums ~ duration.

S) Standard stage timing map + cold_start flag  
Where: all pipelines  
Acceptance: 100% of ingests have stage_timings_ms; cold start flagged best-effort; stage sum matches pipe_s.

P1 (cost control + tail latency + scalability)
Dependencies: A before B/D; E before G; K before L/M.

B) Transcription tiering (fast vs accurate)  
Where: config.py env + audio.py, video.py selection logic  
Adds: transcript_model_tier, model_calls[].tier  
Acceptance: staging defaults to fast and audio/video transcribe_ms p95 improves vs baseline.

D) Hard transcription caps (asset + org plan)  
Where: config.py, audio.py, video.py  
Status: skipped_too_long or skipped_by_policy  
Acceptance: assets over limit do not call transcribe; fields still emitted; user-visible behavior defined.

G) Increase concurrency/autoscale on heavy services  
Where: main.tf (Cloud Run concurrency, max instances, CPU/mem)  
Acceptance: video queue_s p95 <= target under load test.

I) Keep-warm instances for heavy services  
Where: main.tf min instances; app caches  
Acceptance: cold_start contribution to wall_s p95 decreases for audio/video.

J) Split embed-only vs transcribe-capable services (if needed)  
Note: optional if E already isolates modalities  
Acceptance: embed-only service has lower memory footprint and can scale differently.

L) Micro-batch indexing schedule + queue metric  
Where: scheduler + index_builder.py output + query readiness metric  
Acceptance: index_queue_length is tracked; schedule configurable by N manifests or T minutes.

M) Track HNSW build time + index size delta  
Where: index_builder.py  
New fields: hnsw_build_seconds, index_size_delta_bytes, vectors_added, total_vectors, dim, ef_construction, m  
Acceptance: fields present; can correlate build time to vectors added.

T) Dedupe/caching via hashes  
Where: ingest pipeline store (hash lookup table)  
Acceptance: re-ingesting same asset yields cache_hit=true and cuts pipe_s by >80%.

P2 (ops + economics + lifecycle + quality safety net)

N) Derived-bytes guardrails (by component)  
Where: daily rollup job + alerting  
Acceptance: alert if component bytes spike beyond thresholds.

O) TTL/GC audit script + retention reporting  
Where: ops job  
Acceptance: monthly report proves lifecycle rules executed (counts removed, bytes reclaimed).

P) Downsample policy with quality checks  
Where: image.py, video.py (preprocess)  
Acceptance: derived bytes drop while retrieval quality remains acceptable on regression suite.

Q) Per-asset cost summary aggregator  
Where: metrics aggregator job + Metrics-Reference.md  
Fields: cost_cpu_seconds, cost_model_seconds, cost_raw_bytes, cost_derived_bytes, cost_index_seconds_est  
Acceptance: report generated daily and used for pricing inputs.

R) Publish SLAs + alerts per modality  
Acceptance: SLO doc + alert rules live (see next section).

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
- Collect: queue_s, wall_s, pipe_s, stage timings, error rates

Acceptance harness output:
- p50/p95 by modality
- p95 by stage (transcribe_ms, embed_image_ms, etc.)
- cache hit rate (once T implemented)
- index queue length trend + index duration trend

## Dashboards + alerts

Dashboards (by modality):
- queue_depth + queue_s p50/p95
- wall_s p50/p95, pipe_s p50/p95
- stage p95s (especially transcribe_ms, embed_image_ms)
- error rate + transcript_status distribution
- memory peak (if available) and cold_start rate

Alerts (examples):
- video queue_s p95 > 10s for 5m
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
