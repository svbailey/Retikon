# Retikon v3.1 Execution Plan (Sprint by Sprint)

Cadence: 2-week sprints

## Repo boundary (Core vs Pro)

Core (OSS, cloud-agnostic):
- `retikon_core/`
- `local_adapter/`
- `retikon_cli/`
- `sdk/`
- `frontend/dev-console/` (Core UI; Pro features live here behind flags)
- `tests/core/`

Pro (commercial, GCP-specific):
- `gcp_adapter/`
- `infrastructure/terraform/`
- `Dev Docs/pro/`
- `tests/pro/`

All sprint tasks below are labeled by Core/Pro/Docs/UI so we can keep the
boundary clean and make a future split low-risk.

## Sprint 1 - Enterprise identity and RBAC/ABAC core
Goal: build identity and access-control foundations for Pro Enterprise.

Core tasks:
- Add identity provider config scaffolding: `retikon_core/auth/idp.py`.
- Implement RBAC roles and permission bundles: `retikon_core/auth/rbac.py`.
- Add ABAC policy evaluation engine: `retikon_core/auth/abac.py`.
- Add audit log schema (additive) in `retikon_core/schemas/graphar/`.

Pro tasks:
- Extend API auth middleware in `gcp_adapter/query_service.py` and
  `gcp_adapter/ingestion_service.py`.

Tests:
- Core: `tests/core/test_auth_rbac.py`, `tests/core/test_auth_abac.py`.
- Pro: `tests/pro/test_auth_middleware.py` (new).

Deliverables:
- Role- and policy-based access enforced in Pro API layer.

## Sprint 2 - Audit logging and compliance exports
Goal: auditable control plane actions with evidence exports.

Core tasks:
- Implement audit log writers in `retikon_core/audit/`.

Pro tasks:
- Add audit log API endpoints in `gcp_adapter/audit_service.py`.
- Add compliance export APIs for audit and access logs.

UI tasks:
- Update console views for audit log query in `frontend/dev-console/`.

Tests:
- Core: `tests/core/test_audit_logs.py`.
- Pro: `tests/pro/test_audit_service.py` (new).

Deliverables:
- Audit log end-to-end pipeline and UI view.

## Sprint 3 - Privacy controls and redaction
Goal: privacy-safe processing and exports.

Core tasks:
- Add privacy policy engine in `retikon_core/privacy/`.
- Add redaction pipeline hooks in `retikon_core/redaction/`.

Pro tasks:
- Add privacy policy endpoints in `gcp_adapter/privacy_service.py`.

UI tasks:
- Update console with privacy policy views.

Tests:
- Core: `tests/core/test_redaction.py`, `tests/core/test_privacy_policies.py`.
- Pro: `tests/pro/test_privacy_service.py` (new).

Deliverables:
- Redaction policies enforced in exports and query results.

## Sprint 4 - Fleet management and OTA rollouts
Goal: device fleet dashboard and update workflows.

Core tasks:
- Add device registry and status model in `retikon_core/fleet/`.
- Add OTA rollout planner in `retikon_core/fleet/rollouts.py`.
- Add device hardening hooks in `retikon_core/fleet/security.py`.

Pro tasks:
- Add fleet management endpoints in `gcp_adapter/fleet_service.py`.

UI tasks:
- Add fleet UI panels in `frontend/dev-console/`.

Tests:
- Core: `tests/core/test_fleet_rollouts.py`, `tests/core/test_device_security.py`.
- Pro: `tests/pro/test_fleet_service.py` (new).

Deliverables:
- Fleet registry + staged OTA rollouts with rollback.

## Sprint 5 - Advanced Data Factory + connectors
Goal: annotation, training, model registry, and connectors.

Core tasks:
- Add dataset and annotation schema (additive) in `retikon_core/schemas/graphar/`.
- Add annotation services in `retikon_core/data_factory/annotations.py`.
- Add model registry metadata in `retikon_core/data_factory/model_registry.py`.
- Add training orchestration scaffolding in `retikon_core/data_factory/training.py`.
- Add connector interfaces in `retikon_core/connectors/` (generic HTTP only).

Pro tasks:
- Implement managed connector adapters in `gcp_adapter/` (Kafka/Snowflake/etc.).
- Add managed OCR connector hooks (Pro-only).
- Add legacy Office conversion pipeline for `.doc`/`.ppt` in Pro (Core remains
  `.doc`/`.ppt` unsupported).
- Add Data Factory endpoints in `gcp_adapter/data_factory_service.py`.

UI tasks:
- Extend console UI for annotation QA and model registry.

Tests:
- Core: `tests/core/test_data_factory_annotations.py`,
  `tests/core/test_model_registry.py`, `tests/core/test_connectors.py`.
- Pro: `tests/pro/test_data_factory_service.py`, `tests/pro/test_document_conversion.py`.

Deliverables:
- Annotation QA and model registry workflows operational.
- Connectors available for export and streaming (Pro-managed).

## Sprint 6 - Workflow orchestration
Goal: configurable post-processing workflows.

Core tasks:
- Add workflow DSL/API in `retikon_core/workflows/`.

Pro tasks:
- Add workflow scheduler in `gcp_adapter/workflow_service.py`.

UI tasks:
- Add workflow UI in `frontend/dev-console/` (basic run history).

Tests:
- Core: `tests/core/test_workflows.py`.
- Pro: `tests/pro/test_workflow_service.py` (new).

Deliverables:
- Workflow orchestration available for batch jobs.

## Sprint 7 - BYOC Kubernetes adapter (Pro Enterprise)
Goal: portable Pro control plane.

Core tasks:
- Define provider interfaces in `retikon_core/providers/`
  (object store, queue, secrets, state store).

Pro tasks:
- Implement Kubernetes adapter in `k8s_adapter/` (Pro-only).

Docs:
- Add BYOC deployment docs: `Dev Docs/pro/Deployment.md` and new
  `Dev Docs/BYOC-Guide.md`.

Tests:
- Core: `tests/core/test_providers.py`.
- Pro: `tests/pro/test_k8s_adapter_smoke.py` (new).

Deliverables:
- BYOC deployment path validated in staging.

## Sprint 8 - Reliability hardening + chaos testing
Goal: enterprise-grade reliability and resilience testing.

Core tasks:
- Add chaos policy manager in `retikon_core/chaos/`.

Pro tasks:
- Add chaos scheduling endpoints in `gcp_adapter/chaos_service.py`.

Docs:
- Extend monitoring dashboards and runbooks in
  `Dev Docs/pro/Operations-Runbook.md` and `Dev Docs/pro/DLQ-Runbook.md`.

Tests:
- Core: `tests/core/test_chaos_policies.py`.
- Pro: `tests/pro/test_chaos_service.py` (new).

Deliverables:
- Chaos policies and reports in staging.
- Updated ops runbooks.

## Sprint 9 - Query performance acceleration
Goal: reduce multimodal tail latency with optimized runtimes and tiered query services.

Core tasks:
- Add ONNX/quantized embedding backends in `retikon_core/embeddings/`.
- Add routing hooks/interfaces in `retikon_core/query_engine/` (no GPU tiers enabled).

Pro tasks:
- Add GPU query service profile/entrypoint in `gcp_adapter/`.
- Deploy GPU services via `infrastructure/terraform/`.

Docs:
- Add SLO load tests for text-only vs multimodal queries in
  `Dev Docs/pro/Load-Testing.md`.

Tests:
- Core: `tests/core/test_embedding_backends.py`, `tests/core/test_query_routing.py`.
- Pro: `tests/pro/test_query_tiers.py` (new).

Deliverables:
- CPU-optimized (ONNX/quantized) and GPU query tiers available in Pro.
- Documented routing rules and performance baselines.

## Feature-to-Sprint Mapping
See `Dev Docs/Feature-to-Sprint-Mapping.md`.

## Sprint Checklists
Per-sprint checklists are stored in `Dev Docs/sprints/` using the naming
convention `v3.1-sprint-XX.md`.
