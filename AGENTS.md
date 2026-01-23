# Retikon AI Agent Guide

This file defines how AI agents should work in this repository. Read and follow
these instructions before making changes.

## Mission

- Help build the Retikon multimodal RAG platform.
- Keep changes aligned with the sprint plan in
  `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`.
- Prioritize correctness, reproducibility, and minimal diffs.

## Source of Truth

- Primary plan: `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`
- GraphAr schemas: `schemas/graphar/`
- This guide: `AGENTS.md`

If there is a conflict between docs, ask for clarification before proceeding.

## Repo Layout (expected)

- `retikon_core/`: core ingestion and query logic (cloud-agnostic).
- `gcp_adapter/`: Cloud Run entry points (Flask/FastAPI).
- `infrastructure/terraform/`: GCP IaC.
- `schemas/graphar/`: GraphAr YAML definitions.
- `Dev Docs/`: development plan and references.

## Guardrails

- Use "Retikon" naming everywhere (do not reintroduce "lattice").
- Keep changes ASCII-only unless a file already uses Unicode.
- Do not delete user changes or reformat files unnecessarily.
- Do not commit unless explicitly asked.
- Avoid destructive git commands (e.g., `git reset --hard`).

## GraphAr Schema Rules

- Schema changes are additive only.
- IDs are UUIDv4 strings across all vertices and edges.
- Vertex layout:
  - `vertices/<Type>/{core,text,vector}/part-<uuid>.parquet`
- Edge layout:
  - `edges/<Type>/adj_list/part-<uuid>.parquet`
- Use `union_by_name=true` for queries that span schema versions.
- YAMLs live in `schemas/graphar/` and must stay in sync with code.

## Embeddings and Models

Defaults (locked):

- Text: `BAAI/bge-base-en-v1.5` (768 dims)
- Image: `openai/clip-vit-base-patch32` (512 dims)
- Audio: `laion/clap-htsat-fused` (512 dims)

If you want to change models, get approval and update:

- `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`
- `schemas/graphar/*/prefix.yml` vector lengths
- Any embedding code and tests

## Tokenizer and Chunking

- Tokenizer: Hugging Face `AutoTokenizer` for `BAAI/bge-base-en-v1.5`.
- Chunking: 512 token target with 50 token overlap.
- Use `offset_mapping` to store `char_start` and `char_end`.

## File Allowlists

Default allowlists:

- Docs: `.pdf`, `.txt`, `.md`, `.rtf`, `.docx`, `.doc`, `.pptx`, `.ppt`,
  `.csv`, `.tsv`, `.xlsx`, `.xls`
- Images: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`, `.gif` (first frame)
- Audio: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`
- Video: `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.mpeg`, `.mpg`

Both extension and content type must match the modality.

## Runtime Caps

- Video: 300 seconds max
- Audio: 20 minutes max
- Raw download limit: 500 MB (configurable)

## Query Service Rules

- Auth: `X-API-Key` required for `/query`.
- Scoring: `sim = 1.0 - cosine_distance`, clamp to [0.0, 1.0].
- Use HNSW via DuckDB `vss` extension for indexes.

## GCP and DuckDB Auth

- Use ADC / Workload Identity for DuckDB access to GCS.
- Primary path: DuckDB Secrets Manager `credential_chain`.
- Fallback path: DuckDB community GCS extension (ADC), gated by
  `DUCKDB_GCS_FALLBACK=1`.
- Always include a startup auth self-test against
  `gs://<graph-bucket>/retikon_v2/healthcheck.parquet`.

## Development Prerequisites

From `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`, ensure:

- GCP project and billing are enabled.
- Required APIs are enabled (Cloud Run, Eventarc, GCS, Artifact Registry,
  Firestore, Secret Manager, Pub/Sub, Cloud Scheduler, IAM, Logging, Monitoring).
- Terraform backend bucket exists.
- Service accounts exist and have least-privilege IAM roles.
- Secrets exist in Secret Manager (`retikon-query-api-key`).

## Testing

- Prefer `pytest` for unit and integration tests.
- Keep fixtures under `tests/fixtures/`, small and fast.
- For Firestore idempotency tests, use the Firestore emulator when possible.
- For GraphAr, add tests that validate schema and column order.

## Logging and Errors

- Use JSON structured logging with `service`, `env`, `request_id`,
  `correlation_id`, `duration_ms`, and `version`.
- Classify errors as `RecoverableError`, `PermanentError`, `AuthError`,
  `ValidationError`.
- Avoid logging sensitive data (API keys, raw content).

## CI/CD Expectations

- Lint, format, and unit tests must run on PR.
- Build steps must not bake secrets into images.
- Use Artifact Registry for image storage.

## Working Style

- Make small, scoped changes.
- Update docs when changing behavior or config.
- If you must make assumptions, state them explicitly and ask for confirmation.

## Contact and Escalation

If blocked or unsure, summarize the issue and ask for a decision instead of
guessing.
