## 3) Planned Features (v3.1 Execution Plan)

### Sprint 1 - Enterprise identity and RBAC/ABAC core
- **IDP config scaffolding**: Lets enterprises describe their identity providers so SSO integrations are possible.
- **RBAC roles and permissions**: Defines role bundles so access can be managed simply.
- **ABAC engine**: Evaluates attribute-based rules so policies can be fine-grained.
- **Audit log schema update**: Adds schema support so audits can be stored consistently.
- **Pro auth middleware extensions**: Enforces access rules in managed APIs so policies actually apply.

### Sprint 2 - Audit logging and compliance exports
- **Audit log writers**: Record actions so compliance data exists.
- **Audit service endpoints**: Query and export audit logs so compliance teams can retrieve evidence.
- **UI audit views**: Let users view audits in the console so debugging is easier.

### Sprint 3 - Privacy controls and redaction
- **Privacy policy engine**: Centralizes privacy rules so redaction is consistent.
- **Redaction hooks**: Integrates redaction into pipelines so outputs stay safe.
- **Privacy endpoints (Pro)**: Lets admins create/update policies so rules are manageable.
- **Privacy UI**: Shows policies so governance teams can review them.

### Sprint 4 - Fleet management and OTA rollouts
- **Device registry + status model**: Tracks devices so fleets can be managed.
- **OTA rollout planner**: Plans staged updates so rollouts are safe.
- **Device hardening hooks**: Adds security checks so devices stay protected.
- **Fleet service (Pro)**: Exposes APIs so fleet management is available in managed environments.
- **Fleet UI**: Provides dashboard views so operators can monitor rollouts.

### Sprint 5 - Advanced Data Factory + connectors
- **Dataset and annotation schema**: Defines labeling data so training workflows are consistent.
- **Annotation services**: Manage labels so training data is curated.
- **Model registry metadata**: Tracks models so deployments are auditable.
- **Training orchestration scaffolding**: Enables training workflows so models can be updated.
- **Connector interfaces**: Standardizes connector APIs so integrations are predictable.
- **Pro managed connectors + OCR hooks + Office conversion**: Adds enterprise data and OCR capabilities so complex formats are supported.
- **Data factory endpoints (Pro)**: Exposes data factory APIs so workflows are accessible.

### Sprint 6 - Workflow orchestration
- **Workflow DSL/API**: Lets users define post-processing steps so pipelines are configurable.
- **Workflow scheduler (Pro)**: Runs workflows on a schedule so automation is simple.
- **Workflow UI**: Shows runs and status so operators can track jobs.

### Sprint 7 - BYOC Kubernetes adapter
- **Provider interfaces**: Abstract storage, queues, secrets, state so multiple clouds can be supported.
- **Kubernetes adapter (Pro)**: Runs Pro control plane in customer clusters so BYOC is possible.
- **BYOC docs**: Guides deployment so enterprises can self-host.

### Sprint 8 - Reliability hardening + chaos testing
- **Chaos policy manager**: Defines fault injection so reliability is tested.
- **Chaos scheduling endpoints (Pro)**: Runs chaos tests so resilience is measurable.
- **Runbook updates**: Documents ops procedures so on-call can respond quickly.

### Sprint 9 - Query performance acceleration
- **ONNX/quantized embedding backends**: Speeds embeddings so search latency drops.
- **Query routing hooks**: Routes queries to the best tier so performance is optimized.
- **GPU query services (Pro)**: Adds GPU tiers so heavy workloads are fast.
- **Load-test docs**: Defines test baselines so performance changes are measurable.
