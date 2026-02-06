# Retikon Developer Integration Guide

Status: Draft
Owner: Product + Eng
Date: 2026-01-26

This guide explains how developers consume Retikon data and integrate it into
existing platforms and workflows. It includes event schemas, delivery options,
export patterns, query examples, and recipes.

## 1) How Retikon Data Is Used
Retikon outputs are typically consumed in four ways:

1. Real-time actions (event-driven)
   - Webhooks or queues trigger downstream services immediately.
2. Interactive search and retrieval
   - Query API for text/image/audio similarity or keyword search.
3. Batch analytics
   - Export Parquet/CSV/JSON to warehouses or data lakes.
4. Graph exploration
   - Explore node/edge relationships for investigations or enrichment.

## 2) Consumption Modes

### A) Webhooks (HTTP)
Use webhooks for real-time notifications with lightweight integration.

### B) Queues (Pub/Sub, Kafka)
Use queues for scale, retries, and decoupled processing.

### C) Exports (Parquet/CSV/JSON)
Use exports for analytics, compliance, and BI workflows.

### D) Graph Queries
Use graph outputs for entity relationships and investigations.

## 3) Standard Event Envelope (All Modalities)
All event payloads should use the same envelope across video, audio, image,
and document pipelines. This keeps developer integration stable and predictable.

### Event Envelope
```json
{
  "event_id": "uuid-v4",
  "schema_version": "1",
  "event_type": "detection|transcript|embedding|alert|custom",
  "timestamp": "2026-01-26T18:22:11Z",
  "source": {
    "org_id": "org_123",
    "project_id": "proj_123",
    "site_id": "site_01",
    "stream_id": "cam_0007",
    "device_id": "edge_004"
  },
  "media": {
    "media_asset_id": "uuid-v4",
    "media_type": "video|audio|image|document",
    "uri": "gs://bucket/raw/videos/cam_0007/clip.mp4",
    "timestamp_ms": 120000,
    "thumbnail_uri": "gs://bucket/retikon_v2/thumbnails/..."
  },
  "labels": [
    {"name": "person", "confidence": 0.97},
    {"name": "car", "confidence": 0.84}
  ],
  "transcript": {
    "text": "",
    "start_ms": 119000,
    "end_ms": 122000,
    "language": "en"
  },
  "embeddings": {
    "text_vector": "optional",
    "clip_vector": "optional",
    "clap_vector": "optional"
  },
  "metadata": {
    "tags": ["parking-lot", "night"],
    "source_app": "my-app",
    "custom": {"shift": "B"}
  }
}
```

Notes:
- All IDs are UUIDv4.
- `schema_version` is required for compatibility.
- `embeddings` may be omitted in webhook payloads; provide references instead.
- Core local mode returns `file://` (or absolute) paths for asset URIs, while
  cloud deployments return `gs://`, `s3://`, or equivalent schemes.

## 4) Webhook Delivery

### Signing
- Each webhook request includes a signature header, e.g. `x-retikon-signature`.
- Signature is HMAC-SHA256 over `timestamp + "." + body`.
- Include a timestamp header to prevent replay.

### Headers (example)
```
X-Retikon-Timestamp: 1737915731
X-Retikon-Signature: v1=abcdef0123...
```

### Retry Policy
- Exponential backoff with jitter.
- Retry on non-2xx responses.
- Max retries configurable (default 10).
- Delivery logs available in Pro UI.

## 5) Queue Delivery (Pub/Sub, Kafka)
- Event payload is the same JSON envelope as webhooks.
- Add attributes for tenant and modality for routing.

Example attributes:
```
org_id=org_123
project_id=proj_123
modality=video
```

## 6) Export Patterns

Exports are available through the audit service in Pro:
- `GET /audit/export` for audit logs
- `GET /access/export` for access logs

There is no `retikon export` CLI command or `/export` endpoint in the current
codebase.

## 7) Query API Usage

### Text Query
```
POST /query
{
  "query_text": "red truck near loading dock",
  "top_k": 10
}
```

### Image Query (base64)
```
POST /query
{
  "image_base64": "<base64>"
}
```

### Combined Query (Pro)
```
POST /query
{
  "query_text": "person with backpack",
  "image_base64": "<base64>",
  "top_k": 10
}
```

### Demo + Evidence APIs (Staging)
These endpoints support the sales demo experience and BYO uploads in staging.

#### List curated demo datasets
```
GET /demo/datasets
```
Configure datasets by setting one of:
- `DEMO_DATASETS_PATH` pointing to a JSON file (see `Dev Docs/demo-datasets.sample.json`)
- `DEMO_DATASETS_JSON` containing the JSON payload directly

Response:
```
{
  "datasets": [
    {
      "id": "safety-video",
      "title": "Safety Training Video",
      "modality": "video",
      "summary": "Keyframes, transcript highlights, and linked incidents.",
      "sample_query": "Where are the highest risk safety moments?",
      "preview_uri": null,
      "source_uri": null
    }
  ]
}
```

#### Fetch evidence for a result
```
GET /evidence?uri=gs://bucket/raw/videos/sample.mp4
```
Response:
```
{
  "uri": "gs://bucket/raw/videos/sample.mp4",
  "signed_uri": "https://storage.googleapis.com/...",
  "media_asset_id": null,
  "frames": [],
  "transcript_snippets": [],
  "doc_snippets": [],
  "graph_links": [],
  "status": "pending"
}
```

Signed URL verification:
- Run `python scripts/verify_signed_url.py --uri gs://bucket/path` from a staging
  environment to confirm the service account can sign GCS URLs.
- The signing service account must have `iam.serviceAccountTokenCreator` and
  storage read access to the target bucket.

#### Check ingest status for a raw object
```
GET /ingest/status?uri=gs://bucket/raw/videos/sample.mp4
```
Note: If you are calling through the API Gateway hostname, prefer
`GET /dev/ingest-status?uri=...` (same payload) because ingestion ingress is
internal in staging.

Response:
```
{
  "status": "PROCESSING",
  "uri": "gs://bucket/raw/videos/sample.mp4",
  "bucket": "bucket",
  "name": "raw/videos/sample.mp4",
  "generation": "1",
  "doc_id": "<sha256>",
  "firestore": {
    "status": "PROCESSING",
    "manifest_uri": "gs://bucket/retikon_v2/manifests/..."
  }
}
```

## 8) Graph Data Usage
Retikon writes GraphAr Parquet data under `retikon_v2/`.
Developers can query directly with DuckDB or Spark.

DuckDB example:
```
INSTALL httpfs; LOAD httpfs;
CREATE VIEW doc_chunks AS
SELECT * FROM read_parquet('gs://bucket/retikon_v2/vertices/DocChunk/*/*.parquet');

SELECT * FROM doc_chunks LIMIT 5;
```

Graph exploration:
- Use DerivedFrom edges to link chunks, transcripts, and keyframes to MediaAsset.
- Use NextKeyframe and NextTranscript to walk sequences.

## 9) Recipes

### Recipe 1: Send alerts to Slack
- Webhook target points to a small Slack relay service.
- Use event labels and confidence to filter.

### Recipe 2: Trigger a ticket in Jira
- Webhook target hits Jira API with event payload summary.

### Recipe 3: Stream detections into Kafka
- Enable Kafka connector (Pro).
- Consumers enrich and store detections in OLAP.

### Recipe 4: Export daily Parquet to BigQuery
- Schedule export job daily.
- Load into partitioned BigQuery tables.

### Recipe 5: Build a live dashboard
- Use queue stream to drive WebSocket updates.
- Use Data Explorer queries for drill-down.

### Recipe 6: Incident investigation
- Query by text or image.
- Open Graph Explorer to inspect related events.

## 10) Control-Plane Storage (Pro)

- Set `CONTROL_PLANE_STORE=firestore` to use the Firestore-backed control plane.
- Set `CONTROL_PLANE_COLLECTION_PREFIX` (e.g. `staging_`) to isolate environments.
- JSON store is legacy and supported for local/dev only.
- During migration (optional), use `CONTROL_PLANE_READ_MODE=fallback` for Firestore
  primary with JSON fallback and `CONTROL_PLANE_WRITE_MODE=dual`.
- After cutover (staging/prod), use `CONTROL_PLANE_READ_MODE=primary`,
  `CONTROL_PLANE_WRITE_MODE=single`, and `CONTROL_PLANE_FALLBACK_ON_EMPTY=false`.
- Backfill JSON → Firestore with `scripts/firestore_backfill.py`.
- Archive legacy JSON control blobs (e.g. move `control/*.json` to
  `control_archive/<timestamp>/` in the graph bucket).
- Usage metering always writes GraphAr `UsageEvent` parquet. Set
  `METERING_FIRESTORE_ENABLED=1` to also write Firestore `usage_events`
  (optional prefix via `METERING_COLLECTION_PREFIX`).

## 10) Authentication (JWT everywhere)

Production default:
- API Gateway enforces JWT for all user-facing traffic.
- Services validate JWTs directly for defense-in-depth.

Gateway coverage (user-facing):
- `/query`, `/workflows`, `/chaos`, `/audit`, `/access`
- `/privacy`, `/fleet`, `/data-factory`
- `/webhooks`, `/alerts`, `/events`
- `/dev`, `/edge`

Validation checklist (gateway):
- No `Authorization` header returns 401 on `/query`.
- No `Authorization` header returns 401 on `/privacy/policies`.
- No `Authorization` header returns 401 on `/dev/ingest-status`.
- No `Authorization` header returns 401 on `/edge/config`.
- No `Authorization` header returns 401 on `/webhooks`.

### JWT claims contract
Locked for v3.1: claim names and required claims are fixed. Override only for
local/dev testing.

Required in production (`AUTH_REQUIRED_CLAIMS` default):
- `sub` (string, user or service principal id)
- `iss` (issuer)
- `aud` (audience)
- `exp` (epoch seconds)
- `iat` (epoch seconds)
- `org_id` (tenant)

Recommended:
- `email` (string)
- `roles` (array of strings, e.g. `admin|operator|ingestor|reader`)
- `groups` (array of strings)
- `site_id` (string, optional)
- `stream_id` (string, optional)

Example JWT payload:
```json
{
  "sub": "user-123",
  "email": "user@example.com",
  "roles": ["reader"],
  "groups": ["analytics"],
  "org_id": "org-1",
  "site_id": "site-1",
  "stream_id": "stream-3",
  "iss": "https://issuer.example",
  "aud": "retikon",
  "iat": 1737915731,
  "exp": 1737919331
}
```

### Header usage
```
Authorization: Bearer <JWT>
```
When calls are routed through API Gateway, the gateway may forward the JWT
in proxy headers or attach user claims. Enable `AUTH_GATEWAY_USERINFO=1` to
accept `X-Forwarded-Authorization` / `X-Original-Authorization` or
`X-Endpoint-API-UserInfo` from the gateway.

### Local dev JWTs
- Set `AUTH_JWT_HS256_SECRET` and `AUTH_JWT_ALGORITHMS=HS256`.
- Mint an HS256 JWT and pass it via `Authorization: Bearer <JWT>`.

### Internal invokers (Cloud Run IAM)
- Non-gateway services should be locked to explicit service accounts (no `allUsers`).
- Pub/Sub push and Cloud Scheduler should use OIDC tokens with a service account.
- Grant `roles/iam.serviceAccountTokenCreator` to the Pub/Sub and Scheduler service agents for that service account.
- If you rely on GCP OIDC tokens, allow their issuer/audience in `AUTH_ISSUER`/`AUTH_AUDIENCE` (comma-separated).
- Ensure internal OIDC tokens include required claims (e.g., `org_id`) or relax
  `AUTH_REQUIRED_CLAIMS` for internal-only services.

### Mapping to Retikon auth
- `roles` map to RBAC roles; `AUTH_ADMIN_ROLES` controls admin elevation.
- `groups` can be used for ABAC policies; `AUTH_ADMIN_GROUPS` can elevate admin.
- `org_id/site_id/stream_id` map to tenant scope.

### Auth env vars (summary)
- `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_JWKS_URI`
- `AUTH_REQUIRED_CLAIMS` (comma-separated)
- `AUTH_CLAIM_SUB`, `AUTH_CLAIM_EMAIL`, `AUTH_CLAIM_ROLES`, `AUTH_CLAIM_GROUPS`
- `AUTH_CLAIM_ORG_ID`, `AUTH_CLAIM_SITE_ID`, `AUTH_CLAIM_STREAM_ID`
- `AUTH_ADMIN_ROLES`, `AUTH_ADMIN_GROUPS`, `AUTH_JWT_LEEWAY_SECONDS`
- `AUTH_GATEWAY_USERINFO=1` (trust gateway headers for JWT user identity)

### Google Identity Platform defaults
For Firebase/Identity Platform ID tokens:
- `AUTH_ISSUER = https://securetoken.google.com/<PROJECT_ID>`
- `AUTH_AUDIENCE = <PROJECT_ID>`
- `AUTH_JWKS_URI = https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com`

Repo defaults:
- `terraform.tfvars` and `terraform.tfvars.staging` already set these values for
  the dev/staging project. Set prod explicitly.

## 10) SDK Quickstarts

### Python
```
from retikon_sdk import RetikonClient

client = RetikonClient(auth_token="JWT")
results = client.query(query_text="forklift in zone 3")
print(results["results"])
```

### JavaScript
```
import { RetikonClient } from "@retikon/core-sdk";

const client = new RetikonClient({ authToken: "JWT" });
const results = await client.query({ queryText: "forklift in zone 3" });
console.log(results.results);
```

## 11) Error Handling and Idempotency
- All events include `event_id` for dedupe.
- Webhooks retry on non-2xx.
- Queue consumers should be idempotent and store last processed ID.

## 12) Security Best Practices
- Validate webhook signatures.
- Do not log raw media payloads or JWTs.
- Rotate webhook secrets regularly.

## 13) Performance Tips
- Use incremental exports over full exports.
- Batch webhook handling and offload heavy work to queues.
- Use DuckDB snapshots for fast query.

## 14) Versioning and Compatibility
- `schema_version` in every event and GraphAr record.
- Additive schema evolution only.
- Use `union_by_name=true` in DuckDB reads.

## 15) Troubleshooting
- Check DLQ backlog for ingestion failures.
- Validate content-type + extension mismatches.

## 16) Glossary
- MediaAsset: root vertex for an ingested file.
- DocChunk: a chunk of extracted text.
- Transcript: a speech segment from audio/video.
- ImageAsset: image or keyframe from video.
- AudioClip: audio embedding per asset.
