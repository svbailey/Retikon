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

variable "demo_datasets_json" {
  type    = string
  default = ""
}

variable "raw_bucket_name" {
  type = string
}

variable "graph_bucket_name" {
  type = string
}

variable "graph_lifecycle_ttl_days" {
  type    = number
  default = 0
}

variable "graph_lifecycle_prefixes" {
  type    = list(string)
  default = []
}

variable "artifact_repo_name" {
  type    = string
  default = "retikon-repo"
}

variable "ingestion_service_name" {
  type    = string
  default = "retikon-ingestion"
}

variable "ingestion_media_service_name" {
  type    = string
  default = "retikon-ingestion-media"
}

variable "ingestion_embed_enabled" {
  type    = bool
  default = false
}

variable "ingestion_embed_service_name" {
  type    = string
  default = "retikon-ingestion-embed"
}

variable "ingestion_embed_modalities" {
  type    = string
  default = ""
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

variable "workflow_service_name" {
  type    = string
  default = "retikon-workflows"
}

variable "chaos_service_name" {
  type    = string
  default = "retikon-chaos"
}

variable "privacy_service_name" {
  type    = string
  default = "retikon-privacy"
}

variable "fleet_service_name" {
  type    = string
  default = "retikon-fleet"
}

variable "data_factory_service_name" {
  type    = string
  default = "retikon-data-factory"
}

variable "webhook_service_name" {
  type    = string
  default = "retikon-webhooks"
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

variable "query_gpu_region" {
  type    = string
  default = ""
}

variable "query_gpu_image" {
  type    = string
  default = ""
}

variable "audit_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "workflow_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "chaos_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "privacy_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "fleet_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "data_factory_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "webhook_image" {
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

variable "ingestion_min_scale" {
  type    = number
  default = 0
}

variable "ingestion_max_scale" {
  type    = number
  default = 10
}

variable "ingestion_media_memory" {
  type    = string
  default = "4Gi"
}

variable "ingestion_media_cpu" {
  type    = string
  default = "1000m"
}

variable "ingestion_media_concurrency" {
  type    = number
  default = 1
}

variable "ingestion_media_min_scale" {
  type    = number
  default = 0
}

variable "ingestion_media_keep_warm_enabled" {
  type    = bool
  default = false
}

variable "ingestion_media_autoscale_enabled" {
  type    = bool
  default = true
}

variable "ingestion_media_cpu_always_on" {
  type    = bool
  default = false
}

variable "ingestion_media_max_scale" {
  type    = number
  default = 10
}

variable "ingestion_embed_concurrency" {
  type    = number
  default = 1
}

variable "ingestion_embed_cpu" {
  type    = string
  default = "1000m"
}

variable "ingestion_embed_memory" {
  type    = string
  default = "4Gi"
}

variable "ingestion_embed_min_scale" {
  type    = number
  default = 0
}

variable "ingestion_embed_keep_warm_enabled" {
  type    = bool
  default = false
}

variable "ingestion_embed_autoscale_enabled" {
  type    = bool
  default = true
}

variable "ingestion_embed_cpu_always_on" {
  type    = bool
  default = false
}

variable "ingestion_embed_max_scale" {
  type    = number
  default = 5
}

variable "transcribe_tier" {
  type    = string
  default = "accurate"
}

variable "transcribe_enabled" {
  type    = bool
  default = true
}

variable "transcribe_max_ms" {
  type    = number
  default = 0
}

variable "transcribe_max_ms_by_org" {
  type    = string
  default = ""
}

variable "transcribe_max_ms_by_plan" {
  type    = string
  default = ""
}

variable "transcribe_plan_metadata_keys" {
  type    = string
  default = "plan,plan_id,tier"
}

variable "dedupe_cache_enabled" {
  type    = bool
  default = true
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

variable "workflow_timeout_seconds" {
  type    = number
  default = 60
}

variable "chaos_timeout_seconds" {
  type    = number
  default = 60
}

variable "privacy_timeout_seconds" {
  type    = number
  default = 60
}

variable "fleet_timeout_seconds" {
  type    = number
  default = 60
}

variable "data_factory_timeout_seconds" {
  type    = number
  default = 120
}

variable "webhook_timeout_seconds" {
  type    = number
  default = 60
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

variable "audit_batch_size" {
  type    = number
  default = 1
}

variable "audit_batch_flush_seconds" {
  type    = number
  default = 5
}

variable "audit_diagnostics" {
  type    = bool
  default = false
}

variable "audit_parquet_limit" {
  type    = number
  default = 0
}

variable "workflow_require_admin" {
  type    = bool
  default = true
}

variable "chaos_require_admin" {
  type    = bool
  default = true
}

variable "privacy_require_admin" {
  type    = bool
  default = true
}

variable "fleet_require_admin" {
  type    = bool
  default = true
}

variable "data_factory_require_admin" {
  type    = bool
  default = true
}

variable "webhook_require_admin" {
  type    = bool
  default = true
}

variable "workflow_run_mode" {
  type    = string
  default = "queue"
}

variable "data_factory_training_run_mode" {
  type    = string
  default = "inline"
}

variable "data_factory_office_conversion_mode" {
  type    = string
  default = "inline"
}

variable "data_factory_office_conversion_backend" {
  type    = string
  default = "stub"
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

variable "query_trace_hitlists" {
  type    = bool
  default = true
}

variable "query_trace_hitlist_size" {
  type    = number
  default = 5
}

variable "query_default_modalities" {
  type    = string
  default = "document,transcript,image,audio"
}

variable "query_modality_boosts" {
  type    = string
  default = "document=1.0,transcript=1.0,image=1.05,audio=1.05"
}

variable "query_modality_hint_boost" {
  type    = number
  default = 1.15
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

variable "index_duckdb_threads" {
  type    = number
  default = null
}

variable "index_duckdb_memory_limit" {
  type    = string
  default = ""
}

variable "index_duckdb_temp_directory" {
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

variable "workflow_max_scale" {
  type    = number
  default = 10
}

variable "workflow_min_scale" {
  type    = number
  default = 0
}

variable "chaos_max_scale" {
  type    = number
  default = 5
}

variable "chaos_min_scale" {
  type    = number
  default = 0
}

variable "privacy_max_scale" {
  type    = number
  default = 5
}

variable "privacy_min_scale" {
  type    = number
  default = 0
}

variable "fleet_max_scale" {
  type    = number
  default = 5
}

variable "fleet_min_scale" {
  type    = number
  default = 0
}

variable "data_factory_max_scale" {
  type    = number
  default = 5
}

variable "data_factory_min_scale" {
  type    = number
  default = 0
}

variable "webhook_max_scale" {
  type    = number
  default = 5
}

variable "webhook_min_scale" {
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

variable "workflow_memory" {
  type    = string
  default = "1Gi"
}

variable "workflow_cpu" {
  type    = string
  default = "1000m"
}

variable "workflow_concurrency" {
  type    = number
  default = 10
}

variable "chaos_memory" {
  type    = string
  default = "1Gi"
}

variable "chaos_cpu" {
  type    = string
  default = "1000m"
}

variable "chaos_concurrency" {
  type    = number
  default = 10
}

variable "privacy_memory" {
  type    = string
  default = "1Gi"
}

variable "privacy_cpu" {
  type    = string
  default = "1000m"
}

variable "privacy_concurrency" {
  type    = number
  default = 10
}

variable "fleet_memory" {
  type    = string
  default = "1Gi"
}

variable "fleet_cpu" {
  type    = string
  default = "1000m"
}

variable "fleet_concurrency" {
  type    = number
  default = 10
}

variable "data_factory_memory" {
  type    = string
  default = "1Gi"
}

variable "data_factory_cpu" {
  type    = string
  default = "1000m"
}

variable "data_factory_concurrency" {
  type    = number
  default = 10
}

variable "webhook_memory" {
  type    = string
  default = "1Gi"
}

variable "webhook_cpu" {
  type    = string
  default = "1000m"
}

variable "webhook_concurrency" {
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

variable "dev_console_embedding_backend" {
  type    = string
  default = "onnx"
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

variable "workflow_max_delivery_attempts" {
  type    = number
  default = 5
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

variable "index_job_timeout" {
  type    = string
  default = "900s"
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

variable "index_builder_skip_if_unchanged" {
  type    = bool
  default = false
}

variable "index_builder_use_latest_compaction" {
  type    = bool
  default = false
}

variable "index_builder_skip_missing_files" {
  type    = bool
  default = false
}

variable "index_builder_incremental" {
  type    = bool
  default = false
}

variable "index_builder_incremental_max_new_manifests" {
  type    = number
  default = 50
}

variable "index_builder_min_new_manifests" {
  type    = number
  default = 5
}

variable "hnsw_ef_construction" {
  type    = number
  default = 200
}

variable "hnsw_m" {
  type    = number
  default = 16
}

variable "hnsw_ef_search" {
  type    = number
  default = 0
}

variable "index_builder_reload_snapshot" {
  type    = bool
  default = false
}

variable "index_builder_signed_url_ttl_sec" {
  type    = number
  default = 900
}

variable "index_schedule" {
  type    = string
  default = "*/15 * * * *"
}

variable "index_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "index_schedule_enabled" {
  type    = bool
  default = false
}

variable "compaction_schedule" {
  type    = string
  default = "0 * * * *"
}

variable "compaction_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "compaction_enabled" {
  type    = bool
  default = true
}

variable "workflow_schedule" {
  type    = string
  default = "*/5 * * * *"
}

variable "workflow_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "ops_run_id" {
  type    = string
  default = "latest"
}

variable "ops_guardrails_enabled" {
  type    = bool
  default = false
}

variable "ops_guardrails_schedule" {
  type    = string
  default = "15 3 * * *"
}

variable "ops_guardrails_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "ops_guardrails_multiplier" {
  type    = number
  default = 2.0
}

variable "ops_cost_rollup_enabled" {
  type    = bool
  default = false
}

variable "ops_cost_rollup_schedule" {
  type    = string
  default = "30 3 * * *"
}

variable "ops_cost_rollup_schedule_timezone" {
  type    = string
  default = "Etc/UTC"
}

variable "ops_cost_rollup_index_seconds_per_vector" {
  type    = number
  default = 0.0
}

variable "ops_gc_audit_enabled" {
  type    = bool
  default = false
}

variable "ops_gc_audit_schedule" {
  type    = string
  default = "45 3 * * *"
}

variable "ops_gc_audit_schedule_timezone" {
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

variable "compaction_skip_missing" {
  type    = bool
  default = false
}

variable "compaction_relax_nulls" {
  type    = bool
  default = false
}

variable "audit_compaction_enabled" {
  type    = bool
  default = false
}

variable "audit_compaction_target_min_bytes" {
  type    = number
  default = 33554432
}

variable "audit_compaction_target_max_bytes" {
  type    = number
  default = 268435456
}

variable "audit_compaction_max_files_per_batch" {
  type    = number
  default = 500
}

variable "audit_compaction_max_batches" {
  type    = number
  default = 10
}

variable "audit_compaction_min_age_seconds" {
  type    = number
  default = 300
}

variable "audit_compaction_delete_source" {
  type    = bool
  default = false
}

variable "audit_compaction_dry_run" {
  type    = bool
  default = false
}

variable "audit_compaction_strict" {
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

variable "model_inference_timeout_seconds" {
  type    = number
  default = 30
}

variable "model_inference_image_timeout_seconds" {
  type    = number
  default = 0
}

variable "max_video_seconds" {
  type    = number
  default = 300
}

variable "max_audio_seconds" {
  type    = number
  default = 1200
}

variable "audio_transcribe" {
  type    = bool
  default = true
}

variable "audio_profile" {
  type    = bool
  default = false
}

variable "audio_skip_normalize_if_wav" {
  type    = bool
  default = false
}

variable "audio_max_segments" {
  type    = number
  default = 0
}

variable "max_frames_per_video" {
  type    = number
  default = 600
}

variable "video_sample_fps" {
  type    = number
  default = 1.0
}

variable "video_sample_interval_seconds" {
  type    = number
  default = 0
}

variable "video_scene_threshold" {
  type    = number
  default = 0.3
}

variable "video_scene_min_frames" {
  type    = number
  default = 3
}

variable "video_thumbnail_width" {
  type    = number
  default = 320
}

variable "thumbnail_jpeg_quality" {
  type    = number
  default = 85
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

variable "idempotency_ttl_seconds" {
  type    = number
  default = 600
}

variable "idempotency_completed_ttl_seconds" {
  type    = number
  default = 0
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

variable "rate_limit_global_doc_per_min" {
  type    = number
  default = 0
}

variable "rate_limit_global_image_per_min" {
  type    = number
  default = 0
}

variable "rate_limit_global_audio_per_min" {
  type    = number
  default = 0
}

variable "rate_limit_global_video_per_min" {
  type    = number
  default = 0
}

variable "rate_limit_backend" {
  type    = string
  default = "local"
}

variable "rate_limit_redis_host" {
  type    = string
  default = ""
}

variable "rate_limit_redis_db" {
  type    = number
  default = 0
}

variable "rate_limit_redis_ssl" {
  type    = bool
  default = false
}

variable "redis_instance_name" {
  type    = string
  default = "retikon-rate-limit"
}

variable "redis_memory_gb" {
  type    = number
  default = 1
}

variable "redis_tier" {
  type    = string
  default = "BASIC"
}

variable "vpc_network_name" {
  type    = string
  default = "default"
}

variable "vpc_connector_name" {
  type    = string
  default = "retikon-serverless-connector"
}

variable "vpc_connector_cidr" {
  type    = string
  default = "10.8.0.0/28"
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

variable "duckdb_auth_provider" {
  type    = string
  default = "gcp_adapter.duckdb_auth:GcsDuckDBAuthProvider"
}

variable "duckdb_skip_healthcheck" {
  type    = bool
  default = false
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "cors_allow_origins" {
  type    = string
  default = ""
}

variable "dev_console_cors_allow_origins" {
  type    = string
  default = ""
}

variable "allow_browser_direct_access" {
  type    = bool
  default = false
}

variable "auth_issuer" {
  type    = string
  default = ""
}

variable "auth_audience" {
  type    = string
  default = ""
}

variable "auth_jwks_uri" {
  type    = string
  default = ""
}

variable "auth_jwt_algorithms" {
  type    = string
  default = "RS256"
}

variable "auth_required_claims" {
  type    = string
  default = "sub,iss,aud,exp,iat,org_id"
}

variable "dev_console_auth_required_claims" {
  type    = string
  default = ""
}

variable "auth_claim_sub" {
  type    = string
  default = "sub"
}

variable "auth_claim_email" {
  type    = string
  default = "email"
}

variable "auth_claim_roles" {
  type    = string
  default = "roles"
}

variable "auth_claim_groups" {
  type    = string
  default = "groups"
}

variable "auth_claim_org_id" {
  type    = string
  default = "org_id"
}

variable "auth_claim_site_id" {
  type    = string
  default = "site_id"
}

variable "auth_claim_stream_id" {
  type    = string
  default = "stream_id"
}

variable "default_org_id" {
  type    = string
  default = ""
}

variable "default_site_id" {
  type    = string
  default = ""
}

variable "default_stream_id" {
  type    = string
  default = ""
}

variable "auth_admin_roles" {
  type    = string
  default = "admin"
}

variable "auth_admin_groups" {
  type    = string
  default = "admins"
}

variable "auth_jwt_leeway_seconds" {
  type    = number
  default = 0
}

variable "auth_gateway_userinfo" {
  type    = bool
  default = false
}

variable "control_plane_store" {
  type    = string
  default = "json"
}

variable "control_plane_collection_prefix" {
  type    = string
  default = ""
}

variable "control_plane_read_mode" {
  type    = string
  default = "primary"
}

variable "control_plane_write_mode" {
  type    = string
  default = "single"
}

variable "control_plane_fallback_on_empty" {
  type    = bool
  default = true
}

variable "metering_enabled" {
  type    = bool
  default = false
}

variable "metering_firestore_enabled" {
  type    = bool
  default = false
}

variable "metering_firestore_collection" {
  type    = string
  default = "usage_events"
}

variable "ingest_warmup" {
  type    = bool
  default = true
}

variable "ingest_warmup_audio" {
  type    = bool
  default = true
}

variable "ingest_warmup_text" {
  type    = bool
  default = true
}

variable "ingest_media_warmup" {
  type    = bool
  default = true
}

variable "ingest_media_warmup_audio" {
  type    = bool
  default = true
}

variable "ingest_media_warmup_text" {
  type    = bool
  default = true
}

variable "snapshot_reload_allow_internal_sa" {
  type    = bool
  default = false
}

variable "dev_console_snapshot_reload_allow_sa" {
  type    = bool
  default = false
}

variable "metering_collection_prefix" {
  type    = string
  default = ""
}

variable "enable_api_gateway" {
  type    = bool
  default = false
}

variable "api_gateway_name" {
  type    = string
  default = "retikon-gateway"
}

variable "api_gateway_config_name" {
  type    = string
  default = "retikon-gateway-config"
}

variable "api_gateway_region" {
  type    = string
  default = ""
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

variable "embedding_metadata_enabled" {
  type    = bool
  default = true
}

variable "text_embed_batch_size" {
  type    = number
  default = 32
}

variable "image_embed_batch_size" {
  type    = number
  default = 8
}

variable "image_embed_max_dim" {
  type    = number
  default = 0
}

variable "video_embed_max_dim" {
  type    = number
  default = 0
}

variable "text_embed_backend" {
  type    = string
  default = ""
}

variable "image_embed_backend" {
  type    = string
  default = ""
}

variable "audio_embed_backend" {
  type    = string
  default = ""
}

variable "image_text_embed_backend" {
  type    = string
  default = ""
}

variable "audio_text_embed_backend" {
  type    = string
  default = ""
}

variable "whisper_model_name" {
  type    = string
  default = "small"
}

variable "whisper_model_name_fast" {
  type    = string
  default = ""
}

variable "whisper_language" {
  type    = string
  default = ""
}

variable "whisper_language_default" {
  type    = string
  default = ""
}

variable "whisper_language_auto" {
  type    = bool
  default = false
}

variable "whisper_min_confidence" {
  type    = number
  default = 0.6
}

variable "whisper_detect_seconds" {
  type    = number
  default = 30
}

variable "whisper_task" {
  type    = string
  default = "transcribe"
}

variable "whisper_non_english_task" {
  type    = string
  default = "translate"
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

variable "alert_query_5xx_rate" {
  type    = number
  default = 0.02
}

variable "alert_query_p95_seconds" {
  type    = number
  default = 2.0
}

variable "alert_ingest_p95_seconds" {
  type    = number
  default = 3.0
}

variable "alert_queue_wait_ms_p95" {
  type    = number
  default = 10000
}

variable "alert_index_queue_length" {
  type    = number
  default = 200
}

variable "alert_stage_embed_image_ms_p95" {
  type    = number
  default = 12000
}

variable "alert_stage_decode_ms_p95" {
  type    = number
  default = 2000
}

variable "alert_stage_embed_text_ms_p95" {
  type    = number
  default = 2000
}

variable "alert_stage_embed_audio_ms_p95" {
  type    = number
  default = 2000
}

variable "alert_stage_transcribe_ms_p95" {
  type    = number
  default = 45000
}

variable "alert_stage_write_parquet_ms_p95" {
  type    = number
  default = 1500
}

variable "alert_stage_write_manifest_ms_p95" {
  type    = number
  default = 500
}

variable "alert_dlq_backlog" {
  type    = number
  default = 1
}

variable "monitoring_dashboard_name" {
  type    = string
  default = "Retikon Ops"
}

variable "queue_monitor_enabled" {
  type    = bool
  default = false
}

variable "queue_monitor_interval_seconds" {
  type    = number
  default = 30
}

variable "queue_monitor_subscriptions" {
  type    = string
  default = ""
}

variable "billing_account_id" {
  type    = string
  default = ""
}

variable "cost_budget_amount" {
  type    = number
  default = 0
}

variable "cost_budget_currency" {
  type    = string
  default = "USD"
}

variable "cost_budget_thresholds" {
  type    = list(number)
  default = [0.5, 0.75, 0.9, 1.0]
}

variable "firestore_location" {
  type    = string
  default = "nam5"
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

variable "ingest_media_topic_name" {
  type    = string
  default = "retikon-ingest-media"
}

variable "ingest_media_subscription_name" {
  type    = string
  default = "retikon-ingest-media-sub"
}

variable "ingest_media_max_delivery_attempts" {
  type    = number
  default = 5
}

variable "ingest_embed_topic_name" {
  type    = string
  default = "retikon-ingest-embed"
}

variable "ingest_embed_subscription_name" {
  type    = string
  default = "retikon-ingest-embed-sub"
}

variable "workflow_queue_topic_name" {
  type    = string
  default = "retikon-workflow-queue"
}

variable "workflow_dlq_topic_name" {
  type    = string
  default = "retikon-workflow-dlq"
}

variable "workflow_queue_subscription_name" {
  type    = string
  default = "retikon-workflow-queue-sub"
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

variable "workflow_service_account_name" {
  type    = string
  default = "retikon-workflows-sa"
}

variable "chaos_service_account_name" {
  type    = string
  default = "retikon-chaos-sa"
}

variable "privacy_service_account_name" {
  type    = string
  default = "retikon-privacy-sa"
}

variable "fleet_service_account_name" {
  type    = string
  default = "retikon-fleet-sa"
}

variable "data_factory_service_account_name" {
  type    = string
  default = "retikon-data-factory-sa"
}

variable "webhook_service_account_name" {
  type    = string
  default = "retikon-webhooks-sa"
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
