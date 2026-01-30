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
- `QUERY_WARMUP=0|1` (defaults to `1`)
- `QUERY_WARMUP_TEXT="retikon warmup"`
- `QUERY_WARMUP_STEPS=text,image_text,audio_text,image`

## DuckDB settings (shared Core/Pro)

- `DUCKDB_THREADS`
- `DUCKDB_MEMORY_LIMIT`
- `DUCKDB_TEMP_DIRECTORY`
- `DUCKDB_HEALTHCHECK_URI`
- `DUCKDB_ALLOW_INSTALL=0|1`
- `RETIKON_DUCKDB_AUTH_PROVIDER` (e.g., `gcp_adapter.duckdb_auth:GcsDuckDBAuthProvider`)
- `DUCKDB_GCS_FALLBACK=0|1` (GCS provider only)
- `DUCKDB_SKIP_HEALTHCHECK=0|1`

## Pro (GCP) required

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_REGION`
- `STORAGE_BACKEND=gcs`
- `RAW_BUCKET`
- `GRAPH_BUCKET`
- `GRAPH_PREFIX`
- `SNAPSHOT_URI`
- `RETIKON_DUCKDB_AUTH_PROVIDER` (GCP: `gcp_adapter.duckdb_auth:GcsDuckDBAuthProvider`)

## Pro (GCP) auth + governance

- `AUTH_MODE=api_key|jwt|dual`
- `AUTH_ISSUER`
- `AUTH_AUDIENCE`
- `AUTH_JWKS_URI`
- `AUTH_JWT_ALGORITHMS` (defaults to `RS256`)
- `AUTH_JWT_HS256_SECRET` (local/test only)
- `AUTH_JWT_PUBLIC_KEY` (optional RSA/EC public key)
- `AUTH_REQUIRED_CLAIMS` (defaults to `sub`)
- `AUTH_CLAIM_SUB` (defaults to `sub`)
- `AUTH_CLAIM_EMAIL` (defaults to `email`)
- `AUTH_CLAIM_ROLES` (defaults to `roles`)
- `AUTH_CLAIM_GROUPS` (defaults to `groups`)
- `AUTH_CLAIM_ORG_ID` (defaults to `org_id`)
- `AUTH_CLAIM_SITE_ID` (defaults to `site_id`)
- `AUTH_CLAIM_STREAM_ID` (defaults to `stream_id`)
- `AUTH_ADMIN_ROLES` (defaults to `admin`)
- `AUTH_ADMIN_GROUPS` (defaults to `admins`)
- `AUTH_JWT_LEEWAY_SECONDS` (clock skew)
- `QUERY_API_KEY` (dev; prod uses Secret Manager)
- `INGEST_API_KEY` (optional for ingestion auth)
- `AUDIT_API_KEY` (defaults to `QUERY_API_KEY`)
- `AUDIT_REQUIRE_ADMIN=0|1`
- `AUDIT_BATCH_SIZE` (defaults to `1`)
- `AUDIT_BATCH_FLUSH_SECONDS` (defaults to `5`)
- `AUDIT_DIAGNOSTICS=0|1` (log audit query timings)
- `AUDIT_PARQUET_LIMIT` (limit audit files during diagnostics)
- `RBAC_ENFORCE=0|1`
- `ABAC_ENFORCE=0|1`
- `METERING_ENABLED=0|1`
- `AUDIT_LOGGING_ENABLED=0|1`
- `AUDIT_COMPACTION_ENABLED=0|1`
- `AUDIT_COMPACTION_TARGET_MIN_BYTES`
- `AUDIT_COMPACTION_TARGET_MAX_BYTES`
- `AUDIT_COMPACTION_MAX_FILES_PER_BATCH`
- `AUDIT_COMPACTION_MAX_BATCHES`
- `AUDIT_COMPACTION_MIN_AGE_SECONDS`
- `AUDIT_COMPACTION_DELETE_SOURCE=0|1`
- `AUDIT_COMPACTION_DRY_RUN=0|1`
- `AUDIT_COMPACTION_STRICT=0|1`
- `COMPACTION_SKIP_MISSING=0|1`
- `COMPACTION_RELAX_NULLS=0|1`

## CLI/SDK defaults

- `RETIKON_INGEST_URL` (default ingest base URL)
- `RETIKON_QUERY_URL` (default query base URL)
- `RETIKON_TIMEOUT_S` (default request timeout in seconds)
- `RETIKON_TIMEOUT_MS` (JS SDK timeout override, milliseconds)

## Pro ingestion + ops

- `DLQ_TOPIC`
- `FIRESTORE_COLLECTION`
- `IDEMPOTENCY_TTL_SECONDS`
- `MAX_INGEST_ATTEMPTS`
- `SCHEMA_VERSION`

## Notes

- Core local development uses `.env` and defaults in `retikon_cli`.
- Pro deployments should use Secret Manager for API keys in production.
- For non-GCS object stores, set `STORAGE_BACKEND=remote` and provide full URI
  schemes in `RAW_BUCKET`/`GRAPH_BUCKET` (e.g., `s3://bucket`).
