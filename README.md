# Retikon

Retikon is a multimodal RAG platform targeting GCP, with ingestion and query
services built on Cloud Run and GraphAr-formatted data in GCS. This repository
tracks the v2.5 build kit and the development plan.

## Start here

- Development plan: `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`
- Core/Pro boundary rules: `Dev Docs/Core-Pro-Boundary.md`
- Agent rules: `AGENTS.md`
- Core repo map: `Dev Docs/Core-Repo-Map.md`
- Pro repo map: `Dev Docs/Pro-Repo-Map.md`
- GraphAr schemas: `retikon_core/schemas/graphar/README.md`
- Local development: `Dev Docs/Local-Development.md`
- Pro deployment: `Dev Docs/pro/Deployment.md`
- Pro operations: `Dev Docs/pro/Operations-Runbook.md`
- Pro load testing: `Dev Docs/pro/Load-Testing.md`
- Pro snapshot refresh: `Dev Docs/pro/Snapshot-Refresh-Strategy.md`
- Schema reference: `Dev Docs/Schema-Reference.md`
- Golden demo: `Dev Docs/Golden-Demo.md`
- Security checklist: `Dev Docs/Security-Checklist.md`
- Release checklist: `Dev Docs/Release-Checklist.md`
- Developer integration guide: `Dev Docs/Developer-Integration-Guide.md`
- Developer console UI guide: `Dev Docs/Developer-Console-UI-Guide.md`

## Open-core model (Core vs Pro)

Retikon is an open-core platform:

- **Retikon Core (OSS, Apache 2.0)**: local runtime, batch ingestion pipelines,
  GraphAr writer, SDKs + CLI, and a minimal developer console.
- **Retikon Pro (Commercial)**: managed control plane, streaming ingestion,
  compaction/retention automation, fleet ops, observability, governance,
  multi-tenant metering, and enterprise support.

## Support policy

- Core is community-supported via GitHub issues and docs.
- Pro includes SLAs, priority support, and managed operations.

## Quickstart

- Core local run: `Dev Docs/Local-Development.md` (start with `retikon init`)
- Pro deployment (GCP): `Dev Docs/pro/Deployment.md`
- Console usage: `Dev Docs/Developer-Console-UI-Guide.md`

## Monorepo boundary rules

- Core must remain cloud-agnostic (no GCP SDK imports).
- Pro owns GCP-specific adapters, infra, and runbooks.
- See: `Dev Docs/Core-Pro-Boundary.md` for the enforced rules.

## Repository layout (expected)

- `retikon_core/`: cloud-agnostic ingestion and query logic.
- `gcp_adapter/`: Cloud Run entry points (Flask/FastAPI).
- `infrastructure/terraform/`: GCP IaC.
- `retikon_core/schemas/graphar/`: GraphAr schema YAMLs.
- `Dev Docs/`: design and sprint plan.

## Defaults and constraints (locked)

- Embeddings:
  - Text: `BAAI/bge-base-en-v1.5` (768 dims)
  - Image: `openai/clip-vit-base-patch32` (512 dims)
  - Audio: `laion/clap-htsat-fused` (512 dims)
- Tokenizer: Hugging Face `AutoTokenizer` for BGE base.
- Chunking: 512 token target, 50 token overlap.
- Caps: video 300s, audio 20m, raw download 500MB.
- Scoring: `sim = 1.0 - cosine_distance`, clamp to [0.0, 1.0].
- Query auth: `X-API-Key`.
- Dev Console: GCS static hosting (optional Cloud CDN).

## GraphAr layout (strict)

- Root prefix: `gs://<graph-bucket>/retikon_v2/`
- Vertices: `vertices/<Type>/{core,text,vector}/part-<uuid>.parquet`
- Edges: `edges/<Type>/adj_list/part-<uuid>.parquet`
- IDs: UUIDv4 strings for all vertices and edges.
- Schema evolution: additive-only, query with `union_by_name=true`.

## Pro (GCP) prerequisites

You need a GCP project with billing enabled and these APIs:

- Cloud Run, Eventarc, GCS, Artifact Registry
- Firestore, Secret Manager, Pub/Sub, Cloud Scheduler
- IAM, Cloud Resource Manager, Logging, Monitoring

Service accounts must be created for ingestion, query, and index building, with
least-privilege GCS access as defined in the build kit doc.

## Core local development prerequisites

- Python 3.10+
- Node.js 18+ (Dev Console)
- ffmpeg + ffprobe
- poppler-utils (pdftoppm for PDF image extraction; optional but recommended)

## Environment variables

Use the local `.env` file for dev. Do not commit secrets.

Core (local) variables:

- `STORAGE_BACKEND=local`
- `LOCAL_GRAPH_ROOT`
- `SNAPSHOT_URI`
- `MAX_RAW_BYTES`, `MAX_VIDEO_SECONDS`, `MAX_AUDIO_SECONDS`
- `CHUNK_TARGET_TOKENS`, `CHUNK_OVERLAP_TOKENS`
- `USE_REAL_MODELS`, `MODEL_DIR`, `EMBEDDING_DEVICE`
- `TEXT_MODEL_NAME`, `IMAGE_MODEL_NAME`, `AUDIO_MODEL_NAME`, `WHISPER_MODEL_NAME`

Pro (GCP) variables:

- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_REGION`
- `RAW_BUCKET`, `GRAPH_BUCKET`, `GRAPH_PREFIX`
- `SNAPSHOT_URI`
- `QUERY_API_KEY` (dev only; prod uses Secret Manager)
- `AUDIT_API_KEY` (defaults to `QUERY_API_KEY` in Pro)
- `AUDIT_REQUIRE_ADMIN` (set `1` to require admin API keys)
- `INGEST_API_KEY` (optional for ingestion auth)

## Development workflow (high level)

- Review the sprint plan in `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`.
- Implement work in small, testable changes.
- Keep schemas in `retikon_core/schemas/graphar/` in sync with code.
- Add unit tests for new logic and update docs when behavior changes.

## Testing

- Unit and integration tests use `pytest`.
- Firestore tests should use the emulator when possible.
- Keep fixtures under `tests/fixtures/` and small enough for CI.
- Use `-m core` or `-m pro` to run the focused suites.
- Tier-3 GCP smoke: `python scripts/gcp_smoke_test.py` (Pro only).

## Contributing

Read `AGENTS.md` before making changes. It contains the required guardrails
and the authoritative defaults.
