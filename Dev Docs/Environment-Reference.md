# Environment Reference

This document lists environment variables used by Retikon Core and Retikon Pro.
Defaults shown match current code where applicable.

## Core (local) required

- `STORAGE_BACKEND=local`
- `LOCAL_GRAPH_ROOT`
- `SNAPSHOT_URI`
- `ENV` (e.g., `dev`)
- `LOG_LEVEL` (e.g., `INFO`)
- `MAX_RAW_BYTES`
- `MAX_VIDEO_SECONDS`
- `MAX_AUDIO_SECONDS`
- `MAX_FRAMES_PER_VIDEO`
- `CHUNK_TARGET_TOKENS`
- `CHUNK_OVERLAP_TOKENS`

## Core (local) optional

- `USE_REAL_MODELS=0|1`
- `MODEL_DIR`
- `EMBEDDING_DEVICE`
- `TEXT_MODEL_NAME`
- `IMAGE_MODEL_NAME`
- `AUDIO_MODEL_NAME`
- `WHISPER_MODEL_NAME`
- `ENABLE_OCR=0|1`
- `OCR_MAX_PAGES`
- `RETIKON_TOKENIZER` (set to `stub`/`simple` for test/dev)
- `RETIKON_EDITION` (defaults to `core`)
- `RETIKON_CAPABILITIES`

## Query service config (shared Core/Pro)

- `MAX_QUERY_BYTES=4000000`
- `MAX_IMAGE_BASE64_BYTES=2000000`
- `SLOW_QUERY_MS=2000`
- `LOG_QUERY_TIMINGS=0|1`
- `QUERY_WARMUP=0|1`
- `QUERY_WARMUP_TEXT="retikon warmup"`
- `QUERY_WARMUP_STEPS=text,image_text,audio_text,image`

## DuckDB settings (shared Core/Pro)

- `DUCKDB_THREADS`
- `DUCKDB_MEMORY_LIMIT`
- `DUCKDB_TEMP_DIRECTORY`
- `DUCKDB_HEALTHCHECK_URI`
- `DUCKDB_ALLOW_INSTALL=0|1`
- `DUCKDB_GCS_FALLBACK=0|1`
- `DUCKDB_SKIP_HEALTHCHECK=0|1`

## Pro (GCP) required

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_REGION`
- `RAW_BUCKET`
- `GRAPH_BUCKET`
- `GRAPH_PREFIX`
- `SNAPSHOT_URI`

## Pro (GCP) auth + governance

- `QUERY_API_KEY` (dev; prod uses Secret Manager)
- `INGEST_API_KEY` (optional for ingestion auth)
- `AUDIT_API_KEY` (defaults to `QUERY_API_KEY`)
- `AUDIT_REQUIRE_ADMIN=0|1`
- `RBAC_ENFORCE=0|1`
- `ABAC_ENFORCE=0|1`
- `METERING_ENABLED=0|1`
- `AUDIT_LOGGING_ENABLED=0|1`

## Pro ingestion + ops

- `DLQ_TOPIC`
- `FIRESTORE_COLLECTION`
- `IDEMPOTENCY_TTL_SECONDS`
- `MAX_INGEST_ATTEMPTS`
- `SCHEMA_VERSION`

## Notes

- Core local development uses `.env` and defaults in `retikon_cli`.
- Pro deployments should use Secret Manager for API keys in production.
