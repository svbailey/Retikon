# Retikon v3.1 Execution Plan (Sprint by Sprint)

Cadence: 2-week sprints

## Sprint 1 - Enterprise identity and RBAC/ABAC core
Goal: build identity and access-control foundations for Pro Enterprise.

Tasks:
- Add identity provider config scaffolding: `retikon_core/auth/idp.py`.
- Implement RBAC roles and permission bundles: `retikon_core/auth/rbac.py`.
- Add ABAC policy evaluation engine: `retikon_core/auth/abac.py`.
- Extend API auth middleware in `gcp_adapter/query_service.py` and `gcp_adapter/ingestion_service.py`.
- Add audit log schema (additive) in `retikon_core/schemas/graphar/`.

Tests:
- `tests/test_auth_rbac.py`, `tests/test_auth_abac.py`.

Deliverables:
- Role- and policy-based access enforced in API layer.

## Sprint 2 - Audit logging and compliance exports
Goal: auditable control plane actions with evidence exports.

Tasks:
- Implement audit log writers in `retikon_core/audit/`.
- Add audit log API endpoints in `gcp_adapter/audit_service.py`.
- Add compliance export APIs for audit and access logs.
- Update console views for audit log query in `frontend/dev-console/`.

Tests:
- `tests/test_audit_logs.py`.

Deliverables:
- Audit log end-to-end pipeline and UI view.

## Sprint 3 - Privacy controls and redaction
Goal: privacy-safe processing and exports.

Tasks:
- Add privacy policy engine in `retikon_core/privacy/`.
- Add redaction pipeline hooks in `retikon_core/redaction/`.
- Add privacy policy endpoints in `gcp_adapter/privacy_service.py`.
- Update console with privacy policy views.

Tests:
- `tests/test_redaction.py`, `tests/test_privacy_policies.py`.

Deliverables:
- Redaction policies enforced in exports and query results.

## Sprint 4 - Fleet management and OTA rollouts
Goal: device fleet dashboard and update workflows.

Tasks:
- Add device registry and status model in `retikon_core/fleet/`.
- Add OTA rollout planner in `retikon_core/fleet/rollouts.py`.
- Add device hardening hooks (cert rotation, secure boot checks) in `retikon_core/fleet/security.py`.
- Add fleet management endpoints in `gcp_adapter/fleet_service.py`.
- Add fleet UI panels in `frontend/dev-console/`.

Tests:
- `tests/test_fleet_rollouts.py`, `tests/test_device_security.py`.

Deliverables:
- Fleet registry + staged OTA rollouts with rollback.

## Sprint 5 - Advanced Data Factory + connectors
Goal: annotation, training, model registry, and connectors.

Tasks:
- Add dataset and annotation schema (additive) in `retikon_core/schemas/graphar/`.
- Add annotation services in `retikon_core/data_factory/annotations.py`.
- Add model registry metadata in `retikon_core/data_factory/model_registry.py`.
- Add training orchestration scaffolding in `retikon_core/data_factory/training.py`.
- Add connector interfaces in `retikon_core/connectors/` (Kafka, Snowflake, generic HTTP).
- Add legacy Office conversion pipeline for `.doc`/`.ppt` in `retikon_core/data_factory/conversion.py`.
- Add OCR connector hooks for managed OCR services in `retikon_core/connectors/`.
- Add Data Factory endpoints in `gcp_adapter/data_factory_service.py`.
- Extend console UI for annotation QA and model registry.

Tests:
- `tests/test_data_factory_annotations.py`, `tests/test_model_registry.py`, `tests/test_connectors.py`.
- `tests/test_document_conversion.py`.

Deliverables:
- Annotation QA and model registry workflows operational.
- Connectors available for export and streaming.

## Sprint 6 - Workflow orchestration
Goal: configurable post-processing workflows.

Tasks:
- Add workflow DSL/API in `retikon_core/workflows/`.
- Add workflow scheduler in `gcp_adapter/workflow_service.py`.
- Add workflow UI in `frontend/dev-console/` (basic run history).

Tests:
- `tests/test_workflows.py`.

Deliverables:
- Workflow orchestration available for batch jobs.

## Sprint 7 - BYOC Kubernetes adapter (Pro Enterprise)
Goal: portable Pro control plane.

Tasks:
- Define provider interfaces in `retikon_core/providers/` (object store, queue, secrets, state store).
- Implement Kubernetes adapter in `k8s_adapter/` (new).
- Add BYOC deployment docs: `Dev Docs/Deployment.md` and new `Dev Docs/BYOC-Guide.md`.

Tests:
- `tests/test_providers.py` for interface compliance.

Deliverables:
- BYOC deployment path validated in staging.

## Sprint 8 - Reliability hardening + chaos testing
Goal: enterprise-grade reliability and resilience testing.

Tasks:
- Add chaos policy manager in `retikon_core/chaos/`.
- Add chaos scheduling endpoints in `gcp_adapter/chaos_service.py`.
- Extend monitoring dashboards and runbooks in `Dev Docs/Operations-Runbook.md` and `Dev Docs/DLQ-Runbook.md`.

Tests:
- `tests/test_chaos_policies.py`.

Deliverables:
- Chaos policies and reports in staging.
- Updated ops runbooks.

## Sprint 9 - Query performance acceleration
Goal: reduce multimodal tail latency with optimized runtimes and tiered query services.

Tasks:
- Add ONNX/quantized embedding backends in `retikon_core/embeddings/`.
- Add GPU query service profile/entrypoint in `gcp_adapter/` and deploy via Terraform.
- Add query routing by modality/SLA tier in `retikon_core/query_engine/` and adapters.
- Add SLO load tests for text-only vs multimodal queries in `Dev Docs/Load-Testing.md`.

Tests:
- `tests/test_embedding_backends.py`
- `tests/test_query_routing.py`

Deliverables:
- CPU-optimized (ONNX/quantized) and GPU query tiers available in Pro.
- Documented routing rules and performance baselines.

## Feature-to-Sprint Mapping
See `Dev Docs/Feature-to-Sprint-Mapping.md`.

## Sprint Checklists
Per-sprint checklists are stored in `Dev Docs/sprints/` using the naming
convention `v3.1-sprint-XX.md`.
