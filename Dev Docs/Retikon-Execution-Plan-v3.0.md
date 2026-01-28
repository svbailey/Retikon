# Retikon v3.0 Execution Plan (Sprint by Sprint)

Cadence: 2-week sprints

## Sprint 1 - OSS packaging + v3.0 blueprint
Goal: establish open-core boundary, licensing, and v3.0 plan docs without behavior changes.
Status: Complete (2026-01-27)

Tasks (repo paths):
- Add OSS legal docs: `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- Update top-level `README.md` with Core vs Pro boundary, support policy, and quickstart links.
- Add v3.0 product spec: `Dev Docs/Retikon-Product-Spec-v3.0.md`.
- Add v3.0 execution plan: `Dev Docs/Retikon-Execution-Plan-v3.0.md`.
- Add capability registry scaffold in `retikon_core/capabilities.py`.
- Wire capability flags into `retikon_core/config.py` and `retikon_core/logging.py`.
- Remove any legacy "lattice" mentions across docs and code.

Tests:
- Add `tests/test_capabilities.py` for flag handling.
- Ensure existing CI passes.

Deliverables:
- OSS packaging complete.
- Clear Core/Pro boundary documented.

## Sprint 2 - Core local storage + schema evolution
Goal: Core runs locally with filesystem GraphAr storage and additive schemas.
Status: Complete (2026-01-27)

Tasks:
- Add local storage configuration to `retikon_core/config.py` (local base URIs, storage backend).
- Extend `retikon_core/storage/paths.py` to handle local and remote roots consistently.
- Update `retikon_core/storage/writer.py` to support local atomic writes and checksum.
- Extend `retikon_core/storage/manifest.py` to write manifests in local mode.
- Add local object store adapter in `retikon_core/storage/`.
- Remove legacy `.doc`/`.ppt` from Core allowlists and docs; keep `.docx`/`.pptx`.
- Add `schema_version` fields (additive) in `retikon_core/schemas/graphar/*/prefix.yml`.
- Update `retikon_core/storage/validate_graphar.py` for schema_version checks.

Tests:
- Update `tests/test_graphar_writer.py`, `tests/test_graphar_manifest.py`, `tests/test_graphar_validation.py`.
- Add local integration test fixture in `tests/fixtures/`.

Deliverables:
- Core can ingest and write GraphAr to local filesystem.

## Sprint 3 - Local query + search
Goal: local query works with additive schema evolution and search across modalities.
Status: Complete (2026-01-27)

Tasks:
- Update `retikon_core/query_engine/query_runner.py` to support local file paths.
- Ensure all DuckDB reads use `union_by_name=true` for schema evolution.
- Add local snapshot support in `retikon_core/query_engine/index_builder.py`.
- Update `retikon_core/storage/schemas.py` to merge schema versions cleanly.
- Add metadata and keyword search support in `retikon_core/query_engine/`.
- Add query mode/modality filtering to skip unused embeddings (text-only default).
- Add model warmup hooks in local and hosted query services.
- Add slow-query timing breakdown logging (embeddings vs DuckDB).

Tests:
- `tests/test_query_runner.py` with local data.
- `tests/test_graphar_schemas.py` to validate new fields.
- `tests/test_query_modes.py` for modality filtering and warmup toggles.

Deliverables:
- Local query returns text/image/audio results against local GraphAr.

## Sprint 4 - Local services + CLI + edge agent
Goal: developer can run Core locally via CLI and edge agent.
Status: Complete (2026-01-27)

Tasks:
- Add local API entrypoints: `local_adapter/ingestion_service.py`, `local_adapter/query_service.py`.
- Add CLI scaffolding: `retikon_cli/cli.py` (or `scripts/retikon_cli.py`).
- Implement `retikon up`, `retikon daemon`, `retikon ingest`, `retikon query`, `retikon status`.
- Add local edge agent: `retikon_core/edge/agent.py` (batch capture + upload).
- Add local env templates: `.env.example` and `scripts/local_up.sh`.

Tests:
- Add `tests/test_local_services.py` (health + query stub).
- Add `tests/test_cli_local.py` (basic command parsing).
- Add `tests/test_edge_agent.py`.

Deliverables:
- `retikon up` brings up local API services.
- Edge agent can upload batch data locally.

## Sprint 5 - SDKs + minimal web console
Goal: complete developer experience for Core.
Status: Complete (2026-01-27)

Tasks:
- Add SDKs: `sdk/python/` and `sdk/js/` with ingest/query support.
- Add OpenAPI spec: `Dev Docs/openapi/retikon-core.yaml`.
- Update `frontend/dev-console/` for local mode base URL.
- Add minimal UI panels: ingest status, media preview, query runner, logs.
- Wire console API calls to local services.
- Update `frontend/dev-console/README.md` and `.env.example`.
- Add optional OCR plugin packaging (extra deps + build target) and `ENABLE_OCR` flag documentation.
- Update SDKs/CLI/OpenAPI to expose query modes/modalities.
- Add console toggle for text-only vs multimodal queries and persist defaults.

Tests:
- Add minimal frontend smoke tests if used.

Deliverables:
- Core console working against local APIs.
- SDKs published and documented.

## Sprint 6 - Edge gateway + adaptive buffering (Pro)
Goal: managed edge gateway with store-and-forward behavior.
Status: Complete (2026-01-27)

Tasks:
- Add edge gateway service in `gcp_adapter/edge_gateway_service.py`.
- Implement buffering policies in `retikon_core/edge/buffer.py` (TTL, disk cap, replay).
- Add adaptive batching/backpressure controls in `retikon_core/edge/policies.py`.
- Add gateway config endpoints in `gcp_adapter/edge_gateway_service.py`.
- Update Terraform for gateway service in `infrastructure/terraform/`.

Tests:
- `tests/test_edge_buffering.py`, `tests/test_edge_gateway.py`.

Deliverables:
- Managed gateway with offline buffering policies.

## Sprint 7 - Streaming ingestion + queue dispatch (Pro)
Goal: Pro streaming ingestion with queue-based dispatch.

Tasks:
- Add queue abstraction in `retikon_core/queue/`.
- Implement Pub/Sub adapter in `gcp_adapter/queue_pubsub.py`.
- Add streaming ingestion pipeline in `retikon_core/ingestion/streaming.py`.
- Add streaming Cloud Run service entrypoint `gcp_adapter/stream_ingest_service.py`.
- Update Terraform to add service + Pub/Sub topics `infrastructure/terraform/`.
- Add DLQ config and retry policies.

Tests:
- `tests/test_streaming_ingest.py` for micro-batching and backpressure.

Deliverables:
- Streaming ingestion service deployed in GCP.

## Sprint 8 - Compaction + retention optimization (Pro)
Goal: mandatory compaction and tiered retention.

Tasks:
- Add compaction core in `retikon_core/compaction/`.
- Define target file size policy and partitioning logic in `retikon_core/compaction/policy.py`.
- Add compaction job entrypoint in `gcp_adapter/compaction_service.py`.
- Add retention/tiering config in `retikon_core/retention/`.
- Add integrity checks and compaction audit logs in `retikon_core/audit/`.
- Update Terraform for compaction jobs and scheduler.

Tests:
- `tests/test_compaction.py`, `tests/test_retention_policies.py`, `tests/test_audit_logs.py`.

Deliverables:
- Compaction running on schedule.
- Retention policies and audit logs available.

## Sprint 9 - Webhooks + alerts + integrations (Core + Pro)
Goal: event delivery and alerting pipelines.

Tasks:
- Add webhook delivery engine `retikon_core/webhooks/` with signing and retries.
- Add basic alert rules `retikon_core/alerts/`.
- Add delivery logs in `retikon_core/webhooks/logs.py`.
- Add API endpoints in `gcp_adapter/webhook_service.py`.
- Add basic connector hooks (HTTP webhook + Pub/Sub) in `retikon_core/connectors/`.

Tests:
- `tests/test_webhooks.py`, `tests/test_alerts.py`.

Deliverables:
- Webhook delivery and alert rules operational.

## Sprint 10 - Multi-tenancy + metering + release hardening
Goal: basic tenant scoping, usage metering, and production readiness.

Tasks:
- Add tenancy model `retikon_core/tenancy/` (org/site/stream).
- Add scoped API keys and auth enforcement `retikon_core/auth/`.
- Add metering `retikon_core/metering/` and GraphAr schema additions.
- Update GCP services to enforce scopes in `gcp_adapter/ingestion_service.py`, `gcp_adapter/query_service.py`.
- Add autoscaling configuration in Terraform (`infrastructure/terraform/`).
- Update `Dev Docs/pro/Load-Testing.md` with streaming/compaction benchmarks.
- Update `Dev Docs/Release-Checklist.md` for v3.0.
- Add load test baselines for text-only vs multimodal queries.

Tests:
- `tests/test_query_auth.py`, `tests/test_metering.py`.
- Run load tests per `Dev Docs/pro/Load-Testing.md`.

Deliverables:
- Pro MVP feature set complete.
- v3.0 release checklist satisfied.

## Feature-to-Sprint Mapping
See `Dev Docs/Feature-to-Sprint-Mapping.md`.

## Sprint Checklists
Per-sprint checklists are stored in `Dev Docs/sprints/` using the naming
convention `v3.0-sprint-XX.md`.
