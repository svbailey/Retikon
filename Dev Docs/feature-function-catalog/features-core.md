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
