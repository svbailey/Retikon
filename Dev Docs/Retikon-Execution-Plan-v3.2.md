# Retikon v3.2 Execution Plan - Connectors, Tooling, and Quality

Status: Draft
Owner: Product + Eng
Date: 2026-01-27

## Summary
Retikon v3.2 focuses on making Core and Pro the most practical, developer-friendly
multimodal RAG platform by filling ecosystem gaps: connectors, LLM tool
integrations, ranking quality, permissions, and cost controls. This plan
explicitly separates Core (OSS) and Pro (Commercial) work so the boundary stays
clean and the Pro value is clear.

## Goals
- Make Retikon the easiest multimodal RAG stack to set up, run, and integrate.
- Provide a comprehensive connector catalog (sources + sinks) with a consistent
  config model, auth handling, and incremental sync support.
- Add LLM tooling integrations (tool calling, orchestration, evaluation) that
  work with major providers and open-source runtimes.
- Improve search quality with reranking, hybrid retrieval, and evaluation loops.
- Add fine-grained permissions so results are always scoped to tenant and policy.
- Keep Pro unit economics viable with metering, autoscaling, and cost controls.

## Non-goals
- Replacing the GraphAr layout or core schemas (additive only).
- Building a full BI platform; Retikon remains a data + retrieval engine.

## Scope Overview (Core vs Pro)
Core (OSS, Apache 2.0):
- Connector SDK + registry.
- Generic HTTP connector (Core-only baseline).
- Local and hosted query improvements (hybrid + rerank).
- Evaluation harness (offline), basic feedback capture.
- Basic policy filters for query (tenant scoping, simple metadata rules).
- Streamlined local setup (doctor, config generator).

Pro (Commercial):
- Full connector catalog and managed sync scheduler.
- Streaming connectors and managed edge gateways.
- Policy engine with ABAC + row-level enforcement.
- Feedback loops with quality monitoring and active learning hooks.
- Metering, usage analytics, cost guardrails, and autoscaling profiles.

## Connector Registry (Source of Truth)
The connector catalog is captured in a machine-readable registry file:

- `retikon_core/connectors/registry.yml`

This registry is the canonical list for connectors, tiers, and edition scope.
CI should validate that docs and configs only reference registry entries.

## Capability Map Updates (Core vs Pro Flags)
The capability flags are updated in `retikon_core/capabilities.py`.

Core (new flags):
- connectors_core
- connector_registry
- llm_tooling
- llm_agents
- llm_runtimes
- retrieval_quality
- eval_harness
- feedback_basic
- permissions_basic
- dx_bootstrap

Pro (new flags):
- connectors_managed
- connectors_streaming
- permissions_abac
- feedback_advanced
- tool_registry
- cost_controls
- autoscaling_profiles

## Feature Catalog

### A) Connector Platform
1) Connector SDK (Core)
- Standard interfaces: pull, push, streaming, and delta sync.
- Credential providers: static keys, OAuth, service accounts, workload identity.
- Config schema and validation for each connector.
- State checkpointing for incremental sync.
- Backfill + reindex workflows.

2) Connector Registry (Core)
- A machine-readable registry file with connector metadata:
  - id, version, modality support, auth type, incremental support, limits.
- CLI commands to list, validate, and test connectors.

3) Managed Connector Scheduler (Pro)
- Cron + event-driven syncs with retries and DLQ.
- Connector health dashboards and SLA monitoring.

### B) Connector Catalog (Target List)
This is a target list for v3.2 to be exhaustive across the common categories.
Availability is staged by priority and edition.

Core (OSS) connectors (v3.2):
- Generic HTTP connector (pull/push).

Pro (Commercial) connectors:
Tier 0 (Must-have for 3.2):
- Object storage: GCS, S3, Azure Blob
- Warehouses: BigQuery, Snowflake
- Databases: Postgres, MySQL
- Streaming: Kafka, Pub/Sub
- Collaboration: Google Drive, SharePoint/OneDrive, Slack
- Dev tools: GitHub, GitLab

Tier 1 (Should-have for 3.2):
- Warehouses: Redshift, Databricks (Delta Lake)
- Databases: SQL Server, MongoDB
- Support/CRM: Salesforce, Zendesk, ServiceNow, Jira
- Docs/Knowledge: Confluence, Notion
- Messaging: Teams
- File transfer: SFTP

Tier 2 (Backlog / extend):
- Streaming: Kinesis, Event Hubs, RabbitMQ
- Databases: Oracle, DynamoDB, Neo4j
- Storage: MinIO, Wasabi
- Observability/SIEM: Splunk, Datadog
- CMS: SharePoint on-prem, Box, Dropbox

### C) LLM Tooling Integrations (Core)
1) Provider tool-calling adapters
- OpenAI tools (function calling)
- Anthropic tool use
- Google Vertex AI / Gemini function calling
- AWS Bedrock Agents (action groups)
- Azure OpenAI tool calling

2) Agent framework adapters
- LangChain
- LlamaIndex
- Semantic Kernel
- Haystack
- DSPy

3) Model runtime backends
- vLLM
- Hugging Face TGI
- NVIDIA Triton
- ONNX Runtime

4) Evaluation + observability
- Ragas evaluation harness
- OpenAI Evals (optional)
- Arize Phoenix (local eval + traces)
- Langfuse (observability + tracing)

5) Pro extensions
- Managed tool registry with approvals and quotas.
- Secure tool sandboxing and audit logging.
- Tenant-level tool policies and rate limits.

### D) Retrieval Quality (Core)
- Hybrid retrieval (vector + keyword, weighted fusion).
- Reranking stage with a configurable reranker.
- Per-modality relevance tuning and score calibration.
- Evaluation datasets + regression tests in CI.
- Feedback capture: thumbs up/down and issue tagging.

### E) Permissions and Governance
Core:
- Tenant scoping across all query and export paths.
- Simple metadata rules (allow/deny by tag).

Pro:
- Row-level policies (site, stream, device, tags).
- ABAC policy engine with deny-by-default.
- Audit logs for access decisions.

### F) DX and User Friendliness (Core)
- `retikon init` (creates .env, local config, sample data).
- `retikon doctor` (validates ffmpeg, OCR, model cache, GPU).
- One-command local demo that seeds data + opens console.
- Console-first flows for connectors (setup wizards, status) with Pro flags.

### G) Cost Controls (Pro)
- Metering by GB ingested, minutes processed, queries served.
- Cost budgets per tenant with soft/hard limits.
- Autoscaling profiles: cost-optimized, balanced, latency-first.
- Storage compaction + tiering enforced by policy.

## Sprint Backlog (v3.2)
Cadence: 2-week sprints

Sprint 1 - Connector SDK + Registry (Core foundation)
- Owner: Platform Eng (Data)
- Estimate: 2 weeks, 3 eng
- Core scope:
  - Connector SDK interfaces (pull/push/stream/delta).
  - Registry schema + loader using `retikon_core/connectors/registry.yml`.
  - CLI: `retikon connectors list/validate/test`.
  - Generic HTTP connector (Core baseline).

Sprint 2 - Connector Scheduler + Tier 0 Pro connectors
- Owner: Platform Eng (Infra)
- Estimate: 2 weeks, 3 eng
- Pro scope:
  - Managed sync scheduler (cron + retries + DLQ).
  - Tier 0 Pro connectors: BigQuery, Snowflake, Kafka, Pub/Sub, GCS, S3, Azure.
  - Dev console connector setup wizard (basic, Pro).

Sprint 3 - Tool-calling adapters + DX bootstrap
- Owner: ML Platform + DX
- Estimate: 2 weeks, 3 eng
- Core scope:
  - Tool-calling adapters for OpenAI, Anthropic, Google, Bedrock, Azure OpenAI.
  - `retikon init` and `retikon doctor`.
  - Local demo bootstrap (seed data + open console).

Sprint 4 - Agent frameworks + runtime backends
- Owner: ML Platform
- Estimate: 2 weeks, 2 eng
- Core scope:
  - LangChain + LlamaIndex adapters.
  - vLLM + TGI + ONNX Runtime backends.

Sprint 5 - Retrieval quality + evaluation
- Owner: Search/IR
- Estimate: 2 weeks, 2 eng
- Core scope:
  - Hybrid retrieval (keyword + vector fusion).
  - Reranking stage with configurable reranker.
  - Eval harness + CI regression suite (Ragas + Phoenix).
  - Basic feedback capture (thumbs up/down).

Sprint 6 - Permissions + Pro cost controls
- Owner: Platform Eng (Security) + FinOps
- Estimate: 2 weeks, 3 eng
- Core scope:
  - Tenant scoping + simple metadata rules.
- Pro scope:
  - ABAC policy engine + audit logs.
  - Metering, budgets, autoscaling profiles.

## Acceptance Criteria
- Connector catalog is machine-readable and validated in CI.
- Core connector SDK + registry working with generic HTTP connector.
- Tier 0 Pro connectors are production-ready with incremental sync.
- Tool-calling adapters work with 2+ providers in Core.
- Reranking improves top-5 relevance on a standard eval set.
- Permissions are enforced for query and export.
- Pro cost controls expose usage and allow hard budget limits.

## References (Source Catalogs)
- Airbyte connector catalog (sources + destinations): https://airbyte.com/connectors
- Airbyte sources/destinations docs: https://docs.airbyte.com/integrations/sources and https://docs.airbyte.com/integrations/destinations
- Kafka Connect: https://docs.confluent.io/platform/current/connect/index.html and https://kafka.apache.org/documentation/#connect
