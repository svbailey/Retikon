# Sprint Plan v3.05

This plan is aligned to the current Retikon v2.5 code paths and the
Model-Usage Audit. It assumes default-on feature flags, no backfill, and
clean staging validation. All schema changes are additive.

## Global Constraints

- Sprints are 2 weeks; features ship default-on with kill switches.
- No backfill. New features apply to new ingests only; queries must handle
  missing columns/tables gracefully.
- Clean staging environment for every sprint. No reuse of prod data.
- GraphAr changes are additive only and keep UUIDv4 IDs.
- Use union_by_name for schema version drift.

## Default Budgets (Initial Values)

- Rerank:
  - RERANK_TOP_N=100
  - RERANK_BATCH_SIZE=16
  - RERANK_QUERY_MAX_TOKENS=64
  - RERANK_DOC_MAX_TOKENS=256
  - RERANK_TIMEOUT_S=2.0 (skip on timeout)
- OCR:
  - OCR_IMAGES=1
  - OCR_KEYFRAMES=1
  - OCR_MAX_KEYFRAMES=8
  - OCR_TIMEOUT_S=2.0
  - OCR_TOTAL_BUDGET_MS=5000
  - OCR_MIN_TEXT_LEN=8
- Windowed CLAP:
  - AUDIO_SEGMENT_WINDOW_S=5
  - AUDIO_SEGMENT_HOP_S=5
  - AUDIO_SEGMENT_MAX_SEGMENTS=120
- Vision v2 and Text v2:
  - VISION_V2_TIMEOUT_S=2.0
  - TEXT_V2_TIMEOUT_S=2.0
  - TEXT_V2_MAX_TOKENS=512
- Video embeddings:
  - VIDEO_CLIP_WINDOW_S=4
  - VIDEO_CLIP_HOP_S=4
  - VIDEO_CLIP_MAX_CLIPS=60
- Analyze:
  - ANALYZE_MAX_EVIDENCE=40
  - ANALYZE_MAX_OUTPUT_TOKENS=1000
  - ANALYZE_TIMEOUT_S=30
- Detect/Track:
  - DETECT_MAX_FRAMES=120
  - DETECT_MAX_FPS=2
  - DETECT_TIMEOUT_S=60

## Sprint 0: Measurement + Safety Defaults

Goal: Baseline evaluation and auditability so improvements are measurable.

Tasks
- Add golden query pack and eval harness (MRR/top-k overlap/latency per modality).
  - Code: retikon_core/query_engine/query_runner.py
  - Fixtures: tests/fixtures/eval/README.md, tests/fixtures/eval/golden_queries.json
  - Optional CLI: retikon_cli/cli.py
- Add embedding backend metadata in GraphAr core rows.
  - Schemas: retikon_core/schemas/graphar/DocChunk/prefix.yml
    retikon_core/schemas/graphar/Transcript/prefix.yml
    retikon_core/schemas/graphar/ImageAsset/prefix.yml
    retikon_core/schemas/graphar/AudioClip/prefix.yml
  - Writers: retikon_core/ingestion/pipelines/document.py
    retikon_core/ingestion/pipelines/image.py
    retikon_core/ingestion/pipelines/audio.py
    retikon_core/ingestion/pipelines/video.py
- Normalize stub embeddings (L2) to match HF/ONNX behavior.
  - Code: retikon_core/embeddings/stub.py
  - Tests: tests/core/test_embedding_backends.py
- Add config flags with default-on values and kill switches.
  - Code: retikon_core/config.py, retikon_core/services/query_config.py
  - IaC: infrastructure/terraform/variables.tf, infrastructure/terraform/main.tf
    infrastructure/terraform/terraform.tfvars.example

Acceptance
- Eval harness runs on clean staging dataset.
- Embedding metadata is present in newly ingested core rows.
- Stub vectors are L2-normalized.

## Sprint 1: Reranker (A)

Goal: Improve ordering quality without changing retrieval recall.

Tasks
- Implement reranker backend (HF, optional ONNX) with timeouts.
  - Code: retikon_core/embeddings/rerank_backend.py
  - Export/quantize: scripts/download_models.py, scripts/export_onnx.py,
    scripts/quantize_onnx.py
- Integrate rerank into query runner with candidate text assembly.
  - Code: retikon_core/query_engine/query_runner.py
- Add default-on rerank configs.
  - Code: retikon_core/services/query_config.py
  - IaC: infrastructure/terraform/variables.tf, infrastructure/terraform/main.tf

Acceptance
- Golden pack shows top-5 precision improvement on text-bearing queries.
- Rerank skipped for non-text-only results.

## Sprint 2: OCR for Images and Keyframes (B)

Goal: Enable text search inside images and video frames.

Tasks
- Add OCR for images and keyframes; keep PDF OCR behavior.
  - Code: retikon_core/ingestion/ocr.py
    retikon_core/ingestion/pipelines/image.py
    retikon_core/ingestion/pipelines/video.py
- Store OCR output as DocChunks with source metadata.
  - Schema: retikon_core/schemas/graphar/DocChunk/prefix.yml
  - Writers: retikon_core/ingestion/pipelines/image.py
    retikon_core/ingestion/pipelines/video.py
- Add OCR configs and caps (default-on).
  - Code: retikon_core/config.py
  - IaC: infrastructure/terraform/variables.tf, infrastructure/terraform/main.tf

Acceptance
- OCR text appears in new DocChunks with source metadata on new ingests.
- OCR workload respects time and frame caps.

## Sprint 3: Windowed CLAP Audio Segments (C)

Goal: Enable timestamped audio search, not just clip-level matching.

Tasks
- Add AudioSegment GraphAr schema and writer.
  - Schema: retikon_core/schemas/graphar/AudioSegment/prefix.yml
  - Writers: retikon_core/ingestion/pipelines/audio.py
    retikon_core/ingestion/pipelines/video.py
- Index AudioSegment clap embeddings.
  - Code: retikon_core/query_engine/index_builder.py
- Query AudioSegment for audio modality and return timestamps.
  - Code: retikon_core/query_engine/query_runner.py
- Add window/hop/cap configs (default-on).
  - Code: retikon_core/config.py
  - IaC: infrastructure/terraform/variables.tf, infrastructure/terraform/main.tf

Acceptance
- Audio queries return precise time ranges for new ingests.

## Sprint 4: Vision Encoder v2 (SigLIP2) (D)

Goal: Add a modern vision encoder without removing CLIP.

Tasks
- Add v2 image/text embedders (HF + optional ONNX).
  - Code: retikon_core/embeddings/stub.py
    retikon_core/embeddings/onnx_backend.py
  - Models: scripts/download_models.py, scripts/export_onnx.py
- Dual-write image vectors at ingest (v1 + v2).
  - Code: retikon_core/ingestion/pipelines/image.py
    retikon_core/ingestion/pipelines/video.py
- Add v2 vector column + HNSW index.
  - Schema: retikon_core/schemas/graphar/ImageAsset/prefix.yml
  - Index: retikon_core/query_engine/index_builder.py
- Merge v1/v2 in queries when v2 is available.
  - Code: retikon_core/query_engine/query_runner.py

Acceptance
- Vision v2 index builds for new ingests; queries return merged results.

## Sprint 5: Text Encoder v2 (BGE-M3) (E)

Goal: Higher quality text retrieval and multilingual coverage.

Tasks
- Add v2 text embedder (HF + optional ONNX).
  - Code: retikon_core/embeddings/stub.py
    retikon_core/embeddings/onnx_backend.py
  - Models: scripts/download_models.py, scripts/export_onnx.py
- Dual-write text vectors for DocChunk and Transcript.
  - Code: retikon_core/ingestion/pipelines/document.py
    retikon_core/ingestion/pipelines/audio.py
    retikon_core/ingestion/pipelines/video.py
- Add v2 vector columns + HNSW indexes.
  - Schema: retikon_core/schemas/graphar/DocChunk/prefix.yml
    retikon_core/schemas/graphar/Transcript/prefix.yml
  - Index: retikon_core/query_engine/index_builder.py
- Merge v1/v2 in query runner when v2 is available.
  - Code: retikon_core/query_engine/query_runner.py

Acceptance
- Text v2 index builds for new ingests; queries return merged results.

## Sprint 6: Video Embeddings (F)

Goal: Action-aware retrieval beyond keyframes.

Tasks
- Add VideoClip schema and writer with windowed embeddings.
  - Schema: retikon_core/schemas/graphar/VideoClip/prefix.yml
  - Writer: retikon_core/ingestion/pipelines/video.py
- Add video embedding backend and download/export path.
  - Code: retikon_core/embeddings/
  - Models: scripts/download_models.py
- Add HNSW index and query support.
  - Code: retikon_core/query_engine/index_builder.py
    retikon_core/query_engine/query_runner.py

Acceptance
- Video clip index builds on new ingests and supports action queries.

## Sprint 7: Analyze Endpoint (G)

Goal: Retrieval-first analysis with summaries and structured outputs.

Tasks
- Add analyze endpoint with evidence retrieval and caching.
  - Code: gcp_adapter/query_service.py, retikon_core/services/analyze_service.py
- Store analyze outputs as artifacts.
  - Code: retikon_core/storage/paths.py
  - Schema or control store: new GraphAr or control-plane path
- Add default-on configs and caps.
  - Code: retikon_core/services/query_config.py

Acceptance
- Analyze endpoint returns structured output with evidence links.

## Sprint 8: Detect/Track On Demand (H)

Goal: Evidence-grade monitoring on demand.

Tasks
- Add detection/tracking worker and API.
  - Code: gcp_adapter/, retikon_core/detect/
- Store evidence artifacts and link to clips/frames.
  - Code: retikon_core/storage/paths.py
  - Schema: new GraphAr or control-plane path
- Add default-on configs and caps.
  - Code: retikon_core/config.py

Acceptance
- Detect/track results produce stored evidence artifacts for new requests.

## Sprint 9: Docs Alignment (Mandatory)

Goal: Ensure documentation matches actual code behavior.

Tasks
- Update model, config, and schema references:
  - README.md
  - Dev Docs/Retikon-GCP-Build-Kit-v2.5.md
  - Dev Docs/Environment-Reference.md
  - Dev Docs/Local-Development.md
  - Dev Docs/pro/Metrics-Reference.md
  - Dev Docs/pro/Index-Optimization-Plan.md
- Sync GraphAr schema docs:
  - retikon_core/schemas/graphar/README.md
- Update Model-Usage Audit and add a doc sync checklist:
  - Dev Docs/Model-Usage-Audit.md

Acceptance
- Docs pass a manual audit against code and new defaults.
