data "google_project" "project" {}

data "google_storage_project_service_account" "gcs" {}

resource "google_storage_bucket" "raw" {
  name                        = var.raw_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.bucket_force_destroy
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

resource "google_service_account" "ingestion" {
  account_id   = var.ingestion_service_account_name
  display_name = "Retikon Ingestion Service Account"
}

resource "google_service_account" "query" {
  account_id   = var.query_service_account_name
  display_name = "Retikon Query Service Account"
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

resource "google_storage_bucket_iam_member" "query_graph_view" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.query.email}"
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

resource "google_cloud_run_service" "ingestion" {
  name     = "${var.ingestion_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "internal"
    }
  }

  template {
    spec {
      service_account_name = google_service_account.ingestion.email

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
          name  = "CHUNK_TARGET_TOKENS"
          value = tostring(var.chunk_target_tokens)
        }
        env {
          name  = "CHUNK_OVERLAP_TOKENS"
          value = tostring(var.chunk_overlap_tokens)
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
    spec {
      service_account_name = google_service_account.query.email

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
