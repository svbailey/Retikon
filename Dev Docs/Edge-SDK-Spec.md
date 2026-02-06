# Retikon Edge SDK Spec (Open Source, GPU-Agnostic)

Status: Draft
Owner: Product + Eng
Date: 2026-01-26

## 1) Summary

This document specifies an open-source Retikon Edge SDK that performs live
video analytics (counts, detections, tracking, alerts) on CPU by default with
optional accelerator plugins, and emits standardized events and evidence clips
to Retikon Cloud for graph ingestion and retrieval.

The SDK is vendor-neutral (not tied to NVIDIA or any single GPU) and uses a
contract-first integration model based on the Retikon event envelope in
`Dev Docs/Developer-Integration-Guide.md`.

## 2) Goals

- CPU-first, GPU-optional runtime for live video analytics.
- Stable event contract for cloud integration (no breaking changes).
- Modular pipeline: ingest, decode, inference, tracking, analytics, evidence.
- Edge resilience: offline spooling, retries, and deterministic timestamps.
- Clear separation between OSS Edge SDK and Retikon Pro cloud services.

## 3) Non-Goals

- No requirement to match GPU-accelerated performance of DeepStream.
- No cloud-specific dependencies in the Edge SDK (cloud-agnostic by default).
- No changes to existing Retikon Core behavior without explicit approval.

## 4) Assumptions

- Retikon Cloud persists graph data in GraphAr under `retikon_v2/`.
- IDs are UUIDv4 strings across vertices and edges.
- Schema evolution is additive only.
- Event envelope is the canonical interface for cross-service integration.

## 5) Architecture Overview

### 5.1 High-Level Flow

1) Ingest streams (RTSP/camera/file) on edge.
2) Decode frames (CPU baseline, optional hardware decode).
3) Preprocess and run inference (CPU baseline, optional accelerator).
4) Track objects and compute analytics (counts, zones, dwell, line crossing).
5) Emit event envelopes to Retikon Cloud.
6) When triggered, cut evidence clips and upload to object storage.
7) Retikon Cloud ingests events and evidence into GraphAr for retrieval.

### 5.2 Edge Runtime Modules

- Ingest + Decode
- Pipeline Graph Runtime
- Preprocess + Inference
- Tracking
- Analytics
- Evidence Capture
- Event Emitter
- Local Spool + Retry
- Config + Health + Metrics

### 5.3 Cloud Integration Modules (Pro)

- Edge Event Ingest API
- Evidence Upload API (signed URLs)
- GraphAr Writer for new edge artifacts
- Control Plane (device registry, policy, model rollout)

## 6) Edge SDK Module Spec

### 6.1 Ingest + Decode

Inputs:
- RTSP, file, USB/CSI camera.
- Optional multi-profile sources (main + sub streams).

Baseline:
- CPU decode via FFmpeg or GStreamer.

Optional plugins:
- NVDEC, VAAPI, QSV, V4L2.

Sub-stream strategy:
- Use low-res sub-streams for inference, tracking, and analytics.
- Use high-res main streams only for evidence clip extraction.
- If only one stream is available, reuse it for both analytics and evidence.

Outputs:
- Frame stream with timestamps (ms), frame index, and stream id.
- Stream profile id (main or sub) when available.

### 6.2 Pipeline Graph Runtime

Responsibilities:
- DAG scheduling, backpressure, batching, and deterministic timebase.
- Per-stream isolation with shared batching when configured.

Configuration:
- `batch_size`, `max_latency_ms`, `drop_policy`.

Timebase requirements:
- Use NTP or PTP for clock synchronization.
- Track `clock_skew_ms` and include it in health metrics.
- Mark the device not-ready when clock skew exceeds threshold.
- Ensure per-stream timestamps are monotonic and mapped to wall clock.

### 6.3 Preprocess + Inference

Backend interface:
- Input: list of frames or tensors.
- Output: list of detections with bounding boxes, labels, confidences.

Baseline backend:
- ONNX Runtime (CPU).

Optional backends:
- OpenVINO, TensorRT, TFLite, ROCm.

### 6.4 Tracking

Baseline:
- SORT or ByteTrack.

Output:
- Stable object ids with track state per frame.

### 6.5 Analytics

Supported:
- Count by class, direction (line crossing), zone occupancy, dwell time.

Outputs:
- Aggregated counts per time window.
- Rule-triggered alerts.

### 6.6 Evidence Capture

Mechanism:
- Ring buffer of encoded frames.
- Clip extraction on alert trigger.
- Maintain a passive main-stream bitstream buffer for zero-transcode clip
  extraction to minimize CPU load.

Defaults:
- `pre_ms=5000`, `post_ms=5000`, `max_clip_ms=15000`.
- Event metadata must include `pre_ms` and `post_ms` for evidence clips.

### 6.7 Event Emitter

Transports:
- HTTP, gRPC, Kafka, Pub/Sub (adapter-based).

Payload:
- Retikon event envelope (see Section 7).

### 6.8 Local Spool + Retry

Requirements:
- Durable local queue for offline operation.
- Exponential backoff with jitter.
- Configurable max disk usage and TTL.
- Wear-leveling policy for low-endurance storage (metadata-only spool when needed).

Spool modes:
- `metadata_only` for low-endurance storage or constrained devices.
- `full` for environments that can safely buffer evidence metadata and clips.

### 6.9 Config + Health + Metrics

Endpoints:
- `GET /healthz` (liveness)
- `GET /readyz` (readiness)
- `GET /metrics` (Prometheus-compatible)

Health checks:
- NTP or PTP sync status and `clock_skew_ms`.
- Reject event emission when clock skew exceeds the configured threshold.

Logging:
- JSON logs with `service`, `env`, `request_id`, `correlation_id`,
  `duration_ms`, `version`.

Error classes:
- `RecoverableError`, `PermanentError`, `AuthError`, `ValidationError`.

## 7) Data Contract: Event Envelope

Canonical format in `Dev Docs/Developer-Integration-Guide.md`.
All analytics events should include `metadata.model` with `model_id`,
`model_version`, and `runtime` to avoid label drift and aid audits.

### 7.1 Example: Counts (custom)

```json
{
  "event_id": "uuid-v4",
  "schema_version": "1",
  "event_type": "custom",
  "timestamp": "2026-01-26T18:22:11Z",
  "source": {
    "org_id": "org_123",
    "project_id": "proj_123",
    "site_id": "junction_17",
    "stream_id": "cam_0007",
    "device_id": "edge_004"
  },
  "media": {
    "media_asset_id": "uuid-v4",
    "media_type": "video",
    "uri": "gs://bucket/raw/videos/cam_0007/stream.mp4",
    "timestamp_ms": 120000
  },
  "metadata": {
    "window_ms": 60000,
    "counts": {
      "northbound": { "car": 42, "truck": 3 },
      "eastbound": { "car": 55 },
      "pedestrian_crossing": 12
    },
    "line_ids": {
      "northbound": "line_a",
      "eastbound": "line_b",
      "pedestrian_crossing": "zone_p1"
    },
    "model": {
      "model_id": "retikon-yolo-v11-small",
      "model_version": "v2.4.0",
      "runtime": "openvino"
    }
  }
}
```

### 7.2 Example: Evidence Clip (alert)

```json
{
  "event_id": "uuid-v4",
  "schema_version": "1",
  "event_type": "alert",
  "timestamp": "2026-01-26T18:23:05Z",
  "source": {
    "org_id": "org_123",
    "project_id": "proj_123",
    "site_id": "junction_17",
    "stream_id": "cam_0007",
    "device_id": "edge_004"
  },
  "media": {
    "media_asset_id": "uuid-v4",
    "media_type": "video",
    "uri": "gs://bucket/retikon_v2/clips/police_car_001.mp4",
    "timestamp_ms": 123000,
    "thumbnail_uri": "gs://bucket/retikon_v2/thumbnails/police_car_001.jpg"
  },
  "labels": [
    { "name": "police_car", "confidence": 0.93 }
  ],
  "metadata": {
    "pre_ms": 5000,
    "post_ms": 5000,
    "clip_start_ms": 118000,
    "clip_end_ms": 128000,
    "rule_id": "police_car_clip",
    "model": {
      "model_id": "retikon-yolo-v11-small",
      "model_version": "v2.4.0",
      "runtime": "tensorrt"
    }
  }
}
```

## 8) Cloud Interaction (Retikon Pro)

### 8.1 Device Provisioning

Flow:
- Device claims `device_id` with a one-time code.
- Cloud returns a short-lived JWT and refresh policy.

### 8.2 Event Ingest API (Proposed)

- `POST /edge/events`
- Validates event envelope and schema_version.
- Rejects events when `clock_skew_ms` exceeds configured threshold.
- Writes GraphAr vertices/edges and evidence references.

### 8.3 Evidence Upload API (Proposed)

- `POST /edge/evidence/upload-url`
- Returns signed URL for clip upload.
- Edge uploads clip, then sends an `alert` event with the URI.

### 8.4 Config + Policy API (Proposed)

- `GET /edge/config`
- `POST /edge/heartbeat`
- `POST /edge/logs`

## 9) GraphAr Mapping (Additive Only)

Proposed new entities (additive):

Vertices:
- `EdgeDevice`
- `Detection`
- `Track`
- `AnalyticsWindow`
- `EvidenceClip`

Edges:
- `ObservedIn` (Detection -> MediaAsset)
- `MemberOf` (Detection -> Track)
- `AggregatedIn` (Detection -> AnalyticsWindow)
- `DerivedFrom` (EvidenceClip -> MediaAsset)

Constraints:
- UUIDv4 IDs for all vertices and edges.
- Layout: `vertices/<Type>/{core,text,vector}/part-<uuid>.parquet`
- Layout: `edges/<Type>/adj_list/part-<uuid>.parquet`
- Schema evolution is additive only.
- Queries spanning versions use `union_by_name=true`.

## 10) Model Lifecycle (Data Factory -> Edge)

### 10.1 Export Format

- Primary: ONNX plus `model-manifest.json`.
- The manifest is the translation layer that tells the edge how to compile or
  load the model for local hardware.
- Manifests should include per-artifact checksums and may be signed.

`model-manifest.json` example:

```json
{
  "manifest_version": "1.0",
  "model_info": {
    "model_id": "retikon-yolo-v11-small",
    "version": "v2.4.0",
    "task_type": "object_detection",
    "framework": "onnx"
  },
  "deployment_targets": [
    {
      "runtime": "tensorrt",
      "priority": 1,
      "artifact_url": "https://storage.retikon.ai/models/v2.4/yolo_v11.engine",
      "artifact_sha256": "sha256:example",
      "engine_config": {
        "device_id": 0,
        "precision": "fp16",
        "workspace_size_mb": 1024
      }
    },
    {
      "runtime": "openvino",
      "priority": 2,
      "artifact_url": "https://storage.retikon.ai/models/v2.4/yolo_v11_openvino.xml",
      "artifact_sha256": "sha256:example",
      "engine_config": {
        "device_type": "CPU",
        "num_streams": "auto"
      }
    }
  ],
  "inference_config": {
    "input": {
      "tensor_name": "images",
      "shape": [1, 3, 640, 640],
      "format": "NCHW",
      "preprocessing": {
        "scale": 0.00392156,
        "mean": [0, 0, 0],
        "color_format": "RGB"
      }
    },
    "output": {
      "tensor_name": "output0",
      "postprocessing": {
        "nms_threshold": 0.45,
        "confidence_threshold": 0.25,
        "labels": ["person", "bicycle", "car", "motorcycle", "police_car"]
      }
    }
  }
}
```

### 10.2 Registry and Deployment

- Versioned artifacts in object storage.
- Edge agent downloads and verifies checksum.
- Staged rollout with rollback on failure.
- Hardware detection selects the highest priority `deployment_targets` runtime.
- If no runtime is available, fall back to CPU (ONNX Runtime) or mark the model
  unavailable.
- Selected `model_id`, `version`, and `runtime` must be included in event
  metadata for traceability.

### 10.3 Post-Processing Contract

- Standard mapping to `labels[]`, `bbox`, and `confidence`.
- Label arrays map class indices to stable strings in the event envelope.
- Optional class remapping rules remain additive only.

### 10.4 Hot Swap

- Edge receives a manifest update signal (WebSocket, MQTT, or polling).
- Download new artifacts in the background.
- Warm up the new engine, flush current batch, then swap in milliseconds.
- On failure, automatically roll back to the previous model.

## 11) Security and Privacy

- Auth: JWT or mTLS per device, rotated automatically.
- No raw frames uploaded unless policy allows.
- Evidence clips are limited to alerts and configured rules.
- Signed event payloads and strict schema validation.
- Avoid logging sensitive data (tokens, raw content).

## 12) Performance Targets (Guidance)

- Default: 1-2 streams at 720p/15fps on CPU.
- Latency SLO (baseline): p95 < 400 ms for detection events.
- Configurable per deployment.
- For higher stream counts, prefer sub-stream inference with main-stream evidence.

## 13) Testing and Acceptance

### 13.1 Edge SDK Tests

- Unit: pipeline, inference adapter, tracker, analytics rules.
- Integration: RTSP ingest + event emission.
- Contract: golden event envelope validation.

### 13.2 Cloud Tests

- Validate GraphAr schema writes for new entities.
- Ensure `union_by_name=true` for cross-version queries.

### 13.3 Acceptance Criteria

- CPU baseline runs 1 stream end-to-end with counts + alerts.
- Evidence clip upload + graph ingestion validated.
- Offline spool retries without data loss.

## 14) Rollout Strategy

Phase 1:
- Minimal pipeline (CPU inference, counts, alerts, events).

Phase 2:
- Evidence clipper + signed upload.

Phase 3:
- Optional accelerator backends.

Phase 4:
- Fleet management, advanced analytics, policy controls.

## 15) Open Questions

- Which graph schema names should be standardized for edge analytics?
- Target latency SLO per industry (retail, traffic, safety)?
- Which inference backends are required for v1?
