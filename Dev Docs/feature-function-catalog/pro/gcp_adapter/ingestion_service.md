# gcp_adapter/ingestion_service.py

Edition: Pro

## Functions
- `_require_ingest_auth`: Internal helper that require ingest auth, so ingestion runs securely in the managed service.
- `_ingest_api_key`: Internal helper that ingests API key, so ingestion runs securely in the managed service.
- `_authorize_ingest`: Internal helper that authorizes ingest, so ingestion runs securely in the managed service.
- `_rbac_enabled`: Internal helper that checks whether RBAC is enabled, so ingestion runs securely in the managed service.
- `_abac_enabled`: Internal helper that checks whether ABAC is enabled, so ingestion runs securely in the managed service.
- `_enforce_access`: Internal helper that enforces access, so ingestion runs securely in the managed service.
- `_metering_enabled`: Internal helper that checks whether metering is enabled, so ingestion runs securely in the managed service.
- `_audit_logging_enabled`: Internal helper that checks whether audit logging is enabled, so ingestion runs securely in the managed service.
- `_schema_version`: Internal helper that schema version, so ingestion runs securely in the managed service.
- `_default_scope`: Internal helper that default scope, so ingestion runs securely in the managed service.
- `health`: Reports service health, so ingestion runs securely in the managed service.
- `ingest`: Accepts content to ingest and starts processing, so ingestion runs securely in the managed service.
- `_coerce_cloudevent`: Internal helper that converts cloudevent, so ingestion runs securely in the managed service.
- `_get_dlq_publisher`: Internal helper that gets DLQ publisher, so ingestion runs securely in the managed service.
- `_publish_dlq`: Internal helper that sends DLQ, so ingestion runs securely in the managed service.
- `_modality_from_name`: Internal helper that modality from name, so ingestion runs securely in the managed service.

## Classes
- `HealthResponse`: Data structure or helper class for Health Response, so ingestion runs securely in the managed service.
- `IngestResponse`: Data structure or helper class for Ingest Response, so ingestion runs securely in the managed service.
