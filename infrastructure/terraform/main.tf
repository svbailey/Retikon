data "google_project" "project" {}

data "google_storage_project_service_account" "gcs" {}

data "google_compute_network" "default" {
  name = var.vpc_network_name
}

locals {
  api_gateway_openapi = templatefile(
    "${path.module}/apigateway/retikon-gateway.yaml.tmpl",
    {
      api_title    = "Retikon API Gateway"
      api_version  = "1.0.0"
      jwt_issuer   = var.auth_issuer
      jwt_audience = var.auth_audience
      jwt_jwks_uri = var.auth_jwks_uri
      query_url    = google_cloud_run_service.query.status[0].url
      audit_url    = google_cloud_run_service.audit.status[0].url
      workflow_url = google_cloud_run_service.workflow.status[0].url
      chaos_url    = google_cloud_run_service.chaos.status[0].url
      privacy_url  = google_cloud_run_service.privacy.status[0].url
      fleet_url    = google_cloud_run_service.fleet.status[0].url
      data_factory_url = google_cloud_run_service.data_factory.status[0].url
      webhook_url  = google_cloud_run_service.webhook.status[0].url
      dev_console_url = google_cloud_run_service.dev_console.status[0].url
      edge_gateway_url = google_cloud_run_service.edge_gateway.status[0].url
    }
  )
  api_gateway_invoker = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  dev_console_cors_allow_origins = var.dev_console_cors_allow_origins != "" ? var.dev_console_cors_allow_origins : var.cors_allow_origins
}

resource "google_vpc_access_connector" "serverless" {
  name          = "${var.vpc_connector_name}-${var.env}"
  region        = var.region
  network       = data.google_compute_network.default.name
  ip_cidr_range = var.vpc_connector_cidr
}

resource "google_redis_instance" "rate_limit" {
  name               = "${var.redis_instance_name}-${var.env}"
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_gb
  region             = var.region
  authorized_network = data.google_compute_network.default.id
  redis_version      = "REDIS_6_X"
}

resource "google_compute_firewall" "redis_allow" {
  name    = "${var.redis_instance_name}-${var.env}-allow"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["6379"]
  }

  source_ranges = [var.vpc_connector_cidr]
}

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

  dynamic "lifecycle_rule" {
    for_each = var.graph_lifecycle_ttl_days > 0 && length(var.graph_lifecycle_prefixes) > 0 ? [1] : []
    content {
      condition {
        age            = var.graph_lifecycle_ttl_days
        matches_prefix = var.graph_lifecycle_prefixes
      }
      action {
        type = "Delete"
      }
    }
  }
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

resource "google_pubsub_topic" "ingest_media" {
  name = var.ingest_media_topic_name
}

resource "google_pubsub_topic" "ingest_embed" {
  count = var.ingestion_embed_enabled ? 1 : 0
  name  = var.ingest_embed_topic_name
}

resource "google_pubsub_topic" "stream_ingest" {
  name = var.stream_ingest_topic_name
}

resource "google_pubsub_topic" "workflow_queue" {
  name = var.workflow_queue_topic_name
}

resource "google_pubsub_topic" "workflow_dlq" {
  name = var.workflow_dlq_topic_name
}

resource "google_pubsub_subscription" "ingest_dlq" {
  name  = var.ingest_dlq_subscription_name
  topic = google_pubsub_topic.ingest_dlq.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
}

resource "google_pubsub_subscription" "ingest_media" {
  name  = var.ingest_media_subscription_name
  topic = google_pubsub_topic.ingest_media.name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.ingest_dlq.id
    max_delivery_attempts = var.ingest_media_max_delivery_attempts
  }

  push_config {
    push_endpoint = "${google_cloud_run_service.ingestion_media.status[0].url}/ingest"
    oidc_token {
      service_account_email = google_service_account.ingestion.email
      audience              = google_cloud_run_service.ingestion_media.status[0].url
    }
  }
}

resource "google_pubsub_subscription" "ingest_embed" {
  count = var.ingestion_embed_enabled ? 1 : 0
  name  = var.ingest_embed_subscription_name
  topic = google_pubsub_topic.ingest_embed[0].name

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.ingest_dlq.id
    max_delivery_attempts = var.ingest_media_max_delivery_attempts
  }

  push_config {
    push_endpoint = "${google_cloud_run_service.ingestion_embed[0].status[0].url}/ingest"
    oidc_token {
      service_account_email = google_service_account.ingestion.email
      audience              = google_cloud_run_service.ingestion_embed[0].status[0].url
    }
  }
}

resource "google_pubsub_subscription" "stream_ingest" {
  name  = var.stream_ingest_subscription_name
  topic = google_pubsub_topic.stream_ingest.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  retry_policy {
    minimum_backoff = "${var.stream_ingest_retry_min_backoff}s"
    maximum_backoff = "${var.stream_ingest_retry_max_backoff}s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.ingest_dlq.id
    max_delivery_attempts = var.stream_ingest_max_delivery_attempts
  }

  push_config {
    push_endpoint = "${google_cloud_run_service.stream_ingest.status[0].url}/ingest/stream/push"
    oidc_token {
      service_account_email = google_service_account.stream_ingest.email
      audience              = google_cloud_run_service.stream_ingest.status[0].url
    }
  }
}

resource "google_pubsub_subscription" "workflow_queue" {
  name  = var.workflow_queue_subscription_name
  topic = google_pubsub_topic.workflow_queue.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.workflow_dlq.id
    max_delivery_attempts = var.workflow_max_delivery_attempts
  }

  push_config {
    push_endpoint = "${google_cloud_run_service.workflow.status[0].url}/workflows/runner"
    oidc_token {
      service_account_email = google_service_account.workflow.email
      audience              = google_cloud_run_service.workflow.status[0].url
    }
  }
}

resource "google_service_account" "ingestion" {
  account_id   = var.ingestion_service_account_name
  display_name = "Retikon Ingestion Service Account"
}

resource "google_service_account" "query" {
  account_id   = var.query_service_account_name
  display_name = "Retikon Query Service Account"
}

resource "google_service_account_iam_member" "query_token_creator" {
  service_account_id = google_service_account.query.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.query.email}"
}

resource "google_service_account" "audit" {
  account_id   = var.audit_service_account_name
  display_name = "Retikon Audit Service Account"
}

resource "google_service_account" "workflow" {
  account_id   = var.workflow_service_account_name
  display_name = "Retikon Workflow Service Account"
}

resource "google_service_account" "chaos" {
  account_id   = var.chaos_service_account_name
  display_name = "Retikon Chaos Service Account"
}

resource "google_service_account" "privacy" {
  account_id   = var.privacy_service_account_name
  display_name = "Retikon Privacy Service Account"
}

resource "google_service_account" "fleet" {
  account_id   = var.fleet_service_account_name
  display_name = "Retikon Fleet Service Account"
}

resource "google_service_account" "data_factory" {
  account_id   = var.data_factory_service_account_name
  display_name = "Retikon Data Factory Service Account"
}

resource "google_service_account" "webhook" {
  account_id   = var.webhook_service_account_name
  display_name = "Retikon Webhook Service Account"
}

resource "google_service_account" "dev_console" {
  account_id   = var.dev_console_service_account_name
  display_name = "Retikon Dev Console Service Account"
}

resource "google_service_account" "edge_gateway" {
  account_id   = var.edge_gateway_service_account_name
  display_name = "Retikon Edge Gateway Service Account"
}

resource "google_service_account" "stream_ingest" {
  account_id   = var.stream_ingest_service_account_name
  display_name = "Retikon Stream Ingest Service Account"
}

resource "google_service_account" "compaction" {
  account_id   = var.compaction_service_account_name
  display_name = "Retikon Compaction Service Account"
}

resource "google_service_account" "index_builder" {
  account_id   = var.index_service_account_name
  display_name = "Retikon Index Builder Service Account"
}

resource "google_service_account_iam_member" "index_builder_token_creator" {
  service_account_id = google_service_account.index_builder.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.index_builder.email}"
}

resource "google_service_account" "smoke" {
  account_id   = var.smoke_service_account_name
  display_name = "Retikon Ingestion Smoke Test Service Account"
}

resource "google_secret_manager_secret_iam_member" "query_hf_token_accessor" {
  secret_id = "retikon-hf-token"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.query.email}"
}

resource "google_secret_manager_secret_iam_member" "ingestion_hf_token_accessor" {
  secret_id = "retikon-hf-token"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_secret_manager_secret_iam_member" "workflow_hf_token_accessor" {
  secret_id = "retikon-hf-token"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workflow.email}"
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

resource "google_project_iam_member" "ingest_monitoring_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_project_iam_member" "dev_console_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_project_iam_member" "query_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.query.email}"
}

resource "google_project_iam_member" "audit_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.audit.email}"
}

resource "google_project_iam_member" "workflow_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "privacy_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.privacy.email}"
}

resource "google_project_iam_member" "fleet_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.fleet.email}"
}

resource "google_project_iam_member" "data_factory_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.data_factory.email}"
}

resource "google_project_iam_member" "dev_console_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_storage_bucket_iam_member" "compaction_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.compaction.email}"
}

resource "google_project_iam_member" "compaction_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.compaction.email}"
}

resource "google_pubsub_topic_iam_member" "ingest_dlq_publisher" {
  topic  = google_pubsub_topic.ingest_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_pubsub_topic_iam_member" "ingest_media_publisher" {
  topic  = google_pubsub_topic.ingest_media.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_pubsub_topic_iam_member" "ingest_embed_publisher" {
  count  = var.ingestion_embed_enabled ? 1 : 0
  topic  = google_pubsub_topic.ingest_embed[0].name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_pubsub_topic_iam_member" "stream_ingest_dlq_publisher" {
  topic  = google_pubsub_topic.ingest_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.stream_ingest.email}"
}

resource "google_pubsub_topic_iam_member" "stream_ingest_publisher" {
  topic  = google_pubsub_topic.stream_ingest.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.stream_ingest.email}"
}

resource "google_pubsub_topic_iam_member" "workflow_queue_publisher" {
  topic  = google_pubsub_topic.workflow_queue.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_pubsub_topic_iam_member" "workflow_dlq_publisher" {
  topic  = google_pubsub_topic.workflow_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_service_account_iam_member" "pubsub_stream_ingest_token_creator" {
  service_account_id = google_service_account.stream_ingest.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "pubsub_ingest_token_creator" {
  service_account_id = google_service_account.ingestion.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "pubsub_workflow_token_creator" {
  service_account_id = google_service_account.workflow.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "scheduler_workflow_token_creator" {
  service_account_id = google_service_account.workflow.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
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

resource "google_storage_bucket_iam_member" "query_graph_create" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.query.email}"
}

resource "google_storage_bucket_iam_member" "audit_graph_view" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.audit.email}"
}

resource "google_storage_bucket_iam_member" "workflow_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_storage_bucket_iam_member" "chaos_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.chaos.email}"
}

resource "google_storage_bucket_iam_member" "privacy_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.privacy.email}"
}

resource "google_storage_bucket_iam_member" "fleet_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.fleet.email}"
}

resource "google_storage_bucket_iam_member" "data_factory_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.data_factory.email}"
}

resource "google_storage_bucket_iam_member" "webhook_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.webhook.email}"
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

resource "google_storage_bucket_iam_member" "edge_gateway_raw_create" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.edge_gateway.email}"
}

resource "google_storage_bucket_iam_member" "stream_ingest_raw_view" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.stream_ingest.email}"
}

resource "google_storage_bucket_iam_member" "stream_ingest_graph_admin" {
  bucket = google_storage_bucket.graph.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.stream_ingest.email}"
}

resource "google_project_iam_member" "stream_ingest_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.stream_ingest.email}"
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

locals {
  notification_channels = concat(
    var.alert_notification_channels,
    [for channel in google_monitoring_notification_channel.email : channel.name]
  )
  budget_notification_channels = [
    for name in local.notification_channels :
    replace(name, "projects/${var.project_id}/", "projects/${data.google_project.project.number}/")
  ]
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
        "autoscaling.knative.dev/minScale"        = tostring(var.ingestion_min_scale)
        "autoscaling.knative.dev/maxScale"        = tostring(var.ingestion_max_scale)
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.ingestion.email
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
          name  = "APP_MODULE"
          value = "gcp_adapter.ingestion_service:app"
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
          name  = "QUEUE_MONITOR_ENABLED"
          value = var.queue_monitor_enabled ? "1" : "0"
        }
        env {
          name  = "QUEUE_MONITOR_INTERVAL_SECONDS"
          value = tostring(var.queue_monitor_interval_seconds)
        }
        env {
          name  = "QUEUE_MONITOR_SUBSCRIPTIONS"
          value = var.queue_monitor_subscriptions
        }
        env {
          name  = "CORS_ALLOW_ORIGINS"
          value = local.dev_console_cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "METERING_ENABLED"
          value = var.metering_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_ENABLED"
          value = var.metering_firestore_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_COLLECTION"
          value = var.metering_firestore_collection
        }
        env {
          name  = "METERING_COLLECTION_PREFIX"
          value = var.metering_collection_prefix != "" ? var.metering_collection_prefix : var.control_plane_collection_prefix
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "TEXT_EMBED_BATCH_SIZE"
          value = tostring(var.text_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_BATCH_SIZE"
          value = tostring(var.image_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_MAX_DIM"
          value = tostring(var.image_embed_max_dim)
        }
        env {
          name  = "TEXT_EMBED_BACKEND"
          value = var.text_embed_backend
        }
        env {
          name  = "IMAGE_EMBED_BACKEND"
          value = var.image_embed_backend
        }
        env {
          name  = "AUDIO_EMBED_BACKEND"
          value = var.audio_embed_backend
        }
        env {
          name  = "IMAGE_TEXT_EMBED_BACKEND"
          value = var.image_text_embed_backend
        }
        env {
          name  = "AUDIO_TEXT_EMBED_BACKEND"
          value = var.audio_text_embed_backend
        }
        env {
          name  = "INGEST_WARMUP"
          value = var.ingest_warmup ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_AUDIO"
          value = var.ingest_warmup_audio ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_TEXT"
          value = var.ingest_warmup_text ? "1" : "0"
        }
        env {
          name  = "WHISPER_MODEL_NAME"
          value = var.whisper_model_name
        }
        env {
          name  = "WHISPER_LANGUAGE"
          value = var.whisper_language
        }
        env {
          name  = "WHISPER_LANGUAGE_DEFAULT"
          value = var.whisper_language_default
        }
        env {
          name  = "WHISPER_LANGUAGE_AUTO"
          value = var.whisper_language_auto ? "1" : "0"
        }
        env {
          name  = "WHISPER_MIN_CONFIDENCE"
          value = tostring(var.whisper_min_confidence)
        }
        env {
          name  = "WHISPER_DETECT_SECONDS"
          value = tostring(var.whisper_detect_seconds)
        }
        env {
          name  = "WHISPER_TASK"
          value = var.whisper_task
        }
        env {
          name  = "WHISPER_NON_ENGLISH_TASK"
          value = var.whisper_non_english_task
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
          name  = "INGEST_ALLOWED_MODALITIES"
          value = "audio,video"
        }
        env {
          name  = "INGEST_MEDIA_URL"
          value = google_cloud_run_service.ingestion_media.status[0].url
        }
        env {
          name  = "INGEST_MEDIA_TOPIC"
          value = "projects/${var.project_id}/topics/${var.ingest_media_topic_name}"
        }
        env {
          name  = "INGEST_MEDIA_MODALITIES"
          value = "audio,video"
        }
        env {
          name  = "INGEST_MEDIA_EMBED_URL"
          value = try(google_cloud_run_service.ingestion_embed[0].status[0].url, "")
        }
        env {
          name  = "INGEST_MEDIA_EMBED_TOPIC"
          value = var.ingestion_embed_enabled ? "projects/${var.project_id}/topics/${var.ingest_embed_topic_name}" : ""
        }
        env {
          name  = "INGEST_MEDIA_EMBED_MODALITIES"
          value = var.ingestion_embed_modalities
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
          name  = "GOOGLE_SERVICE_ACCOUNT_EMAIL"
          value = google_service_account.query.email
        }
        env {
          name  = "AUDIT_BATCH_SIZE"
          value = tostring(var.audit_batch_size)
        }
        env {
          name  = "AUDIT_BATCH_FLUSH_SECONDS"
          value = tostring(var.audit_batch_flush_seconds)
        }
        env {
          name  = "MAX_RAW_BYTES"
          value = tostring(var.max_raw_bytes)
        }
        env {
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
        }
        env {
          name  = "MODEL_INFERENCE_IMAGE_TIMEOUT_S"
          value = tostring(var.model_inference_image_timeout_seconds)
        }
        env {
          name  = "MODEL_INFERENCE_IMAGE_TIMEOUT_S"
          value = tostring(var.model_inference_image_timeout_seconds)
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
          name  = "AUDIO_TRANSCRIBE"
          value = var.audio_transcribe ? "1" : "0"
        }
        env {
          name  = "TRANSCRIBE_ENABLED"
          value = var.transcribe_enabled ? "1" : "0"
        }
        env {
          name  = "AUDIO_PROFILE"
          value = var.audio_profile ? "1" : "0"
        }
        env {
          name  = "AUDIO_SKIP_NORMALIZE_IF_WAV"
          value = var.audio_skip_normalize_if_wav ? "1" : "0"
        }
        env {
          name  = "AUDIO_MAX_SEGMENTS"
          value = tostring(var.audio_max_segments)
        }
        env {
          name  = "TRANSCRIBE_TIER"
          value = var.transcribe_tier
        }
        env {
          name  = "TRANSCRIBE_MAX_MS"
          value = tostring(var.transcribe_max_ms)
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_ORG"
          value = var.transcribe_max_ms_by_org
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_PLAN"
          value = var.transcribe_max_ms_by_plan
        }
        env {
          name  = "TRANSCRIBE_PLAN_METADATA_KEYS"
          value = var.transcribe_plan_metadata_keys
        }
        env {
          name  = "ENABLE_DEDUPE_CACHE"
          value = var.dedupe_cache_enabled ? "1" : "0"
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
          name = "HF_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
        }
        env {
          name  = "RATE_LIMIT_BACKEND"
          value = var.rate_limit_backend
        }
        env {
          name  = "REDIS_HOST"
          value = var.rate_limit_redis_host != "" ? var.rate_limit_redis_host : google_redis_instance.rate_limit.host
        }
        env {
          name  = "REDIS_PORT"
          value = tostring(google_redis_instance.rate_limit.port)
        }
        env {
          name  = "REDIS_DB"
          value = tostring(var.rate_limit_redis_db)
        }
        env {
          name  = "REDIS_SSL"
          value = var.rate_limit_redis_ssl ? "1" : "0"
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
          value = tostring(var.idempotency_ttl_seconds)
        }
        env {
          name  = "IDEMPOTENCY_COMPLETED_TTL_SECONDS"
          value = tostring(var.idempotency_completed_ttl_seconds)
        }
        env {
          name  = "ENABLE_DEDUPE_CACHE"
          value = var.dedupe_cache_enabled ? "1" : "0"
        }
        env {
          name  = "ALLOWED_DOC_EXT"
          value = ".pdf,.txt,.md,.rtf,.docx,.pptx,.csv,.tsv,.xlsx,.xls"
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
          value = tostring(var.video_sample_fps)
        }
        env {
          name  = "VIDEO_SAMPLE_INTERVAL_SECONDS"
          value = tostring(var.video_sample_interval_seconds)
        }
        env {
          name  = "VIDEO_SCENE_THRESHOLD"
          value = tostring(var.video_scene_threshold)
        }
        env {
          name  = "VIDEO_SCENE_MIN_FRAMES"
          value = tostring(var.video_scene_min_frames)
        }
        env {
          name  = "VIDEO_THUMBNAIL_WIDTH"
          value = tostring(var.video_thumbnail_width)
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

resource "google_cloud_run_service_iam_member" "ingestion_media_invoker" {
  location = google_cloud_run_service.ingestion_media.location
  service  = google_cloud_run_service.ingestion_media.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.ingestion.email}"
}

resource "google_cloud_run_service_iam_member" "ingestion_embed_invoker" {
  count    = var.ingestion_embed_enabled ? 1 : 0
  location = google_cloud_run_service.ingestion_embed[0].location
  service  = google_cloud_run_service.ingestion_embed[0].name
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
        "autoscaling.knative.dev/maxScale"        = tostring(var.query_max_scale)
        "autoscaling.knative.dev/minScale"        = tostring(var.query_min_scale)
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.query.email
      container_concurrency = var.query_concurrency
      timeout_seconds       = var.query_timeout_seconds

      containers {
        image = var.query_image

        resources {
          limits = {
            cpu    = var.query_cpu
            memory = var.query_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.query_service:app"
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
          name  = "CORS_ALLOW_ORIGINS"
          value = var.cors_allow_origins
        }
        env {
          name  = "DEMO_DATASETS_JSON"
          value = var.demo_datasets_json
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.dev_console_auth_required_claims != "" ? var.dev_console_auth_required_claims : var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "METERING_ENABLED"
          value = var.metering_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_ENABLED"
          value = var.metering_firestore_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_COLLECTION"
          value = var.metering_firestore_collection
        }
        env {
          name  = "METERING_COLLECTION_PREFIX"
          value = var.metering_collection_prefix != "" ? var.metering_collection_prefix : var.control_plane_collection_prefix
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "GOOGLE_SERVICE_ACCOUNT_EMAIL"
          value = google_service_account.query.email
        }
        env {
          name  = "AUDIT_BATCH_SIZE"
          value = tostring(var.audit_batch_size)
        }
        env {
          name  = "AUDIT_BATCH_FLUSH_SECONDS"
          value = tostring(var.audit_batch_flush_seconds)
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name = "HF_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
        }
        env {
          name  = "RATE_LIMIT_BACKEND"
          value = var.rate_limit_backend
        }
        env {
          name  = "REDIS_HOST"
          value = var.rate_limit_redis_host != "" ? var.rate_limit_redis_host : google_redis_instance.rate_limit.host
        }
        env {
          name  = "REDIS_PORT"
          value = tostring(google_redis_instance.rate_limit.port)
        }
        env {
          name  = "REDIS_DB"
          value = tostring(var.rate_limit_redis_db)
        }
        env {
          name  = "REDIS_SSL"
          value = var.rate_limit_redis_ssl ? "1" : "0"
        }
        env {
          name  = "SLOW_QUERY_MS"
          value = tostring(var.query_slow_ms)
        }
        env {
          name  = "LOG_QUERY_TIMINGS"
          value = var.query_log_timings ? "1" : "0"
        }
        env {
          name  = "QUERY_WARMUP"
          value = var.query_warmup ? "1" : "0"
        }
        env {
          name  = "QUERY_WARMUP_TEXT"
          value = var.query_warmup_text
        }
        env {
          name  = "QUERY_WARMUP_STEPS"
          value = var.query_warmup_steps
        }
        env {
          name  = "QUERY_DEFAULT_MODALITIES"
          value = var.query_default_modalities
        }
        env {
          name  = "QUERY_MODALITY_BOOSTS"
          value = var.query_modality_boosts
        }
        env {
          name  = "QUERY_MODALITY_HINT_BOOST"
          value = tostring(var.query_modality_hint_boost)
        }
        env {
          name  = "EMBEDDING_BACKEND"
          value = var.query_embedding_backend
        }
        env {
          name  = "SNAPSHOT_RELOAD_ALLOW_INTERNAL_SA"
          value = var.snapshot_reload_allow_internal_sa ? "1" : "0"
        }
        env {
          name  = "INTERNAL_AUTH_ALLOWED_SAS"
          value = var.snapshot_reload_allow_internal_sa ? "${google_service_account.dev_console.email},${google_service_account.index_builder.email}" : ""
        }
        env {
          name  = "DUCKDB_THREADS"
          value = var.duckdb_threads != null ? tostring(var.duckdb_threads) : ""
        }
        env {
          name  = "DUCKDB_MEMORY_LIMIT"
          value = var.duckdb_memory_limit
        }
        env {
          name  = "DUCKDB_TEMP_DIRECTORY"
          value = var.duckdb_temp_directory
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "RETIKON_DUCKDB_AUTH_PROVIDER"
          value = var.duckdb_auth_provider
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

resource "google_cloud_run_service" "query_gpu" {
  count    = var.query_gpu_enabled ? 1 : 0
  name     = "${var.query_gpu_service_name}-${var.env}"
  location = var.query_gpu_region != "" ? var.query_gpu_region : var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress"     = "all"
      "run.googleapis.com/accelerator" = var.query_gpu_accelerator_type
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale"                 = tostring(var.query_gpu_max_scale)
        "autoscaling.knative.dev/minScale"                 = tostring(var.query_gpu_min_scale)
        "run.googleapis.com/gpu-zonal-redundancy-disabled" = "true"
        "run.googleapis.com/vpc-access-connector"          = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"             = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.query.email
      container_concurrency = var.query_gpu_concurrency
      timeout_seconds       = var.query_gpu_timeout_seconds

      containers {
        image = var.query_gpu_image != "" ? var.query_gpu_image : var.query_image

        resources {
          limits = {
            cpu              = var.query_gpu_cpu
            memory           = var.query_gpu_memory
            "nvidia.com/gpu" = tostring(var.query_gpu_accelerator_count)
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.query_service_gpu:app"
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
          name  = "CORS_ALLOW_ORIGINS"
          value = var.cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "METERING_ENABLED"
          value = var.metering_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_ENABLED"
          value = var.metering_firestore_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_COLLECTION"
          value = var.metering_firestore_collection
        }
        env {
          name  = "METERING_COLLECTION_PREFIX"
          value = var.metering_collection_prefix != "" ? var.metering_collection_prefix : var.control_plane_collection_prefix
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "QUERY_TIER_OVERRIDE"
          value = "gpu"
        }
        env {
          name  = "EMBEDDING_DEVICE"
          value = "cuda"
        }
        env {
          name = "HF_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
        }
        env {
          name  = "RATE_LIMIT_BACKEND"
          value = var.rate_limit_backend
        }
        env {
          name  = "REDIS_HOST"
          value = var.rate_limit_redis_host != "" ? var.rate_limit_redis_host : google_redis_instance.rate_limit.host
        }
        env {
          name  = "REDIS_PORT"
          value = tostring(google_redis_instance.rate_limit.port)
        }
        env {
          name  = "REDIS_DB"
          value = tostring(var.rate_limit_redis_db)
        }
        env {
          name  = "REDIS_SSL"
          value = var.rate_limit_redis_ssl ? "1" : "0"
        }
        env {
          name  = "SLOW_QUERY_MS"
          value = tostring(var.query_slow_ms)
        }
        env {
          name  = "LOG_QUERY_TIMINGS"
          value = var.query_log_timings ? "1" : "0"
        }
        env {
          name  = "QUERY_WARMUP"
          value = var.query_warmup ? "1" : "0"
        }
        env {
          name  = "QUERY_WARMUP_TEXT"
          value = var.query_warmup_text
        }
        env {
          name  = "QUERY_WARMUP_STEPS"
          value = var.query_warmup_steps
        }
        env {
          name  = "QUERY_DEFAULT_MODALITIES"
          value = var.query_default_modalities
        }
        env {
          name  = "QUERY_MODALITY_BOOSTS"
          value = var.query_modality_boosts
        }
        env {
          name  = "QUERY_MODALITY_HINT_BOOST"
          value = tostring(var.query_modality_hint_boost)
        }
        env {
          name  = "EMBEDDING_BACKEND"
          value = var.query_embedding_backend
        }
        env {
          name  = "SNAPSHOT_RELOAD_ALLOW_INTERNAL_SA"
          value = var.snapshot_reload_allow_internal_sa ? "1" : "0"
        }
        env {
          name  = "INTERNAL_AUTH_ALLOWED_SAS"
          value = var.snapshot_reload_allow_internal_sa ? "${google_service_account.dev_console.email},${google_service_account.index_builder.email}" : ""
        }
        env {
          name  = "DUCKDB_THREADS"
          value = var.duckdb_threads != null ? tostring(var.duckdb_threads) : ""
        }
        env {
          name  = "DUCKDB_MEMORY_LIMIT"
          value = var.duckdb_memory_limit
        }
        env {
          name  = "DUCKDB_TEMP_DIRECTORY"
          value = var.duckdb_temp_directory
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "RETIKON_DUCKDB_AUTH_PROVIDER"
          value = var.duckdb_auth_provider
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

resource "google_cloud_run_service" "audit" {
  name     = "${var.audit_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.audit_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.audit_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.audit.email
      container_concurrency = var.audit_concurrency
      timeout_seconds       = var.audit_timeout_seconds

      containers {
        image = var.audit_image

        resources {
          limits = {
            cpu    = var.audit_cpu
            memory = var.audit_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.audit_service:app"
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
          name  = "CORS_ALLOW_ORIGINS"
          value = var.cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "AUDIT_REQUIRE_ADMIN"
          value = var.audit_require_admin ? "1" : "0"
        }
        env {
          name  = "AUDIT_DIAGNOSTICS"
          value = var.audit_diagnostics ? "1" : "0"
        }
        env {
          name  = "AUDIT_PARQUET_LIMIT"
          value = tostring(var.audit_parquet_limit)
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "RETIKON_DUCKDB_AUTH_PROVIDER"
          value = var.duckdb_auth_provider
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

resource "google_cloud_run_service" "workflow" {
  name     = "${var.workflow_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.workflow_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.workflow_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.workflow.email
      container_concurrency = var.workflow_concurrency
      timeout_seconds       = var.workflow_timeout_seconds

      containers {
        image = var.workflow_image

        resources {
          limits = {
            cpu    = var.workflow_cpu
            memory = var.workflow_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.workflow_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name = "HF_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"
          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name  = "INTERNAL_AUTH_ALLOWED_SAS"
          value = google_service_account.workflow.email
        }
        env {
          name  = "WORKFLOW_REQUIRE_ADMIN"
          value = var.workflow_require_admin ? "1" : "0"
        }
        env {
          name  = "WORKFLOW_RUN_MODE"
          value = var.workflow_run_mode
        }
        env {
          name  = "WORKFLOW_QUEUE_TOPIC"
          value = "projects/${var.project_id}/topics/${var.workflow_queue_topic_name}"
        }
        env {
          name  = "WORKFLOW_DLQ_TOPIC"
          value = "projects/${var.project_id}/topics/${var.workflow_dlq_topic_name}"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "chaos" {
  name     = "${var.chaos_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.chaos_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.chaos_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.chaos.email
      container_concurrency = var.chaos_concurrency
      timeout_seconds       = var.chaos_timeout_seconds

      containers {
        image = var.chaos_image

        resources {
          limits = {
            cpu    = var.chaos_cpu
            memory = var.chaos_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.chaos_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "CHAOS_REQUIRE_ADMIN"
          value = var.chaos_require_admin ? "1" : "0"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "privacy" {
  name     = "${var.privacy_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.privacy_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.privacy_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.privacy.email
      container_concurrency = var.privacy_concurrency
      timeout_seconds       = var.privacy_timeout_seconds

      containers {
        image = var.privacy_image

        resources {
          limits = {
            cpu    = var.privacy_cpu
            memory = var.privacy_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.privacy_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "PRIVACY_REQUIRE_ADMIN"
          value = var.privacy_require_admin ? "1" : "0"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "fleet" {
  name     = "${var.fleet_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.fleet_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.fleet_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.fleet.email
      container_concurrency = var.fleet_concurrency
      timeout_seconds       = var.fleet_timeout_seconds

      containers {
        image = var.fleet_image

        resources {
          limits = {
            cpu    = var.fleet_cpu
            memory = var.fleet_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.fleet_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "FLEET_REQUIRE_ADMIN"
          value = var.fleet_require_admin ? "1" : "0"
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "data_factory" {
  name     = "${var.data_factory_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.data_factory_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.data_factory_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.data_factory.email
      container_concurrency = var.data_factory_concurrency
      timeout_seconds       = var.data_factory_timeout_seconds

      containers {
        image = var.data_factory_image

        resources {
          limits = {
            cpu    = var.data_factory_cpu
            memory = var.data_factory_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.data_factory_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "DATA_FACTORY_REQUIRE_ADMIN"
          value = var.data_factory_require_admin ? "1" : "0"
        }
        env {
          name  = "TRAINING_RUN_MODE"
          value = var.data_factory_training_run_mode
        }
        env {
          name  = "OFFICE_CONVERSION_MODE"
          value = var.data_factory_office_conversion_mode
        }
        env {
          name  = "OFFICE_CONVERSION_BACKEND"
          value = var.data_factory_office_conversion_backend
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "webhook" {
  name     = "${var.webhook_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.webhook_max_scale)
        "autoscaling.knative.dev/minScale" = tostring(var.webhook_min_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.webhook.email
      container_concurrency = var.webhook_concurrency
      timeout_seconds       = var.webhook_timeout_seconds

      containers {
        image = var.webhook_image

        resources {
          limits = {
            cpu    = var.webhook_cpu
            memory = var.webhook_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.webhook_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "WEBHOOK_REQUIRE_ADMIN"
          value = var.webhook_require_admin ? "1" : "0"
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
      service_account_name  = google_service_account.dev_console.email
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
          name  = "CORS_ALLOW_ORIGINS"
          value = var.cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "DEV_CONSOLE_SNAPSHOT_RELOAD_ALLOW_SA"
          value = var.dev_console_snapshot_reload_allow_sa ? "1" : "0"
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
        }
        env {
          name  = "MAX_PREVIEW_BYTES"
          value = tostring(var.max_preview_bytes)
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
          name  = "IMAGE_MODEL_NAME"
          value = var.image_model_name
        }
        env {
          name  = "EMBEDDING_BACKEND"
          value = var.dev_console_embedding_backend
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "edge_gateway" {
  name     = "${var.edge_gateway_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = tostring(var.edge_gateway_max_scale)
      }
    }

    spec {
      service_account_name  = google_service_account.edge_gateway.email
      container_concurrency = var.edge_gateway_concurrency

      containers {
        image = var.edge_gateway_image

        resources {
          limits = {
            cpu    = var.edge_gateway_cpu
            memory = var.edge_gateway_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.edge_gateway_service:app"
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
          name  = "CORS_ALLOW_ORIGINS"
          value = var.cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "MAX_RAW_BYTES"
          value = tostring(var.max_raw_bytes)
        }
        env {
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
        }
        env {
          name  = "EDGE_BUFFER_DIR"
          value = "/tmp/retikon_edge_buffer"
        }
        env {
          name  = "EDGE_BUFFER_MAX_BYTES"
          value = tostring(var.edge_buffer_max_bytes)
        }
        env {
          name  = "EDGE_BUFFER_TTL_SECONDS"
          value = tostring(var.edge_buffer_ttl_seconds)
        }
        env {
          name  = "EDGE_BATCH_MIN"
          value = tostring(var.edge_batch_min)
        }
        env {
          name  = "EDGE_BATCH_MAX"
          value = tostring(var.edge_batch_max)
        }
        env {
          name  = "EDGE_BACKLOG_LOW"
          value = tostring(var.edge_backlog_low)
        }
        env {
          name  = "EDGE_BACKLOG_HIGH"
          value = tostring(var.edge_backlog_high)
        }
        env {
          name  = "EDGE_BACKPRESSURE_MAX"
          value = tostring(var.edge_backpressure_max)
        }
        env {
          name  = "EDGE_BACKPRESSURE_HARD"
          value = tostring(var.edge_backpressure_hard)
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service" "stream_ingest" {
  name     = "${var.stream_ingest_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale"        = tostring(var.stream_ingest_max_scale)
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.stream_ingest.email
      container_concurrency = var.stream_ingest_concurrency

      containers {
        image = var.stream_ingest_image

        resources {
          limits = {
            cpu    = var.stream_ingest_cpu
            memory = var.stream_ingest_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.stream_ingest_service:app"
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
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "WHISPER_LANGUAGE"
          value = var.whisper_language
        }
        env {
          name  = "WHISPER_LANGUAGE_DEFAULT"
          value = var.whisper_language_default
        }
        env {
          name  = "WHISPER_LANGUAGE_AUTO"
          value = var.whisper_language_auto ? "1" : "0"
        }
        env {
          name  = "WHISPER_MIN_CONFIDENCE"
          value = tostring(var.whisper_min_confidence)
        }
        env {
          name  = "WHISPER_DETECT_SECONDS"
          value = tostring(var.whisper_detect_seconds)
        }
        env {
          name  = "WHISPER_TASK"
          value = var.whisper_task
        }
        env {
          name  = "WHISPER_NON_ENGLISH_TASK"
          value = var.whisper_non_english_task
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
          name  = "MODEL_INFERENCE_TIMEOUT_S"
          value = tostring(var.model_inference_timeout_seconds)
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
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
          value = tostring(var.idempotency_ttl_seconds)
        }
        env {
          name  = "IDEMPOTENCY_COMPLETED_TTL_SECONDS"
          value = tostring(var.idempotency_completed_ttl_seconds)
        }
        env {
          name  = "ALLOWED_DOC_EXT"
          value = ".pdf,.txt,.md,.rtf,.docx,.pptx,.csv,.tsv,.xlsx,.xls"
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
          value = tostring(var.video_sample_fps)
        }
        env {
          name  = "VIDEO_SAMPLE_INTERVAL_SECONDS"
          value = tostring(var.video_sample_interval_seconds)
        }
        env {
          name  = "VIDEO_SCENE_THRESHOLD"
          value = tostring(var.video_scene_threshold)
        }
        env {
          name  = "VIDEO_SCENE_MIN_FRAMES"
          value = tostring(var.video_scene_min_frames)
        }
        env {
          name  = "VIDEO_THUMBNAIL_WIDTH"
          value = tostring(var.video_thumbnail_width)
        }
        env {
          name  = "STREAM_INGEST_TOPIC"
          value = "projects/${var.project_id}/topics/${var.stream_ingest_topic_name}"
        }
        env {
          name  = "STREAM_BATCH_MAX"
          value = tostring(var.stream_ingest_batch_max)
        }
        env {
          name  = "STREAM_BATCH_MAX_DELAY_MS"
          value = tostring(var.stream_ingest_batch_max_delay_ms)
        }
        env {
          name  = "STREAM_BACKLOG_MAX"
          value = tostring(var.stream_ingest_backlog_max)
        }
      }
    }
  }

  autogenerate_revision_name = true
}

resource "google_api_gateway_api" "retikon" {
  count    = var.enable_api_gateway ? 1 : 0
  provider = google-beta

  api_id = var.api_gateway_name
}

resource "google_api_gateway_api_config" "retikon" {
  count    = var.enable_api_gateway ? 1 : 0
  provider = google-beta

  api                = google_api_gateway_api.retikon[0].api_id
  api_config_id_prefix = var.api_gateway_config_name

  openapi_documents {
    document {
      path     = "retikon-gateway.yaml"
      contents = base64encode(local.api_gateway_openapi)
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_cloud_run_service" "ingestion_media" {
  name     = "${var.ingestion_media_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale"        = tostring(var.ingestion_media_keep_warm_enabled ? var.ingestion_media_min_scale : 0)
        "autoscaling.knative.dev/maxScale"        = tostring(var.ingestion_media_autoscale_enabled ? var.ingestion_media_max_scale : 1)
        "run.googleapis.com/cpu-throttling"       = var.ingestion_media_cpu_always_on ? "false" : "true"
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.ingestion.email
      container_concurrency = var.ingestion_media_autoscale_enabled ? var.ingestion_media_concurrency : 1

      containers {
        image = var.ingestion_image

        resources {
          limits = {
            cpu    = var.ingestion_media_cpu
            memory = var.ingestion_media_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.ingestion_service:app"
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
          name  = "QUEUE_MONITOR_ENABLED"
          value = var.queue_monitor_enabled ? "1" : "0"
        }
        env {
          name  = "QUEUE_MONITOR_INTERVAL_SECONDS"
          value = tostring(var.queue_monitor_interval_seconds)
        }
        env {
          name  = "QUEUE_MONITOR_SUBSCRIPTIONS"
          value = var.queue_monitor_subscriptions
        }
        env {
          name  = "CORS_ALLOW_ORIGINS"
          value = local.dev_console_cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "METERING_ENABLED"
          value = var.metering_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_ENABLED"
          value = var.metering_firestore_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_COLLECTION"
          value = var.metering_firestore_collection
        }
        env {
          name  = "METERING_COLLECTION_PREFIX"
          value = var.metering_collection_prefix != "" ? var.metering_collection_prefix : var.control_plane_collection_prefix
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "TEXT_EMBED_BATCH_SIZE"
          value = tostring(var.text_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_BATCH_SIZE"
          value = tostring(var.image_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_MAX_DIM"
          value = tostring(var.image_embed_max_dim)
        }
        env {
          name  = "TEXT_EMBED_BACKEND"
          value = var.text_embed_backend
        }
        env {
          name  = "IMAGE_EMBED_BACKEND"
          value = var.image_embed_backend
        }
        env {
          name  = "AUDIO_EMBED_BACKEND"
          value = var.audio_embed_backend
        }
        env {
          name  = "IMAGE_TEXT_EMBED_BACKEND"
          value = var.image_text_embed_backend
        }
        env {
          name  = "AUDIO_TEXT_EMBED_BACKEND"
          value = var.audio_text_embed_backend
        }
        env {
          name  = "INGEST_WARMUP"
          value = var.ingest_media_warmup ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_AUDIO"
          value = var.ingest_media_warmup_audio ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_TEXT"
          value = var.ingest_media_warmup_text ? "1" : "0"
        }
        env {
          name  = "WHISPER_MODEL_NAME"
          value = var.whisper_model_name
        }
        env {
          name  = "WHISPER_LANGUAGE"
          value = var.whisper_language
        }
        env {
          name  = "WHISPER_LANGUAGE_DEFAULT"
          value = var.whisper_language_default
        }
        env {
          name  = "WHISPER_LANGUAGE_AUTO"
          value = var.whisper_language_auto ? "1" : "0"
        }
        env {
          name  = "WHISPER_MIN_CONFIDENCE"
          value = tostring(var.whisper_min_confidence)
        }
        env {
          name  = "WHISPER_DETECT_SECONDS"
          value = tostring(var.whisper_detect_seconds)
        }
        env {
          name  = "WHISPER_TASK"
          value = var.whisper_task
        }
        env {
          name  = "WHISPER_NON_ENGLISH_TASK"
          value = var.whisper_non_english_task
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
          name  = "INGEST_ALLOWED_MODALITIES"
          value = "audio,video"
        }
        env {
          name  = "INTERNAL_AUTH_ALLOWED_SAS"
          value = google_service_account.ingestion.email
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
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
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
          name  = "VIDEO_SCENE_THRESHOLD"
          value = tostring(var.video_scene_threshold)
        }
        env {
          name  = "VIDEO_SCENE_MIN_FRAMES"
          value = tostring(var.video_scene_min_frames)
        }
        env {
          name  = "VIDEO_THUMBNAIL_WIDTH"
          value = tostring(var.video_thumbnail_width)
        }
        env {
          name  = "VIDEO_SAMPLE_FPS"
          value = tostring(var.video_sample_fps)
        }
        env {
          name  = "VIDEO_SAMPLE_INTERVAL_SECONDS"
          value = tostring(var.video_sample_interval_seconds)
        }
        env {
          name  = "AUDIO_TRANSCRIBE"
          value = var.audio_transcribe ? "1" : "0"
        }
        env {
          name  = "TRANSCRIBE_ENABLED"
          value = var.transcribe_enabled ? "1" : "0"
        }
        env {
          name  = "AUDIO_PROFILE"
          value = var.audio_profile ? "1" : "0"
        }
        env {
          name  = "AUDIO_SKIP_NORMALIZE_IF_WAV"
          value = var.audio_skip_normalize_if_wav ? "1" : "0"
        }
        env {
          name  = "AUDIO_MAX_SEGMENTS"
          value = tostring(var.audio_max_segments)
        }
        env {
          name  = "TRANSCRIBE_TIER"
          value = var.transcribe_tier
        }
        env {
          name  = "TRANSCRIBE_MAX_MS"
          value = tostring(var.transcribe_max_ms)
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_ORG"
          value = var.transcribe_max_ms_by_org
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_PLAN"
          value = var.transcribe_max_ms_by_plan
        }
        env {
          name  = "TRANSCRIBE_PLAN_METADATA_KEYS"
          value = var.transcribe_plan_metadata_keys
        }
        env {
          name  = "ENABLE_DEDUPE_CACHE"
          value = var.dedupe_cache_enabled ? "1" : "0"
        }
        env {
          name = "HF_TOKEN"

          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"

          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name  = "FIRESTORE_COLLECTION"
          value = "ingestion_events"
        }
        env {
          name  = "IDEMPOTENCY_TTL_SECONDS"
          value = tostring(var.idempotency_ttl_seconds)
        }
        env {
          name  = "IDEMPOTENCY_COMPLETED_TTL_SECONDS"
          value = tostring(var.idempotency_completed_ttl_seconds)
        }
        env {
          name  = "MAX_INGEST_ATTEMPTS"
          value = tostring(var.max_ingest_attempts)
        }
        env {
          name  = "ALLOWED_DOC_EXT"
          value = ".pdf,.txt,.md,.rtf,.docx,.pptx,.csv,.tsv,.xlsx,.xls"
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
        }
        env {
          name  = "RATE_LIMIT_BACKEND"
          value = var.rate_limit_backend
        }
        env {
          name  = "REDIS_HOST"
          value = var.rate_limit_redis_host != "" ? var.rate_limit_redis_host : google_redis_instance.rate_limit.host
        }
        env {
          name  = "REDIS_PORT"
          value = tostring(google_redis_instance.rate_limit.port)
        }
        env {
          name  = "REDIS_DB"
          value = tostring(var.rate_limit_redis_db)
        }
        env {
          name  = "REDIS_SSL"
          value = var.rate_limit_redis_ssl ? "1" : "0"
        }
        env {
          name  = "DLQ_TOPIC"
          value = "projects/${var.project_id}/topics/${var.ingest_dlq_topic_name}"
        }
      }
    }
  }
}

resource "google_cloud_run_service" "ingestion_embed" {
  count    = var.ingestion_embed_enabled ? 1 : 0
  name     = "${var.ingestion_embed_service_name}-${var.env}"
  location = var.region

  metadata {
    annotations = {
      "run.googleapis.com/ingress" = "all"
    }
  }

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale"        = tostring(var.ingestion_embed_keep_warm_enabled ? var.ingestion_embed_min_scale : 0)
        "autoscaling.knative.dev/maxScale"        = tostring(var.ingestion_embed_autoscale_enabled ? var.ingestion_embed_max_scale : 1)
        "run.googleapis.com/cpu-throttling"       = var.ingestion_embed_cpu_always_on ? "false" : "true"
        "run.googleapis.com/vpc-access-connector" = google_vpc_access_connector.serverless.id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }

    spec {
      service_account_name  = google_service_account.ingestion.email
      container_concurrency = var.ingestion_embed_autoscale_enabled ? var.ingestion_embed_concurrency : 1

      containers {
        image = var.ingestion_image

        resources {
          limits = {
            cpu    = var.ingestion_embed_cpu
            memory = var.ingestion_embed_memory
          }
        }

        env {
          name  = "APP_MODULE"
          value = "gcp_adapter.ingestion_service:app"
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
          name  = "QUEUE_MONITOR_ENABLED"
          value = var.queue_monitor_enabled ? "1" : "0"
        }
        env {
          name  = "QUEUE_MONITOR_INTERVAL_SECONDS"
          value = tostring(var.queue_monitor_interval_seconds)
        }
        env {
          name  = "QUEUE_MONITOR_SUBSCRIPTIONS"
          value = var.queue_monitor_subscriptions
        }
        env {
          name  = "CORS_ALLOW_ORIGINS"
          value = local.dev_console_cors_allow_origins
        }
        env {
          name  = "AUTH_ISSUER"
          value = var.auth_issuer
        }
        env {
          name  = "AUTH_AUDIENCE"
          value = var.auth_audience
        }
        env {
          name  = "AUTH_JWKS_URI"
          value = var.auth_jwks_uri
        }
        env {
          name  = "AUTH_GATEWAY_USERINFO"
          value = var.auth_gateway_userinfo ? "1" : "0"
        }
        env {
          name  = "AUTH_JWT_ALGORITHMS"
          value = var.auth_jwt_algorithms
        }
        env {
          name  = "AUTH_REQUIRED_CLAIMS"
          value = var.auth_required_claims
        }
        env {
          name  = "AUTH_CLAIM_SUB"
          value = var.auth_claim_sub
        }
        env {
          name  = "AUTH_CLAIM_EMAIL"
          value = var.auth_claim_email
        }
        env {
          name  = "AUTH_CLAIM_ROLES"
          value = var.auth_claim_roles
        }
        env {
          name  = "AUTH_CLAIM_GROUPS"
          value = var.auth_claim_groups
        }
        env {
          name  = "AUTH_CLAIM_ORG_ID"
          value = var.auth_claim_org_id
        }
        env {
          name  = "AUTH_CLAIM_SITE_ID"
          value = var.auth_claim_site_id
        }
        env {
          name  = "AUTH_CLAIM_STREAM_ID"
          value = var.auth_claim_stream_id
        }
        env {
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
        }
        env {
          name  = "AUTH_ADMIN_ROLES"
          value = var.auth_admin_roles
        }
        env {
          name  = "AUTH_ADMIN_GROUPS"
          value = var.auth_admin_groups
        }
        env {
          name  = "AUTH_JWT_LEEWAY_SECONDS"
          value = tostring(var.auth_jwt_leeway_seconds)
        }
        env {
          name  = "CONTROL_PLANE_STORE"
          value = var.control_plane_store
        }
        env {
          name  = "CONTROL_PLANE_COLLECTION_PREFIX"
          value = var.control_plane_collection_prefix
        }
        env {
          name  = "CONTROL_PLANE_READ_MODE"
          value = var.control_plane_read_mode
        }
        env {
          name  = "CONTROL_PLANE_WRITE_MODE"
          value = var.control_plane_write_mode
        }
        env {
          name  = "CONTROL_PLANE_FALLBACK_ON_EMPTY"
          value = var.control_plane_fallback_on_empty ? "1" : "0"
        }
        env {
          name  = "METERING_ENABLED"
          value = var.metering_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_ENABLED"
          value = var.metering_firestore_enabled ? "1" : "0"
        }
        env {
          name  = "METERING_FIRESTORE_COLLECTION"
          value = var.metering_firestore_collection
        }
        env {
          name  = "METERING_COLLECTION_PREFIX"
          value = var.metering_collection_prefix != "" ? var.metering_collection_prefix : var.control_plane_collection_prefix
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "TEXT_EMBED_BATCH_SIZE"
          value = tostring(var.text_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_BATCH_SIZE"
          value = tostring(var.image_embed_batch_size)
        }
        env {
          name  = "IMAGE_EMBED_MAX_DIM"
          value = tostring(var.image_embed_max_dim)
        }
        env {
          name  = "TEXT_EMBED_BACKEND"
          value = var.text_embed_backend
        }
        env {
          name  = "IMAGE_EMBED_BACKEND"
          value = var.image_embed_backend
        }
        env {
          name  = "AUDIO_EMBED_BACKEND"
          value = var.audio_embed_backend
        }
        env {
          name  = "IMAGE_TEXT_EMBED_BACKEND"
          value = var.image_text_embed_backend
        }
        env {
          name  = "AUDIO_TEXT_EMBED_BACKEND"
          value = var.audio_text_embed_backend
        }
        env {
          name  = "INGEST_WARMUP"
          value = var.ingest_media_warmup ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_AUDIO"
          value = var.ingest_media_warmup_audio ? "1" : "0"
        }
        env {
          name  = "INGEST_WARMUP_TEXT"
          value = var.ingest_media_warmup_text ? "1" : "0"
        }
        env {
          name  = "WHISPER_MODEL_NAME"
          value = var.whisper_model_name
        }
        env {
          name  = "WHISPER_LANGUAGE"
          value = var.whisper_language
        }
        env {
          name  = "WHISPER_LANGUAGE_DEFAULT"
          value = var.whisper_language_default
        }
        env {
          name  = "WHISPER_LANGUAGE_AUTO"
          value = var.whisper_language_auto ? "1" : "0"
        }
        env {
          name  = "WHISPER_MIN_CONFIDENCE"
          value = tostring(var.whisper_min_confidence)
        }
        env {
          name  = "WHISPER_DETECT_SECONDS"
          value = tostring(var.whisper_detect_seconds)
        }
        env {
          name  = "WHISPER_TASK"
          value = var.whisper_task
        }
        env {
          name  = "WHISPER_NON_ENGLISH_TASK"
          value = var.whisper_non_english_task
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
          name  = "INGEST_ALLOWED_MODALITIES"
          value = "document,image"
        }
        env {
          name  = "INTERNAL_AUTH_ALLOWED_SAS"
          value = google_service_account.ingestion.email
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
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
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
          name  = "VIDEO_SCENE_THRESHOLD"
          value = tostring(var.video_scene_threshold)
        }
        env {
          name  = "VIDEO_SCENE_MIN_FRAMES"
          value = tostring(var.video_scene_min_frames)
        }
        env {
          name  = "VIDEO_THUMBNAIL_WIDTH"
          value = tostring(var.video_thumbnail_width)
        }
        env {
          name  = "VIDEO_SAMPLE_FPS"
          value = tostring(var.video_sample_fps)
        }
        env {
          name  = "VIDEO_SAMPLE_INTERVAL_SECONDS"
          value = tostring(var.video_sample_interval_seconds)
        }
        env {
          name  = "AUDIO_TRANSCRIBE"
          value = "0"
        }
        env {
          name  = "TRANSCRIBE_ENABLED"
          value = "0"
        }
        env {
          name  = "AUDIO_PROFILE"
          value = var.audio_profile ? "1" : "0"
        }
        env {
          name  = "AUDIO_SKIP_NORMALIZE_IF_WAV"
          value = var.audio_skip_normalize_if_wav ? "1" : "0"
        }
        env {
          name  = "AUDIO_MAX_SEGMENTS"
          value = tostring(var.audio_max_segments)
        }
        env {
          name  = "TRANSCRIBE_TIER"
          value = "off"
        }
        env {
          name  = "TRANSCRIBE_MAX_MS"
          value = "0"
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_ORG"
          value = var.transcribe_max_ms_by_org
        }
        env {
          name  = "TRANSCRIBE_MAX_MS_BY_PLAN"
          value = var.transcribe_max_ms_by_plan
        }
        env {
          name  = "TRANSCRIBE_PLAN_METADATA_KEYS"
          value = var.transcribe_plan_metadata_keys
        }
        env {
          name  = "ENABLE_DEDUPE_CACHE"
          value = var.dedupe_cache_enabled ? "1" : "0"
        }
        env {
          name = "HF_TOKEN"

          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name = "HUGGINGFACE_HUB_TOKEN"

          value_from {
            secret_key_ref {
              name = "retikon-hf-token"
              key  = "latest"
            }
          }
        }
        env {
          name  = "FIRESTORE_COLLECTION"
          value = "ingestion_events"
        }
        env {
          name  = "IDEMPOTENCY_TTL_SECONDS"
          value = tostring(var.idempotency_ttl_seconds)
        }
        env {
          name  = "IDEMPOTENCY_COMPLETED_TTL_SECONDS"
          value = tostring(var.idempotency_completed_ttl_seconds)
        }
        env {
          name  = "MAX_INGEST_ATTEMPTS"
          value = tostring(var.max_ingest_attempts)
        }
        env {
          name  = "ALLOWED_DOC_EXT"
          value = ".pdf,.txt,.md,.rtf,.docx,.pptx,.csv,.tsv,.xlsx,.xls"
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
          name  = "RATE_LIMIT_GLOBAL_DOC_PER_MIN"
          value = tostring(var.rate_limit_global_doc_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_IMAGE_PER_MIN"
          value = tostring(var.rate_limit_global_image_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_AUDIO_PER_MIN"
          value = tostring(var.rate_limit_global_audio_per_min)
        }
        env {
          name  = "RATE_LIMIT_GLOBAL_VIDEO_PER_MIN"
          value = tostring(var.rate_limit_global_video_per_min)
        }
        env {
          name  = "RATE_LIMIT_BACKEND"
          value = var.rate_limit_backend
        }
        env {
          name  = "REDIS_HOST"
          value = var.rate_limit_redis_host != "" ? var.rate_limit_redis_host : google_redis_instance.rate_limit.host
        }
        env {
          name  = "REDIS_PORT"
          value = tostring(google_redis_instance.rate_limit.port)
        }
        env {
          name  = "REDIS_DB"
          value = tostring(var.rate_limit_redis_db)
        }
        env {
          name  = "REDIS_SSL"
          value = var.rate_limit_redis_ssl ? "1" : "0"
        }
        env {
          name  = "DLQ_TOPIC"
          value = "projects/${var.project_id}/topics/${var.ingest_dlq_topic_name}"
        }
      }
    }
  }
}

resource "google_api_gateway_gateway" "retikon" {
  count    = var.enable_api_gateway ? 1 : 0
  provider = google-beta

  gateway_id = var.api_gateway_name
  api_config = google_api_gateway_api_config.retikon[0].id
  region     = var.api_gateway_region != "" ? var.api_gateway_region : var.region
}

resource "google_cloud_run_service_iam_member" "query_invoker" {
  location = google_cloud_run_service.query.location
  service  = google_cloud_run_service.query.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "query_browser_invoker" {
  count    = var.allow_browser_direct_access ? 1 : 0
  location = google_cloud_run_service.query.location
  service  = google_cloud_run_service.query.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_service_iam_member" "query_internal_invoker" {
  location = google_cloud_run_service.query.location
  service  = google_cloud_run_service.query.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.dev_console.email}"
}

resource "google_cloud_run_service_iam_member" "query_gpu_invoker" {
  count    = var.query_gpu_enabled ? 1 : 0
  location = google_cloud_run_service.query_gpu[0].location
  service  = google_cloud_run_service.query_gpu[0].name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "audit_invoker" {
  location = google_cloud_run_service.audit.location
  service  = google_cloud_run_service.audit.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "workflow_invoker" {
  location = google_cloud_run_service.workflow.location
  service  = google_cloud_run_service.workflow.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "workflow_internal_invoker" {
  location = google_cloud_run_service.workflow.location
  service  = google_cloud_run_service.workflow.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_cloud_run_service_iam_member" "chaos_invoker" {
  location = google_cloud_run_service.chaos.location
  service  = google_cloud_run_service.chaos.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "privacy_invoker" {
  location = google_cloud_run_service.privacy.location
  service  = google_cloud_run_service.privacy.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "fleet_invoker" {
  location = google_cloud_run_service.fleet.location
  service  = google_cloud_run_service.fleet.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "data_factory_invoker" {
  location = google_cloud_run_service.data_factory.location
  service  = google_cloud_run_service.data_factory.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "data_factory_internal_invoker" {
  location = google_cloud_run_service.data_factory.location
  service  = google_cloud_run_service.data_factory.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.data_factory.email}"
}

resource "google_cloud_run_service_iam_member" "webhook_invoker" {
  location = google_cloud_run_service.webhook.location
  service  = google_cloud_run_service.webhook.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "dev_console_invoker" {
  location = google_cloud_run_service.dev_console.location
  service  = google_cloud_run_service.dev_console.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "dev_console_browser_invoker" {
  count    = var.allow_browser_direct_access ? 1 : 0
  location = google_cloud_run_service.dev_console.location
  service  = google_cloud_run_service.dev_console.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_service_iam_member" "edge_gateway_invoker" {
  location = google_cloud_run_service.edge_gateway.location
  service  = google_cloud_run_service.edge_gateway.name
  role     = "roles/run.invoker"
  member   = var.enable_api_gateway ? local.api_gateway_invoker : "allUsers"
}

resource "google_cloud_run_service_iam_member" "stream_ingest_invoker" {
  location = google_cloud_run_service.stream_ingest.location
  service  = google_cloud_run_service.stream_ingest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.stream_ingest.email}"
}

resource "google_project_iam_member" "eventarc_service_agent" {
  project = var.project_id
  role    = "roles/eventarc.serviceAgent"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-eventarc.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "apigateway_service_management_admin" {
  count   = var.enable_api_gateway ? 1 : 0
  project = var.project_id
  role    = "roles/servicemanagement.admin"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-apigateway.iam.gserviceaccount.com"
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
  name     = "retikon-ingest-docs-${var.env}"
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
      timeout         = var.index_job_timeout

      containers {
        image   = var.index_image
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
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "DEFAULT_ORG_ID"
          value = var.default_org_id
        }
        env {
          name  = "DEFAULT_SITE_ID"
          value = var.default_site_id
        }
        env {
          name  = "DEFAULT_STREAM_ID"
          value = var.default_stream_id
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
          name  = "INDEX_BUILDER_DUCKDB_THREADS"
          value = var.index_duckdb_threads == null ? "" : tostring(var.index_duckdb_threads)
        }
        env {
          name  = "INDEX_BUILDER_DUCKDB_MEMORY_LIMIT"
          value = var.index_duckdb_memory_limit
        }
        env {
          name  = "INDEX_BUILDER_DUCKDB_TEMP_DIRECTORY"
          value = var.index_duckdb_temp_directory
        }
        env {
          name  = "DUCKDB_ALLOW_INSTALL"
          value = var.duckdb_allow_install ? "1" : "0"
        }
        env {
          name  = "RETIKON_DUCKDB_AUTH_PROVIDER"
          value = var.duckdb_auth_provider
        }
        env {
          name  = "INDEX_BUILDER_WORK_DIR"
          value = var.index_builder_work_dir
        }
        env {
          name  = "RETIKON_DUCKDB_URI_SIGNER"
          value = "gcp_adapter.duckdb_uri_signer:sign_gcs_uri"
        }
        env {
          name  = "GOOGLE_SERVICE_ACCOUNT_EMAIL"
          value = google_service_account.index_builder.email
        }
        env {
          name  = "INDEX_BUILDER_COPY_LOCAL"
          value = var.index_builder_copy_local ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_FALLBACK_LOCAL"
          value = var.index_builder_fallback_local ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_SKIP_IF_UNCHANGED"
          value = var.index_builder_skip_if_unchanged ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_USE_LATEST_COMPACTION"
          value = var.index_builder_use_latest_compaction ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_SKIP_MISSING_FILES"
          value = var.index_builder_skip_missing_files ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_INCREMENTAL"
          value = var.index_builder_incremental ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_RELOAD_SNAPSHOT"
          value = var.index_builder_reload_snapshot ? "1" : "0"
        }
        env {
          name  = "INDEX_BUILDER_INCREMENTAL_MAX_NEW_MANIFESTS"
          value = tostring(var.index_builder_incremental_max_new_manifests)
        }
        env {
          name  = "INDEX_BUILDER_MIN_NEW_MANIFESTS"
          value = tostring(var.index_builder_min_new_manifests)
        }
        env {
          name  = "HNSW_EF_CONSTRUCTION"
          value = tostring(var.hnsw_ef_construction)
        }
        env {
          name  = "HNSW_M"
          value = tostring(var.hnsw_m)
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

resource "google_cloud_run_v2_job" "compaction" {
  provider = google-beta

  name     = "${var.compaction_job_name}-${var.env}"
  location = var.region

  template {
    template {
      service_account = google_service_account.compaction.email
      max_retries     = 0
      timeout         = "900s"

      containers {
        image   = var.compaction_image
        command = ["python"]
        args    = ["-m", "gcp_adapter.compaction_service"]

        env {
          name  = "ENV"
          value = var.env
        }
        env {
          name  = "LOG_LEVEL"
          value = var.log_level
        }
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
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
          name  = "COMPACTION_TARGET_MIN_BYTES"
          value = tostring(var.compaction_target_min_bytes)
        }
        env {
          name  = "COMPACTION_TARGET_MAX_BYTES"
          value = tostring(var.compaction_target_max_bytes)
        }
        env {
          name  = "COMPACTION_MAX_GROUPS_PER_BATCH"
          value = tostring(var.compaction_max_groups_per_batch)
        }
        env {
          name  = "COMPACTION_DELETE_SOURCE"
          value = var.compaction_delete_source ? "1" : "0"
        }
        env {
          name  = "COMPACTION_DRY_RUN"
          value = var.compaction_dry_run ? "1" : "0"
        }
        env {
          name  = "COMPACTION_STRICT"
          value = var.compaction_strict ? "1" : "0"
        }
        env {
          name  = "COMPACTION_SKIP_MISSING"
          value = var.compaction_skip_missing ? "1" : "0"
        }
        env {
          name  = "COMPACTION_RELAX_NULLS"
          value = var.compaction_relax_nulls ? "1" : "0"
        }
        env {
          name  = "AUDIT_COMPACTION_ENABLED"
          value = var.audit_compaction_enabled ? "1" : "0"
        }
        env {
          name  = "AUDIT_COMPACTION_TARGET_MIN_BYTES"
          value = tostring(var.audit_compaction_target_min_bytes)
        }
        env {
          name  = "AUDIT_COMPACTION_TARGET_MAX_BYTES"
          value = tostring(var.audit_compaction_target_max_bytes)
        }
        env {
          name  = "AUDIT_COMPACTION_MAX_FILES_PER_BATCH"
          value = tostring(var.audit_compaction_max_files_per_batch)
        }
        env {
          name  = "AUDIT_COMPACTION_MAX_BATCHES"
          value = tostring(var.audit_compaction_max_batches)
        }
        env {
          name  = "AUDIT_COMPACTION_MIN_AGE_SECONDS"
          value = tostring(var.audit_compaction_min_age_seconds)
        }
        env {
          name  = "AUDIT_COMPACTION_DELETE_SOURCE"
          value = var.audit_compaction_delete_source ? "1" : "0"
        }
        env {
          name  = "AUDIT_COMPACTION_DRY_RUN"
          value = var.audit_compaction_dry_run ? "1" : "0"
        }
        env {
          name  = "AUDIT_COMPACTION_STRICT"
          value = var.audit_compaction_strict ? "1" : "0"
        }
        env {
          name  = "RETENTION_HOT_DAYS"
          value = tostring(var.retention_hot_days)
        }
        env {
          name  = "RETENTION_WARM_DAYS"
          value = tostring(var.retention_warm_days)
        }
        env {
          name  = "RETENTION_COLD_DAYS"
          value = tostring(var.retention_cold_days)
        }
        env {
          name  = "RETENTION_DELETE_DAYS"
          value = tostring(var.retention_delete_days)
        }
        env {
          name  = "RETENTION_APPLY"
          value = var.retention_apply ? "1" : "0"
        }

        resources {
          limits = {
            cpu    = var.compaction_cpu
            memory = var.compaction_memory
          }
        }
      }
    }
  }
}

resource "google_cloud_scheduler_job" "index_builder" {
  count     = var.index_schedule_enabled ? 1 : 0
  name      = "${var.index_job_name}-${var.env}"
  schedule  = var.index_schedule
  time_zone = var.index_schedule_timezone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.index_builder.name}:run"

    oauth_token {
      service_account_email = google_service_account.index_builder.email
    }
  }
}

resource "google_cloud_scheduler_job" "compaction" {
  count     = var.compaction_enabled ? 1 : 0
  name      = "${var.compaction_job_name}-${var.env}"
  schedule  = var.compaction_schedule
  time_zone = var.compaction_schedule_timezone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.compaction.name}:run"

    oauth_token {
      service_account_email = google_service_account.compaction.email
    }
  }
}

resource "google_cloud_scheduler_job" "workflow_tick" {
  name      = "retikon-workflow-schedule-${var.env}"
  schedule  = var.workflow_schedule
  time_zone = var.workflow_schedule_timezone

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_service.workflow.status[0].url}/workflows/schedule/tick"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.workflow.email
      audience              = google_cloud_run_service.workflow.status[0].url
    }

    body = base64encode("{}")
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

resource "google_monitoring_alert_policy" "query_5xx_rate" {
  display_name = "Retikon Query 5xx rate"
  combiner     = "OR"

  conditions {
    display_name = "Query 5xx rate"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_query_5xx_rate
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

resource "google_monitoring_alert_policy" "ingest_p95_latency" {
  display_name = "Retikon Ingest p95 latency"
  combiner     = "OR"

  conditions {
    display_name = "Ingest p95 latency"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_ingest_p95_seconds
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

resource "google_monitoring_alert_policy" "ingest_queue_wait_p95" {
  display_name = "Retikon ingest queue wait p95"
  combiner     = "OR"

  conditions {
    display_name = "Ingest queue wait p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_queue_wait_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_queue_wait_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_embed_image_p95" {
  display_name = "Retikon ingest embed_image_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Embed image p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_image_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_embed_image_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_decode_p95" {
  display_name = "Retikon ingest decode_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Decode p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_decode_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_decode_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_embed_text_p95" {
  display_name = "Retikon ingest embed_text_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Embed text p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_text_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_embed_text_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_embed_audio_p95" {
  display_name = "Retikon ingest embed_audio_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Embed audio p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_audio_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_embed_audio_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_transcribe_p95" {
  display_name = "Retikon ingest transcribe_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Transcribe p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_transcribe_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_transcribe_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_write_parquet_p95" {
  display_name = "Retikon ingest write_parquet_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Write parquet p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_write_parquet_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_write_parquet_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "ingest_write_manifest_p95" {
  display_name = "Retikon ingest write_manifest_ms p95"
  combiner     = "OR"

  conditions {
    display_name = "Write manifest p95 (ms)"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_write_manifest_ms\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_stage_write_manifest_ms_p95
      duration        = "300s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_NONE"
        group_by_fields      = ["metric.label.modality"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
}

resource "google_monitoring_alert_policy" "index_queue_length" {
  display_name = "Retikon index queue length"
  combiner     = "OR"

  conditions {
    display_name = "Index queue length p95"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/retikon_index_queue_length\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_index_queue_length
      duration        = "900s"

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

resource "google_billing_budget" "cost_anomaly" {
  count           = var.billing_account_id != "" && var.cost_budget_amount > 0 ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "Retikon ${var.env} cost anomaly"

  budget_filter {
    projects = ["projects/${data.google_project.project.number}"]
  }

  amount {
    specified_amount {
      currency_code = var.cost_budget_currency
      units         = tostring(var.cost_budget_amount)
    }
  }

  dynamic "threshold_rules" {
    for_each = var.cost_budget_thresholds
    content {
      threshold_percent = threshold_rules.value
    }
  }

  all_updates_rule {
    monitoring_notification_channels = local.budget_notification_channels
    disable_default_iam_recipients   = true
  }
}

resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.alert_notification_emails)

  display_name = "Retikon Alerts - ${each.value}"
  type         = "email"

  labels = {
    email_address = each.value
  }
}

locals {
  ingest_stage_metric_extractors = {
    decode_ms         = "EXTRACT(jsonPayload.stage_timings_ms.decode_ms)"
    embed_text_ms     = "EXTRACT(jsonPayload.stage_timings_ms.embed_text_ms)"
    embed_image_ms    = "EXTRACT(jsonPayload.stage_timings_ms.embed_image_ms)"
    embed_audio_ms    = "EXTRACT(jsonPayload.stage_timings_ms.embed_audio_ms)"
    transcribe_ms     = "EXTRACT(jsonPayload.stage_timings_ms.transcribe_ms)"
    write_parquet_ms  = "EXTRACT(jsonPayload.stage_timings_ms.write_parquet_ms)"
    write_manifest_ms = "EXTRACT(jsonPayload.stage_timings_ms.write_manifest_ms)"
  }
}

resource "google_logging_metric" "ingest_queue_wait_ms" {
  name   = "retikon_ingest_queue_wait_ms"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.service=\"retikon-ingestion\" AND jsonPayload.queue_wait_ms>0"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"

    labels {
      key         = "modality"
      value_type  = "STRING"
      description = "Ingest modality"
    }
  }

  value_extractor = "EXTRACT(jsonPayload.queue_wait_ms)"
  label_extractors = {
    modality = "EXTRACT(jsonPayload.modality)"
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 1
    }
  }
}

resource "google_logging_metric" "ingest_stage_timings_ms" {
  for_each = local.ingest_stage_metric_extractors

  name   = "retikon_ingest_stage_${each.key}"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.service=\"retikon-ingestion\" AND jsonPayload.stage_timings_ms.${each.key}>=0"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"

    labels {
      key         = "modality"
      value_type  = "STRING"
      description = "Ingest modality"
    }
  }

  value_extractor = each.value
  label_extractors = {
    modality = "EXTRACT(jsonPayload.modality)"
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 1
    }
  }
}

resource "google_logging_metric" "index_queue_length" {
  name   = "retikon_index_queue_length"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.service=\"retikon-query\" AND jsonPayload.index_queue_length>=0"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "1"
  }

  value_extractor = "EXTRACT(jsonPayload.index_queue_length)"

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 1
    }
  }
}

resource "google_logging_metric" "ingest_queue_depth_backlog" {
  name   = "retikon_ingest_queue_depth_backlog"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.service=\"retikon-ingestion\" AND jsonPayload.queue_depth_backlog>=0"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "1"

    labels {
      key         = "modality"
      value_type  = "STRING"
      description = "Ingest modality"
    }
  }

  value_extractor = "EXTRACT(jsonPayload.queue_depth_backlog)"
  label_extractors = {
    modality = "EXTRACT(jsonPayload.modality)"
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 1
    }
  }
}

resource "google_monitoring_dashboard" "ops" {
  dashboard_json = jsonencode(
    {
      displayName = var.monitoring_dashboard_name
      mosaicLayout = {
        columns = 12
        tiles = [
          {
            xPos   = 0
            yPos   = 0
            width  = 4
            height = 4
            widget = {
              title = "Ingestion 5xx rate (req/s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
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
              title = "Query latency p50/p95/p99 (s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "p50"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_50"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "p95"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "p99"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_99"
                          crossSeriesReducer = "REDUCE_MAX"
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
              title = "DLQ backlog"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.ingest_dlq_subscription_name}\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                              perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
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
          },
          {
            xPos   = 0
            yPos   = 4
            width  = 6
            height = 4
            widget = {
              title = "Query request rate by code class (req/s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "2xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"2xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "4xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"4xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "5xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
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
            xPos   = 6
            yPos   = 4
            width  = 6
            height = 4
            widget = {
              title = "Ingest request rate by code class (req/s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "2xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"2xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "4xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"4xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "5xx"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_RATE"
                          crossSeriesReducer = "REDUCE_SUM"
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
            xPos   = 0
            yPos   = 8
            width  = 6
            height = 4
            widget = {
              title = "Ingest latency p50/p95/p99 (s)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "p50"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_50"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "p95"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "p99"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/request_latencies\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_99"
                          crossSeriesReducer = "REDUCE_MAX"
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
            xPos   = 6
            yPos   = 8
            width  = 6
            height = 4
            widget = {
              title = "Workflow queue backlog"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.workflow_queue_subscription_name}\" AND metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MAX"
                          crossSeriesReducer = "REDUCE_MAX"
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
          },
          {
            xPos   = 0
            yPos   = 12
            width  = 6
            height = 4
            widget = {
              title = "CPU utilization (query + ingest)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "query"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/container/cpu/utilizations\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MEAN"
                          crossSeriesReducer = "REDUCE_MEAN"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "ingest"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/container/cpu/utilizations\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MEAN"
                          crossSeriesReducer = "REDUCE_MEAN"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "utilization"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 6
            yPos   = 12
            width  = 6
            height = 4
            widget = {
              title = "Memory utilization (query + ingest)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "query"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/container/memory/utilizations\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MEAN"
                          crossSeriesReducer = "REDUCE_MEAN"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "ingest"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/container/memory/utilizations\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MEAN"
                          crossSeriesReducer = "REDUCE_MEAN"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "utilization"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 0
            yPos   = 16
            width  = 6
            height = 4
            widget = {
              title = "Ephemeral disk (tmpfs) usage (query + ingest)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "query"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.query.name}\" AND metric.type=\"run.googleapis.com/container/memory/tmpfs_usage\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MAX"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "ingest"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_service.ingestion.name}\" AND metric.type=\"run.googleapis.com/container/memory/tmpfs_usage\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MAX"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "bytes"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 0
            yPos   = 20
            width  = 6
            height = 4
            widget = {
              title = "Ingest queue wait p50/p95 (ms)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "$${metric.label.modality} p50"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_queue_wait_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_50"
                          crossSeriesReducer = "REDUCE_NONE"
                          groupByFields      = ["metric.label.modality"]
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "$${metric.label.modality} p95"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_queue_wait_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_NONE"
                          groupByFields      = ["metric.label.modality"]
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "milliseconds"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 6
            yPos   = 20
            width  = 6
            height = 4
            widget = {
              title = "Ingest queue depth by modality"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "$${metric.label.modality}"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_queue_depth_backlog\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_MAX"
                          crossSeriesReducer = "REDUCE_NONE"
                          groupByFields      = ["metric.label.modality"]
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
          },
          {
            xPos   = 0
            yPos   = 24
            width  = 6
            height = 4
            widget = {
              title = "Ingest stage timings p95 (ms)"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    legendTemplate = "decode_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_decode_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "embed_text_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_text_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "embed_image_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_image_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "embed_audio_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_embed_audio_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "transcribe_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_transcribe_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "write_parquet_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_write_parquet_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  },
                  {
                    plotType = "LINE"
                    legendTemplate = "write_manifest_ms"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_ingest_stage_write_manifest_ms\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "milliseconds"
                  scale = "LINEAR"
                }
              }
            }
          },
          {
            xPos   = 6
            yPos   = 24
            width  = 6
            height = 4
            widget = {
              title = "Index queue length p95"
              xyChart = {
                dataSets = [
                  {
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = "metric.type=\"logging.googleapis.com/user/retikon_index_queue_length\""
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = "ALIGN_PERCENTILE_95"
                          crossSeriesReducer = "REDUCE_MAX"
                        }
                      }
                    }
                  }
                ]
                yAxis = {
                  label = "manifests"
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
        image   = var.smoke_image
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
