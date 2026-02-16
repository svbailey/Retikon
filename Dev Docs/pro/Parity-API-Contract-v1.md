# Parity API Contract v1

Status: draft baseline for Sprint 1 implementation.
Version: `v1`.

This contract defines the platform-facing behavior for Search, Embed, Tasks,
Analyze, and fusion explainability. It is the source of truth for integration
tests and client compatibility.

## 1) Search API

Endpoint: `POST /query`

### 1.1 Request

- `query_text` (string, optional)
- `image_base64` (string, optional)
- `mode` (string, optional)
- `modalities` (string[], optional)
- `top_k` (int, optional, pre-fusion candidate cap)
- `group_by` (`video|none`, optional, default `none`)
- `sort_by` (`score|clip_count`, optional, default `score`)
- `page_limit` (int, optional, post-fusion return count)
- `page_token` (string, optional, opaque cursor)
- `filters` (FilterNode, optional)

Validation:
- at least one of `query_text` or `image_base64` is required for vector search.
- if `query_text` only: run text-led retrieval over enabled modalities.
- if `image_base64` only: run image retrieval over image/keyframe moments.
- if both are provided: run both query paths and fuse results.
- unknown request fields are rejected.
- if both `top_k` and `page_limit` are provided: `page_limit <= top_k` is required.
- clients should set `page_limit`; `top_k` is an advanced tuning field.
- precedence rule:
  - if `modalities` is provided, it takes precedence over `mode`
  - else `mode` resolves to default modality sets
  - else default mode is `all`

Mode mapping v1:
- `mode=text` -> `text+ocr`
- `mode=image` -> `vision`
- `mode=audio` -> `audio`
- `mode=video` -> `video+vision+audio+text+ocr`
- `mode=all` -> `text+ocr+vision+audio+video`

### 1.2 FilterSpec v1

Filter node grammar:
- `all: FilterNode[]` (AND)
- `any: FilterNode[]` (OR)
- `not: FilterNode` (NOT)
- `field` + `op` + `value` leaf node

Allowed ops:
- `eq`, `neq`, `in`, `nin`, `gt`, `gte`, `lt`, `lte`, `between`, `exists`

Allowed value types:
- string, number, bool, RFC3339 timestamp

Guaranteed system fields:
- `asset_id`, `asset_type`, `duration_ms`, `created_at`, `source_type`,
  `start_ms`, `end_ms`

Custom fields:
- `metadata.<key>` (mapped to control-plane metadata namespace)
  - resolved by control-plane metadata lookup to an `asset_id` allowlist, then
    applied in DuckDB filtering

Validation behavior:
- unknown field/op/type returns `400` with structured error details.

### 1.3 Pagination and determinism

Pagination is cursor-only.

- `page_token` is base64url-encoded JSON and treated as opaque by clients.
- Token contains:
  - `query_fingerprint`
  - `snapshot_marker`
  - `last_sort_tuple`
- `snapshot_marker` is the active index build id / dataset version emitted by
  index builder metadata.

Sort stability rules:
- `sort_by=score`:
  - `score desc`, tie-break `asset_id asc`, `start_ms asc`,
    `primary_evidence_id asc`
- `sort_by=clip_count`:
  - `clip_count desc`, then same tie-breakers

Guarantee:
- identical request + identical snapshot marker yields deterministic page order.

### 1.4 Response

- `results: Moment[]`
- `next_page_token` (optional)
- `grouping` (optional when `group_by=video`):
  - `total_videos` (int)
  - `total_moments` (int)
  - `videos[]`:
    - `asset_id`
    - `clip_count`
    - `best_score`
    - `top_moments[]` (subset of canonical `Moment` objects)
- `meta`:
  - `fusion_method`
  - `weight_version`
  - `snapshot_marker`
  - `request_id` (optional)
  - `trace_id` (optional)

## 2) Canonical Moment schema

Fields:
- `asset_id` (string)
- `asset_type` (string)
- `start_ms` (int|null)
- `end_ms` (int|null)
- `score` (float in `[0.0, 1.0]`)
- `modality` (`text|vision|audio|ocr|video`)
- `highlight_text` (string|null)
- `primary_evidence_id` (string)
- `evidence_refs` (EvidenceRef[])
- `why` (WhyContribution[])

EvidenceRef keys:
- `doc_chunk_id`, `transcript_segment_id`, `image_asset_id`,
  `audio_segment_id`, `video_clip_id`

Moment validity rules:
- text moment: requires `doc_chunk_id` or `transcript_segment_id`
- OCR moment: requires `doc_chunk_id` with OCR source metadata
- vision moment: requires `image_asset_id`
- audio moment: requires `audio_segment_id`
- video moment: requires `video_clip_id`
- docs-only moment:
  - `start_ms/end_ms` are null
  - `highlight_text` and evidence ref are still required

## 3) Fusion specification v1

Method: weighted RRF.

Formula:
- `rrf_score = sum_m (w_m / (k + rank_m))`
- default `k=60`
- fusion unit is `Moment` (not asset-level pre-aggregation)

Default weights:
- `text=1.0`
- `ocr=1.0`
- `vision=0.8`
- `audio=0.8`
- `video=1.0`
- `fts=1.2`

Reranker behavior:
- applied to text-bearing candidate sets only
- timeout/failure path skips rerank and returns fused base ranking
- rerank outcome logged in `why`/trace metadata

Missing-modality behavior:
- modalities missing for an asset/moment contribute no rank term
- missing modalities are not penalized as worst-rank placeholders

Calibration:
- weight tuning runs against golden pack
- selected weight set is versioned as `weight_version`

## 4) Embed API

### 4.1 Sync Embed v1

Endpoint: `POST /embed`

Supported inputs:
- text
- image_base64

Unsupported in sync:
- raw audio/video payloads

Validation:
- exactly one sync input type is allowed per request (text or image)

Response:
- `embedding` (float[])
- `dims` (int)
- `model_name` (string)
- `normalized` (bool, always `true`)
- `backend` (string)
- `artifact_id` (string)
- `preprocess`:
  - text token cap + truncation info
  - image resize info

Limits:
- request payload caps enforced with structured `400/413` errors.

### 4.2 Async Embed v2

Endpoints:
- `POST /embed/async`
- `GET /tasks/{task_id}`
- `GET /embed/results/{task_id}`

Supported inputs:
- audio/video by `asset_id` or upload reference only
- raw bytes are rejected

Output:
- same metadata shape as sync embed + task linkage

## 5) Shared Task lifecycle contract

Task object:
- `task_id`
- `type`
- `status` (`queued|running|succeeded|failed|canceled`)
- `progress` (0..100)
- `started_at`, `finished_at`
- `error` (nullable structured object)
- `result_ref`

Task endpoints:
- create job endpoint per feature
- `GET /tasks/{task_id}` for polling
- result endpoint per feature uses `task_id` or `result_ref`

## 6) Analyze contract v1

Endpoint: `POST /analyze` (task-based)

Request:
- `asset_id` (required)
- `prompt` (required)
- `stream` (optional, must be `false` in v1)

Streaming:
- v1 non-streaming only
- `stream=false` accepted/reserved for forward-compatible v2

Result schema:
- `summary` (string)
- `chapters[]` with `title,start_ms,end_ms,evidence_refs[]`
- `events[]` with `start_ms,end_ms,label,confidence,evidence_refs[]`

Grounding rule:
- every chapter/event requires at least one valid `evidence_ref`.

Caching key:
- `(asset_id, prompt_hash, evidence_hash, model_version)`

## 7) Detect/Track governance requirements

Detect/Track outputs must include:
- evidence artifacts (boxes/masks/tracks JSON)
- frame refs and timestamps
- `why` metadata: model id/version, thresholds, sampling parameters

Model governance:
- CI enforces allowed model-license list for detect/track artifacts
- response/artifact metadata persists `model_id` and `model_license`

## 8) Error model (typed errors)

All endpoints return a shared error payload on non-2xx responses.

Error payload:
- `error.code` (string)
- `error.message` (string)
- `error.details[]` (optional):
  - `field` (string)
  - `reason` (string)
  - `expected` (any)
  - `actual` (any)

Core error codes:
- `VALIDATION_ERROR`
- `PAYLOAD_TOO_LARGE`
- `UNSUPPORTED_MODE`
- `UNSUPPORTED_MODALITY`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `TASK_NOT_FOUND`
- `TASK_FAILED`
- `TIMEOUT`
- `INTERNAL_ERROR`

## 9) Compatibility and change control

- Backward-compatible additions are additive only.
- Breaking contract changes require new contract version file.
- Integration tests must pin to contract version and validate sample payloads.
