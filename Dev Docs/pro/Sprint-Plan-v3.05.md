# Sprint Plan v3.05 (Parity Rewrite)

This rewrite keeps the existing v3.05 sequencing and constraints, and adds the
missing product-surface contracts required for TwelveLabs-class parity:

- Search contract (grouping, sorting, pagination, filters, multimodal inputs)
- Embed API (sync + async)
- Task lifecycle as a shared primitive
- Fusion + explainability (`why matched`)
- Analyze structured outputs with evidence grounding
- Optional Entity Search as a later sprint

All schema changes remain additive.

## Global Constraints

- Sprints are 2 weeks; features ship default-on with kill switches.
- No backfill. New features apply to new ingests only; queries must handle
  missing columns/tables gracefully.
- Clean staging environment for every sprint. No reuse of prod data.
- GraphAr changes are additive only and keep UUIDv4 IDs.
- Use `union_by_name=true` for schema version drift.

## TwelveLabs Parity Surfaces (Scope Map)

- P1 Search API
  - Inputs: `query_text`, optional `image_base64`, `mode/modalities`, filters
  - Outputs: canonical `Moment[]` with score, time range, evidence, why matched
  - Features: `group_by`, `sort_by`, pagination, metadata/time filters
- P2 Embed API
  - Sync embeddings for short text/image
  - Async embeddings for long/heavy audio/video
  - Returns vectors + model/dims/normalization/backend metadata
- P3 Analyze API
  - Retrieval-first evidence selection
  - Structured JSON outputs with schema validation
  - Evidence refs to concrete moments
- P4 Optional Entity Search (post Sprint 8)
  - Entity collections, references, entity-based filters/querying

## Cross-Cutting Contracts (Apply to Sprints 1-8)

### A) Canonical Moment Output Schema

Used by Search, Analyze evidence, and Detect/Track outputs.

- `asset_id`, `asset_type`
- `start_ms`, `end_ms` (nullable for docs)
- `score` (normalized 0.0..1.0)
- `modality` (`text|vision|audio|ocr|video`)
- `highlight_text` (required when text-bearing evidence exists)
- `evidence_refs[]` (`doc_chunk_id|transcript_segment_id|image_asset_id|audio_segment_id|video_clip_id`)
- `why[]` (per-modality contribution, rerank metadata, FTS/BM25 reason flags)

### B) Shared Task Lifecycle Contract

Used by Analyze, Detect/Track, async Embed, and long-running media jobs.

- `task_id`, `type`
- `status` (`queued|running|succeeded|failed|canceled`)
- `progress`, `started_at`, `finished_at`
- `error`
- `result_ref` (artifact path or graph/control-plane reference)

### C) Fusion Specification

Define and version the merge strategy:

- Score normalization per modality (cosine to 0..1, BM25 scaling)
- Fusion method v1: weighted RRF
- Reranker scope (which candidates), timeout fallback behavior
- Include fusion telemetry in eval harness and regression tests

### D) Parity Contract Document (Versioned)

Create and maintain one contract doc as the source of truth for API behavior:

- `SearchRequest` / `SearchResponse` (Moment schema, grouping, sorting, pagination, filters)
- `EmbedRequest` / `EmbedResponse` (sync + async)
- Task lifecycle API
- Analyze schema + grounding rules
- Fusion behavior and fallback rules

### E) FilterSpec v1 (Required)

Define filter grammar and metadata source-of-truth in the contract doc:

- Allowed logical nodes: `all[]` (AND), `any[]` (OR), `not`
- Allowed operators: `eq`, `neq`, `in`, `nin`, `gt`, `gte`, `lt`, `lte`,
  `between`, `exists`
- Supported value types: `string`, `number`, `bool`, `time`
- Guaranteed system fields:
  - `asset_id`, `asset_type`, `duration_ms`, `created_at`,
    `source_type`, `start_ms`, `end_ms`
- Custom fields:
  - `metadata.<key>` namespace mapped to control-plane metadata
- Validation behavior:
  - Unknown fields/operators return typed validation errors (no silent ignore)

### F) Pagination Stability Rules (Required)

Define deterministic pagination in the contract doc:

- Cursor-based pagination only (`page_token`), no offset pagination
- Stable sort keys:
  - `sort_by=score`: `score desc`, tie-breakers `asset_id asc`, `start_ms asc`,
    `primary_evidence_id asc`
  - `sort_by=clip_count`: `clip_count desc`, then same tie-breakers
- `page_token` encodes:
  - query fingerprint
  - snapshot/version marker
  - last-sort tuple
- Stability guarantee:
  - deterministic pages for identical request + identical snapshot

### G) Moment Validity Rules (Required)

Each returned moment must include modality-appropriate evidence:

- Text moment: `doc_chunk_id` or `transcript_segment_id` in `evidence_refs[]`
- OCR moment: `doc_chunk_id` with OCR source metadata
- Vision moment: `image_asset_id` (or keyframe-linked image asset id)
- Audio moment: `audio_segment_id`
- Video moment: `video_clip_id`
- Docs-only moments:
  - `start_ms`/`end_ms` are null, but `highlight_text` + evidence refs are
    still required

### H) Fusion v1 Default + Calibration (Required)

Use a concrete default and calibration loop:

- Fusion method v1: weighted RRF
- Initial modality weights:
  - `text=1.0`, `ocr=1.0`, `vision=0.8`, `audio=0.8`, `video=1.0`, `fts=1.2`
- Store fusion metadata in responses/artifacts:
  - `fusion_method`, `weight_version`
- Add calibration task to eval harness:
  - compare weight sets on golden pack
  - persist chosen weight version and metric deltas

### I) Typed Error Contract (Required)

Define one shared error schema across Search/Embed/Tasks/Analyze/Detect:

- `error.code`, `error.message`, `error.details[]`
- baseline codes include:
  - `VALIDATION_ERROR`, `PAYLOAD_TOO_LARGE`, `UNSUPPORTED_MODE`,
    `TASK_NOT_FOUND`, `TIMEOUT`, `INTERNAL_ERROR`
- integration tests validate status + typed error payload shape

## Default Budgets (Initial Values)

- Rerank:
  - `RERANK_TOP_N=20`
  - `RERANK_BATCH_SIZE=8`
  - `RERANK_QUERY_MAX_TOKENS=32`
  - `RERANK_DOC_MAX_TOKENS=128`
  - `RERANK_MIN_CANDIDATES=2`
  - `RERANK_MAX_TOTAL_CHARS=6000`
  - `RERANK_SKIP_SCORE_GAP=1.0`
  - `RERANK_SKIP_MIN_SCORE=0.7`
  - `RERANK_TIMEOUT_S=2.0` (skip on timeout)
- OCR:
  - `OCR_IMAGES=1`
  - `OCR_KEYFRAMES=1`
  - `OCR_MAX_KEYFRAMES=8`
  - `OCR_TIMEOUT_S=2.0`
  - `OCR_TOTAL_BUDGET_MS=5000`
  - `OCR_MIN_TEXT_LEN=8`
- Windowed CLAP:
  - `AUDIO_SEGMENT_WINDOW_S=5`
  - `AUDIO_SEGMENT_HOP_S=5`
  - `AUDIO_SEGMENT_MAX_SEGMENTS=120`
- Vision v2 and Text v2:
  - `VISION_V2_TIMEOUT_S=2.0`
  - `TEXT_V2_TIMEOUT_S=2.0`
  - `TEXT_V2_MAX_TOKENS=512`
- Video embeddings:
  - `VIDEO_CLIP_WINDOW_S=4`
  - `VIDEO_CLIP_HOP_S=4`
  - `VIDEO_CLIP_MAX_CLIPS=60`
- Analyze:
  - `ANALYZE_MAX_EVIDENCE=40`
  - `ANALYZE_MAX_OUTPUT_TOKENS=1000`
  - `ANALYZE_TIMEOUT_S=30`
- Detect/Track:
  - `DETECT_MAX_FRAMES=120`
  - `DETECT_MAX_FPS=2`
  - `DETECT_TIMEOUT_S=60`

## Sprint 0: Measurement + Safety Defaults

Goal: Baseline evaluation and auditability so improvements are measurable.

Tasks
- Add golden query pack and eval harness (MRR/top-k overlap/latency per modality).
  - Code: `retikon_core/query_engine/query_runner.py`
  - Fixtures: `tests/fixtures/eval/README.md`, `tests/fixtures/eval/golden_queries.json`
  - Optional CLI: `retikon_cli/cli.py`
- Add embedding backend metadata in GraphAr core rows.
  - Schemas: `retikon_core/schemas/graphar/DocChunk/prefix.yml`
    `retikon_core/schemas/graphar/Transcript/prefix.yml`
    `retikon_core/schemas/graphar/ImageAsset/prefix.yml`
    `retikon_core/schemas/graphar/AudioClip/prefix.yml`
  - Writers: `retikon_core/ingestion/pipelines/document.py`
    `retikon_core/ingestion/pipelines/image.py`
    `retikon_core/ingestion/pipelines/audio.py`
    `retikon_core/ingestion/pipelines/video.py`
- Normalize stub embeddings (L2) to match HF/ONNX behavior.
  - Code: `retikon_core/embeddings/stub.py`
  - Tests: `tests/core/test_embedding_backends.py`
- Add config flags with default-on values and kill switches.
  - Code: `retikon_core/config.py`, `retikon_core/services/query_config.py`
  - IaC: `infrastructure/terraform/variables.tf`, `infrastructure/terraform/main.tf`
    `infrastructure/terraform/terraform.tfvars.example`

Acceptance
- Eval harness runs on clean staging dataset.
- Embedding metadata is present in newly ingested core rows.
- Stub vectors are L2-normalized.

Sprint 0 acceptance evidence (2026-02-16)
- Clean staging eval executed against `tests/fixtures/eval/golden_queries.json`.
- Output: `tests/fixtures/eval/results-20260216-123153.json`.
- Overall: `recall@10=1.0`, `recall@50=1.0`, `MRR@10=1.0`, `top_k_overlap=1.0`.

## Sprint 1: Reranker + Search Contract v1 (Parity P1 Foundation)

Goal: Improve ordering quality and ship productized search response behavior.

Tasks
- Implement reranker backend (HF, optional ONNX) with timeouts.
  - Code: `retikon_core/embeddings/rerank_backend.py`
  - Export/quantize: `scripts/download_models.py`, `scripts/export_onnx.py`,
    `scripts/quantize_onnx.py`
- Integrate rerank into query runner with candidate text assembly.
  - Code: `retikon_core/query_engine/query_runner.py`
- Add canonical `highlight_text` extraction to winning text-bearing candidates.
  - Code: `retikon_core/query_engine/query_runner.py`
    `retikon_core/services/query_service_core.py`
- Add Search contract v1 request/response fields:
  - request: `group_by=video|none`, `sort_by=score|clip_count`,
    `page_limit`, `page_token`, `filters`
  - mode/modality precedence:
    - `modalities` overrides `mode`
    - `mode` maps to default modality sets when `modalities` is omitted
  - response: canonical `Moment[]` + typed grouping payload:
    - `grouping.total_videos`, `grouping.total_moments`,
      `grouping.videos[].{asset_id, clip_count, best_score, top_moments[]}`
  - Code: `retikon_core/services/query_service_core.py`, `gcp_adapter/query_service.py`
- Implement deterministic cursor pagination with stable tie-breakers.
  - Code: `retikon_core/services/query_service_core.py`
    `retikon_core/query_engine/query_runner.py`
- Add fusion spec v1 implementation and `why[]` contribution logging.
  - Code: `retikon_core/query_engine/query_runner.py`
  - Tests: `tests/pro/test_query_modes.py` and eval harness assertions

Acceptance
- Golden pack shows top-5 precision improvement on text-bearing queries.
- Search supports `group_by=video`, `sort_by=score|clip_count`, stable pagination.
- Grouping output matches contract shape (`total_videos`, `total_moments`, `videos[]`).
- Text-bearing results include `highlight_text`.
- Rerank timeout skip path returns fused results without failure.
- Pagination is deterministic for identical query + snapshot.

Sprint 1 implementation evidence (2026-02-16)
- Runtime implemented:
  - reranker backend module (`retikon_core/embeddings/rerank_backend.py`)
  - weighted-RRF fusion + `why[]` + highlight extraction (`retikon_core/query_engine/query_runner.py`)
  - Search contract v1 request/response + deterministic cursor paging + grouping payload
    (`retikon_core/services/query_service_core.py`)
  - typed error payloads on query endpoints (`gcp_adapter/query_service.py`,
    `local_adapter/query_service.py`)
  - reranker model tooling updates (`scripts/download_models.py`,
    `scripts/export_onnx.py`, `scripts/quantize_onnx.py`)
- Config/IaC wired:
  - query/rerank/fusion env parsing (`retikon_core/services/query_config.py`)
  - Terraform vars/env wiring (`infrastructure/terraform/variables.tf`,
    `infrastructure/terraform/main.tf`, `infrastructure/terraform/terraform.tfvars.example`)
  - environment reference updated (`Dev Docs/Environment-Reference.md`)
- Test coverage added/updated:
  - `tests/pro/test_query_contract_v1.py`
  - `tests/core/test_rerank_backend.py`
  - `tests/core/test_query_runner.py`
  - `tests/core/test_query_service_core.py`
  - `tests/core/test_query_service_config.py`
  - `tests/conftest.py` rate-limit state isolation fixture
- Validation:
  - targeted query/rerank contract suite passed (`47 passed`)
  - full repository suite passed: `244 passed, 17 skipped`
  - metadata namespace filters (`metadata.<key>`) are explicitly blocked with
    typed `UNSUPPORTED_MODE` until control-plane metadata resolver wiring lands.

## Sprint 2: OCR for Images/Keyframes + FTS/BM25 Wiring (Parity P1 Exact Match)

Goal: Make image/keyframe text searchable and improve exact-ID retrieval.

Tasks
- Add OCR for images and keyframes; keep PDF OCR behavior.
  - Code: `retikon_core/ingestion/ocr.py`
    `retikon_core/ingestion/pipelines/image.py`
    `retikon_core/ingestion/pipelines/video.py`
- Store OCR output as DocChunks with source metadata.
  - Schema: `retikon_core/schemas/graphar/DocChunk/prefix.yml`
  - Writers: `retikon_core/ingestion/pipelines/image.py`
    `retikon_core/ingestion/pipelines/video.py`
- Add OCR confidence filtering and optional quality metadata.
  - Code: `retikon_core/ingestion/ocr.py`
- Wire DuckDB FTS extension and BM25 for ID-like queries.
  - Code: `retikon_core/query_engine/warm_start.py`
    `retikon_core/query_engine/index_builder.py`
    `retikon_core/query_engine/query_runner.py`
  - Deployment: production image ships/loads `fts` extension deterministically
    (no runtime surprise installs)
- Add search filters v1 for OCR sources (`source_type`, `asset_id`, keyframe time range).
  - Code: `retikon_core/services/query_service_core.py`
    `retikon_core/query_engine/query_runner.py`
  - Contract: enforce `FilterSpec v1` field/operator validation

Acceptance
- OCR text appears in new DocChunks with source metadata on new ingests.
- FTS/BM25 path runs for ID-like queries and merges with vector results.
- OCR hits return `highlight_text` and `why[]` includes FTS evidence when applicable.
- Queries remain safe for older ingests with no OCR rows (no backfill).

## Sprint 3: Windowed CLAP Audio Segments + Audio UX (Parity P1 Sound Moments)

Goal: Enable timestamped audio search with clean user-facing moments.

Tasks
- Add `AudioSegment` GraphAr schema and writer.
  - Schema: `retikon_core/schemas/graphar/AudioSegment/prefix.yml`
  - Writers: `retikon_core/ingestion/pipelines/audio.py`
    `retikon_core/ingestion/pipelines/video.py`
- Index `AudioSegment.clap_embedding`.
  - Code: `retikon_core/query_engine/index_builder.py`
- Query `AudioSegment` and return canonical moment ranges.
  - Code: `retikon_core/query_engine/query_runner.py`
- Add RMS/VAD-style silence gating before segment embedding.
  - Code: `retikon_core/ingestion/pipelines/audio.py`
    `retikon_core/ingestion/pipelines/video.py`
- Merge adjacent/overlapping segment hits into single moments.
  - Code: `retikon_core/query_engine/query_runner.py`
- Add filters v2 (`asset_type`, `time_range`, metadata pass-through).
  - Code: `retikon_core/services/query_service_core.py`

Acceptance
- Audio queries return precise `start_ms/end_ms` for new ingests.
- Silence filtering reduces segment counts on real audio workloads.
- Adjacent-hit merge produces clean moments (no overlapping-window spam).

## Sprint 4: Vision Encoder v2 (SigLIP2) + Image Query Parity (P1)

Goal: Add a modern vision encoder and improve image-query explainability.

Tasks
- Add v2 image/text embedders (HF + optional ONNX).
  - Code: `retikon_core/embeddings/stub.py`
    `retikon_core/embeddings/onnx_backend.py`
  - Models: `scripts/download_models.py`, `scripts/export_onnx.py`
- Dual-write image vectors at ingest (v1 + v2).
  - Code: `retikon_core/ingestion/pipelines/image.py`
    `retikon_core/ingestion/pipelines/video.py`
- Add v2 vector column + HNSW index.
  - Schema: `retikon_core/schemas/graphar/ImageAsset/prefix.yml`
  - Index: `retikon_core/query_engine/index_builder.py`
- Merge v1/v2 in queries when v2 is available.
  - Code: `retikon_core/query_engine/query_runner.py`
- Ensure image query contract returns canonical moments for images and keyframes,
  with grouping/pagination and per-model `why[]`.
  - Code: `retikon_core/services/query_service_core.py`
    `retikon_core/query_engine/query_runner.py`

Acceptance
- Vision v2 index builds for new ingests; queries return merged results.
- Image query returns keyframe moments with stable grouping/pagination.
- `why[]` indicates model contribution (`vision_v1|vision_v2`).

## Sprint 5: Text Encoder v2 + Embed API v1 (Parity P2 Begins)

Goal: Improve text retrieval and expose first-class embedding APIs.

Tasks
- Add v2 text embedder (HF + optional ONNX).
  - Code: `retikon_core/embeddings/stub.py`
    `retikon_core/embeddings/onnx_backend.py`
  - Models: `scripts/download_models.py`, `scripts/export_onnx.py`
  - Model choice is finalized via model registry approval, with explicit
    CPU-tier and GPU-tier mapping documented in the parity contract.
- Dual-write text vectors for DocChunk and Transcript.
  - Code: `retikon_core/ingestion/pipelines/document.py`
    `retikon_core/ingestion/pipelines/audio.py`
    `retikon_core/ingestion/pipelines/video.py`
- Add v2 vector columns + HNSW indexes.
  - Schema: `retikon_core/schemas/graphar/DocChunk/prefix.yml`
    `retikon_core/schemas/graphar/Transcript/prefix.yml`
  - Index: `retikon_core/query_engine/index_builder.py`
- Merge v1/v2 in query runner when v2 is available.
  - Code: `retikon_core/query_engine/query_runner.py`
- Add sync Embed API v1 (`POST /embed`) for text/image.
  - Code: `gcp_adapter/query_service.py`, `retikon_core/services/`
  - Response fields: `embedding`, `dims`, `model_name`, `normalized`,
    `backend`, `artifact_id`
  - Contract:
    - Sync supports text/image only
    - `normalized=true` always for returned vectors
    - Include preprocess metadata (`token_limit`, truncation, image resize)
    - Enforce payload size limits with typed validation errors

Acceptance
- Text v2 index builds for new ingests; queries return merged results.
- `/embed` returns stable vectors and required metadata.
- Missing v2 vectors on older ingests degrade gracefully (no backfill).

## Sprint 6: Video Embeddings (VideoClips) + Async Embed v2 (Parity P2/P1)

Goal: Close action-retrieval gap and add async embed lifecycle.

Tasks
- Add VideoClip schema and writer with windowed embeddings.
  - Schema: `retikon_core/schemas/graphar/VideoClip/prefix.yml`
  - Writer: `retikon_core/ingestion/pipelines/video.py`
- Add video embedding backend and download/export path.
  - Code: `retikon_core/embeddings/`
  - Models: `scripts/download_models.py`
  - v1 implementation target: CPU-safe clip representation
    (pooled keyframe vision vectors + motion-delta features)
  - v2 true video model remains a later optional upgrade
- Add HNSW index and query support.
  - Code: `retikon_core/query_engine/index_builder.py`
    `retikon_core/query_engine/query_runner.py`
- Define video moment semantics in response:
  - `start_ms`, `end_ms`, optional representative preview frame ref
  - supports `group_by=video` and `clip_count`
- Add async Embed API v2 for long audio/video inputs using shared Task contract.
  - Code: `gcp_adapter/query_service.py`, `retikon_core/services/`
- Enforce CPU guardrails (`VIDEO_CLIP_MAX_CLIPS`, timeouts, graceful skip).
  - Timeout behavior: skip clip-vector write, keep ingest success for
    keyframes/transcript/audio, and emit structured skip reason

Acceptance
- VideoClip index builds on new ingests and supports action queries.
- Async Embed tasks run end-to-end with task polling and result refs.
- Video results are groupable/sortable and conform to canonical Moment schema.
- Action-query subset in golden pack shows measurable lift vs pre-VideoClip baseline.

## Sprint 7: Analyze Endpoint + Structured JSON Contract (Parity P3)

Goal: Retrieval-first analysis with machine-readable grounded outputs.

Tasks
- Add analyze endpoint with evidence retrieval and caching.
  - Code: `gcp_adapter/query_service.py`, `retikon_core/services/analyze_service.py`
- Make Analyze task-based by default (`POST /analyze` returns `task_id`).
  - Code: `retikon_core/services/`, adapter routes
- Define and enforce Analyze output schema:
  - `summary`
  - `chapters[]` (`title`, `start_ms`, `end_ms`)
  - `events[]` (`start_ms`, `end_ms`, `label`, `confidence`, `evidence_refs[]`)
- Streaming policy:
  - v1 Analyze is non-streaming task completion
  - reserve `stream=false` request flag for forward-compatible v2 streaming
- Require evidence grounding for every chapter/event with canonical refs.
- Store outputs and evidence sets as reproducible artifacts.
  - Code: `retikon_core/storage/paths.py`
- Add cache key policy: `(asset_id, prompt_hash, evidence_hash, model_version)`.

Acceptance
- Analyze output validates against schema.
- Every chapter/event includes `evidence_refs[]`.
- Task lifecycle and caching prevent redundant recompute.

## Sprint 8: Detect/Track On Demand + Evidence Artifacts (Parity Evidence Grade)

Goal: Monitoring-grade detection outputs with explainability and reproducibility.

Tasks
- Add detection/tracking worker and API.
  - Code: `gcp_adapter/`, `retikon_core/detect/`
- Make Detect/Track task-based using shared lifecycle contract.
- Store evidence artifacts:
  - boxes/masks/tracks JSON
  - frame refs + timestamps
  - model metadata used
  - links to `VideoClip` / `ImageAsset` / canonical `Moment`
  - Code: `retikon_core/storage/paths.py`
- Add `why[]` metadata (model version, thresholds, frame sampling decisions).
- Add model registry + license guardrails:
  - enforce allowed license list for detect/track models in CI
  - persist `model_id`, `model_license`, thresholds, and sampling params
- Add default-on configs and caps.
  - Code: `retikon_core/config.py`

Acceptance
- Detect/track requests produce linked, persisted evidence artifacts.
- Outputs are referenceable from Search moments and Analyze results.

## Sprint 9: Docs Alignment + Parity Contract (Mandatory)

Goal: Ensure documentation matches actual code behavior and API contracts.

Tasks
- Update model, config, and schema references:
  - `README.md`
  - `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`
  - `Dev Docs/Environment-Reference.md`
  - `Dev Docs/Local-Development.md`
  - `Dev Docs/pro/Metrics-Reference.md`
  - `Dev Docs/pro/Index-Optimization-Plan.md`
- Sync GraphAr schema docs:
  - `retikon_core/schemas/graphar/README.md`
- Update Model-Usage Audit and add a doc sync checklist:
  - `Dev Docs/Model-Usage-Audit.md`
- Add parity contract source-of-truth doc:
  - `Dev Docs/pro/Parity-API-Contract-v1.md`
  - Includes Search, Embed, Analyze, Task lifecycle, fusion rules

Acceptance
- Docs pass a manual audit against code and defaults.
- Contract doc is versioned and used by integration tests.

## Sprint 10 (Optional): Entity Search Module (Parity P4)

Goal: Add entity-centric retrieval as an advanced, governance-heavy feature.

Tasks
- Add `EntityCollection`, `Entity`, and reference asset pipelines.
- Add query/filter syntax for entity-aware retrieval.
- Add governance/tier gating and audit policy controls.

Acceptance
- Entity searches return canonical moments with entity-linked evidence.
- Controls enforce policy boundaries and tenancy rules.
