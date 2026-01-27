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

output "ingestion_service_url" {
  value = google_cloud_run_service.ingestion.status[0].url
}

output "query_service_url" {
  value = google_cloud_run_service.query.status[0].url
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

output "stream_ingest_topic" {
  value = google_pubsub_topic.stream_ingest.name
}

output "stream_ingest_subscription" {
  value = google_pubsub_subscription.stream_ingest.name
}
