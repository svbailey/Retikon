output "raw_bucket_name" {
  value = google_storage_bucket.raw.name
}

output "graph_bucket_name" {
  value = google_storage_bucket.graph.name
}

output "artifact_registry_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}

output "ingestion_service_name" {
  value = google_cloud_run_service.ingestion.name
}

output "query_service_name" {
  value = google_cloud_run_service.query.name
}

output "query_gpu_service_name" {
  value = var.query_gpu_enabled ? google_cloud_run_service.query_gpu[0].name : null
}

output "audit_service_name" {
  value = google_cloud_run_service.audit.name
}

output "workflow_service_name" {
  value = google_cloud_run_service.workflow.name
}

output "ingestion_service_url" {
  value = google_cloud_run_service.ingestion.status[0].url
}

output "query_service_url" {
  value = google_cloud_run_service.query.status[0].url
}

output "query_gpu_service_url" {
  value = var.query_gpu_enabled ? google_cloud_run_service.query_gpu[0].status[0].url : null
}

output "audit_service_url" {
  value = google_cloud_run_service.audit.status[0].url
}

output "workflow_service_url" {
  value = google_cloud_run_service.workflow.status[0].url
}

output "dev_console_service_url" {
  value = google_cloud_run_service.dev_console.status[0].url
}

output "edge_gateway_service_url" {
  value = google_cloud_run_service.edge_gateway.status[0].url
}

output "stream_ingest_service_url" {
  value = google_cloud_run_service.stream_ingest.status[0].url
}

output "compaction_job_name" {
  value = google_cloud_run_v2_job.compaction.name
}

output "query_api_key" {
  value     = local.resolved_query_api_key
  sensitive = true
}

output "ingest_dlq_topic" {
  value = google_pubsub_topic.ingest_dlq.name
}

output "ingest_dlq_subscription" {
  value = google_pubsub_subscription.ingest_dlq.name
}

output "workflow_queue_topic" {
  value = google_pubsub_topic.workflow_queue.name
}

output "workflow_queue_subscription" {
  value = google_pubsub_subscription.workflow_queue.name
}

output "workflow_dlq_topic" {
  value = google_pubsub_topic.workflow_dlq.name
}

output "stream_ingest_topic" {
  value = google_pubsub_topic.stream_ingest.name
}

output "stream_ingest_subscription" {
  value = google_pubsub_subscription.stream_ingest.name
}
