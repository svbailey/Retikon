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

variable "index_job_name" {
  type    = string
  default = "retikon-index-builder"
}

variable "ingestion_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "query_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "index_image" {
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

variable "query_memory" {
  type    = string
  default = "2Gi"
}

variable "query_cpu" {
  type    = string
  default = "1000m"
}

variable "index_memory" {
  type    = string
  default = "2Gi"
}

variable "index_cpu" {
  type    = string
  default = "1000m"
}

variable "graph_prefix" {
  type    = string
  default = "retikon_v2"
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

variable "chunk_target_tokens" {
  type    = number
  default = 512
}

variable "chunk_overlap_tokens" {
  type    = number
  default = 50
}

variable "log_level" {
  type    = string
  default = "INFO"
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

variable "ingestion_service_account_name" {
  type    = string
  default = "retikon-ingest-sa"
}

variable "query_service_account_name" {
  type    = string
  default = "retikon-query-sa"
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
