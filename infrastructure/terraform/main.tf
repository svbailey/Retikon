data "google_project" "project" {}

data "google_storage_project_service_account" "gcs" {}

resource "google_storage_bucket" "raw" {
  name                        = var.raw_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.bucket_force_destroy

  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["raw/"]
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "graph" {
  name                        = var.graph_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.bucket_force_destroy
}

resource "google_artifact_registry_repository" "repo" {
  repository_id = var.artifact_repo_name
  format        = "DOCKER"
  location      = var.region
}

resource "google_pubsub_topic" "ingest_transport" {
  name = var.eventarc_transport_topic_name
}

resource "google_pubsub_topic" "ingest_dlq" {
  name = var.ingest_dlq_topic_name
}

resource "google_pubsub_subscription" "ingest_dlq" {
  name  = var.ingest_dlq_subscription_name
  topic = google_pubsub_topic.ingest_dlq.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
}

resource "google_service_account" "ingestion" {
  account_id   = var.ingestion_service_account_name
  display_name = "Retikon Ingestion Service Account"
}

resource "google_service_account" "query" {
  account_id   = var.query_service_account_name
  display_name = "Retikon Query Service Account"
}

resource "google_service_account" "dev_console" {
  account_id   = var.dev_console_service_account_name
  display_name = "Retikon Dev Console Service Account"
}

resource "google_service_account" "index_builder" {
  account_id   = var.index_service_account_name
  display_name = "Retikon Index Builder Service Account"
}

resource "google_service_account" "smoke" {
  account_id   = var.smoke_service_account_name
  display_name = "Retikon Ingestion Smoke Test Service Account"
}

resource "google_storage_bucket_iam_member" "ingest_raw_view" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_storage_bucket_iam_member" "ingest_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "ingest_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "dev_console_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_project_iam_member" "dev_console_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_pubsub_topic_iam_member" "ingest_dlq_publisher" {
  topic  = google_pubsub_topic.ingest_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_pubsub_topic_iam_member" "eventarc_transport_publisher" {
  topic  = google_pubsub_topic.ingest_transport.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-eventarc.iam.gserviceaccount.com"
}

resource "google_storage_bucket_iam_member" "query_graph_view" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.query.email}"
}

resource "google_storage_bucket_iam_member" "dev_console_raw_view" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_storage_bucket_iam_member" "dev_console_raw_create" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_storage_bucket_iam_member" "dev_console_graph_view" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_storage_bucket_iam_member" "index_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.index_builder.email}"
}

resource "google_firestore_database" "default" {
  provider    = google-beta
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"
}

resource "google_secret_manager_secret" "query_api_key" {
  secret_id = "retikon-query-api-key"

  replication {
    auto {}
  }
}

resource "random_password" "query_api_key" {
  length  = 48
  special = false
}

locals {
  resolved_query_api_key = var.query_api_key != null ? var.query_api_key : random_password.query_api_key.result
  notification_channels = concat(
    var.alert_notification_channels,
    [for channel in google_monitoring_notification_channel.email : channel.name]
  )
}

resource "google_secret_manager_secret_version" "query_api_key" {
  secret      = google_secret_manager_secret.query_api_key.id
  secret_data = local.resolved_query_api_key
}

resource "google_secret_manager_secret_iam_member" "query_api_key_access" {
  secret_id = google_secret_manager_secret.query_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.query.email}"
}

resource "google_secret_manager_secret_iam_member" "dev_console_api_key_access" {
  secret_id = google_secret_manager_secret.query_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_cloud_run_service" "ingestion" {
  name     = "${var.ingestion_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "internal-and-cloud-load-balancing"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.ingestion_max_scale)
      }
    }

    spec {
      service_account_name = google_service_account.ingestion.email
      container_concurrency = var.ingestion_concurrency

      containers {
        image = var.ingestion_image

        resources {
          limits = {
            cpu    = var.ingestion_cpu
            memory = var.ingestion_memory
          }
        }

        env {
          name  = "ENV"
          value = var.env
        }
        env {
          name  = "LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "USE_REAL_MODELS"
          value = var.use_real_models ? "1" : "0"
        }
        env {
          name  = "MODEL_DIR"
          value = var.model_dir
        }
        env {
          name  = "TEXT_MODEL_NAME"
          value = var.text_model_name
        }
        env {
          name  = "IMAGE_MODEL_NAME"
          value = var.image_model_name
        }
        env {
          name  = "AUDIO_MODEL_NAME"
          value = var.audio_model_name
        }
        env {
          name  = "WHISPER_MODEL_NAME"
          value = var.whisper_model_name
        }
        env {
          name  = "RAW_BUCKET"
          value = google_storage_bucket.raw.name
        }
        env {
          name  = "GRAPH_BUCKET"
          value = google_storage_bucket.graph.name
        }
        env {
          name  = "GRAPH_PREFIX"
          value = var.graph_prefix
        }
        env {
          name  = "MAX_RAW_BYTES"
          value = tostring(var.max_raw_bytes)
        }
        env {
          name  = "MAX_VIDEO_SECONDS"
          value = tostring(var.max_video_seconds)
        }
        env {
          name  = "MAX_AUDIO_SECONDS"
          value = tostring(var.max_audio_seconds)
        }
        env {
          name  = "MAX_FRAMES_PER_VIDEO"
          value = tostring(var.max_frames_per_video)
        }
        env {
          name  = "CHUNK_TARGET_TOKENS"
          value = tostring(var.chunk_target_tokens)
        }
        env {
          name  = "CHUNK_OVERLAP_TOKENS"
          value = tostring(var.chunk_overlap_tokens)
        }
        env {
          name  = "MAX_INGEST_ATTEMPTS"
          value = tostring(var.max_ingest_attempts)
        }
        env {
          name  = "RATE_LIMIT_DOC_PER_MIN"
          value = tostring(var.rate_limit_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_video_per_min)
        }
        env {
          name  = "DLQ_TOPIC"
          value = "projects/${var.project_id}/topics/${var.ingest_dlq_topic_name}"
        }
        env {
          name  = "FIRESTORE_COLLECTION"
          value = "ingestion_events"
        }
        env {
          name  = "IDEMPOTENCY_TTL_SECONDS"
          value = "600"
        }
        env {
          name  = "ALLOWED_DOC_EXT"
          value = ".pdf,.txt,.md,.rtf,.docx,.doc,.pptx,.ppt,.csv,.tsv,.xlsx,.xls"
        }
        env {
          name  = "ALLOWED_IMAGE_EXT"
          value = ".jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif"
        }
        env {
          name  = "ALLOWED_AUDIO_EXT"
          value = ".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus"
        }
        env {
          name  = "ALLOWED_VIDEO_EXT"
          value = ".mp4,.mov,.mkv,.webm,.avi,.mpeg,.mpg"
        }
        env {
          name  = "INGESTION_DRY_RUN"
          value = "0"
        }
        env {
          name  = "VIDEO_SAMPLE_FPS"
          value = "1.0"
        }
        env {
          name  = "VIDEO_SAMPLE_INTERVAL_SECONDS"
          value = "0"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service_iam_member" "ingestion_invoker" {
  location = google_cloud_run_service.ingestion.location
  service  = google_cloud_run_service.ingestion.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_cloud_run_service_iam_member" "ingestion_smoke_invoker" {
  location = google_cloud_run_service.ingestion.location
  service  = google_cloud_run_service.ingestion.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.smoke.email}"
}

resource "google_cloud_run_service" "query" {
  name     = "${var.query_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.query_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.query_min_scale)
      }
    }

    spec {
      service_account_name = google_service_account.query.email
      container_concurrency = var.query_concurrency

      containers {
        image = var.query_image

        resources {
          limits = {
            cpu    = var.query_cpu
            memory = var.query_memory
          }
        }

        env {
          name  = "ENV"
          value = var.env
        }
        env {
          name  = "LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "USE_REAL_MODELS"
          value = var.use_real_models ? "1" : "0"
        }
        env {
          name  = "MODEL_DIR"
          value = var.model_dir
        }
        env {
          name  = "TEXT_MODEL_NAME"
          value = var.text_model_name
        }
        env {
          name  = "IMAGE_MODEL_NAME"
          value = var.image_model_name
        }
        env {
          name  = "AUDIO_MODEL_NAME"
          value = var.audio_model_name
        }
        env {
          name  = "GRAPH_BUCKET"
          value = google_storage_bucket.graph.name
        }
        env {
          name  = "GRAPH_PREFIX"
          value = var.graph_prefix
        }
        env {
          name  = "SNAPSHOT_URI"
          value = var.snapshot_uri
        }
        env {
          name  = "MAX_RAW_BYTES"
          value = tostring(var.max_raw_bytes)
        }
        env {
          name  = "MAX_VIDEO_SECONDS"
          value = tostring(var.max_video_seconds)
        }
        env {
          name  = "MAX_AUDIO_SECONDS"
          value = tostring(var.max_audio_seconds)
        }
        env {
          name  = "CHUNK_TARGET_TOKENS"
          value = tostring(var.chunk_target_tokens)
        }
        env {
          name  = "CHUNK_OVERLAP_TOKENS"
          value = tostring(var.chunk_overlap_tokens)
        }
        env {
          name = "QUERY_API_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.query_api_key.secret_id
              key  = "latest"
            }
          }
        }
        env {
          name  = "MAX_QUERY_BYTES"
          value = tostring(var.max_query_bytes)
        }
        env {
          name  = "MAX_IMAGE_BASE64_BYTES"
          value = tostring(var.max_image_base64_bytes)
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "DUCKDB_GCS_FALLBACK"
          value = var.duckdb_gcs_fallback ? "1" : "0"
        }
        env {
          name  = "DUCKDB_SKIP_HEALTHCHECK"
          value = var.duckdb_skip_healthcheck ? "1" : "0"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "dev_console" {
  name     = "${var.dev_console_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "5"
      }
    }

    spec {
      service_account_name = google_service_account.dev_console.email
      container_concurrency = var.dev_console_concurrency

      containers {
        image = var.dev_console_image

        resources {
          limits = {
            cpu    = var.dev_console_cpu
            memory = var.dev_console_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.dev_console_service:app"
        }
        env {
          name  = "ENV"
          value = var.env
        }
        env {
          name  = "LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "RAW_BUCKET"
          value = google_storage_bucket.raw.name
        }
        env {
          name  = "RAW_PREFIX"
          value = var.raw_prefix
        }
        env {
          name  = "GRAPH_BUCKET"
          value = google_storage_bucket.graph.name
        }
        env {
          name  = "GRAPH_PREFIX"
          value = var.graph_prefix
        }
        env {
          name  = "SNAPSHOT_URI"
          value = var.snapshot_uri
        }
        env {
          name  = "QUERY_SERVICE_URL"
          value = google_cloud_run_service.query.status[0].url
        }
        env {
          name  = "INDEX_JOB_NAME"
          value = google_cloud_run_v2_job.index_builder.name
        }
        env {
          name  = "INDEX_JOB_REGION"
          value = var.region
        }
        env {
          name  = "MAX_RAW_BYTES"
          value = tostring(var.max_raw_bytes)
        }
        env {
          name  = "MAX_PREVIEW_BYTES"
          value = tostring(var.max_preview_bytes)
        }
        env {
          name = "DEV_CONSOLE_API_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.query_api_key.secret_id
              key  = "latest"
            }
          }
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service_iam_member" "query_invoker" {
  location = google_cloud_run_service.query.location
  service  = google_cloud_run_service.query.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_service_iam_member" "dev_console_invoker" {
  location = google_cloud_run_service.dev_console.location
  service  = google_cloud_run_service.dev_console.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_project_iam_member" "eventarc_service_agent" {
  project = var.project_id
  role    = "roles/eventarc.serviceAgent"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-eventarc.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "eventarc_event_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_eventarc_trigger" "gcs_ingest" {
  name     = "retikon-ingest-trigger-${var.env}"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.raw.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_service.ingestion.name
      region  = var.region
      path    = "/ingest"
    }
  }

  service_account = google_service_account.ingestion.email

  depends_on = [
    google_project_iam_member.eventarc_service_agent,
    google_project_iam_member.eventarc_event_receiver,
    google_project_iam_member.gcs_pubsub_publisher,
    google_cloud_run_service_iam_member.ingestion_invoker,
  ]
}

resource "google_cloud_run_v2_job" "index_builder" {
  provider = google-beta

  name     = "${var.index_job_name}-${var.env}"
  location = var.region

  template {
    template {
      service_account = google_service_account.index_builder.email
      max_retries     = 0
      timeout         = "900s"

      containers {
        image = var.index_image
        command = ["python"]
        args    = ["-m", "retikon_core.query_engine.index_builder"]

        env {
          name  = "ENV"
          value = var.env
        }
        env {
          name  = "LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "GRAPH_BUCKET"
          value = google_storage_bucket.graph.name
        }
        env {
          name  = "GRAPH_PREFIX"
          value = var.graph_prefix
        }
        env {
          name  = "SNAPSHOT_URI"
          value = var.snapshot_uri
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_WORK_DIR"
          value = var.index_builder_work_dir
        }
        env {
          name  = "INDEX_BUILDER_COPY_LOCAL"
          value = var.index_builder_copy_local ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_FALLBACK_LOCAL"
          value = var.index_builder_fallback_local ? "1" : "0"
        }

        resources {
          limits = {
            cpu    = var.index_cpu
            memory = var.index_memory
          }
        }
      }
    }
  }
}

resource "google_monitoring_alert_policy" "ingest_5xx_rate" {
  display_name = "Retikon Ingest 5xx rate"
  combiner     = "OR"

  conditions {
    display_name = "Ingest 5xx rate"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_ingest_5xx_rate
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "query_p95_latency" {
  display_name = "Retikon Query p95 latency"
  combiner     = "OR"

  conditions {
    display_name = "Query p95 latency"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_query_p95_seconds
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "dlq_backlog" {
  display_name = "Retikon DLQ backlog"
  combiner     = "OR"

  conditions {
    display_name = "DLQ undelivered messages"

    condition_threshold {
      filter          = "resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.ingest_dlq_subscription_name}\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_dlq_backlog
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.alert_notification_emails)

  display_name = "Retikon Alerts - ${each.value}"
  type         = "email"

  labels = {
    email_address = each.value
  }
}

resource "google_monitoring_dashboard" "ops" {
  dashboard_json = jsonencode(
    {
      displayName  = var.monitoring_dashboard_name
      mosaicLayout = {
        columns = 12
        tiles = [
          {
            xPos   = 0
            yPos   = 0
            width  = 4
            height = 4
            widget = {
              title   = "Ingestion 5xx rate (req/s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                        aggregation = {
                          alignmentPeriod     = "60s"
                          perSeriesAligner    = "ALIGN_RATE"
                          crossSeriesReducer  = "REDUCE_SUM"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "req/s"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 4
            yPos   = 0
            width  = 4
            height = 4
            widget = {
              title   = "Query p95 latency (s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod     = "60s"
                          perSeriesAligner    = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer  = "REDUCE_MAX"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "seconds"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 8
            yPos   = 0
            width  = 4
            height = 4
            widget = {
              title   = "DLQ backlog"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.ingest_dlq_subscription_name}\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
                        aggregation = {
                          alignmentPeriod     = "60s"
                          perSeriesAligner    = "ALIGN_MAX"
                          crossSeriesReducer  = "REDUCE_MAX"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "messages"
                  scale = "LINEAR"
                }
              }
            }
          }
        ]
      }
    }
  )
}

resource "google_cloud_run_v2_job" "ingest_smoke" {
  provider = google-beta

  name     = "${var.smoke_job_name}-${var.env}"
  location = var.region

  template {
    template {
      service_account = google_service_account.smoke.email
      max_retries     = 0
      timeout         = "300s"

      containers {
        image = var.smoke_image
        command = ["sh", "-c"]
        args = [
          <<-EOT
          set -euo pipefail
          TOKEN=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=$${INGEST_URL}")
          curl -sS -H "Authorization: Bearer $${TOKEN}" "$${INGEST_URL}/health"
          EOT
        ]

        env {
          name  = "INGEST_URL"
          value = google_cloud_run_service.ingestion.status[0].url
        }
      }
    }
  }

  depends_on = [
    google_cloud_run_service_iam_member.ingestion_smoke_invoker,
  ]
}
