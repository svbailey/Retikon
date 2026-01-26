# Retikon Product Spec v3.0

Status: Draft
Owner: Product + Eng
Date: 2026-01-26

## Summary
Retikon v3.0 delivers an open-source Core developer platform that runs locally for free, plus a proprietary Pro tier for production-scale deployments. Core provides universal batch ingestion, multimodal pipelines, local query, SDKs, CLI, a minimal web console, and a local edge agent. Pro adds streaming ingestion, queue-based dispatch, adaptive batching/backpressure, managed edge gateways, mandatory compaction, event lifecycle state, webhooks with delivery logs, basic multi-tenancy/metering, and GCP-first SaaS deployment.

## Goals
- Make Retikon Core a zero-friction developer onramp with Apache 2.0 licensing.
- Preserve current GraphAr layout and model defaults while adding additive schema evolution.
- Deliver a sellable Pro MVP focused on scale, reliability, and operational visibility.
- Keep Core and Pro cleanly separated for open-core delivery.

## Non-goals
- Multi-cloud BYOC in v3.0 (planned for v3.1).
- Full enterprise RBAC/SSO/ABAC (planned for v3.1).
- Advanced Data Factory UI and model registry (planned for v3.1).

## Principles
- Compatibility first: no breaking GraphAr changes; additive only.
- Developer-first: CLI and console are first-class.
- Operational clarity: every pipeline action must be observable.
- Cost efficiency: compaction and batching are default, not optional, in Pro.

## Tier Scope
Core (Apache 2.0):
- Engine + pipelines + GraphAr writer.
- Local runtime (filesystem or local object store).
- Edge agent for local capture and batch ingest.
- SDKs (Python, JS; C++ optional in v3.0, target in v3.1).
- CLI + minimal web console.
- Batch ingestion for files (documents, audio, images, video).
- Basic webhook delivery (low throughput, basic retries).
- OCR support is optional and disabled by default (plugin + flag).

Pro (Commercial):
- Streaming ingestion + queue dispatch + DLQ.
- Adaptive batching/backpressure, network-aware buffering.
- Managed edge gateways + remote config.
- Mandatory compaction + retention optimization.
- Event lifecycle state + dedupe + TTL.
- Webhooks with delivery logs, templates, and higher throughput.
- Basic multi-tenancy (org/site/stream) + metering.
- GCP-first SaaS deployment with autoscaling.

## Functional Requirements

### Universal Ingestion
Core:
- Batch ingestion for files across allowlisted modalities.
- Validation of content type + file extension.
- Ingestion API supports metadata tags and source identifiers.
- Idempotency via Firestore for GCP, local state store for local mode.
- Edge agent supports local capture and batch uploads with configurable schedules.

Pro:
- Persistent streaming ingestion with micro-batching and backpressure.
- Queue-based dispatch for ingestion (Pub/Sub for v3.0).
- Managed edge gateway with store-and-forward buffering.
- Offline buffering policies: TTL, disk cap, replay behavior, and rate limits.
- Adaptive batching rules for latency vs throughput (configurable per stream).
- Remote gateway management hooks (config update, health, restart).

### Programmable Senses
Core:
- Video, audio, image, document pipelines as defined in v2.5.
- Maintain hard caps: video 300s, audio 20m, raw 500MB default.
- Maintain embeddings: BGE base 768, CLIP 512, CLAP 512.
- OCR for PDFs/images is optional (disabled by default, enabled via plugin/flag).
- Basic text summarization and classification hooks (optional, off by default).
- Legacy Office formats (.doc, .ppt) are not supported in Core.

Pro:
- Streaming variants for video/audio pipelines.
- Long-video chunking and segment stitching.
- Speaker identification (audio) and higher-accuracy models for noisy inputs.
- Custom model hooks (SDK) for ingestion-time inference.
- Custom image classifiers and model deployment hooks.
- Managed OCR with higher throughput and accuracy (metered).

### Retention and Compaction
Core:
- Local storage retention is user-controlled (disk capacity).
- Manifest tracking per ingestion run.

Pro:
- Mandatory compaction jobs (hourly/daily) with target file sizes.
- Partitioning by date/site/stream/profile.
- Compaction metrics and lag tracking.
- Tiered storage policies (hot/warm/cold) and data aging rules.
- Integrity checks: checksums, audit logs for compaction actions.

### Search and Query
Core:
- Text, image, and audio similarity search using existing embeddings.
- Keyword and metadata search.
- Reverse image search.

Pro:
- Multi-modal query composition (combine text + image + audio).
- Saved queries and query analytics.

### Developer Experience
Core:
- CLI: local up/daemon, ingest, query, status, events tail.
- SDKs: Python + JS with API parity; C++ target for v3.1.
- Minimal web console: ingest status, media preview, query runner, logs.

Pro:
- Web console with delivery logs, usage view, and stream health.
- Data Explorer UI (query filters, saved searches, basic analytics).

### Data Factory
Core:
- Export API for GraphAr and raw assets.
- Basic alerts and webhook rules.

Pro:
- Webhook event delivery with retries, signing, and delivery logs.
- Event lifecycle state store for long-running events.
- Alert rules with multi-condition logic and time windows.
- Basic connector integrations (HTTP webhooks, optional Pub/Sub).
- Legacy Office conversion pipeline is Pro-only (v3.1 target).

### Access and Governance
Core:
- API key for query service (X-API-Key).
- Basic API key management.

Pro:
- Scoped API keys by org/site/stream.
- Metering and usage reporting.
- Audit logs for control-plane actions.

### Fleet and Reliability Ops
Core:
- Service health endpoints and structured logs.

Pro:
- Observability dashboards (metrics + logs).
- Autoscaling and HA configuration.
- Alerting thresholds for backlog, latency, and error rates.
- Managed gateway health monitoring.

### Security
Core:
- TLS for all API communication.
- No secrets baked into images.

Pro:
- Customer-managed keys (optional, via KMS).
- Device cert lifecycle management (initial provisioning only in v3.0).
- OCR dependency isolation: default Core image excludes heavy OCR binaries.

## Architecture Requirements
- Maintain strict GraphAr layout under `retikon_v2/`.
- Add `schema_version` fields in new records; use `union_by_name=true` for queries.
- Separate cloud-specific entrypoints in `gcp_adapter/` and cloud-agnostic logic in `retikon_core/`.
- Core local mode must avoid GCP-specific dependencies.

## Data Model Requirements
- Additive schema evolution only in `retikon_core/schemas/graphar/`.
- Manifest per ingestion run with file list, counts, checksums.
- Event lifecycle records include start/end timestamps and state transitions.

## API Requirements
Core endpoints (local + GCP):
- `GET /health`
- `POST /ingest` (batch)
- `POST /query`
- `POST /alerts` (basic rules)
- `POST /webhooks` (basic config)

Pro endpoints:
- `POST /ingest/stream` (streaming)
- `GET /ingest/stream/status`
- `GET /events/deliveries`
- `GET /usage`

## CLI Requirements
- `retikon up` (local stack)
- `retikon daemon` (headless)
- `retikon ingest --path ...`
- `retikon query --text ... --image ... --audio ...`
- `retikon status`
- `retikon events tail`

## Console Requirements
Core console (minimal):
- Ingestion status list
- Media preview and basic timeline
- Query runner (text/image/audio)
- Recent logs

Pro console (v3.0):
- Delivery logs and usage view
- Stream health view
- Saved queries and basic analytics

## Observability and Logging
- JSON structured logs with service, env, request_id, correlation_id, duration_ms, version.
- Metrics: ingest rate, queue backlog, processing latency, compaction lag.
- Alert thresholds configurable per environment.

## Security and Compliance
- Encryption in transit for all tiers.
- Encryption at rest for Pro; Core relies on host disk encryption.
- Audit logs for Pro control-plane actions.

## Performance Targets
Core:
- Local query p95 <= 800ms on small datasets (<10k assets).

Pro:
- Streaming ingestion backlog < 60s under target throughput.
- Compaction lag < 24h for continuous streams.
- Webhook delivery p95 < 5s for successful deliveries.

## Compatibility and Migration
- Keep `retikon_v2/` prefix.
- Additive schema evolution only.
- Provide a manifest per ingestion run; no breaking schema changes.

## Acceptance Criteria (v3.0)
- Core local stack runs with `retikon up` and supports ingest + query.
- Core provides CLI + SDKs + minimal console.
- Pro services provide streaming ingestion, queue dispatch, compaction, event lifecycle state, webhooks, and basic multi-tenancy/metering.
- Audit logs and usage reporting available in Pro.
- Load test baselines documented in `Dev Docs/Load-Testing.md`.
- Developer consumption patterns documented in `Dev Docs/Developer-Integration-Guide.md`.
- Advanced UI behavior documented in `Dev Docs/Developer-Console-UI-Guide.md`.

## Out of Scope (v3.1)
- SSO/SAML/OAuth integration.
- Full RBAC/ABAC with field-level policies.
- Fleet management UI and OTA rollout tools.
- BYOC Kubernetes deployment.
- Advanced Data Factory UI (annotation, model registry).
