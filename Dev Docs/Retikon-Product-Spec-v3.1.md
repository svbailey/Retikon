# Retikon Product Spec v3.1

Status: Draft
Owner: Product + Eng
Date: 2026-01-26

## Summary
Retikon v3.1 extends the v3.0 open-core platform with enterprise governance, fleet operations, advanced Data Factory tooling, privacy controls, and a BYOC Kubernetes deployment option. v3.1 focuses on regulated, multi-tenant production environments and adds full enterprise identity, RBAC/ABAC policies, fleet UI, annotation/model registry workflows, connectors, and portability beyond GCP.

## Goals
- Deliver enterprise identity, access control, and auditability.
- Add BYOC (Kubernetes) deployment for Pro Enterprise.
- Expand Data Factory with annotation QA, training orchestration, and model registry.
- Provide fleet management, device hardening, and staged rollouts for edge devices.

## Non-goals
- Core license changes (Core remains Apache 2.0).
- Breaking changes to GraphAr layout or model defaults.

## Tier Additions (Pro Enterprise)
- SSO/SAML/OAuth identity federation.
- Full RBAC + ABAC with field-level policies and masking.
- Multi-tenant isolation with project-level data boundaries.
- Fleet management UI with OTA staging and rollback.
- Advanced Data Factory UI (annotation QA, model registry, training orchestration).
- Privacy controls (redaction, PII masking) and compliance exports.
- BYOC Kubernetes deployment with provider abstractions.

## Functional Requirements

### Access and Governance
- Identity provider integrations with group-to-role mapping.
- RBAC roles and permission bundles; ABAC policies for data scopes.
- Audit logs for all control-plane actions with retention controls.
- Field-level masking and export controls for sensitive data.
- Compliance evidence exports (audit trails, access logs, retention actions).

### Privacy Controls
- Redaction policies for faces, license plates, and PII in transcripts.
- Configurable masking rules per tenant/stream.
- Privacy-safe exports with irreversible redaction options.

### Fleet and Reliability
- Fleet dashboard: device registration, status, heartbeat, location grouping.
- OTA updates with staged rollout, canary, and rollback.
- Policy-based device configuration and drift detection.
- Device hardening: cert rotation, secure boot validation, anomaly detection.
- Chaos testing policies with reports and rollback workflows.

### Data Factory (Advanced)
- Annotation UI with QA workflow and dataset versioning.
- Model registry with promotion workflows (dev -> staging -> prod).
- Training orchestration UI and export connectors.
- Workflow DSL/API for batch jobs with retries and schedules.
- Legacy Office conversion pipeline (.doc/.ppt -> .docx/.pptx) for ingestion.

### Portability
- BYOC Kubernetes adapter for Pro Enterprise.
- Provider abstraction layers for object store, queue, secrets, state store.
- Deployment manifests and upgrade guides.

### Connectors
- Streaming connectors (Kafka and Pub/Sub).
- Warehouse/lakehouse export connectors (Snowflake, BigQuery, S3-compatible).
- SIEM/observability connectors (Splunk or generic HTTP collector).
 - OCR service connectors for scalable processing (managed).

## Architecture Requirements
- Keep GraphAr additive evolution and `retikon_v2/` prefix.
- Extend interfaces for object store, queue, secrets, state store to support BYOC.
- Maintain separation between core logic and deployment adapters.

## API Requirements
- SSO and user management endpoints.
- Audit log query endpoints.
- Fleet management endpoints (register, update, rollout).
- Data Factory endpoints for datasets, annotations, training jobs, and model registry.
- Privacy policy management endpoints.

## Console Requirements
- Admin console for user/role management.
- Fleet view with rollout controls and health stats.
- Annotation and model registry dashboards.
- Compliance views for audit logs and policy enforcement.

## Observability and Compliance
- Extended metrics and audit logging with retention controls.
- Evidence exports for compliance.
- Compliance-ready log retention configuration.

## Performance Targets
- Fleet operations: staged rollout to 10k devices within 1 hour.
- Audit log query p95 <= 1s for 7-day window.
- Privacy redaction pipeline adds <= 10 percent latency to media processing.

## Acceptance Criteria (v3.1)
- Enterprise identity and RBAC/ABAC enforced across APIs.
- Fleet UI and OTA rollouts functional with rollback.
- Annotation QA and model registry workflows usable end-to-end.
- Privacy policies enforced in exports and query responses.
- BYOC Kubernetes deployment documented and validated.
- Developer consumption patterns documented in `Dev Docs/Developer-Integration-Guide.md`.
- Advanced UI behavior documented in `Dev Docs/Developer-Console-UI-Guide.md`.

## Dependencies
- v3.0 Core and Pro MVP complete.
- Provider abstractions defined in core.
