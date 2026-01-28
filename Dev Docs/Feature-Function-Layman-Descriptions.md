# Retikon Feature and Function Descriptions (Layman Terms)

Date: 2026-01-28

This document explains what each feature and function does, and why it exists, in plain language.
Descriptions are intentionally short and non-technical so they can be used for documentation planning.
Internal helpers are included because they are still part of the codebase, but they are marked as internal.

## 1) Current Core Features (What and Why)

### Ingestion and processing
- **Multimodal ingestion**: Handles documents, images, audio, and video so all common content can enter the system.
- **Download and staging**: Downloads inputs to a safe temp area so processing is consistent and resumable.
- **OCR for images and PDFs**: Extracts text from images/PDFs so visual documents become searchable.
- **Audio transcription**: Turns speech into text so audio becomes searchable.
- **Media probing and keyframes**: Analyzes video/audio properties and extracts frames so video is searchable and previewable.
- **Rate limiting**: Throttles heavy inputs so ingestion stays stable under load.
- **Streaming ingest utilities**: Batches and flushes events so live feeds can be handled efficiently.
- **Idempotency (memory + SQLite)**: Prevents duplicate work so retries do not create duplicate data.

### Search and indexing
- **Snapshot index builder**: Builds a local DuckDB snapshot so queries are fast.
- **Query runner**: Executes text, keyword, metadata, and image searches so users can retrieve results in multiple ways.
- **Warm start**: Pre-loads extensions and credentials so query startup is fast and secure.
- **Privacy redaction in queries**: Removes sensitive text before results return so privacy rules are enforced.

### Storage and schemas
- **GraphAr schemas**: Defines how data is stored so readers and writers stay compatible.
- **Manifests and writers**: Track output files so ingestion output is organized and auditable.
- **Schema validation**: Validates GraphAr files so corrupt data is caught early.

### Governance, privacy, and compliance
- **RBAC and ABAC**: Enforces who can do what so access is controlled.
- **API key management**: Stores and verifies keys so API access is secured.
- **Privacy policy engine**: Applies privacy policies so sensitive data is protected.
- **Redaction**: Removes sensitive content so exports and results are safe to share.
- **Audit logs**: Records actions so compliance reviews are possible.
- **Alerts and webhooks**: Sends notifications so downstream systems can react.
- **Retention policies**: Controls how long data stays so storage and compliance needs are met.
- **Compaction**: Shrinks and rewrites data so storage stays efficient.
- **Metering**: Records usage so costs and limits can be tracked.
- **Tenancy scoping**: Filters data by tenant so multi-tenant isolation is enforced.

### Edge, local runtime, and tooling
- **Edge agent + buffer**: Collects and buffers files at the edge so uploads are resilient.
- **Local adapters**: Run ingest/query locally so developers can test quickly.
- **CLI**: Starts services and runs ingest/query so operators can use the system from the terminal.
- **SDKs (Python/JS)**: Provide simple client APIs so users can integrate quickly.
- **Dev console UI**: Walks users through upload, ingest, index, query, and audit so onboarding is smooth.

### Connectors (registry-driven)
- **Connector registry**: Lists supported connectors so integrations are consistent and documented.
- **Core edition connectors (from registry)**: gcs, s3, azure_blob, postgres, mysql, google_drive, github, gitlab. These exist to give open-source users practical data sources and sinks.
- **Pro edition connectors (from registry)**: bigquery, snowflake, kafka, pubsub, sharepoint, onedrive, slack, redshift, databricks_delta, sqlserver, mongodb, salesforce, zendesk, servicenow, jira, confluence, notion, teams, sftp, kinesis, event_hubs, rabbitmq, oracle, dynamodb, neo4j, minio, wasabi, splunk, datadog, sharepoint_onprem, box, dropbox. These exist to cover enterprise data systems.

### Capability flags
- **Core capability flags** (in `retikon_core/capabilities.py`) exist so features can be toggled by edition or environment without changing code.

## 2) Current Pro Features (What and Why)

### Managed services (GCP)
- **Ingestion service**: Runs ingestion in Cloud Run so production ingest is scalable and secure.
- **Query service**: Runs search in Cloud Run so production query is scalable and secure.
- **Audit service**: Exposes audit logs and exports so compliance reporting is easy.
- **Privacy service**: Manages privacy policies so admins can update rules centrally.
- **Dev console service**: Supports uploads and previews so ops teams can inspect data safely.
- **Stream ingest service**: Accepts streaming events so real-time pipelines work.
- **Edge gateway service**: Buffers uploads at the edge so devices can operate with flaky networks.
- **Webhook service**: Manages webhooks and alerts so external systems can be notified.

### Pro infrastructure (Terraform)
- **GCS buckets**: Raw + graph buckets store inputs and outputs so the pipeline is durable.
- **Pub/Sub + DLQ**: Event transport and dead-lettering keep ingestion reliable.
- **Cloud Run services/jobs**: Services and jobs run in managed compute so ops is simple.
- **Eventarc triggers**: GCS events trigger ingest so uploads auto-process.
- **Scheduler**: Runs compaction on a schedule so storage stays efficient.
- **Secret Manager**: Stores API keys so secrets are not baked into images.
- **Monitoring + alerting**: Dashboards and alerts keep ops teams informed.

### Pro capability flags
- **Pro capability flags** (in `retikon_core/capabilities.py`) exist so paid features can be clearly separated from OSS features.

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

## 4) Planned Features (v3.2 Execution Plan + Sprints)

### v3.2 feature catalog (core)
- **Connector SDK + registry**: Standardizes integrations so new connectors are easy to add.
- **Generic HTTP connector**: Provides a baseline connector so any HTTP source/sink can integrate.
- **Tool-calling adapters**: Lets LLMs call tools so agents can act.
- **Agent framework adapters**: Integrates frameworks so users can bring their preferred orchestration.
- **Runtime backends (vLLM, TGI, ONNX)**: Adds deployment options so inference is flexible.
- **Hybrid retrieval + reranking**: Improves relevance so results are higher quality.
- **Eval harness + feedback**: Measures quality so regressions are caught early.
- **Basic permissions**: Enforces tenant scoping so data is isolated.
- **DX bootstrap**: Makes local setup easier so adoption is faster.

### v3.2 feature catalog (pro)
- **Managed connector scheduler**: Runs syncs so connectors stay up to date.
- **Streaming connectors**: Enables real-time data flows so latency is low.
- **ABAC + row-level enforcement**: Protects data so governance is strong.
- **Advanced feedback loops**: Captures usage signals so quality can improve.
- **Cost controls + autoscaling profiles**: Keeps spend predictable so enterprise ops are viable.

### Sprint 01 - Connector SDK + Registry (Core)
- **Connector interfaces + registry loader**: Standardizes connector metadata so config is consistent.
- **CLI commands**: Lists/validates connectors so users can trust configuration.
- **Generic HTTP connector**: Gives a default integration path so onboarding is quick.

### Sprint 02 - Connector Scheduler + Tier 0 Pro connectors
- **Managed scheduler**: Runs and retries connector syncs so data stays fresh.
- **Tier 0 connectors**: Adds core enterprise systems so customers can integrate quickly.
- **Console connector wizard**: Guides setup so configuration is less error-prone.

### Sprint 03 - Tool-calling adapters + DX bootstrap
- **Tool-calling adapters**: Enables LLM tools so agents can act on data.
- **`retikon init` + `retikon doctor` improvements**: Simplifies setup so developers can start fast.
- **Local demo bootstrap**: Seeds data + opens console so demos are easy.

### Sprint 04 - Agent frameworks + runtime backends
- **LangChain + LlamaIndex adapters**: Supports popular frameworks so users can adopt quickly.
- **vLLM + TGI + ONNX Runtime backends**: Adds runtime options so deployment is flexible.

### Sprint 05 - Retrieval quality + evaluation
- **Hybrid retrieval**: Blends keyword + vector so recall is higher.
- **Reranking**: Improves result ordering so precision improves.
- **Eval harness**: Automates evaluation so regressions are caught.
- **Feedback capture**: Collects user signals so quality can improve.

### Sprint 06 - Permissions + Pro cost controls
- **Tenant scoping + metadata rules**: Enforces isolation so data is protected.
- **ABAC + audit logs (Pro)**: Adds governance so access is controlled and provable.
- **Metering + budgets + autoscaling profiles (Pro)**: Controls cost so enterprise usage is sustainable.

## 5) Function Catalog (Core)

### `local_adapter/ingestion_service.py`
- Functions
  - `_infer_modality`: Internal helper that figures out modality, so local development workflows run.
  - `_prefix_for_modality`: Internal helper that builds a prefix for for modality, so local development workflows run.
  - `health`: Reports service health, so local development workflows run.
  - `ingest`: Accepts content to ingest and starts processing, so local development workflows run.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so local development workflows run.
  - `IngestRequest`: Data structure or helper class for Ingest Request, so local development workflows run.
  - `IngestResponse`: Data structure or helper class for Ingest Response, so local development workflows run.

### `local_adapter/query_service.py`
- Functions
  - `lifespan`: Function that sets up startup and shutdown hooks, so local development workflows run.
  - `_correlation_id`: Internal helper that correlation id, so local development workflows run.
  - `_cors_origins`: Internal helper that cors origins, so local development workflows run.
  - `add_correlation_id`: Function that add correlation id, so local development workflows run.
  - `_api_key_required`: Internal helper that api key required, so local development workflows run.
  - `_get_api_key`: Internal helper that gets api key, so local development workflows run.
  - `_authorize`: Internal helper that authorizes it, so local development workflows run.
  - `_is_local_uri`: Internal helper that checks whether local uri, so local development workflows run.
  - `_default_snapshot_uri`: Internal helper that builds the default snapshot uri, so local development workflows run.
  - `_default_healthcheck_uri`: Internal helper that builds the default healthcheck uri, so local development workflows run.
  - `_apply_privacy_redaction`: Internal helper that applies privacy redaction, so local development workflows run.
  - `_load_snapshot`: Internal helper that loads snapshot, so local development workflows run.
  - `_resolve_modalities`: Internal helper that resolves modalities, so local development workflows run.
  - `_resolve_search_type`: Internal helper that resolves search type, so local development workflows run.
  - `_warm_query_models`: Internal helper that warms up query models, so local development workflows run.
  - `health`: Reports service health, so local development workflows run.
  - `query`: Runs a search request and returns results, so local development workflows run.
  - `reload_snapshot`: Function that reload snapshot, so local development workflows run.
- Classes
  - `SnapshotState`: Data structure or helper class for Snapshot State, so local development workflows run.
  - `HealthResponse`: Data structure or helper class for Health Response, so local development workflows run.
  - `QueryRequest`: Data structure or helper class for Query Request, so local development workflows run.
  - `QueryHit`: Data structure or helper class for Query Hit, so local development workflows run.
  - `QueryResponse`: Data structure or helper class for Query Response, so local development workflows run.

### `retikon_cli/cli.py`
- Functions
  - `_resolve_ingest_url`: Internal helper that builds the resolve ingest url, so users can run services from the CLI.
  - `_resolve_query_url`: Internal helper that builds the resolve query url, so users can run services from the CLI.
  - `_request_json`: Internal helper that request json, so users can run services from the CLI.
  - `_print_json`: Internal helper that print json, so users can run services from the CLI.
  - `_read_env_file`: Internal helper that reads env file, so users can run services from the CLI.
  - `_append_missing_env`: Internal helper that append missing env, so users can run services from the CLI.
  - `_apply_env`: Internal helper that applies env, so users can run services from the CLI.
  - `_update_env_file`: Internal helper that updates env file, so users can run services from the CLI.
  - `_ensure_env_file`: Internal helper that ensures env file, so users can run services from the CLI.
  - `_infer_modality`: Internal helper that figures out modality, so users can run services from the CLI.
  - `_prefix_for_modality`: Internal helper that builds a prefix for for modality, so users can run services from the CLI.
  - `_seed_local_graph`: Internal helper that seeds local graph, so users can run services from the CLI.
  - `_build_local_snapshot`: Internal helper that builds local snapshot, so users can run services from the CLI.
  - `_uvicorn_cmd`: Internal helper that builds the uvicorn command, so users can run services from the CLI.
  - `_run_services`: Internal helper that run services, so users can run services from the CLI.
  - `cmd_up`: Function that runs the cli command up, so users can run services from the CLI.
  - `cmd_daemon`: Function that runs the cli command daemon, so users can run services from the CLI.
  - `cmd_ingest`: Function that runs the cli command ingest, so users can run services from the CLI.
  - `_parse_metadata`: Internal helper that parses metadata, so users can run services from the CLI.
  - `cmd_query`: Function that runs the cli command query, so users can run services from the CLI.
  - `cmd_status`: Function that runs the cli command status, so users can run services from the CLI.
  - `cmd_init`: Function that runs the cli command init, so users can run services from the CLI.
  - `cmd_doctor`: Function that runs the cli command doctor, so users can run services from the CLI.
  - `build_parser`: Function that builds parser, so users can run services from the CLI.
  - `main`: Entry point that runs the module, so users can run services from the CLI.

### `retikon_core/alerts/rules.py`
- Functions
  - `rule_matches`: Function that rule matches, so alerts can be triggered on events.
  - `evaluate_rules`: Function that evaluate rules, so alerts can be triggered on events.
  - `_matches_type`: Internal helper that matches type, so alerts can be triggered on events.

### `retikon_core/alerts/store.py`
- Functions
  - `alert_registry_uri`: Function that builds the alert registry uri, so alerts can be triggered on events.
  - `load_alerts`: Function that loads alerts, so alerts can be triggered on events.
  - `save_alerts`: Function that saves alerts, so alerts can be triggered on events.
  - `register_alert`: Function that registers alert, so alerts can be triggered on events.
  - `update_alert`: Function that updates alert, so alerts can be triggered on events.
  - `_normalize_list`: Internal helper that cleans up list, so alerts can be triggered on events.
  - `_rule_from_dict`: Internal helper that builds rule from a dict, so alerts can be triggered on events.
  - `_normalize_destinations`: Internal helper that cleans up destinations, so alerts can be triggered on events.
  - `_coerce_iterable`: Internal helper that converts iterable, so alerts can be triggered on events.
  - `_coerce_float`: Internal helper that converts float, so alerts can be triggered on events.

### `retikon_core/alerts/types.py`
- Classes
  - `AlertDestination`: Data structure or helper class for Alert Destination, so alerts can be triggered on events.
  - `AlertRule`: Data structure or helper class for Alert Rule, so alerts can be triggered on events.
  - `AlertMatch`: Data structure or helper class for Alert Match, so alerts can be triggered on events.

### `retikon_core/audit/compaction.py`
- Functions
  - `write_compaction_audit_log`: Function that writes compaction audit log, so actions are logged for compliance.
- Classes
  - `CompactionAuditRecord`: Data structure or helper class for Compaction Audit Record, so actions are logged for compliance.

### `retikon_core/audit/logs.py`
- Functions
  - `_resolve_scope`: Internal helper that resolves scope, so actions are logged for compliance.
  - `record_audit_log`: Function that records audit log, so actions are logged for compliance.
- Classes
  - `AuditLogRecord`: Data structure or helper class for Audit Log Record, so actions are logged for compliance.

### `retikon_core/auth/abac.py`
- Functions
  - `_policies_uri`: Internal helper that builds the policies uri, so access is controlled and auditable.
  - `load_policies`: Function that loads policies, so access is controlled and auditable.
  - `build_attributes`: Function that builds attributes, so access is controlled and auditable.
  - `is_allowed`: Function that checks whether allowed, so access is controlled and auditable.
  - `abac_allowed`: Function that abac allowed, so access is controlled and auditable.
  - `evaluate_policies`: Function that evaluate policies, so access is controlled and auditable.
  - `_matches`: Internal helper that matches, so access is controlled and auditable.
  - `_match_value`: Internal helper that match value, so access is controlled and auditable.
  - `_coerce_dict`: Internal helper that converts dict, so access is controlled and auditable.
- Classes
  - `Policy`: Data structure or helper class for Policy, so access is controlled and auditable.

### `retikon_core/auth/authorize.py`
- Functions
  - `authorize_api_key`: Function that authorizes api key, so access is controlled and auditable.

### `retikon_core/auth/idp.py`
- Functions
  - `_idp_config_uri`: Internal helper that builds the idp config uri, so access is controlled and auditable.
  - `load_idp_configs`: Function that loads idp configs, so access is controlled and auditable.
  - `_coerce_str`: Internal helper that converts str, so access is controlled and auditable.
  - `_coerce_dict`: Internal helper that converts dict, so access is controlled and auditable.
- Classes
  - `IdentityProviderConfig`: Data structure or helper class for Identity Provider Config, so access is controlled and auditable.

### `retikon_core/auth/rbac.py`
- Functions
  - `_bindings_uri`: Internal helper that builds the bindings uri, so access is controlled and auditable.
  - `load_role_bindings`: Function that loads role bindings, so access is controlled and auditable.
  - `_default_role`: Internal helper that default role, so access is controlled and auditable.
  - `_permissions_for_roles`: Internal helper that permissions for roles, so access is controlled and auditable.
  - `is_action_allowed`: Function that checks whether action allowed, so access is controlled and auditable.
- Classes
  - `Role`: Data structure or helper class for Role, so access is controlled and auditable.

### `retikon_core/auth/store.py`
- Functions
  - `api_key_registry_uri`: Function that builds the api key registry uri, so access is controlled and auditable.
  - `resolve_registry_base`: Function that resolves registry base, so access is controlled and auditable.
  - `hash_key`: Function that hashes key, so access is controlled and auditable.
  - `load_api_keys`: Function that loads api keys, so access is controlled and auditable.
  - `save_api_keys`: Function that saves api keys, so access is controlled and auditable.
  - `register_api_key`: Function that registers api key, so access is controlled and auditable.
  - `find_api_key`: Function that finds api key, so access is controlled and auditable.
  - `_api_key_from_dict`: Internal helper that builds api key from a dict, so access is controlled and auditable.
  - `_coerce_str`: Internal helper that converts str, so access is controlled and auditable.

### `retikon_core/auth/types.py`
- Classes
  - `ApiKey`: Data structure or helper class for API Key, so access is controlled and auditable.
  - `AuthContext`: Data structure or helper class for Auth Context, so access is controlled and auditable.

### `retikon_core/capabilities.py`
- Functions
  - `_parse_list`: Internal helper that parses list, so features can be toggled by edition.
  - `_validate_capabilities`: Internal helper that checks capabilities, so features can be toggled by edition.
  - `get_edition`: Function that gets edition, so features can be toggled by edition.
  - `resolve_capabilities`: Function that resolves capabilities, so features can be toggled by edition.
  - `has_capability`: Function that checks whether it has capability, so features can be toggled by edition.

### `retikon_core/compaction/io.py`
- Functions
  - `_sha256_file`: Internal helper that sha256 file, so storage stays compact and efficient.
  - `_write_local`: Internal helper that writes local, so storage stays compact and efficient.
  - `_write_remote`: Internal helper that writes remote, so storage stays compact and efficient.
  - `_open_uri`: Internal helper that builds the open uri, so storage stays compact and efficient.
  - `_read_schema`: Internal helper that reads schema, so storage stays compact and efficient.
  - `_align_table`: Internal helper that align table, so storage stays compact and efficient.
  - `unify_schema`: Function that unify schema, so storage stays compact and efficient.
  - `iter_tables`: Function that iter tables, so storage stays compact and efficient.
  - `write_parquet_tables`: Function that writes parquet tables, so storage stays compact and efficient.
  - `delete_uri`: Function that builds the delete uri, so storage stays compact and efficient.
  - `uri_modified_at`: Function that uri modified at, so storage stays compact and efficient.
- Classes
  - `ParquetWriteResult`: Data structure or helper class for Parquet Write Result, so storage stays compact and efficient.

### `retikon_core/compaction/policy.py`
- Classes
  - `CompactionPolicy`: Data structure or helper class for Compaction Policy, so storage stays compact and efficient.
    - Methods
      - `from_env`: Function that builds from env, so storage stays compact and efficient.
      - `plan`: Function that plans it, so storage stays compact and efficient.

### `retikon_core/compaction/runner.py`
- Functions
  - `_glob_files`: Internal helper that glob files, so storage stays compact and efficient.
  - `_read_manifest`: Internal helper that reads manifest, so storage stays compact and efficient.
  - `_run_id_from_manifest_uri`: Internal helper that builds the run id from manifest uri, so storage stays compact and efficient.
  - `_parse_graph_uri`: Internal helper that builds the parse graph uri, so storage stays compact and efficient.
  - `load_manifests`: Function that loads manifests, so storage stays compact and efficient.
  - `_group_manifests`: Internal helper that group manifests, so storage stays compact and efficient.
  - `_expected_kinds`: Internal helper that expected kinds, so storage stays compact and efficient.
  - `_compact_batch`: Internal helper that compact batch, so storage stays compact and efficient.
  - `_schema_version_for`: Internal helper that schema version for, so storage stays compact and efficient.
  - `run_compaction`: Function that run compaction, so storage stays compact and efficient.
  - `main`: Entry point that runs the module, so storage stays compact and efficient.
- Classes
  - `CompactionResult`: Data structure or helper class for Compaction Result, so storage stays compact and efficient.

### `retikon_core/compaction/types.py`
- Classes
  - `ManifestFile`: Data structure or helper class for Manifest File, so storage stays compact and efficient.
  - `ManifestInfo`: Data structure or helper class for Manifest Info, so storage stays compact and efficient.
  - `CompactionGroup`: Data structure or helper class for Compaction Group, so storage stays compact and efficient.
    - Methods
      - `file_kinds`: Function that file kinds, so storage stays compact and efficient.
      - `bytes_by_kind`: Function that bytes by kind, so storage stays compact and efficient.
      - `rows_by_kind`: Function that rows by kind, so storage stays compact and efficient.
  - `CompactionBatch`: Data structure or helper class for Compaction Batch, so storage stays compact and efficient.
    - Methods
      - `bytes_by_kind`: Function that bytes by kind, so storage stays compact and efficient.
      - `rows_by_kind`: Function that rows by kind, so storage stays compact and efficient.
  - `CompactionOutput`: Data structure or helper class for Compaction Output, so storage stays compact and efficient.
  - `CompactionReport`: Data structure or helper class for Compaction Report, so storage stays compact and efficient.

### `retikon_core/config.py`
- Functions
  - `_parse_ext_list`: Internal helper that parses ext list, so settings are read consistently.
  - `_parse_float`: Internal helper that parses float, so settings are read consistently.
  - `get_config`: Function that gets config, so settings are read consistently.
- Classes
  - `Config`: Data structure or helper class for Config, so settings are read consistently.
    - Methods
      - `graph_root_uri`: Function that builds the graph root uri, so settings are read consistently.
      - `from_env`: Function that builds from env, so settings are read consistently.

### `retikon_core/connectors/http.py`
- Functions
  - `send_webhook_event`: Function that send webhook event, so connectors can send and receive data.

### `retikon_core/edge/agent.py`
- Functions
  - `guess_content_type`: Function that guesses content type, so edge ingestion is resilient.
  - `_post_json`: Internal helper that post json, so edge ingestion is resilient.
  - `ingest_path`: Function that builds the ingest path, so edge ingestion is resilient.
  - `_iter_files`: Internal helper that iter files, so edge ingestion is resilient.
  - `_allowed_exts_from_env`: Internal helper that loads allowed exts from env, so edge ingestion is resilient.
  - `scan_and_ingest`: Function that scan and ingest, so edge ingestion is resilient.
  - `run_agent`: Function that run agent, so edge ingestion is resilient.

### `retikon_core/edge/buffer.py`
- Functions
  - `_atomic_write_bytes`: Internal helper that atomic write bytes, so edge ingestion is resilient.
  - `_atomic_write_json`: Internal helper that atomic write json, so edge ingestion is resilient.
- Classes
  - `BufferItem`: Data structure or helper class for Buffer Item, so edge ingestion is resilient.
    - Methods
      - `read_bytes`: Function that reads bytes, so edge ingestion is resilient.
  - `BufferStats`: Data structure or helper class for Buffer Stats, so edge ingestion is resilient.
  - `EdgeBuffer`: Data structure or helper class for Edge Buffer, so edge ingestion is resilient.
    - Methods
      - `__init__`: Sets up the object, so edge ingestion is resilient.
      - `add_bytes`: Function that add bytes, so edge ingestion is resilient.
      - `list_items`: Function that lists items, so edge ingestion is resilient.
      - `stats`: Function that stats, so edge ingestion is resilient.
      - `prune`: Function that prune, so edge ingestion is resilient.
      - `replay`: Function that replay, so edge ingestion is resilient.
      - `_remove_item`: Internal helper that remove item, so edge ingestion is resilient.

### `retikon_core/edge/policies.py`
- Classes
  - `AdaptiveBatchPolicy`: Data structure or helper class for Adaptive Batch Policy, so edge ingestion is resilient.
    - Methods
      - `tune`: Function that tunes it, so edge ingestion is resilient.
  - `BackpressurePolicy`: Data structure or helper class for Backpressure Policy, so edge ingestion is resilient.
    - Methods
      - `should_accept`: Function that decides whether it should accept, so edge ingestion is resilient.

### `retikon_core/embeddings/stub.py`
- Functions
  - `_use_real_models`: Internal helper that use real models, so embeddings are generated for search.
  - `_model_dir`: Internal helper that builds the model directory, so embeddings are generated for search.
  - `_text_model_name`: Internal helper that text model name, so embeddings are generated for search.
  - `_image_model_name`: Internal helper that image model name, so embeddings are generated for search.
  - `_audio_model_name`: Internal helper that audio model name, so embeddings are generated for search.
  - `_embedding_device`: Internal helper that embedding device, so embeddings are generated for search.
  - `_seed_from_bytes`: Internal helper that seeds from bytes, so embeddings are generated for search.
  - `_deterministic_vector`: Internal helper that deterministic vector, so embeddings are generated for search.
  - `_get_cached_embedder`: Internal helper that gets cached embedder, so embeddings are generated for search.
  - `_get_real_text_embedder`: Internal helper that gets real text embedder, so embeddings are generated for search.
  - `_get_real_image_embedder`: Internal helper that gets real image embedder, so embeddings are generated for search.
  - `_get_real_image_text_embedder`: Internal helper that gets real image text embedder, so embeddings are generated for search.
  - `_get_real_audio_embedder`: Internal helper that gets real audio embedder, so embeddings are generated for search.
  - `_get_real_audio_text_embedder`: Internal helper that gets real audio text embedder, so embeddings are generated for search.
  - `get_text_embedder`: Function that gets text embedder, so embeddings are generated for search.
  - `get_image_embedder`: Function that gets image embedder, so embeddings are generated for search.
  - `get_image_text_embedder`: Function that gets image text embedder, so embeddings are generated for search.
  - `get_audio_embedder`: Function that gets audio embedder, so embeddings are generated for search.
  - `get_audio_text_embedder`: Function that gets audio text embedder, so embeddings are generated for search.
- Classes
  - `TextEmbedder`: Data structure or helper class for Text Embedder, so embeddings are generated for search.
    - Methods
      - `encode`: Function that encode, so embeddings are generated for search.
  - `ImageEmbedder`: Data structure or helper class for Image Embedder, so embeddings are generated for search.
    - Methods
      - `encode`: Function that encode, so embeddings are generated for search.
  - `AudioEmbedder`: Data structure or helper class for Audio Embedder, so embeddings are generated for search.
    - Methods
      - `encode`: Function that encode, so embeddings are generated for search.
  - `StubTextEmbedder`: Data structure or helper class for Stub Text Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `StubImageEmbedder`: Data structure or helper class for Stub Image Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `StubAudioEmbedder`: Data structure or helper class for Stub Audio Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `RealTextEmbedder`: Data structure or helper class for Real Text Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `RealClipImageEmbedder`: Data structure or helper class for Real Clip Image Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `RealClipTextEmbedder`: Data structure or helper class for Real Clip Text Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `RealClapAudioEmbedder`: Data structure or helper class for Real Clap Audio Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.
  - `RealClapTextEmbedder`: Data structure or helper class for Real Clap Text Embedder, so embeddings are generated for search.
    - Methods
      - `__init__`: Sets up the object, so embeddings are generated for search.
      - `encode`: Function that encode, so embeddings are generated for search.

### `retikon_core/errors.py`
- Classes
  - `RetikonError`: Data structure or helper class for Retikon Error, so errors are categorized clearly.
  - `RecoverableError`: Data structure or helper class for Recoverable Error, so errors are categorized clearly.
  - `PermanentError`: Data structure or helper class for Permanent Error, so errors are categorized clearly.
  - `AuthError`: Data structure or helper class for Auth Error, so errors are categorized clearly.
  - `ValidationError`: Data structure or helper class for Validation Error, so errors are categorized clearly.

### `retikon_core/fleet/rollouts.py`
- Functions
  - `_normalize_percentages`: Internal helper that cleans up percentages, so the system works as expected.
  - `_device_ids`: Internal helper that device ids, so the system works as expected.
  - `plan_rollout`: Function that plans rollout, so the system works as expected.
  - `rollback_plan`: Function that rollback plan, so the system works as expected.
- Classes
  - `RolloutInput`: Data structure or helper class for Rollout Input, so the system works as expected.

### `retikon_core/fleet/security.py`
- Functions
  - `evaluate_hardening`: Function that evaluate hardening, so the system works as expected.
  - `device_hardening`: Function that device hardening, so the system works as expected.
- Classes
  - `HardeningCheck`: Data structure or helper class for Hardening Check, so the system works as expected.

### `retikon_core/fleet/store.py`
- Functions
  - `device_registry_uri`: Function that builds the device registry uri, so the system works as expected.
  - `load_devices`: Function that loads devices, so the system works as expected.
  - `save_devices`: Function that saves devices, so the system works as expected.
  - `register_device`: Function that registers device, so the system works as expected.
  - `update_device`: Function that updates device, so the system works as expected.
  - `update_device_status`: Function that updates device status, so the system works as expected.
  - `_normalize_list`: Internal helper that cleans up list, so the system works as expected.
  - `_device_from_dict`: Internal helper that builds device from a dict, so the system works as expected.
  - `_coerce_optional_str`: Internal helper that converts optional str, so the system works as expected.
  - `_coerce_iterable`: Internal helper that converts iterable, so the system works as expected.
  - `_coerce_metadata`: Internal helper that converts metadata, so the system works as expected.

### `retikon_core/fleet/types.py`
- Classes
  - `DeviceRecord`: Data structure or helper class for Device Record, so the system works as expected.
  - `RolloutStage`: Data structure or helper class for Rollout Stage, so the system works as expected.
  - `RolloutPlan`: Data structure or helper class for Rollout Plan, so the system works as expected.
  - `HardeningResult`: Data structure or helper class for Hardening Result, so the system works as expected.

### `retikon_core/ingestion/dlq.py`
- Classes
  - `DlqPayload`: Data structure or helper class for DLQ Payload, so content can be safely ingested and processed.
  - `NoopDlqPublisher`: Data structure or helper class for Noop DLQ Publisher, so content can be safely ingested and processed.
    - Methods
      - `publish`: Function that sends it, so content can be safely ingested and processed.

### `retikon_core/ingestion/download.py`
- Functions
  - `_info_for_uri`: Internal helper that builds the info for uri, so content can be safely ingested and processed.
  - `_extract_metadata`: Internal helper that extracts metadata, so content can be safely ingested and processed.
  - `download_to_tmp`: Function that downloads to tmp, so content can be safely ingested and processed.
  - `cleanup_tmp`: Function that cleanup tmp, so content can be safely ingested and processed.
- Classes
  - `DownloadResult`: Data structure or helper class for Download Result, so content can be safely ingested and processed.

### `retikon_core/ingestion/eventarc.py`
- Functions
  - `_coerce_int`: Internal helper that converts int, so content can be safely ingested and processed.
  - `parse_cloudevent`: Function that parses cloudevent, so content can be safely ingested and processed.
- Classes
  - `GcsEvent`: Data structure or helper class for GCS Event, so content can be safely ingested and processed.
    - Methods
      - `extension`: Function that extension, so content can be safely ingested and processed.

### `retikon_core/ingestion/idempotency.py`
- Functions
  - `build_doc_id`: Function that builds doc id, so content can be safely ingested and processed.
- Classes
  - `IdempotencyDecision`: Data structure or helper class for Idempotency Decision, so content can be safely ingested and processed.
  - `InMemoryIdempotency`: Data structure or helper class for In Memory Idempotency, so content can be safely ingested and processed.
    - Methods
      - `__init__`: Sets up the object, so content can be safely ingested and processed.
      - `begin`: Function that begin, so content can be safely ingested and processed.
      - `mark_completed`: Function that marks completed, so content can be safely ingested and processed.
      - `mark_failed`: Function that marks failed, so content can be safely ingested and processed.
      - `mark_dlq`: Function that marks dlq, so content can be safely ingested and processed.

### `retikon_core/ingestion/idempotency_sqlite.py`
- Classes
  - `SqliteIdempotency`: Data structure or helper class for Sqlite Idempotency, so content can be safely ingested and processed.
    - Methods
      - `__post_init__`: Internal helper that post init  , so content can be safely ingested and processed.
      - `_connect`: Internal helper that connect, so content can be safely ingested and processed.
      - `_init_db`: Internal helper that init db, so content can be safely ingested and processed.
      - `begin`: Function that begin, so content can be safely ingested and processed.
      - `mark_completed`: Function that marks completed, so content can be safely ingested and processed.
      - `mark_failed`: Function that marks failed, so content can be safely ingested and processed.
      - `mark_dlq`: Function that marks dlq, so content can be safely ingested and processed.

### `retikon_core/ingestion/media.py`
- Functions
  - `_ensure_tool`: Internal helper that ensures tool, so content can be safely ingested and processed.
  - `_raise_media_error`: Internal helper that raise media error, so content can be safely ingested and processed.
  - `_parse_fraction`: Internal helper that parses fraction, so content can be safely ingested and processed.
  - `_parse_int`: Internal helper that parses int, so content can be safely ingested and processed.
  - `probe_media`: Function that probe media, so content can be safely ingested and processed.
  - `normalize_audio`: Function that cleans up audio, so content can be safely ingested and processed.
  - `extract_audio`: Function that extracts audio, so content can be safely ingested and processed.
  - `extract_frames`: Function that extracts frames, so content can be safely ingested and processed.
  - `_parse_pts_times`: Internal helper that parses pts times, so content can be safely ingested and processed.
  - `_extract_scene_frames`: Internal helper that extracts scene frames, so content can be safely ingested and processed.
  - `extract_keyframes`: Function that extracts keyframes, so content can be safely ingested and processed.
  - `frame_timestamp_ms`: Function that frame timestamp ms, so content can be safely ingested and processed.
- Classes
  - `MediaProbe`: Data structure or helper class for Media Probe, so content can be safely ingested and processed.
  - `FrameInfo`: Data structure or helper class for Frame Info, so content can be safely ingested and processed.

### `retikon_core/ingestion/ocr.py`
- Functions
  - `_load_pytesseract`: Internal helper that loads pytesseract, so content can be safely ingested and processed.
  - `ocr_text_from_image`: Function that ocr text from image, so content can be safely ingested and processed.
  - `ocr_text_from_pdf`: Function that ocr text from pdf, so content can be safely ingested and processed.

### `retikon_core/ingestion/pipelines/audio.py`
- Functions
  - `_text_model`: Internal helper that text model, so content can be safely ingested and processed.
  - `_audio_model`: Internal helper that audio model, so content can be safely ingested and processed.
  - `ingest_audio`: Function that ingests audio, so content can be safely ingested and processed.

### `retikon_core/ingestion/pipelines/document.py`
- Functions
  - `_pipeline_model`: Internal helper that pipeline model, so content can be safely ingested and processed.
  - `_tokenizer_name`: Internal helper that tokenizer name, so content can be safely ingested and processed.
  - `_tokenizer_cache_dir`: Internal helper that builds the tokenizer cache directory, so content can be safely ingested and processed.
  - `_use_simple_tokenizer`: Internal helper that use simple tokenizer, so content can be safely ingested and processed.
  - `_load_tokenizer`: Internal helper that loads tokenizer, so content can be safely ingested and processed.
  - `_extract_text`: Internal helper that extracts text, so content can be safely ingested and processed.
  - `_table_to_text`: Internal helper that table to text, so content can be safely ingested and processed.
  - `_chunk_text`: Internal helper that chunk text, so content can be safely ingested and processed.
  - `ingest_document`: Function that ingests document, so content can be safely ingested and processed.
- Classes
  - `Chunk`: Data structure or helper class for Chunk, so content can be safely ingested and processed.
  - `_SimpleTokenizer`: Data structure or helper class for _ Simple Tokenizer, so content can be safely ingested and processed.
    - Methods
      - `__call__`: Internal helper that call  , so content can be safely ingested and processed.

### `retikon_core/ingestion/pipelines/image.py`
- Functions
  - `_pipeline_model`: Internal helper that pipeline model, so content can be safely ingested and processed.
  - `_thumbnail_uri`: Internal helper that builds the thumbnail uri, so content can be safely ingested and processed.
  - `_write_thumbnail`: Internal helper that writes thumbnail, so content can be safely ingested and processed.
  - `ingest_image`: Function that ingests image, so content can be safely ingested and processed.

### `retikon_core/ingestion/pipelines/types.py`
- Classes
  - `PipelineResult`: Data structure or helper class for Pipeline Result, so content can be safely ingested and processed.

### `retikon_core/ingestion/pipelines/video.py`
- Functions
  - `_text_model`: Internal helper that text model, so content can be safely ingested and processed.
  - `_image_model`: Internal helper that image model, so content can be safely ingested and processed.
  - `_audio_model`: Internal helper that audio model, so content can be safely ingested and processed.
  - `_resolve_fps`: Internal helper that resolves fps, so content can be safely ingested and processed.
  - `_thumbnail_uri`: Internal helper that builds the thumbnail uri, so content can be safely ingested and processed.
  - `_write_thumbnail`: Internal helper that writes thumbnail, so content can be safely ingested and processed.
  - `ingest_video`: Function that ingests video, so content can be safely ingested and processed.

### `retikon_core/ingestion/rate_limit.py`
- Functions
  - `_rate_for_modality`: Internal helper that rate for modality, so content can be safely ingested and processed.
  - `enforce_rate_limit`: Function that enforces rate limit, so content can be safely ingested and processed.
- Classes
  - `TokenBucket`: Data structure or helper class for Token Bucket, so content can be safely ingested and processed.
    - Methods
      - `allow`: Function that allows it, so content can be safely ingested and processed.

### `retikon_core/ingestion/router.py`
- Functions
  - `pipeline_version`: Function that pipeline version, so content can be safely ingested and processed.
  - `_schema_version`: Internal helper that schema version, so content can be safely ingested and processed.
  - `_modality_for_name`: Internal helper that modality for name, so content can be safely ingested and processed.
  - `_ensure_allowed`: Internal helper that ensures allowed, so content can be safely ingested and processed.
  - `_normalize_content_type`: Internal helper that cleans up content type, so content can be safely ingested and processed.
  - `_extension_for_event`: Internal helper that extension for event, so content can be safely ingested and processed.
  - `_check_size`: Internal helper that check size, so content can be safely ingested and processed.
  - `_make_source`: Internal helper that make source, so content can be safely ingested and processed.
  - `_run_pipeline`: Internal helper that run pipeline, so content can be safely ingested and processed.
  - `process_event`: Function that process event, so content can be safely ingested and processed.
- Classes
  - `PipelineOutcome`: Data structure or helper class for Pipeline Outcome, so content can be safely ingested and processed.

### `retikon_core/ingestion/streaming.py`
- Functions
  - `stream_event_to_dict`: Function that streams event to dict, so content can be safely ingested and processed.
  - `stream_event_from_dict`: Function that builds stream event from a dict, so content can be safely ingested and processed.
  - `decode_stream_batch`: Function that decode stream batch, so content can be safely ingested and processed.
  - `_coerce_int`: Internal helper that converts int, so content can be safely ingested and processed.
- Classes
  - `StreamEvent`: Data structure or helper class for Stream Event, so content can be safely ingested and processed.
    - Methods
      - `to_gcs_event`: Function that converts to gcs event, so content can be safely ingested and processed.
  - `StreamDispatchResult`: Data structure or helper class for Stream Dispatch Result, so content can be safely ingested and processed.
  - `StreamBackpressureError`: Data structure or helper class for Stream Backpressure Error, so content can be safely ingested and processed.
  - `StreamBatcher`: Data structure or helper class for Stream Batcher, so content can be safely ingested and processed.
    - Methods
      - `__init__`: Sets up the object, so content can be safely ingested and processed.
      - `backlog`: Function that backlog, so content can be safely ingested and processed.
      - `can_accept`: Function that checks whether it can accept, so content can be safely ingested and processed.
      - `add`: Function that add, so content can be safely ingested and processed.
      - `flush`: Function that flushes it, so content can be safely ingested and processed.
      - `_maybe_flush`: Internal helper that maybe flush, so content can be safely ingested and processed.
      - `_drain`: Internal helper that drain, so content can be safely ingested and processed.
  - `StreamIngestPipeline`: Data structure or helper class for Stream Ingest Pipeline, so content can be safely ingested and processed.
    - Methods
      - `__init__`: Sets up the object, so content can be safely ingested and processed.
      - `enqueue`: Function that enqueue, so content can be safely ingested and processed.
      - `enqueue_events`: Function that enqueue events, so content can be safely ingested and processed.
      - `flush`: Function that flushes it, so content can be safely ingested and processed.
      - `_publish_batch`: Internal helper that sends batch, so content can be safely ingested and processed.

### `retikon_core/ingestion/transcribe.py`
- Functions
  - `transcribe_audio`: Function that transcribes audio, so content can be safely ingested and processed.
  - `_use_real_models`: Internal helper that use real models, so content can be safely ingested and processed.
  - `_stub_transcribe`: Internal helper that stub transcribe, so content can be safely ingested and processed.
  - `_load_whisper_model`: Internal helper that loads whisper model, so content can be safely ingested and processed.
  - `_whisper_transcribe`: Internal helper that whisper transcribe, so content can be safely ingested and processed.
- Classes
  - `TranscriptSegment`: Data structure or helper class for Transcript Segment, so content can be safely ingested and processed.

### `retikon_core/ingestion/types.py`
- Classes
  - `IngestSource`: Data structure or helper class for Ingest Source, so content can be safely ingested and processed.
    - Methods
      - `uri`: Function that uri, so content can be safely ingested and processed.
      - `extension`: Function that extension, so content can be safely ingested and processed.

### `retikon_core/logging.py`
- Functions
  - `_utc_timestamp`: Internal helper that utc timestamp, so logs are consistent and machine-readable.
  - `configure_logging`: Function that configures logging, so logs are consistent and machine-readable.
  - `get_logger`: Function that gets logger, so logs are consistent and machine-readable.
- Classes
  - `JsonFormatter`: Data structure or helper class for JSON Formatter, so logs are consistent and machine-readable.
    - Methods
      - `format`: Function that format, so logs are consistent and machine-readable.
  - `BaseFieldFilter`: Data structure or helper class for Base Field Filter, so logs are consistent and machine-readable.
    - Methods
      - `__init__`: Sets up the object, so logs are consistent and machine-readable.
      - `filter`: Function that filters it, so logs are consistent and machine-readable.

### `retikon_core/metering/types.py`
- Classes
  - `UsageEvent`: Data structure or helper class for Usage Event, so usage is tracked.

### `retikon_core/metering/writer.py`
- Functions
  - `record_usage`: Function that records usage, so usage is tracked.

### `retikon_core/privacy/engine.py`
- Functions
  - `build_context`: Function that builds context, so sensitive data is protected.
  - `resolve_redaction_types`: Function that resolves redaction types, so sensitive data is protected.
  - `redact_text_for_context`: Function that redacts text for context, so sensitive data is protected.
  - `_admin_bypass_enabled`: Internal helper that checks whether admin bypass is enabled, so sensitive data is protected.
  - `_matches_context`: Internal helper that matches context, so sensitive data is protected.
  - `_matches_scope`: Internal helper that matches scope, so sensitive data is protected.

### `retikon_core/privacy/store.py`
- Functions
  - `privacy_policy_registry_uri`: Function that builds the privacy policy registry uri, so sensitive data is protected.
  - `load_privacy_policies`: Function that loads privacy policies, so sensitive data is protected.
  - `save_privacy_policies`: Function that saves privacy policies, so sensitive data is protected.
  - `register_privacy_policy`: Function that registers privacy policy, so sensitive data is protected.
  - `update_privacy_policy`: Function that updates privacy policy, so sensitive data is protected.
  - `_normalize_list`: Internal helper that cleans up list, so sensitive data is protected.
  - `_policy_from_dict`: Internal helper that builds policy from a dict, so sensitive data is protected.
  - `_coerce_optional_str`: Internal helper that converts optional str, so sensitive data is protected.
  - `_coerce_iterable`: Internal helper that converts iterable, so sensitive data is protected.

### `retikon_core/privacy/types.py`
- Classes
  - `PrivacyPolicy`: Data structure or helper class for Privacy Policy, so sensitive data is protected.
  - `PrivacyContext`: Data structure or helper class for Privacy Context, so sensitive data is protected.
    - Methods
      - `with_modality`: Function that with modality, so sensitive data is protected.

### `retikon_core/query_engine/index_builder.py`
- Functions
  - `_parse_uri`: Internal helper that builds the parse uri, so search is fast and accurate.
  - `_is_remote`: Internal helper that checks whether remote, so search is fast and accurate.
  - `_glob_files`: Internal helper that glob files, so search is fast and accurate.
  - `_normalize_uri`: Internal helper that builds the normalize uri, so search is fast and accurate.
  - `_vertex_kind_from_uri`: Internal helper that builds the vertex kind from uri, so search is fast and accurate.
  - `_read_manifest`: Internal helper that reads manifest, so search is fast and accurate.
  - `_localize_manifest_uri`: Internal helper that builds the localize manifest uri, so search is fast and accurate.
  - `_load_manifest_groups`: Internal helper that loads manifest groups, so search is fast and accurate.
  - `_relative_object_path`: Internal helper that builds the relative object path, so search is fast and accurate.
  - `_copy_graph_to_local`: Internal helper that copies graph to local, so search is fast and accurate.
  - `_table_sources`: Internal helper that table sources, so search is fast and accurate.
  - `_create_table`: Internal helper that creates table, so search is fast and accurate.
  - `_file_size_bytes`: Internal helper that file size bytes, so search is fast and accurate.
  - `_write_report`: Internal helper that writes report, so search is fast and accurate.
  - `_upload_file`: Internal helper that uploads file, so search is fast and accurate.
  - `_sql_list`: Internal helper that sql list, so search is fast and accurate.
  - `_table_has_column`: Internal helper that table has column, so search is fast and accurate.
  - `_configure_gcs_secret`: Internal helper that configures gcs secret, so search is fast and accurate.
  - `_is_gcs_uri`: Internal helper that checks whether gcs uri, so search is fast and accurate.
  - `build_snapshot`: Function that builds snapshot, so search is fast and accurate.
  - `_config_from_env`: Internal helper that loads config from env, so search is fast and accurate.
  - `main`: Entry point that runs the module, so search is fast and accurate.
- Classes
  - `IndexBuildReport`: Data structure or helper class for Index Build Report, so search is fast and accurate.
  - `TableSource`: Data structure or helper class for Table Source, so search is fast and accurate.
    - Methods
      - `ready`: Function that ready, so search is fast and accurate.
  - `ManifestGroup`: Data structure or helper class for Manifest Group, so search is fast and accurate.

### `retikon_core/query_engine/query_runner.py`
- Functions
  - `_normalize_modalities`: Internal helper that cleans up modalities, so search is fast and accurate.
  - `_apply_duckdb_settings`: Internal helper that applies duckdb settings, so search is fast and accurate.
  - `_clamp_score`: Internal helper that clamp score, so search is fast and accurate.
  - `_score_from_distance`: Internal helper that score from distance, so search is fast and accurate.
  - `_decode_base64_image`: Internal helper that decode base64 image, so search is fast and accurate.
  - `_connect`: Internal helper that connect, so search is fast and accurate.
  - `_query_rows`: Internal helper that runs a search for rows, so search is fast and accurate.
  - `_keyword_pattern`: Internal helper that keyword pattern, so search is fast and accurate.
  - `_table_has_column`: Internal helper that table has column, so search is fast and accurate.
  - `_scope_filters`: Internal helper that scope filters, so search is fast and accurate.
  - `_cached_text_vector`: Internal helper that cached text vector, so search is fast and accurate.
  - `_cached_image_text_vector`: Internal helper that cached image text vector, so search is fast and accurate.
  - `_cached_audio_text_vector`: Internal helper that cached audio text vector, so search is fast and accurate.
  - `search_by_text`: Function that search by text, so search is fast and accurate.
  - `search_by_keyword`: Function that search by keyword, so search is fast and accurate.
  - `search_by_metadata`: Function that search by metadata, so search is fast and accurate.
  - `search_by_image`: Function that search by image, so search is fast and accurate.
- Classes
  - `QueryResult`: Data structure or helper class for Query Result, so search is fast and accurate.

### `retikon_core/query_engine/snapshot.py`
- Functions
  - `_sidecar_uri`: Internal helper that builds the sidecar uri, so search is fast and accurate.
  - `_download_remote`: Internal helper that downloads remote, so search is fast and accurate.
  - `_read_local_json`: Internal helper that reads local json, so search is fast and accurate.
  - `download_snapshot`: Function that downloads snapshot, so search is fast and accurate.
- Classes
  - `SnapshotInfo`: Data structure or helper class for Snapshot Info, so search is fast and accurate.

### `retikon_core/query_engine/warm_start.py`
- Functions
  - `_load_extension`: Internal helper that loads extension, so search is fast and accurate.
  - `load_extensions`: Function that loads extensions, so search is fast and accurate.
  - `_configure_gcs_secret`: Internal helper that configures gcs secret, so search is fast and accurate.
  - `_is_gcs_uri`: Internal helper that checks whether gcs uri, so search is fast and accurate.
  - `get_secure_connection`: Function that gets secure connection, so search is fast and accurate.
- Classes
  - `DuckDBAuthInfo`: Data structure or helper class for Duck D B Auth Info, so search is fast and accurate.

### `retikon_core/queue/types.py`
- Classes
  - `QueueMessage`: Data structure or helper class for Queue Message, so the system works as expected.
  - `QueuePublisher`: Data structure or helper class for Queue Publisher, so the system works as expected.
    - Methods
      - `publish`: Function that sends it, so the system works as expected.

### `retikon_core/redaction/text.py`
- Functions
  - `_normalize_types`: Internal helper that cleans up types, so sensitive data is removed before output.
  - `_resolve_types`: Internal helper that resolves types, so sensitive data is removed before output.
  - `redact_text`: Function that redacts text, so sensitive data is removed before output.

### `retikon_core/retention/policy.py`
- Classes
  - `RetentionPolicy`: Data structure or helper class for Retention Policy, so retention rules are enforced.
    - Methods
      - `from_env`: Function that builds from env, so retention rules are enforced.
      - `tier_for_age`: Function that tier for age, so retention rules are enforced.

### `retikon_core/storage/manifest.py`
- Functions
  - `build_manifest`: Function that builds manifest, so data is stored in the GraphAr layout.
  - `write_manifest`: Function that writes manifest, so data is stored in the GraphAr layout.
- Classes
  - `ManifestFile`: Data structure or helper class for Manifest File, so data is stored in the GraphAr layout.

### `retikon_core/storage/object_store.py`
- Functions
  - `atomic_write_bytes`: Function that atomic write bytes, so data is stored in the GraphAr layout.
- Classes
  - `ObjectStore`: Data structure or helper class for Object Store, so data is stored in the GraphAr layout.
    - Methods
      - `from_base_uri`: Function that builds the from base uri, so data is stored in the GraphAr layout.
      - `join`: Function that join, so data is stored in the GraphAr layout.
      - `open`: Function that opens it, so data is stored in the GraphAr layout.
      - `makedirs`: Function that makedirs, so data is stored in the GraphAr layout.

### `retikon_core/storage/paths.py`
- Functions
  - `_strip_slashes`: Internal helper that strip slashes, so data is stored in the GraphAr layout.
  - `_join_parts`: Internal helper that join parts, so data is stored in the GraphAr layout.
  - `graph_root`: Function that graph root, so data is stored in the GraphAr layout.
  - `join_uri`: Function that builds the join uri, so data is stored in the GraphAr layout.
  - `vertex_dir`: Function that builds the vertex directory, so data is stored in the GraphAr layout.
  - `edge_dir`: Function that builds the edge directory, so data is stored in the GraphAr layout.
  - `part_filename`: Function that part filename, so data is stored in the GraphAr layout.
  - `vertex_part_uri`: Function that builds the vertex part uri, so data is stored in the GraphAr layout.
  - `edge_part_uri`: Function that builds the edge part uri, so data is stored in the GraphAr layout.
  - `manifest_uri`: Function that builds the manifest uri, so data is stored in the GraphAr layout.
- Classes
  - `GraphPaths`: Data structure or helper class for Graph Paths, so data is stored in the GraphAr layout.
    - Methods
      - `vertex`: Function that vertex, so data is stored in the GraphAr layout.
      - `edge`: Function that edge, so data is stored in the GraphAr layout.
      - `manifest`: Function that manifest, so data is stored in the GraphAr layout.

### `retikon_core/storage/schemas.py`
- Functions
  - `_schema_path`: Internal helper that builds the schema path, so data is stored in the GraphAr layout.
  - `load_schema`: Function that loads schema, so data is stored in the GraphAr layout.
  - `load_schemas`: Function that loads schemas, so data is stored in the GraphAr layout.
  - `_field_type`: Internal helper that field type, so data is stored in the GraphAr layout.
  - `_select_fields`: Internal helper that select fields, so data is stored in the GraphAr layout.
  - `schema_for`: Function that schema for, so data is stored in the GraphAr layout.
  - `merge_schemas`: Function that merge schemas, so data is stored in the GraphAr layout.
- Classes
  - `GraphArSchema`: Data structure or helper class for Graph Ar Schema, so data is stored in the GraphAr layout.
    - Methods
      - `fields`: Function that fields, so data is stored in the GraphAr layout.

### `retikon_core/storage/validate_graphar.py`
- Functions
  - `_load_schema`: Internal helper that loads schema, so data is stored in the GraphAr layout.
  - `_validate_schema`: Internal helper that checks schema, so data is stored in the GraphAr layout.
  - `validate_all`: Function that checks all, so data is stored in the GraphAr layout.
  - `main`: Entry point that runs the module, so data is stored in the GraphAr layout.
- Classes
  - `ValidationError`: Data structure or helper class for Validation Error, so data is stored in the GraphAr layout.

### `retikon_core/storage/writer.py`
- Functions
  - `_sha256_file`: Internal helper that sha256 file, so data is stored in the GraphAr layout.
  - `_write_local`: Internal helper that writes local, so data is stored in the GraphAr layout.
  - `_write_remote`: Internal helper that writes remote, so data is stored in the GraphAr layout.
  - `write_parquet`: Function that writes parquet, so data is stored in the GraphAr layout.
- Classes
  - `WriteResult`: Data structure or helper class for Write Result, so data is stored in the GraphAr layout.

### `retikon_core/tenancy/resolve.py`
- Functions
  - `scope_from_metadata`: Function that scope from metadata, so tenant scoping is enforced.
  - `tenancy_fields`: Function that tenancy fields, so tenant scoping is enforced.
  - `_normalize_metadata`: Internal helper that cleans up metadata, so tenant scoping is enforced.
  - `_pick`: Internal helper that pick, so tenant scoping is enforced.

### `retikon_core/tenancy/types.py`
- Classes
  - `TenantScope`: Data structure or helper class for Tenant Scope, so tenant scoping is enforced.
    - Methods
      - `is_empty`: Function that checks whether empty, so tenant scoping is enforced.

### `retikon_core/webhooks/delivery.py`
- Functions
  - `deliver_webhook`: Function that delivers webhook, so events can be delivered to external systems.
  - `deliver_webhooks`: Function that delivers webhooks, so events can be delivered to external systems.
  - `_should_retry`: Internal helper that decides whether it should retry, so events can be delivered to external systems.
- Classes
  - `DeliveryOptions`: Data structure or helper class for Delivery Options, so events can be delivered to external systems.
  - `DeliveryResult`: Data structure or helper class for Delivery Result, so events can be delivered to external systems.

### `retikon_core/webhooks/logs.py`
- Functions
  - `write_webhook_delivery_log`: Function that writes webhook delivery log, so events can be delivered to external systems.
- Classes
  - `WebhookDeliveryRecord`: Data structure or helper class for Webhook Delivery Record, so events can be delivered to external systems.

### `retikon_core/webhooks/signer.py`
- Functions
  - `sign_payload`: Function that signs payload, so events can be delivered to external systems.

### `retikon_core/webhooks/store.py`
- Functions
  - `webhook_registry_uri`: Function that builds the webhook registry uri, so events can be delivered to external systems.
  - `load_webhooks`: Function that loads webhooks, so events can be delivered to external systems.
  - `save_webhooks`: Function that saves webhooks, so events can be delivered to external systems.
  - `register_webhook`: Function that registers webhook, so events can be delivered to external systems.
  - `update_webhook`: Function that updates webhook, so events can be delivered to external systems.
  - `_normalize_event_types`: Internal helper that cleans up event types, so events can be delivered to external systems.
  - `_webhook_from_dict`: Internal helper that builds webhook from a dict, so events can be delivered to external systems.
  - `_coerce_optional_str`: Internal helper that converts optional str, so events can be delivered to external systems.
  - `_coerce_iterable`: Internal helper that converts iterable, so events can be delivered to external systems.
  - `_coerce_headers`: Internal helper that converts headers, so events can be delivered to external systems.
  - `_coerce_float`: Internal helper that converts float, so events can be delivered to external systems.

### `retikon_core/webhooks/types.py`
- Functions
  - `event_to_dict`: Function that event to dict, so events can be delivered to external systems.
- Classes
  - `WebhookRegistration`: Data structure or helper class for Webhook Registration, so events can be delivered to external systems.
  - `WebhookEvent`: Data structure or helper class for Webhook Event, so events can be delivered to external systems.

### `sdk/python/retikon_sdk/client.py`
- Classes
  - `RetikonClient`: Data structure or helper class for Retikon Client, so clients can call the APIs safely.
    - Methods
      - `_headers`: Internal helper that headers, so clients can call the APIs safely.
      - `_request`: Internal helper that request, so clients can call the APIs safely.
      - `ingest`: Accepts content to ingest and starts processing, so clients can call the APIs safely.
      - `query`: Runs a search request and returns results, so clients can call the APIs safely.
      - `health`: Reports service health, so clients can call the APIs safely.
      - `reload_snapshot`: Function that reload snapshot, so clients can call the APIs safely.

### `frontend/dev-console/src/App.tsx`
- Functions
  - `App`: Function that app, so the dev console UI can guide workflows.
  - `resizeImage`: Function that resizeimage, so the dev console UI can guide workflows.
  - `statusLabel`: Function that statuslabel, so the dev console UI can guide workflows.
  - `toPercent`: Function that topercent, so the dev console UI can guide workflows.
  - `addActivity`: Function that addactivity, so the dev console UI can guide workflows.
  - `applyManualUri`: Function that applymanualuri, so the dev console UI can guide workflows.
  - `copyCurl`: Function that copycurl, so the dev console UI can guide workflows.
  - `copyIndexCommand`: Function that copyindexcommand, so the dev console UI can guide workflows.
  - `copyUploadCommand`: Function that copyuploadcommand, so the dev console UI can guide workflows.
  - `curlCommand`: Function that curlcommand, so the dev console UI can guide workflows.
  - `devHeaders`: Function that devheaders, so the dev console UI can guide workflows.
  - `fetchAuditLogs`: Function that fetchauditlogs, so the dev console UI can guide workflows.
  - `fetchFleetDevices`: Function that fetchfleetdevices, so the dev console UI can guide workflows.
  - `fetchFleetRollout`: Function that fetchfleetrollout, so the dev console UI can guide workflows.
  - `fetchGraphObject`: Function that fetchgraphobject, so the dev console UI can guide workflows.
  - `fetchIndexStatus`: Function that fetchindexstatus, so the dev console UI can guide workflows.
  - `fetchIngestStatus`: Function that fetchingeststatus, so the dev console UI can guide workflows.
  - `fetchKeyframes`: Function that fetchkeyframes, so the dev console UI can guide workflows.
  - `fetchManifest`: Function that fetchmanifest, so the dev console UI can guide workflows.
  - `fetchParquetPreview`: Function that fetchparquetpreview, so the dev console UI can guide workflows.
  - `fetchPrivacyPolicies`: Function that fetchprivacypolicies, so the dev console UI can guide workflows.
  - `fetchSnapshotStatus`: Function that fetchsnapshotstatus, so the dev console UI can guide workflows.
  - `handleImageChange`: Function that handleimagechange, so the dev console UI can guide workflows.
  - `handleLocalIngest`: Function that handlelocalingest, so the dev console UI can guide workflows.
  - `handleSubmit`: Function that handlesubmit, so the dev console UI can guide workflows.
  - `handleUpload`: Function that handleupload, so the dev console UI can guide workflows.
  - `loadVideoPreview`: Function that loadvideopreview, so the dev console UI can guide workflows.
  - `previewObject`: Function that previewobject, so the dev console UI can guide workflows.
  - `reloadSnapshot`: Function that reloadsnapshot, so the dev console UI can guide workflows.
  - `triggerIndex`: Function that triggerindex, so the dev console UI can guide workflows.


### `sdk/js/index.js`
- Classes
  - `RetikonClient`: Data structure or helper class for Retikon Client, so clients can call the APIs from JavaScript.
    - Methods
      - `constructor`: Function that constructor, so clients can call the APIs from JavaScript.
      - `_headers`: Internal helper that headers, so clients can call the APIs from JavaScript.
      - `ingest`: Accepts content to ingest and starts processing, so clients can call the APIs from JavaScript.
      - `query`: Runs a search request and returns results, so clients can call the APIs from JavaScript.
      - `health`: Reports service health, so clients can call the APIs from JavaScript.
      - `reloadSnapshot`: Function that reloadsnapshot, so clients can call the APIs from JavaScript.


## 6) Function Catalog (Pro)

### `gcp_adapter/audit_service.py`
- Functions
  - `lifespan`: Function that sets up startup and shutdown hooks, so audit access and exports are available.
  - `_cors_origins`: Internal helper that cors origins, so audit access and exports are available.
  - `_api_key_required`: Internal helper that api key required, so audit access and exports are available.
  - `_require_admin`: Internal helper that require admin, so audit access and exports are available.
  - `_audit_api_key`: Internal helper that audit api key, so audit access and exports are available.
  - `_graph_uri`: Internal helper that builds the graph uri, so audit access and exports are available.
  - `_healthcheck_uri`: Internal helper that builds the healthcheck uri, so audit access and exports are available.
  - `_authorize`: Internal helper that authorizes it, so audit access and exports are available.
  - `_open_conn`: Internal helper that opens conn, so audit access and exports are available.
  - `_glob_exists`: Internal helper that glob exists, so audit access and exports are available.
  - `_open_local_conn`: Internal helper that opens local conn, so audit access and exports are available.
  - `_resolve_parquet_files`: Internal helper that resolves parquet files, so audit access and exports are available.
  - `_parse_timestamp`: Internal helper that parses timestamp, so audit access and exports are available.
  - `_serialize_value`: Internal helper that serialize value, so audit access and exports are available.
  - `_redact_record`: Internal helper that redacts record, so audit access and exports are available.
  - `_build_filters`: Internal helper that builds filters, so audit access and exports are available.
  - `_query_rows`: Internal helper that runs a search for rows, so audit access and exports are available.
  - `_stream_query`: Internal helper that streams query, so audit access and exports are available.
  - `_audit_pattern`: Internal helper that audit pattern, so audit access and exports are available.
  - `_usage_pattern`: Internal helper that usage pattern, so audit access and exports are available.
  - `_privacy_context`: Internal helper that privacy context, so audit access and exports are available.
  - `_privacy_policies`: Internal helper that privacy policies, so audit access and exports are available.
  - `health`: Reports service health, so audit access and exports are available.
  - `audit_logs`: Function that audit logs, so audit access and exports are available.
  - `audit_export`: Function that audit export, so audit access and exports are available.
  - `access_export`: Function that access export, so audit access and exports are available.

### `gcp_adapter/compaction_service.py`
- Functions
  - `_graph_uri`: Internal helper that builds the graph uri, so compaction jobs run in the managed service.
  - `main`: Entry point that runs the module, so compaction jobs run in the managed service.

### `gcp_adapter/dev_console_service.py`
- Functions
  - `_cors_origins`: Internal helper that cors origins, so the dev console can upload and inspect data.
  - `_require_api_key`: Internal helper that require api key, so the dev console can upload and inspect data.
  - `_project_id`: Internal helper that project id, so the dev console can upload and inspect data.
  - `_graph_settings`: Internal helper that graph settings, so the dev console can upload and inspect data.
  - `_raw_bucket`: Internal helper that raw bucket, so the dev console can upload and inspect data.
  - `_raw_prefix`: Internal helper that raw prefix, so the dev console can upload and inspect data.
  - `_max_raw_bytes`: Internal helper that max raw bytes, so the dev console can upload and inspect data.
  - `_max_preview_bytes`: Internal helper that max preview bytes, so the dev console can upload and inspect data.
  - `_query_service_url`: Internal helper that builds the query service url, so the dev console can upload and inspect data.
  - `_parse_gs_uri`: Internal helper that builds the parse gs uri, so the dev console can upload and inspect data.
  - `_ensure_graph_uri`: Internal helper that builds the ensure graph uri, so the dev console can upload and inspect data.
  - `_ensure_raw_uri`: Internal helper that builds the ensure raw uri, so the dev console can upload and inspect data.
  - `_format_value`: Internal helper that format value, so the dev console can upload and inspect data.
  - `_preview_parquet`: Internal helper that preview parquet, so the dev console can upload and inspect data.
  - `_firestore_collection`: Internal helper that firestore collection, so the dev console can upload and inspect data.
  - `_storage_client`: Internal helper that storage client, so the dev console can upload and inspect data.
  - `_firestore_client`: Internal helper that firestore client, so the dev console can upload and inspect data.
  - `health`: Reports service health, so the dev console can upload and inspect data.
  - `upload_file`: Function that uploads file, so the dev console can upload and inspect data.
  - `ingest_status`: Function that ingests status, so the dev console can upload and inspect data.
  - `manifest`: Function that manifest, so the dev console can upload and inspect data.
  - `parquet_preview`: Function that parquet preview, so the dev console can upload and inspect data.
  - `fetch_object`: Function that fetch object, so the dev console can upload and inspect data.
  - `fetch_graph_object`: Function that fetch graph object, so the dev console can upload and inspect data.
  - `snapshot_status`: Function that snapshot status, so the dev console can upload and inspect data.
  - `index_build`: Function that index build, so the dev console can upload and inspect data.
  - `snapshot_reload`: Function that snapshot reload, so the dev console can upload and inspect data.
  - `index_status`: Function that index status, so the dev console can upload and inspect data.
- Classes
  - `ObjectRef`: Data structure or helper class for Object Ref, so the dev console can upload and inspect data.

### `gcp_adapter/dlq_pubsub.py`
- Classes
  - `PubSubDlqPublisher`: Data structure or helper class for Pub Sub DLQ Publisher, so DLQ events can be published.
    - Methods
      - `__init__`: Sets up the object, so DLQ events can be published.
      - `publish`: Function that sends it, so DLQ events can be published.

### `gcp_adapter/edge_gateway_service.py`
- Functions
  - `_cors_origins`: Internal helper that cors origins, so edge gateways can buffer and upload safely.
  - `_buffer_dir`: Internal helper that builds the buffer directory, so edge gateways can buffer and upload safely.
  - `_buffer_max_bytes`: Internal helper that buffer max bytes, so edge gateways can buffer and upload safely.
  - `_buffer_ttl_seconds`: Internal helper that buffer ttl seconds, so edge gateways can buffer and upload safely.
  - `_raw_prefix`: Internal helper that raw prefix, so edge gateways can buffer and upload safely.
  - `_raw_bucket`: Internal helper that raw bucket, so edge gateways can buffer and upload safely.
  - `_raw_base_uri`: Internal helper that builds the raw base uri, so edge gateways can buffer and upload safely.
  - `_max_raw_bytes`: Internal helper that max raw bytes, so edge gateways can buffer and upload safely.
  - `_force_buffer`: Internal helper that force buffer, so edge gateways can buffer and upload safely.
  - `_init_state`: Internal helper that init state, so edge gateways can buffer and upload safely.
  - `_object_path`: Internal helper that builds the object path, so edge gateways can buffer and upload safely.
  - `_write_to_store`: Internal helper that writes to store, so edge gateways can buffer and upload safely.
  - `_store_payload`: Internal helper that store payload, so edge gateways can buffer and upload safely.
  - `_buffer_payload`: Internal helper that buffer payload, so edge gateways can buffer and upload safely.
  - `_replay_item`: Internal helper that replay item, so edge gateways can buffer and upload safely.
  - `health`: Reports service health, so edge gateways can buffer and upload safely.
  - `get_config`: Function that gets config, so edge gateways can buffer and upload safely.
  - `update_config`: Function that updates config, so edge gateways can buffer and upload safely.
  - `buffer_status`: Function that buffer status, so edge gateways can buffer and upload safely.
  - `buffer_replay`: Function that buffer replay, so edge gateways can buffer and upload safely.
  - `buffer_prune`: Function that buffer prune, so edge gateways can buffer and upload safely.
  - `upload`: Function that uploads it, so edge gateways can buffer and upload safely.
- Classes
  - `UploadResponse`: Data structure or helper class for Upload Response, so edge gateways can buffer and upload safely.
  - `BufferStatus`: Data structure or helper class for Buffer Status, so edge gateways can buffer and upload safely.
  - `ConfigResponse`: Data structure or helper class for Config Response, so edge gateways can buffer and upload safely.
  - `ConfigUpdate`: Data structure or helper class for Config Update, so edge gateways can buffer and upload safely.
  - `GatewayState`: Data structure or helper class for Gateway State, so edge gateways can buffer and upload safely.

### `gcp_adapter/fleet_service.py`
- Functions
  - `_cors_origins`: Internal helper that cors origins, so the system works as expected.
  - `_api_key_required`: Internal helper that api key required, so the system works as expected.
  - `_require_admin`: Internal helper that require admin, so the system works as expected.
  - `_fleet_api_key`: Internal helper that fleet api key, so the system works as expected.
  - `_authorize`: Internal helper that authorizes it, so the system works as expected.
  - `_get_config`: Internal helper that gets config, so the system works as expected.
  - `_device_response`: Internal helper that device response, so the system works as expected.
  - `_filtered_devices`: Internal helper that filtered devices, so the system works as expected.
  - `health`: Reports service health, so the system works as expected.
  - `list_devices`: Function that lists devices, so the system works as expected.
  - `create_device`: Function that creates device, so the system works as expected.
  - `update_status`: Function that updates status, so the system works as expected.
  - `plan_rollouts`: Function that plans rollouts, so the system works as expected.
  - `rollback_rollout`: Function that rollback rollout, so the system works as expected.
  - `hardening_check`: Function that hardening check, so the system works as expected.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so the system works as expected.
  - `DeviceCreateRequest`: Data structure or helper class for Device Create Request, so the system works as expected.
  - `DeviceStatusRequest`: Data structure or helper class for Device Status Request, so the system works as expected.
  - `DeviceResponse`: Data structure or helper class for Device Response, so the system works as expected.
  - `RolloutRequest`: Data structure or helper class for Rollout Request, so the system works as expected.
  - `RolloutStageResponse`: Data structure or helper class for Rollout Stage Response, so the system works as expected.
  - `RolloutResponse`: Data structure or helper class for Rollout Response, so the system works as expected.
  - `RollbackRequest`: Data structure or helper class for Rollback Request, so the system works as expected.
  - `HardeningRequest`: Data structure or helper class for Hardening Request, so the system works as expected.
  - `HardeningResponse`: Data structure or helper class for Hardening Response, so the system works as expected.

### `gcp_adapter/idempotency_firestore.py`
- Classes
  - `FirestoreIdempotency`: Data structure or helper class for Firestore Idempotency, so idempotency is enforced with Firestore.
    - Methods
      - `begin`: Function that begin, so idempotency is enforced with Firestore.
      - `mark_completed`: Function that marks completed, so idempotency is enforced with Firestore.
      - `mark_failed`: Function that marks failed, so idempotency is enforced with Firestore.
      - `mark_dlq`: Function that marks dlq, so idempotency is enforced with Firestore.

### `gcp_adapter/ingestion_service.py`
- Functions
  - `_correlation_id`: Internal helper that correlation id, so ingestion runs securely in the managed service.
  - `_require_ingest_auth`: Internal helper that require ingest auth, so ingestion runs securely in the managed service.
  - `_ingest_api_key`: Internal helper that ingests api key, so ingestion runs securely in the managed service.
  - `_authorize_ingest`: Internal helper that authorizes ingest, so ingestion runs securely in the managed service.
  - `_rbac_enabled`: Internal helper that checks whether rbac is enabled, so ingestion runs securely in the managed service.
  - `_abac_enabled`: Internal helper that checks whether abac is enabled, so ingestion runs securely in the managed service.
  - `_enforce_access`: Internal helper that enforces access, so ingestion runs securely in the managed service.
  - `_metering_enabled`: Internal helper that checks whether metering is enabled, so ingestion runs securely in the managed service.
  - `_audit_logging_enabled`: Internal helper that checks whether audit logging is enabled, so ingestion runs securely in the managed service.
  - `_schema_version`: Internal helper that schema version, so ingestion runs securely in the managed service.
  - `_default_scope`: Internal helper that default scope, so ingestion runs securely in the managed service.
  - `add_correlation_id`: Function that add correlation id, so ingestion runs securely in the managed service.
  - `health`: Reports service health, so ingestion runs securely in the managed service.
  - `ingest`: Accepts content to ingest and starts processing, so ingestion runs securely in the managed service.
  - `_coerce_cloudevent`: Internal helper that converts cloudevent, so ingestion runs securely in the managed service.
  - `_get_dlq_publisher`: Internal helper that gets dlq publisher, so ingestion runs securely in the managed service.
  - `_publish_dlq`: Internal helper that sends dlq, so ingestion runs securely in the managed service.
  - `_modality_from_name`: Internal helper that modality from name, so ingestion runs securely in the managed service.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so ingestion runs securely in the managed service.
  - `IngestResponse`: Data structure or helper class for Ingest Response, so ingestion runs securely in the managed service.

### `gcp_adapter/privacy_service.py`
- Functions
  - `_cors_origins`: Internal helper that cors origins, so privacy policies can be managed.
  - `_api_key_required`: Internal helper that api key required, so privacy policies can be managed.
  - `_require_admin`: Internal helper that require admin, so privacy policies can be managed.
  - `_privacy_api_key`: Internal helper that privacy api key, so privacy policies can be managed.
  - `_authorize`: Internal helper that authorizes it, so privacy policies can be managed.
  - `_get_config`: Internal helper that gets config, so privacy policies can be managed.
  - `_policy_response`: Internal helper that policy response, so privacy policies can be managed.
  - `_normalize_list`: Internal helper that cleans up list, so privacy policies can be managed.
  - `health`: Reports service health, so privacy policies can be managed.
  - `list_policies`: Function that lists policies, so privacy policies can be managed.
  - `create_policy`: Function that creates policy, so privacy policies can be managed.
  - `update_policy`: Function that updates policy, so privacy policies can be managed.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so privacy policies can be managed.
  - `PrivacyPolicyRequest`: Data structure or helper class for Privacy Policy Request, so privacy policies can be managed.
  - `PrivacyPolicyUpdateRequest`: Data structure or helper class for Privacy Policy Update Request, so privacy policies can be managed.
  - `PrivacyPolicyResponse`: Data structure or helper class for Privacy Policy Response, so privacy policies can be managed.

### `gcp_adapter/pubsub_event_publisher.py`
- Classes
  - `PubSubEventPublisher`: Data structure or helper class for Pub Sub Event Publisher, so events can be published to Pub/Sub.
    - Methods
      - `__init__`: Sets up the object, so events can be published to Pub/Sub.
      - `publish`: Function that sends it, so events can be published to Pub/Sub.
      - `publish_json`: Function that sends json, so events can be published to Pub/Sub.

### `gcp_adapter/query_service.py`
- Functions
  - `lifespan`: Function that sets up startup and shutdown hooks, so queries run securely in the managed service.
  - `_correlation_id`: Internal helper that correlation id, so queries run securely in the managed service.
  - `_cors_origins`: Internal helper that cors origins, so queries run securely in the managed service.
  - `add_correlation_id`: Function that add correlation id, so queries run securely in the managed service.
  - `_api_key_required`: Internal helper that api key required, so queries run securely in the managed service.
  - `_get_api_key`: Internal helper that gets api key, so queries run securely in the managed service.
  - `_graph_root_uri`: Internal helper that builds the graph root uri, so queries run securely in the managed service.
  - `_authorize`: Internal helper that authorizes it, so queries run securely in the managed service.
  - `_rbac_enabled`: Internal helper that checks whether rbac is enabled, so queries run securely in the managed service.
  - `_abac_enabled`: Internal helper that checks whether abac is enabled, so queries run securely in the managed service.
  - `_enforce_access`: Internal helper that enforces access, so queries run securely in the managed service.
  - `_metering_enabled`: Internal helper that checks whether metering is enabled, so queries run securely in the managed service.
  - `_audit_logging_enabled`: Internal helper that checks whether audit logging is enabled, so queries run securely in the managed service.
  - `_schema_version`: Internal helper that schema version, so queries run securely in the managed service.
  - `_apply_privacy_redaction`: Internal helper that applies privacy redaction, so queries run securely in the managed service.
  - `_graph_settings`: Internal helper that graph settings, so queries run securely in the managed service.
  - `_load_snapshot`: Internal helper that loads snapshot, so queries run securely in the managed service.
  - `_resolve_modalities`: Internal helper that resolves modalities, so queries run securely in the managed service.
  - `_resolve_search_type`: Internal helper that resolves search type, so queries run securely in the managed service.
  - `_warm_query_models`: Internal helper that warms up query models, so queries run securely in the managed service.
  - `health`: Reports service health, so queries run securely in the managed service.
  - `query`: Runs a search request and returns results, so queries run securely in the managed service.
  - `reload_snapshot`: Function that reload snapshot, so queries run securely in the managed service.
- Classes
  - `SnapshotState`: Data structure or helper class for Snapshot State, so queries run securely in the managed service.
  - `HealthResponse`: Data structure or helper class for Health Response, so queries run securely in the managed service.
  - `QueryRequest`: Data structure or helper class for Query Request, so queries run securely in the managed service.
  - `QueryHit`: Data structure or helper class for Query Hit, so queries run securely in the managed service.
  - `QueryResponse`: Data structure or helper class for Query Response, so queries run securely in the managed service.

### `gcp_adapter/queue_pubsub.py`
- Functions
  - `parse_pubsub_push`: Function that parses pub/sub push, so Pub/Sub push messages are handled.
- Classes
  - `PubSubPushEnvelope`: Data structure or helper class for Pub Sub Push Envelope, so Pub/Sub push messages are handled.
  - `PubSubPublisher`: Data structure or helper class for Pub Sub Publisher, so Pub/Sub push messages are handled.
    - Methods
      - `__init__`: Sets up the object, so Pub/Sub push messages are handled.
      - `publish`: Function that sends it, so Pub/Sub push messages are handled.
      - `publish_json`: Function that sends json, so Pub/Sub push messages are handled.

### `gcp_adapter/stream_ingest_service.py`
- Functions
  - `_correlation_id`: Internal helper that correlation id, so streaming ingestion is reliable.
  - `add_correlation_id`: Function that add correlation id, so streaming ingestion is reliable.
  - `_stream_topic`: Internal helper that streams topic, so streaming ingestion is reliable.
  - `_batch_max`: Internal helper that batch max, so streaming ingestion is reliable.
  - `_batch_latency_ms`: Internal helper that batch latency ms, so streaming ingestion is reliable.
  - `_backlog_max`: Internal helper that backlog max, so streaming ingestion is reliable.
  - `_flush_interval_s`: Internal helper that flushes interval s, so streaming ingestion is reliable.
  - `_init_pipeline`: Internal helper that init pipeline, so streaming ingestion is reliable.
  - `_flush_loop`: Internal helper that flushes loop, so streaming ingestion is reliable.
  - `_start_flush_loop`: Internal helper that start flush loop, so streaming ingestion is reliable.
  - `_stop_flush_loop`: Internal helper that stop flush loop, so streaming ingestion is reliable.
  - `health`: Reports service health, so streaming ingestion is reliable.
  - `stream_status`: Function that streams status, so streaming ingestion is reliable.
  - `ingest_stream`: Function that ingests stream, so streaming ingestion is reliable.
  - `ingest_stream_push`: Function that ingests stream push, so streaming ingestion is reliable.
  - `_parse_stream_events`: Internal helper that parses stream events, so streaming ingestion is reliable.
  - `_get_dlq_publisher`: Internal helper that gets dlq publisher, so streaming ingestion is reliable.
  - `_publish_dlq`: Internal helper that sends dlq, so streaming ingestion is reliable.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so streaming ingestion is reliable.
  - `StreamIngestResponse`: Data structure or helper class for Stream Ingest Response, so streaming ingestion is reliable.
  - `StreamStatusResponse`: Data structure or helper class for Stream Status Response, so streaming ingestion is reliable.

### `gcp_adapter/webhook_service.py`
- Functions
  - `_correlation_id`: Internal helper that correlation id, so webhooks and alerts are managed.
  - `add_correlation_id`: Function that add correlation id, so webhooks and alerts are managed.
  - `health`: Reports service health, so webhooks and alerts are managed.
  - `list_webhooks`: Function that lists webhooks, so webhooks and alerts are managed.
  - `create_webhook`: Function that creates webhook, so webhooks and alerts are managed.
  - `list_alerts`: Function that lists alerts, so webhooks and alerts are managed.
  - `create_alert`: Function that creates alert, so webhooks and alerts are managed.
  - `dispatch_event`: Function that dispatches event, so webhooks and alerts are managed.
  - `_get_config`: Internal helper that gets config, so webhooks and alerts are managed.
  - `_delivery_options`: Internal helper that delivery options, so webhooks and alerts are managed.
  - `_logs_enabled`: Internal helper that checks whether logs is enabled, so webhooks and alerts are managed.
  - `_webhook_response`: Internal helper that webhook response, so webhooks and alerts are managed.
  - `_alert_response`: Internal helper that alert response, so webhooks and alerts are managed.
  - `_resolve_webhooks`: Internal helper that resolves webhooks, so webhooks and alerts are managed.
  - `_resolve_pubsub_topics`: Internal helper that resolves pub/sub topics, so webhooks and alerts are managed.
  - `_accepts_event`: Internal helper that accepts event, so webhooks and alerts are managed.
  - `_publish_pubsub`: Internal helper that sends pub/sub, so webhooks and alerts are managed.
- Classes
  - `HealthResponse`: Data structure or helper class for Health Response, so webhooks and alerts are managed.
  - `WebhookCreateRequest`: Data structure or helper class for Webhook Create Request, so webhooks and alerts are managed.
  - `WebhookResponse`: Data structure or helper class for Webhook Response, so webhooks and alerts are managed.
  - `AlertDestinationRequest`: Data structure or helper class for Alert Destination Request, so webhooks and alerts are managed.
  - `AlertCreateRequest`: Data structure or helper class for Alert Create Request, so webhooks and alerts are managed.
  - `AlertResponse`: Data structure or helper class for Alert Response, so webhooks and alerts are managed.
  - `EventRequest`: Data structure or helper class for Event Request, so webhooks and alerts are managed.
  - `EventDeliveryResponse`: Data structure or helper class for Event Delivery Response, so webhooks and alerts are managed.

## 7) Function Catalog (Other Tools)

### `scripts/dlq_tool.py`
- Functions
  - `_subscription_path`: Internal helper that builds the subscription path, so operational tooling can be run by engineers.
  - `_topic_path`: Internal helper that builds the topic path, so operational tooling can be run by engineers.
  - `_decode_payload`: Internal helper that decode payload, so operational tooling can be run by engineers.
  - `list_messages`: Function that lists messages, so operational tooling can be run by engineers.
  - `pull_messages`: Function that pull messages, so operational tooling can be run by engineers.
  - `replay_messages`: Function that replay messages, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.

### `scripts/download_models.py`
- Functions
  - `_env`: Internal helper that env, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.

### `scripts/gcp_smoke_test.py`
- Functions
  - `_run`: Internal helper that run, so operational tooling can be run by engineers.
  - `_run_json`: Internal helper that run json, so operational tooling can be run by engineers.
  - `_env`: Internal helper that env, so operational tooling can be run by engineers.
  - `_upload_sample`: Internal helper that uploads sample, so operational tooling can be run by engineers.
  - `_object_meta`: Internal helper that object meta, so operational tooling can be run by engineers.
  - `_access_secret`: Internal helper that access secret, so operational tooling can be run by engineers.
  - `_query`: Internal helper that runs a search for it, so operational tooling can be run by engineers.
  - `_wait_firestore_status`: Internal helper that wait firestore status, so operational tooling can be run by engineers.
  - `_read_manifest`: Internal helper that reads manifest, so operational tooling can be run by engineers.
  - `_delete_object`: Internal helper that deletes object, so operational tooling can be run by engineers.
  - `_delete_manifest_outputs`: Internal helper that deletes manifest outputs, so operational tooling can be run by engineers.
  - `_publish_dlq`: Internal helper that sends dlq, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.
- Classes
  - `SmokeContext`: Data structure or helper class for Smoke Context, so operational tooling can be run by engineers.

### `scripts/load_test_ingest.py`
- Functions
  - `_percentile`: Internal helper that percentile, so operational tooling can be run by engineers.
  - `_classify`: Internal helper that classify, so operational tooling can be run by engineers.
  - `_iter_files`: Internal helper that iter files, so operational tooling can be run by engineers.
  - `_doc_id`: Internal helper that doc id, so operational tooling can be run by engineers.
  - `_upload_object`: Internal helper that uploads object, so operational tooling can be run by engineers.
  - `_poll_firestore`: Internal helper that poll firestore, so operational tooling can be run by engineers.
  - `_repeat_files`: Internal helper that repeat files, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.

### `scripts/load_test_query.py`
- Functions
  - `_percentile`: Internal helper that percentile, so operational tooling can be run by engineers.
  - `_load_image_base64`: Internal helper that loads image base64, so operational tooling can be run by engineers.
  - `_build_payload`: Internal helper that builds payload, so operational tooling can be run by engineers.
  - `_worker`: Internal helper that worker, so operational tooling can be run by engineers.
  - `run_load_test`: Function that run load test, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.

### `scripts/upload_demo_dataset.py`
- Functions
  - `_classify`: Internal helper that classify, so operational tooling can be run by engineers.
  - `_iter_files`: Internal helper that iter files, so operational tooling can be run by engineers.
  - `_upload_object`: Internal helper that uploads object, so operational tooling can be run by engineers.
  - `main`: Entry point that runs the module, so operational tooling can be run by engineers.
