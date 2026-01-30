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

## 10) SDK Quickstarts

### Python
```
from retikon_sdk import RetikonClient

client = RetikonClient(api_key="...")
results = client.query(query_text="forklift in zone 3")
print(results["results"])
```

### JavaScript
```
import { RetikonClient } from "@retikon/core-sdk";

const client = new RetikonClient({ apiKey: "..." });
const results = await client.query({ queryText: "forklift in zone 3" });
console.log(results.results);
```

## 11) Error Handling and Idempotency
- All events include `event_id` for dedupe.
- Webhooks retry on non-2xx.
- Queue consumers should be idempotent and store last processed ID.

## 12) Security Best Practices
- Validate webhook signatures.
- Use scoped API keys.
- Do not log raw media payloads or API keys.
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
- Ensure `QUERY_API_KEY` is set for non-dev environments.

## 16) Glossary
- MediaAsset: root vertex for an ingested file.
- DocChunk: a chunk of extracted text.
- Transcript: a speech segment from audio/video.
- ImageAsset: image or keyframe from video.
- AudioClip: audio embedding per asset.
