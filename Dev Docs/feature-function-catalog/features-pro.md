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
