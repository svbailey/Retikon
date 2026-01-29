variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "env" {
  type    = string
  default = "dev"
}

variable "raw_bucket_name" {
  type = string
}

variable "graph_bucket_name" {
  type = string
}

variable "artifact_repo_name" {
  type    = string
  default = "retikon-repo"
}

variable "ingestion_service_name" {
  type    = string
  default = "retikon-ingestion"
}

variable "query_service_name" {
  type    = string
  default = "retikon-query"
}

variable "query_gpu_service_name" {
  type    = string
  default = "retikon-query-gpu"
}

variable "audit_service_name" {
  type    = string
  default = "retikon-audit"
}

variable "index_job_name" {
  type    = string
  default = "retikon-index-builder"
}

variable "compaction_job_name" {
  type    = string
  default = "retikon-compaction"
}

variable "dev_console_service_name" {
  type    = string
  default = "retikon-dev-console"
}

variable "edge_gateway_service_account_name" {
  type    = string
  default = "retikon-edge-gateway"
}

variable "edge_gateway_service_name" {
  type    = string
  default = "retikon-edge-gateway"
}

variable "stream_ingest_service_account_name" {
  type    = string
  default = "retikon-stream-ingest"
}

variable "stream_ingest_service_name" {
  type    = string
  default = "retikon-stream-ingest"
}

variable "compaction_service_account_name" {
  type    = string
  default = "retikon-compaction"
}

variable "ingestion_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "query_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "query_gpu_enabled" {
  type    = bool
  default = false
}

variable "query_gpu_image" {
  type    = string
  default = ""
}

variable "audit_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "index_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "dev_console_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "edge_gateway_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "stream_ingest_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "compaction_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "ingestion_memory" {
  type    = string
  default = "4Gi"
}

variable "ingestion_cpu" {
  type    = string
  default = "1000m"
}

variable "ingestion_concurrency" {
  type    = number
  default = 1
}

variable "ingestion_max_scale" {
  type    = number
  default = 10
}

variable "query_memory" {
  type    = string
  default = "2Gi"
}

variable "query_cpu" {
  type    = string
  default = "1000m"
}

variable "query_gpu_cpu" {
  type    = string
  default = "4000m"
}

variable "query_concurrency" {
  type    = number
  default = 10
}

variable "query_gpu_concurrency" {
  type    = number
  default = 4
}

variable "query_timeout_seconds" {
  type    = number
  default = 300
}

variable "query_gpu_timeout_seconds" {
  type    = number
  default = 300
}

variable "audit_timeout_seconds" {
  type    = number
  default = 300
}

variable "query_slow_ms" {
  type    = number
  default = 2000
}

variable "query_log_timings" {
  type    = bool
  default = false
}

variable "audit_require_admin" {
  type    = bool
  default = true
}

variable "query_warmup" {
  type    = bool
  default = true
}

variable "query_warmup_text" {
  type    = string
  default = "retikon warmup"
}

variable "query_warmup_steps" {
  type    = string
  default = "text,image_text,audio_text,image"
}

variable "query_embedding_backend" {
  type    = string
  default = ""
}

variable "duckdb_threads" {
  type    = number
  default = null
}

variable "duckdb_memory_limit" {
  type    = string
  default = ""
}

variable "duckdb_temp_directory" {
  type    = string
  default = ""
}

variable "query_max_scale" {
  type    = number
  default = 20
}

variable "query_min_scale" {
  type    = number
  default = 0
}

variable "query_gpu_max_scale" {
  type    = number
  default = 5
}

variable "query_gpu_min_scale" {
  type    = number
  default = 0
}

variable "query_gpu_memory" {
  type    = string
  default = "16Gi"
}

variable "query_gpu_accelerator_count" {
  type    = number
  default = 1
}

variable "query_gpu_accelerator_type" {
  type    = string
  default = "nvidia-l4"
}

variable "audit_max_scale" {
  type    = number
  default = 10
}

variable "audit_min_scale" {
  type    = number
  default = 0
}

variable "audit_memory" {
  type    = string
  default = "1Gi"
}

variable "audit_cpu" {
  type    = string
  default = "1000m"
}

variable "audit_concurrency" {
  type    = number
  default = 10
}

variable "dev_console_memory" {
  type    = string
  default = "1Gi"
}

variable "dev_console_cpu" {
  type    = string
  default = "1000m"
}

variable "dev_console_concurrency" {
  type    = number
  default = 10
}

variable "edge_buffer_max_bytes" {
  type    = number
  default = 2147483648
}

variable "edge_buffer_ttl_seconds" {
  type    = number
  default = 86400
}

variable "edge_batch_min" {
  type    = number
  default = 1
}

variable "edge_batch_max" {
  type    = number
  default = 50
}

variable "edge_backlog_low" {
  type    = number
  default = 10
}

variable "edge_backlog_high" {
  type    = number
  default = 100
}

variable "edge_backpressure_max" {
  type    = number
  default = 1000
}

variable "edge_backpressure_hard" {
  type    = number
  default = 2000
}

variable "edge_gateway_memory" {
  type    = string
  default = "1Gi"
}

variable "edge_gateway_cpu" {
  type    = string
  default = "1000m"
}

variable "edge_gateway_concurrency" {
  type    = number
  default = 10
}

variable "edge_gateway_max_scale" {
  type    = number
  default = 20
}

variable "stream_ingest_memory" {
  type    = string
  default = "1Gi"
}

variable "stream_ingest_cpu" {
  type    = string
  default = "1000m"
}

variable "stream_ingest_concurrency" {
  type    = number
  default = 10
}

variable "stream_ingest_max_scale" {
  type    = number
  default = 20
}

variable "stream_ingest_topic_name" {
  type    = string
  default = "retikon-stream-ingest"
}

variable "stream_ingest_subscription_name" {
  type    = string
  default = "retikon-stream-ingest-sub"
}

variable "stream_ingest_batch_max" {
  type    = number
  default = 50
}

variable "stream_ingest_batch_max_delay_ms" {
  type    = number
  default = 2000
}

variable "stream_ingest_backlog_max" {
  type    = number
  default = 1000
}

variable "stream_ingest_max_delivery_attempts" {
  type    = number
  default = 10
}

variable "stream_ingest_retry_min_backoff" {
  type    = number
  default = 10
}

variable "stream_ingest_retry_max_backoff" {
  type    = number
  default = 600
}

variable "index_memory" {
  type    = string
  default = "2Gi"
}

variable "index_cpu" {
  type    = string
  default = "1000m"
}

variable "compaction_memory" {
  type    = string
  default = "2Gi"
}

variable "compaction_cpu" {
  type    = string
  default = "1000m"
}

variable "index_builder_work_dir" {
  type    = string
  default = "/tmp"
}

variable "index_builder_copy_local" {
  type    = bool
  default = false
}

variable "index_builder_fallback_local" {
  type    = bool
  default = true
}

variable "compaction_schedule" {
  type    = string
  default = "0 * * * *"
}

variable "compaction_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "compaction_target_min_bytes" {
  type    = number
  default = 104857600
}

variable "compaction_target_max_bytes" {
  type    = number
  default = 1073741824
}

variable "compaction_max_groups_per_batch" {
  type    = number
  default = 50
}

variable "compaction_delete_source" {
  type    = bool
  default = false
}

variable "compaction_dry_run" {
  type    = bool
  default = false
}

variable "compaction_strict" {
  type    = bool
  default = true
}

variable "retention_hot_days" {
  type    = number
  default = 0
}

variable "retention_warm_days" {
  type    = number
  default = 30
}

variable "retention_cold_days" {
  type    = number
  default = 180
}

variable "retention_delete_days" {
  type    = number
  default = 0
}

variable "retention_apply" {
  type    = bool
  default = false
}

variable "graph_prefix" {
  type    = string
  default = "retikon_v2"
}

variable "raw_prefix" {
  type    = string
  default = "raw"
}

variable "snapshot_uri" {
  type = string
}

variable "max_raw_bytes" {
  type    = number
  default = 500000000
}

variable "max_video_seconds" {
  type    = number
  default = 300
}

variable "max_audio_seconds" {
  type    = number
  default = 1200
}

variable "max_frames_per_video" {
  type    = number
  default = 600
}

variable "chunk_target_tokens" {
  type    = number
  default = 512
}

variable "chunk_overlap_tokens" {
  type    = number
  default = 50
}

variable "max_ingest_attempts" {
  type    = number
  default = 5
}

variable "rate_limit_doc_per_min" {
  type    = number
  default = 60
}

variable "rate_limit_image_per_min" {
  type    = number
  default = 60
}

variable "rate_limit_audio_per_min" {
  type    = number
  default = 20
}

variable "rate_limit_video_per_min" {
  type    = number
  default = 10
}

variable "max_query_bytes" {
  type    = number
  default = 4000000
}

variable "max_image_base64_bytes" {
  type    = number
  default = 2000000
}

variable "max_preview_bytes" {
  type    = number
  default = 5242880
}

variable "duckdb_allow_install" {
  type    = bool
  default = true
}

variable "duckdb_gcs_fallback" {
  type    = bool
  default = false
}

variable "duckdb_skip_healthcheck" {
  type    = bool
  default = false
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "use_real_models" {
  type    = bool
  default = true
}

variable "model_dir" {
  type    = string
  default = "/app/models"
}

variable "text_model_name" {
  type    = string
  default = "BAAI/bge-base-en-v1.5"
}

variable "image_model_name" {
  type    = string
  default = "openai/clip-vit-base-patch32"
}

variable "audio_model_name" {
  type    = string
  default = "laion/clap-htsat-fused"
}

variable "whisper_model_name" {
  type    = string
  default = "small"
}

variable "alert_notification_channels" {
  type    = list(string)
  default = []
}

variable "alert_notification_emails" {
  type    = list(string)
  default = []
}

variable "alert_ingest_5xx_rate" {
  type    = number
  default = 0.02
}

variable "alert_query_p95_seconds" {
  type    = number
  default = 2.0
}

variable "alert_dlq_backlog" {
  type    = number
  default = 1
}

variable "monitoring_dashboard_name" {
  type    = string
  default = "Retikon Ops"
}

variable "firestore_location" {
  type    = string
  default = "nam5"
}

variable "query_api_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "bucket_force_destroy" {
  type    = bool
  default = true
}

variable "eventarc_transport_topic_name" {
  type    = string
  default = "retikon-ingest-transport"
}

variable "ingest_dlq_topic_name" {
  type    = string
  default = "retikon-ingest-dlq"
}

variable "ingest_dlq_subscription_name" {
  type    = string
  default = "retikon-ingest-dlq-sub"
}

variable "ingestion_service_account_name" {
  type    = string
  default = "retikon-ingest-sa"
}

variable "query_service_account_name" {
  type    = string
  default = "retikon-query-sa"
}

variable "audit_service_account_name" {
  type    = string
  default = "retikon-audit-sa"
}

variable "dev_console_service_account_name" {
  type    = string
  default = "retikon-dev-console-sa"
}

variable "index_service_account_name" {
  type    = string
  default = "retikon-index-sa"
}

variable "smoke_service_account_name" {
  type    = string
  default = "retikon-smoke-sa"
}

variable "smoke_job_name" {
  type    = string
  default = "retikon-ingest-smoke"
}

variable "smoke_image" {
  type    = string
  default = "curlimages/curl:8.10.1"
}
