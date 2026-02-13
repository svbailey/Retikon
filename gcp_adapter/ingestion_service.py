import base64
import binascii
import io
import json
import os
import resource
import threading
import time
import uuid
import wave
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import fsspec
import requests  # type: ignore[import-untyped]
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from fastapi import FastAPI, Header, HTTPException, Request
from google.cloud import firestore
from google.cloud import storage
from pydantic import BaseModel

from gcp_adapter.auth import authorize_internal_service_account, authorize_request
from gcp_adapter.dlq_pubsub import PubSubDlqPublisher
from gcp_adapter.eventarc import parse_cloudevent
from gcp_adapter.idempotency_firestore import (
    FirestoreIdempotency,
    find_completed_by_checksum,
    find_completed_by_content_hash,
    resolve_checksum,
    resolve_content_hash_scope,
    resolve_scope_key,
    update_object_metadata,
)
from gcp_adapter.metering import record_usage
from gcp_adapter.queue_monitor import load_queue_monitor
from gcp_adapter.queue_pubsub import PubSubPublisher
from gcp_adapter.stores import abac_allowed, is_action_allowed
from retikon_core.audit import record_audit_log
from retikon_core.auth import ACTION_INGEST, AuthContext
from retikon_core.config import Config, get_config
from retikon_core.embeddings import get_audio_embedder, get_text_embedder
from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import PermanentError, RecoverableError, ValidationError
from retikon_core.ingestion import process_event
from retikon_core.ingestion.download import cleanup_tmp, download_to_tmp
from retikon_core.ingestion.idempotency import build_doc_id
from retikon_core.ingestion.pipelines.metrics import build_dedupe_stage_timings
from retikon_core.ingestion.rate_limit import (
    RateLimitBackendError,
    RateLimitExceeded,
    enforce_rate_limit,
)
from retikon_core.ingestion.router import pipeline_version
from retikon_core.ingestion.storage_event import StorageEvent
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    add_correlation_id_middleware,
    build_health_response,
)
from retikon_core.tenancy.types import TenantScope

SERVICE_NAME = "retikon-ingestion"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
add_correlation_id_middleware(app)

_dlq_publisher: PubSubDlqPublisher | None = None
_media_publisher: PubSubPublisher | None = None
_queue_monitor = None
_cold_start = True
_cold_start_lock = threading.Lock()


class _IngestLoadTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def increment(self, modality: str) -> dict[str, int]:
        with self._lock:
            self._counts[modality] = self._counts.get(modality, 0) + 1
            total = sum(self._counts.values())
            return {
                "inflight": self._counts[modality],
                "inflight_total": total,
            }

    def decrement(self, modality: str) -> None:
        with self._lock:
            current = self._counts.get(modality, 0)
            if current <= 1:
                self._counts.pop(modality, None)
            else:
                self._counts[modality] = current - 1


_ingest_load = _IngestLoadTracker()


@app.on_event("startup")
async def _warmup_on_startup() -> None:
    _warm_ingest_models()
    _start_queue_monitor()


class IngestResponse(BaseModel):
    status: str
    trace_id: str


class IngestStatusResponse(BaseModel):
    status: str
    uri: str
    bucket: str
    name: str
    generation: str
    doc_id: str
    firestore: dict | None = None


def _authorize_ingest(request: Request, config: Config) -> AuthContext | None:
    if _is_gcs_notification(request):
        try:
            return authorize_request(
                request=request,
                require_admin=False,
            )
        except HTTPException as exc:
            if exc.status_code == 401:
                internal = authorize_internal_service_account(request)
                if internal:
                    return internal
                return None
            raise
    try:
        return authorize_request(
            request=request,
            require_admin=False,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            internal = authorize_internal_service_account(request)
            if internal:
                return internal
        raise


def _is_gcs_notification(request: Request) -> bool:
    if request.query_params.get("__GCP_CloudEventsMode") == "GCS_NOTIFICATION":
        return True
    ce_source = request.headers.get("ce-source", "")
    ce_type = request.headers.get("ce-type", "")
    if "storage.googleapis.com" in ce_source:
        return True
    return "google.cloud.storage" in ce_type


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _raw_prefix() -> str:
    return os.getenv("RAW_PREFIX", "raw").strip("/")


def _allowed_modalities() -> set[str] | None:
    raw = os.getenv("INGEST_ALLOWED_MODALITIES", "").strip()
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _media_delegate_url() -> str | None:
    raw = os.getenv("INGEST_MEDIA_URL", "").strip()
    if not raw:
        return None
    if raw.endswith("/ingest"):
        return raw
    return raw.rstrip("/") + "/ingest"


def _media_delegate_topic() -> str | None:
    raw = os.getenv("INGEST_MEDIA_TOPIC", "").strip()
    return raw or None


def _media_delegate_modalities() -> set[str]:
    raw = os.getenv("INGEST_MEDIA_MODALITIES", "audio,video").strip()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _media_embed_delegate_url() -> str | None:
    raw = os.getenv("INGEST_MEDIA_EMBED_URL", "").strip()
    if not raw:
        return None
    if raw.endswith("/ingest"):
        return raw
    return raw.rstrip("/") + "/ingest"


def _media_embed_delegate_topic() -> str | None:
    raw = os.getenv("INGEST_MEDIA_EMBED_TOPIC", "").strip()
    return raw or None


def _media_embed_delegate_modalities() -> set[str]:
    raw = os.getenv("INGEST_MEDIA_EMBED_MODALITIES", "").strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _fetch_id_token(audience: str) -> str | None:
    env = os.getenv("ENV", "dev").lower()
    if env in {"dev", "local", "test"}:
        return None
    if audience.startswith(("http://localhost", "http://127.0.0.1")):
        return None
    request = google_requests.Request()
    return id_token.fetch_id_token(request, audience)


def _get_media_publisher() -> PubSubPublisher:
    global _media_publisher
    if _media_publisher is None:
        _media_publisher = PubSubPublisher()
    return _media_publisher


def _publish_media_ingest(
    *,
    topic: str,
    payload: dict[str, Any],
    trace_id: str,
    correlation_id: str | None,
    modality: str,
) -> IngestResponse:
    publisher = _get_media_publisher()
    attributes: dict[str, str] = {"modality": modality}
    if trace_id:
        attributes["request_id"] = trace_id
    if correlation_id:
        attributes["correlation_id"] = correlation_id
    publisher.publish_json(topic=topic, payload=payload, attributes=attributes)
    return IngestResponse(status="queued", trace_id=trace_id)


def _delegate_media_ingest(
    *,
    url: str,
    payload: dict[str, Any],
    trace_id: str,
    correlation_id: str | None,
) -> IngestResponse:
    parsed = urlparse(url)
    audience = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else url
    token = _fetch_id_token(audience)
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if trace_id:
        headers["x-request-id"] = trace_id
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 300:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = {}
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return IngestResponse(
        status=str(data.get("status", "accepted")),
        trace_id=str(data.get("trace_id", trace_id)),
    )


def _enforce_access(
    action: str,
    auth_context: AuthContext | None,
    config: Config,
) -> None:
    base_uri = config.graph_root_uri()
    if _rbac_enabled():
        if not is_action_allowed(auth_context, action, base_uri):
            raise HTTPException(status_code=403, detail="Forbidden")
    if _abac_enabled():
        if not abac_allowed(auth_context, action, base_uri):
            raise HTTPException(status_code=403, detail="Forbidden")


def _metering_enabled() -> bool:
    return os.getenv("METERING_ENABLED", "0") == "1"


def _audit_logging_enabled() -> bool:
    return os.getenv("AUDIT_LOGGING_ENABLED", "1") == "1"


def _schema_version() -> str:
    return os.getenv("SCHEMA_VERSION", "1")


def _default_scope(config: Config) -> TenantScope:
    return TenantScope(
        org_id=config.default_org_id,
        site_id=config.default_site_id,
        stream_id=config.default_stream_id,
    )


def _scope_key(scope: TenantScope | None) -> str:
    if scope is None:
        return resolve_scope_key(None, None, None)
    return resolve_scope_key(scope.org_id, scope.site_id, scope.stream_id)


def _storage_client() -> storage.Client:
    return storage.Client()


def _firestore_client() -> firestore.Client:
    return firestore.Client()


def _queue_wait_ms(bucket: str, name: str) -> float | None:
    try:
        client = _storage_client()
        blob = client.bucket(bucket).blob(name)
        blob.reload()
    except Exception as exc:
        logger.warning(
            "Queue wait lookup failed",
            extra={"bucket": bucket, "object_name": name, "error_message": str(exc)},
        )
        return None
    created_at = blob.time_created
    if created_at is None:
        return None
    now = datetime.now(timezone.utc)
    created_at = created_at.astimezone(timezone.utc)
    return round((now - created_at).total_seconds() * 1000.0, 2)


def _hydrate_storage_event(event: StorageEvent) -> StorageEvent:
    if (
        event.content_type
        and event.size is not None
        and (event.md5_hash or event.crc32c)
    ):
        return event
    try:
        blob = _storage_client().bucket(event.bucket).blob(event.name)
        blob.reload()
    except Exception as exc:
        logger.warning(
            "Failed to refresh storage metadata",
            extra={
                "bucket": event.bucket,
                "object_name": event.name,
                "error_message": str(exc),
            },
        )
        return event
    return StorageEvent(
        bucket=event.bucket,
        name=event.name,
        generation=event.generation,
        content_type=event.content_type or blob.content_type,
        size=event.size if event.size is not None else blob.size,
        md5_hash=event.md5_hash or blob.md5_hash,
        crc32c=event.crc32c or blob.crc32c,
    )


def _warmup_enabled() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("INGEST_WARMUP", default) == "1"


def _warmup_audio_enabled() -> bool:
    return os.getenv("INGEST_WARMUP_AUDIO", "1") == "1"


def _warmup_text_enabled() -> bool:
    return os.getenv("INGEST_WARMUP_TEXT", "1") == "1"


def _consume_cold_start() -> bool:
    global _cold_start
    with _cold_start_lock:
        was_cold = _cold_start
        _cold_start = False
    return was_cold


def _instance_id() -> str:
    return (
        os.getenv("K_REVISION")
        or os.getenv("HOSTNAME")
        or os.getenv("CLOUD_RUN_EXECUTION")
        or "unknown"
    )


def _system_metrics(
    usage_start: resource.struct_rusage,
    cold_start: bool,
) -> dict[str, object]:
    usage_end = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "cpu_user_s": round(usage_end.ru_utime - usage_start.ru_utime, 4),
        "cpu_sys_s": round(usage_end.ru_stime - usage_start.ru_stime, 4),
        "memory_peak_kb": int(usage_end.ru_maxrss),
        "cold_start": cold_start,
        "instance_id": _instance_id(),
    }


def _silent_wav_bytes(
    duration_ms: int = 250,
    sample_rate: int = 48000,
) -> bytes:
    frames = int(sample_rate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _warm_ingest_models() -> None:
    if not _warmup_enabled():
        return
    warmup_start = time.monotonic()
    allowed = _allowed_modalities()
    transcribe_enabled = os.getenv("TRANSCRIBE_ENABLED", "1") == "1"
    transcribe_tier = os.getenv("TRANSCRIBE_TIER", "accurate").strip().lower()
    audio_transcribe_enabled = (
        transcribe_enabled
        and os.getenv("AUDIO_TRANSCRIBE", "1") == "1"
        and transcribe_tier != "off"
    )
    warm_audio = _warmup_audio_enabled() and (
        allowed is None or "audio" in allowed or "video" in allowed
    )
    docs_enabled = allowed is None or "document" in allowed
    audio_video_enabled = allowed is None or "audio" in allowed or "video" in allowed
    warm_text = _warmup_text_enabled() and (
        docs_enabled or (audio_video_enabled and audio_transcribe_enabled)
    )
    if warm_audio:
        try:
            audio_bytes = _silent_wav_bytes()
            run_inference(
                "audio_warmup",
                lambda: get_audio_embedder(512).encode([audio_bytes])[0],
            )
            logger.info("Audio embedder warmed")
        except Exception as exc:
            logger.warning("Audio warmup failed", extra={"error_message": str(exc)})
    if warm_text:
        try:
            run_inference(
                "text_warmup",
                lambda: get_text_embedder(768).encode(["retikon warmup"]),
            )
            logger.info("Text embedder warmed")
        except Exception as exc:
            logger.warning("Text warmup failed", extra={"error_message": str(exc)})
    logger.info(
        "Ingest warmup complete",
        extra={
            "warmup_ms": int((time.monotonic() - warmup_start) * 1000),
        },
    )


def _start_queue_monitor() -> None:
    global _queue_monitor
    if _queue_monitor is not None:
        return
    monitor = load_queue_monitor()
    if monitor is None:
        return
    monitor.start()
    _queue_monitor = monitor


def _queue_depth_snapshot() -> dict[str, Any] | None:
    monitor = _queue_monitor
    if monitor is None:
        return None
    return monitor.snapshot()


def _manifest_metrics(manifest_uri: str, *, bucket: str, name: str) -> dict[str, object] | None:
    try:
        fs, path = fsspec.core.url_to_fs(manifest_uri)
        with fs.open(path, "rb") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.warning(
            "Failed to read manifest metrics",
            extra={
                "bucket": bucket,
                "object_name": name,
                "manifest_uri": manifest_uri,
                "error_message": str(exc),
            },
        )
        return None
    if not isinstance(payload, dict):
        return None
    metrics = payload.get("metrics")
    return metrics if isinstance(metrics, dict) else None


def _apply_checksum_dedupe(
    *,
    client: firestore.Client,
    collection: str,
    doc_id: str,
    bucket: str,
    name: str,
    scope_key: str,
    checksum: str | None,
    size_bytes: int | None,
    content_type: str | None,
    duration_ms: int | None = None,
    queue_wait_ms: float | None = None,
    wall_ms: int | None = None,
    system_metrics: dict[str, object] | None = None,
) -> bool:
    if not checksum:
        return False
    try:
        match = find_completed_by_checksum(
            client=client,
            collection=collection,
            checksum=checksum,
            scope_key=scope_key,
            size_bytes=size_bytes,
            content_type=content_type,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning(
            "Checksum dedupe lookup failed",
            extra={
                "bucket": bucket,
                "name": name,
                "scope_key": scope_key,
                "error_message": str(exc),
            },
        )
        return False
    if not match:
        return False
    payload: dict[str, object] = {
        "status": "COMPLETED",
        "updated_at": datetime.now(timezone.utc),
        "dedupe_checksum": checksum,
        "dedupe_source_doc_id": match.get("doc_id"),
        "cache_hit": True,
        "cache_source": "both",
    }
    match_hash = match.get("content_hash_sha256")
    if match_hash:
        payload["content_hash_sha256"] = match_hash
        payload["content_hash_scope"] = resolve_content_hash_scope(
            match_hash,
            scope_key,
        )
    if size_bytes is not None:
        payload["object_size_bytes"] = size_bytes
    if content_type:
        payload["object_content_type"] = content_type
    resolved_duration = duration_ms
    if resolved_duration is None:
        match_duration = match.get("object_duration_ms")
        if match_duration is not None:
            resolved_duration = int(match_duration)
    if resolved_duration is not None:
        payload["object_duration_ms"] = resolved_duration
    for key in ("manifest_uri", "media_asset_id", "counts"):
        if key in match:
            payload[key] = match[key]
    metrics_payload: dict[str, object] = {}
    dedupe_pipe_ms = None
    if wall_ms is not None:
        dedupe_pipe_ms = round(float(wall_ms), 2)
        metrics_payload["stage_timings_ms"] = build_dedupe_stage_timings(dedupe_pipe_ms)
        metrics_payload["pipe_ms"] = dedupe_pipe_ms
    match_metrics = match.get("metrics")
    if isinstance(match_metrics, dict):
        pipeline_metrics = match_metrics.get("pipeline")
        if isinstance(pipeline_metrics, dict):
            pipeline_copy = dict(pipeline_metrics)
            if dedupe_pipe_ms is not None:
                pipeline_copy.pop("stage_timings_ms", None)
                pipeline_copy.pop("pipe_ms", None)
            metrics_payload["pipeline"] = pipeline_copy
        elif pipeline_metrics is not None:
            metrics_payload["pipeline"] = pipeline_metrics
        if dedupe_pipe_ms is None:
            stage_timings = match_metrics.get("stage_timings_ms")
            if not isinstance(stage_timings, dict) and isinstance(
                pipeline_metrics, dict
            ):
                stage_timings = pipeline_metrics.get("stage_timings_ms")
            if isinstance(stage_timings, dict):
                metrics_payload["stage_timings_ms"] = stage_timings
            pipe_ms = match_metrics.get("pipe_ms")
            if not isinstance(pipe_ms, (int, float)) and isinstance(
                pipeline_metrics, dict
            ):
                pipe_ms = pipeline_metrics.get("pipe_ms")
            if isinstance(pipe_ms, (int, float)):
                metrics_payload["pipe_ms"] = round(float(pipe_ms), 2)
    if "stage_timings_ms" not in metrics_payload:
        manifest_uri = match.get("manifest_uri")
        if isinstance(manifest_uri, str) and manifest_uri:
            manifest_metrics = _manifest_metrics(
                manifest_uri,
                bucket=bucket,
                name=name,
            )
            if isinstance(manifest_metrics, dict):
                stage_timings = manifest_metrics.get("stage_timings_ms")
                if isinstance(stage_timings, dict):
                    metrics_payload["stage_timings_ms"] = stage_timings
                    if "pipe_ms" not in metrics_payload:
                        total = 0.0
                        for value in stage_timings.values():
                            if isinstance(value, (int, float)):
                                total += float(value)
                        metrics_payload["pipe_ms"] = round(total, 2)
    if queue_wait_ms is not None:
        metrics_payload["queue_wait_ms"] = queue_wait_ms
    if wall_ms is not None:
        metrics_payload["wall_ms"] = wall_ms
    if system_metrics:
        metrics_payload["system"] = system_metrics
    if not isinstance(metrics_payload.get("stage_timings_ms"), dict):
        logger.info(
            "Dedupe match missing stage timings; skipping checksum dedupe",
            extra={
                "bucket": bucket,
                "name": name,
                "dedupe_source_doc_id": match.get("doc_id"),
            },
        )
        return False
    if metrics_payload:
        payload["metrics"] = metrics_payload
    client.collection(collection).document(doc_id).update(payload)
    return True


def _apply_content_hash_dedupe(
    *,
    client: firestore.Client,
    collection: str,
    doc_id: str,
    bucket: str,
    name: str,
    scope_key: str,
    content_hash: str | None,
    size_bytes: int | None,
    content_type: str | None,
    duration_ms: int | None = None,
    pipeline_version_value: str | None = None,
    queue_wait_ms: float | None = None,
    wall_ms: int | None = None,
    system_metrics: dict[str, object] | None = None,
) -> bool:
    if not content_hash:
        return False
    try:
        match = find_completed_by_content_hash(
            client=client,
            collection=collection,
            content_hash=content_hash,
            scope_key=scope_key,
            size_bytes=size_bytes,
            content_type=content_type,
            duration_ms=duration_ms,
            pipeline_version=pipeline_version_value,
        )
    except Exception as exc:
        logger.warning(
            "Content hash dedupe lookup failed",
            extra={
                "bucket": bucket,
                "name": name,
                "scope_key": scope_key,
                "error_message": str(exc),
            },
        )
        return False
    if not match:
        return False
    payload: dict[str, object] = {
        "status": "COMPLETED",
        "updated_at": datetime.now(timezone.utc),
        "content_hash_sha256": content_hash,
        "content_hash_scope": resolve_content_hash_scope(content_hash, scope_key),
        "dedupe_content_hash": content_hash,
        "dedupe_source_doc_id": match.get("doc_id"),
        "cache_hit": True,
        "cache_source": "both",
    }
    if size_bytes is not None:
        payload["object_size_bytes"] = size_bytes
    if content_type:
        payload["object_content_type"] = content_type
    resolved_duration = duration_ms
    if resolved_duration is None:
        match_duration = match.get("object_duration_ms")
        if match_duration is not None:
            resolved_duration = int(match_duration)
    if resolved_duration is not None:
        payload["object_duration_ms"] = resolved_duration
    for key in ("manifest_uri", "media_asset_id", "counts"):
        if key in match:
            payload[key] = match[key]
    metrics_payload: dict[str, object] = {}
    dedupe_pipe_ms = None
    if wall_ms is not None:
        dedupe_pipe_ms = round(float(wall_ms), 2)
        metrics_payload["stage_timings_ms"] = build_dedupe_stage_timings(dedupe_pipe_ms)
        metrics_payload["pipe_ms"] = dedupe_pipe_ms
    match_metrics = match.get("metrics")
    if isinstance(match_metrics, dict):
        pipeline_metrics = match_metrics.get("pipeline")
        if isinstance(pipeline_metrics, dict):
            pipeline_copy = dict(pipeline_metrics)
            if dedupe_pipe_ms is not None:
                pipeline_copy.pop("stage_timings_ms", None)
                pipeline_copy.pop("pipe_ms", None)
            metrics_payload["pipeline"] = pipeline_copy
        elif pipeline_metrics is not None:
            metrics_payload["pipeline"] = pipeline_metrics
        if dedupe_pipe_ms is None:
            stage_timings = match_metrics.get("stage_timings_ms")
            if not isinstance(stage_timings, dict) and isinstance(
                pipeline_metrics, dict
            ):
                stage_timings = pipeline_metrics.get("stage_timings_ms")
            if isinstance(stage_timings, dict):
                metrics_payload["stage_timings_ms"] = stage_timings
            pipe_ms = match_metrics.get("pipe_ms")
            if not isinstance(pipe_ms, (int, float)) and isinstance(
                pipeline_metrics, dict
            ):
                pipe_ms = pipeline_metrics.get("pipe_ms")
            if isinstance(pipe_ms, (int, float)):
                metrics_payload["pipe_ms"] = round(float(pipe_ms), 2)
    if "stage_timings_ms" not in metrics_payload:
        manifest_uri = match.get("manifest_uri")
        if isinstance(manifest_uri, str) and manifest_uri:
            manifest_metrics = _manifest_metrics(
                manifest_uri,
                bucket=bucket,
                name=name,
            )
            if isinstance(manifest_metrics, dict):
                stage_timings = manifest_metrics.get("stage_timings_ms")
                if isinstance(stage_timings, dict):
                    metrics_payload["stage_timings_ms"] = stage_timings
                    if "pipe_ms" not in metrics_payload:
                        total = 0.0
                        for value in stage_timings.values():
                            if isinstance(value, (int, float)):
                                total += float(value)
                        metrics_payload["pipe_ms"] = round(total, 2)
    if queue_wait_ms is not None:
        metrics_payload["queue_wait_ms"] = queue_wait_ms
    if wall_ms is not None:
        metrics_payload["wall_ms"] = wall_ms
    if system_metrics:
        metrics_payload["system"] = system_metrics
    if not isinstance(metrics_payload.get("stage_timings_ms"), dict):
        logger.info(
            "Dedupe match missing stage timings; skipping content hash dedupe",
            extra={
                "bucket": bucket,
                "name": name,
                "dedupe_source_doc_id": match.get("doc_id"),
            },
        )
        return False
    if metrics_payload:
        payload["metrics"] = metrics_payload
    client.collection(collection).document(doc_id).update(payload)
    return True


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path:
        raise HTTPException(status_code=400, detail="Invalid gs:// URI")
    bucket = parsed.netloc
    name = parsed.path.lstrip("/")
    return bucket, name


def _raw_bucket_name(config: Config) -> str:
    raw_bucket = config.raw_bucket
    if raw_bucket.startswith("gs://"):
        return raw_bucket[len("gs://") :].rstrip("/")
    return raw_bucket.strip("/")


def _ensure_raw_uri(uri: str, config: Config) -> None:
    bucket = _raw_bucket_name(config)
    if not uri.startswith(f"gs://{bucket}/"):
        raise HTTPException(status_code=403, detail="Path outside raw bucket")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/ingest/status", response_model=IngestStatusResponse)
async def ingest_status(
    request: Request,
    uri: str,
    x_request_id: str | None = Header(default=None),
) -> IngestStatusResponse:
    try:
        config = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    auth_context = _authorize_ingest(request, config)
    _enforce_access(ACTION_INGEST, auth_context, config)
    trace_id = x_request_id or str(uuid.uuid4())

    if _audit_logging_enabled():
        try:
            record_audit_log(
                base_uri=config.graph_root_uri(),
                action="ingest.status.read",
                decision="allow",
                auth_context=auth_context,
                scope=auth_context.scope if (auth_context and auth_context.scope) else _default_scope(config),
                resource=request.url.path,
                request_id=trace_id,
                pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
                schema_version=_schema_version(),
            )
        except Exception as exc:
            logger.warning(
                "Failed to record audit log",
                extra={"error_message": str(exc)},
            )

    _ensure_raw_uri(uri, config)
    bucket, name = _parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(bucket).blob(name)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Object not found")
    blob.reload()
    generation = str(blob.generation or "")
    doc_id = build_doc_id(bucket, name, generation)
    doc = (
        _firestore_client()
        .collection(config.firestore_collection)
        .document(doc_id)
        .get()
    )
    data = doc.to_dict() if doc.exists else None
    status = (data or {}).get("status") if data else "MISSING"
    return IngestStatusResponse(
        status=status,
        uri=uri,
        bucket=bucket,
        name=name,
        generation=generation,
        doc_id=doc_id,
        firestore=data,
    )


@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest(
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> IngestResponse:
    start_time = time.monotonic()
    usage_start = resource.getrusage(resource.RUSAGE_SELF)
    try:
        config = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    auth_context = _authorize_ingest(request, config)
    _enforce_access(ACTION_INGEST, auth_context, config)

    trace_id = x_request_id or str(uuid.uuid4())
    logger.info(
        "Received ingest event",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
            "status": "authorized" if auth_context else "anonymous",
        },
    )
    if _audit_logging_enabled():
        try:
            record_audit_log(
                base_uri=config.graph_root_uri(),
                action=ACTION_INGEST,
                decision="allow",
                auth_context=auth_context,
                scope=auth_context.scope if (auth_context and auth_context.scope) else _default_scope(config),
                resource=request.url.path,
                request_id=trace_id,
                pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
                schema_version=_schema_version(),
            )
        except Exception as exc:
            logger.warning(
                "Failed to record audit log",
                extra={"error_message": str(exc)},
            )

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    cloudevent_payload = _coerce_cloudevent(request, body)
    try:
        gcs_event = parse_cloudevent(cloudevent_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    gcs_event = _hydrate_storage_event(gcs_event)
    queue_wait_ms = _queue_wait_ms(gcs_event.bucket, gcs_event.name)
    modality = _modality_from_name(gcs_event.name)
    if modality is None:
        raise HTTPException(status_code=400, detail="Unsupported modality")
    delegate_url = _media_delegate_url()
    delegate_topic = _media_delegate_topic()
    delegate_modalities = _media_delegate_modalities()
    embed_url = _media_embed_delegate_url()
    embed_topic = _media_embed_delegate_topic()
    embed_modalities = _media_embed_delegate_modalities()
    if embed_modalities and modality in embed_modalities:
        if embed_topic:
            logger.info(
                "Queueing ingest to embed-only media topic",
                extra={
                    "request_id": trace_id,
                    "correlation_id": request.state.correlation_id,
                    "modality": modality,
                    "topic": embed_topic,
                },
            )
            return _publish_media_ingest(
                topic=embed_topic,
                payload=cloudevent_payload,
                trace_id=trace_id,
                correlation_id=request.state.correlation_id,
                modality=modality,
            )
        if embed_url:
            logger.info(
                "Delegating ingest to embed-only media service",
                extra={
                    "request_id": trace_id,
                    "correlation_id": request.state.correlation_id,
                    "modality": modality,
                },
            )
            return _delegate_media_ingest(
                url=embed_url,
                payload=cloudevent_payload,
                trace_id=trace_id,
                correlation_id=request.state.correlation_id,
            )
    if modality in delegate_modalities:
        if delegate_topic:
            logger.info(
                "Queueing ingest to media topic",
                extra={
                    "request_id": trace_id,
                    "correlation_id": request.state.correlation_id,
                    "modality": modality,
                    "topic": delegate_topic,
                },
            )
            return _publish_media_ingest(
                topic=delegate_topic,
                payload=cloudevent_payload,
                trace_id=trace_id,
                correlation_id=request.state.correlation_id,
                modality=modality,
            )
        if delegate_url:
            logger.info(
                "Delegating ingest to media service",
                extra={
                    "request_id": trace_id,
                    "correlation_id": request.state.correlation_id,
                    "modality": modality,
                },
            )
            return _delegate_media_ingest(
                url=delegate_url,
                payload=cloudevent_payload,
                trace_id=trace_id,
                correlation_id=request.state.correlation_id,
            )
    allowed = _allowed_modalities()
    if allowed is not None and modality not in allowed:
        raise HTTPException(status_code=400, detail="Modality not allowed")
    cold_start = _consume_cold_start()
    scope = auth_context.scope if (auth_context and auth_context.scope) else _default_scope(config)
    scope_key = _scope_key(scope)

    if config.ingestion_dry_run:
        try:
            enforce_rate_limit(modality, config=config, scope=scope)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except RateLimitBackendError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return IngestResponse(status="accepted", trace_id=trace_id)

    firestore_client = firestore.Client()
    idempotency = FirestoreIdempotency(
        firestore_client,
        config.firestore_collection,
        processing_ttl=timedelta(seconds=config.idempotency_ttl_seconds),
        completed_ttl=timedelta(seconds=config.idempotency_completed_ttl_seconds),
    )
    checksum = resolve_checksum(gcs_event.md5_hash, gcs_event.crc32c)
    decision = idempotency.begin(
        bucket=gcs_event.bucket,
        name=gcs_event.name,
        generation=gcs_event.generation,
        size=gcs_event.size,
        pipeline_version=pipeline_version(),
    )
    attempt_count = decision.attempt_count

    dlq_publisher = _get_dlq_publisher(config.dlq_topic)

    if decision.action == "skip_completed":
        return IngestResponse(status="completed", trace_id=trace_id)
    if decision.action == "skip_processing":
        return IngestResponse(status="processing", trace_id=trace_id)
    try:
        update_object_metadata(
            client=firestore_client,
            collection=config.firestore_collection,
            doc_id=decision.doc_id,
            bucket=gcs_event.bucket,
            name=gcs_event.name,
            generation=gcs_event.generation,
            checksum=checksum,
            content_type=gcs_event.content_type,
            size_bytes=gcs_event.size,
            scope_key=scope_key,
            scope_org_id=scope.org_id,
            scope_site_id=scope.site_id,
            scope_stream_id=scope.stream_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to update idempotency metadata",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "error_message": str(exc),
            },
        )
    if config.max_ingest_attempts > 0 and attempt_count >= config.max_ingest_attempts:
        logger.warning(
            "Ingest skipped: max attempts reached",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": modality,
                "bytes_downloaded": gcs_event.size,
                "attempt_count": attempt_count,
                "error_code": "MAX_ATTEMPTS",
                "error_message": "Max ingest attempts exceeded",
            },
        )
        _publish_dlq(
            dlq_publisher,
            error_code="MAX_ATTEMPTS",
            error_message="Max ingest attempts exceeded",
            attempt_count=attempt_count,
            gcs_event=gcs_event,
            cloudevent=cloudevent_payload,
        )
        idempotency.mark_dlq(decision.doc_id, "MAX_ATTEMPTS", "Max attempts exceeded")
        return IngestResponse(status="dlq", trace_id=trace_id)

    download = None
    content_hash = None
    try:
        try:
            if config.dedupe_cache_enabled and _apply_checksum_dedupe(
                client=firestore_client,
                collection=config.firestore_collection,
                doc_id=decision.doc_id,
                bucket=gcs_event.bucket,
                name=gcs_event.name,
                scope_key=scope_key,
                checksum=checksum,
                size_bytes=gcs_event.size,
                content_type=gcs_event.content_type,
                queue_wait_ms=queue_wait_ms,
                wall_ms=int((time.monotonic() - start_time) * 1000),
                system_metrics=_system_metrics(usage_start, cold_start),
            ):
                logger.info(
                    "Ingest deduped by checksum",
                    extra={
                        "request_id": trace_id,
                        "correlation_id": request.state.correlation_id,
                        "modality": modality,
                        "bytes_downloaded": gcs_event.size,
                        "attempt_count": attempt_count,
                    },
                )
                return IngestResponse(status="completed", trace_id=trace_id)
            object_uri = config.raw_object_uri(
                gcs_event.name,
                bucket=gcs_event.bucket,
            )
            download = download_to_tmp(object_uri, config.max_raw_bytes)
            content_hash = download.content_hash_sha256
            if content_hash:
                content_scope = resolve_content_hash_scope(content_hash, scope_key)
                firestore_client.collection(config.firestore_collection).document(
                    decision.doc_id
                ).update(
                    {
                        "content_hash_sha256": content_hash,
                        "content_hash_scope": content_scope,
                    }
                )
            if config.dedupe_cache_enabled and _apply_content_hash_dedupe(
                client=firestore_client,
                collection=config.firestore_collection,
                doc_id=decision.doc_id,
                bucket=gcs_event.bucket,
                name=gcs_event.name,
                scope_key=scope_key,
                content_hash=content_hash,
                size_bytes=gcs_event.size,
                content_type=gcs_event.content_type,
                pipeline_version_value=pipeline_version(),
                queue_wait_ms=queue_wait_ms,
                wall_ms=int((time.monotonic() - start_time) * 1000),
                system_metrics=_system_metrics(usage_start, cold_start),
            ):
                logger.info(
                    "Ingest deduped by content hash",
                    extra={
                        "request_id": trace_id,
                        "correlation_id": request.state.correlation_id,
                        "modality": modality,
                        "bytes_downloaded": gcs_event.size,
                        "attempt_count": attempt_count,
                    },
                )
                cleanup_tmp(download.path)
                return IngestResponse(status="completed", trace_id=trace_id)
            enforce_rate_limit(modality, config=config, scope=scope)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except RateLimitBackendError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        inflight_snapshot = _ingest_load.increment(modality)
        try:
            outcome = process_event(
                event=gcs_event,
                config=config,
                rate_limit_scope=scope,
                skip_rate_limit=True,
                download=download,
            )
        finally:
            _ingest_load.decrement(modality)
            download = None
        system_metrics = _system_metrics(usage_start, cold_start)
        wall_ms = int((time.monotonic() - start_time) * 1000)
        idempotency.mark_completed(decision.doc_id)
        update_payload = {
            "manifest_uri": outcome.manifest_uri,
            "media_asset_id": outcome.media_asset_id,
            "counts": outcome.counts,
            "cache_hit": False,
            "cache_source": "none",
        }
        if content_hash:
            update_payload["content_hash_sha256"] = content_hash
            update_payload["content_hash_scope"] = resolve_content_hash_scope(
                content_hash,
                scope_key,
            )
        if outcome.duration_ms is not None:
            update_payload["object_duration_ms"] = outcome.duration_ms
        metrics_payload: dict[str, object] = {}
        pipeline_metrics = outcome.metrics
        if pipeline_metrics:
            metrics_payload["pipeline"] = pipeline_metrics
            stage_timings = pipeline_metrics.get("stage_timings_ms")
            if isinstance(stage_timings, dict):
                metrics_payload["stage_timings_ms"] = stage_timings
            pipe_ms = pipeline_metrics.get("pipe_ms")
            if isinstance(pipe_ms, (int, float)):
                metrics_payload["pipe_ms"] = round(float(pipe_ms), 2)
        if queue_wait_ms is not None:
            metrics_payload["queue_wait_ms"] = queue_wait_ms
        metrics_payload["wall_ms"] = wall_ms
        queue_depth_payload: dict[str, Any] = {}
        if inflight_snapshot:
            queue_depth_payload["inflight"] = inflight_snapshot
        monitor_snapshot = _queue_depth_snapshot()
        if monitor_snapshot:
            queue_depth_payload["subscriptions"] = monitor_snapshot.get("subscriptions")
            queue_depth_payload["updated_at"] = monitor_snapshot.get("updated_at")
        if queue_depth_payload:
            metrics_payload["queue_depth"] = queue_depth_payload
        metrics_payload["system"] = system_metrics
        if metrics_payload:
            update_payload["metrics"] = metrics_payload
        queue_depth_backlog = None
        queue_depth_oldest = None
        subscriptions = queue_depth_payload.get("subscriptions") if queue_depth_payload else None
        if isinstance(subscriptions, dict):
            entry = subscriptions.get(outcome.modality or modality)
            if isinstance(entry, dict):
                backlog = entry.get("backlog")
                if isinstance(backlog, (int, float)):
                    queue_depth_backlog = int(backlog)
                oldest = entry.get("oldest_unacked_s")
                if isinstance(oldest, (int, float)):
                    queue_depth_oldest = round(float(oldest), 2)
        firestore_client.collection(config.firestore_collection).document(
            decision.doc_id
        ).update(update_payload)
        duration_ms = wall_ms
        stage_timings_ms = None
        pipe_ms = None
        if isinstance(pipeline_metrics, dict):
            stage_timings_ms = pipeline_metrics.get("stage_timings_ms")
            pipe_ms = pipeline_metrics.get("pipe_ms")
        logger.info(
            "Ingest completed",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": outcome.modality,
                "bytes_downloaded": gcs_event.size,
                "processing_ms": duration_ms,
                "duration_ms": duration_ms,
                "media_asset_id": outcome.media_asset_id,
                "attempt_count": attempt_count,
                "queue_wait_ms": queue_wait_ms,
                "queue_depth_backlog": queue_depth_backlog,
                "queue_depth_oldest_unacked_s": queue_depth_oldest,
                "pipe_ms": pipe_ms if isinstance(pipe_ms, (int, float)) else None,
                "stage_timings_ms": stage_timings_ms
                if isinstance(stage_timings_ms, dict)
                else None,
                "cpu_user_s": system_metrics["cpu_user_s"],
                "cpu_sys_s": system_metrics["cpu_sys_s"],
                "memory_peak_kb": system_metrics["memory_peak_kb"],
            },
        )
        if _metering_enabled():
            scope = auth_context.scope if (auth_context and auth_context.scope) else _default_scope(config)
            bytes_in = gcs_event.size if gcs_event.size is not None else 0
            try:
                record_usage(
                    base_uri=config.graph_root_uri(),
                    event_type="ingest",
                    scope=scope,
                    api_key_id=auth_context.api_key_id if auth_context else None,
                    modality=outcome.modality,
                    units=1,
                    bytes_in=bytes_in,
                    pipeline_version=pipeline_version(),
                    schema_version=_schema_version(),
                    response_time_ms=duration_ms,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to record usage",
                    extra={"error_message": str(exc)},
                )
        return IngestResponse(status=outcome.status, trace_id=trace_id)
    except PermanentError as exc:
        if download is not None:
            cleanup_tmp(download.path)
        _publish_dlq(
            dlq_publisher,
            error_code="PERMANENT",
            error_message=str(exc),
            attempt_count=attempt_count,
            gcs_event=gcs_event,
            cloudevent=cloudevent_payload,
        )
        idempotency.mark_dlq(decision.doc_id, "PERMANENT", str(exc))
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            "Ingest failed",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": _modality_from_name(gcs_event.name),
                "bytes_downloaded": gcs_event.size,
                "processing_ms": duration_ms,
                "duration_ms": duration_ms,
                "attempt_count": attempt_count,
                "error_code": "PERMANENT",
                "error_message": str(exc),
            },
        )
        return IngestResponse(status="failed", trace_id=trace_id)
    except RecoverableError as exc:
        if download is not None:
            cleanup_tmp(download.path)
        if (
            config.max_ingest_attempts > 0
            and attempt_count >= config.max_ingest_attempts
        ):
            logger.warning(
                "Ingest failed (recoverable, max attempts reached)",
                extra={
                    "request_id": trace_id,
                    "correlation_id": request.state.correlation_id,
                    "modality": _modality_from_name(gcs_event.name),
                    "bytes_downloaded": gcs_event.size,
                    "attempt_count": attempt_count,
                    "error_code": "RECOVERABLE",
                    "error_message": str(exc),
                },
            )
            _publish_dlq(
                dlq_publisher,
                error_code="RECOVERABLE",
                error_message=str(exc),
                attempt_count=attempt_count,
                gcs_event=gcs_event,
                cloudevent=cloudevent_payload,
            )
            idempotency.mark_dlq(decision.doc_id, "RECOVERABLE", str(exc))
            return IngestResponse(status="dlq", trace_id=trace_id)
        logger.exception(
            "Ingest failed (recoverable)",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": _modality_from_name(gcs_event.name),
                "bytes_downloaded": gcs_event.size,
                "attempt_count": attempt_count,
                "error_code": "RECOVERABLE",
                "error_message": str(exc),
            },
        )
        idempotency.mark_failed(decision.doc_id, "RECOVERABLE", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        if download is not None:
            cleanup_tmp(download.path)
        logger.exception(
            "Ingest failed (unexpected)",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": _modality_from_name(gcs_event.name),
                "bytes_downloaded": gcs_event.size,
                "attempt_count": attempt_count,
                "error_code": "UNKNOWN",
                "error_message": str(exc),
            },
        )
        idempotency.mark_failed(decision.doc_id, "UNKNOWN", str(exc))
        raise HTTPException(status_code=500, detail="Unexpected error") from exc


def _coerce_cloudevent(request: Request, body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and "specversion" in body:
        return body

    def header(name: str) -> str | None:
        return request.headers.get(name)

    def _decode_json_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                try:
                    decoded = base64.b64decode(raw.encode("utf-8"))
                except (ValueError, binascii.Error):
                    return None
                try:
                    return json.loads(decoded.decode("utf-8"))
                except json.JSONDecodeError:
                    return None
        return None

    data: dict[str, Any] | None = None
    if isinstance(body, dict):
        message = body.get("message") if isinstance(body.get("message"), dict) else None
        if message and "data" in message:
            data = _decode_json_payload(message.get("data"))
        else:
            data = body
    else:
        data = _decode_json_payload(body)

    if isinstance(data, dict) and "specversion" in data and "data" in data:
        return data

    return {
        "id": header("ce-id"),
        "type": header("ce-type"),
        "source": header("ce-source"),
        "specversion": header("ce-specversion") or "1.0",
        "time": header("ce-time"),
        "subject": header("ce-subject"),
        "data": data,
    }


def _get_dlq_publisher(topic: str | None) -> PubSubDlqPublisher | None:
    global _dlq_publisher
    if not topic:
        return None
    if _dlq_publisher is None:
        _dlq_publisher = PubSubDlqPublisher(topic)
    return _dlq_publisher


def _publish_dlq(
    publisher: PubSubDlqPublisher | None,
    *,
    error_code: str,
    error_message: str,
    attempt_count: int,
    gcs_event: Any,
    cloudevent: dict[str, Any],
) -> None:
    if publisher is None:
        return
    publisher.publish(
        error_code=error_code,
        error_message=error_message,
        attempt_count=attempt_count,
        modality=_modality_from_name(gcs_event.name),
        gcs_event={
            "bucket": gcs_event.bucket,
            "name": gcs_event.name,
            "generation": gcs_event.generation,
            "content_type": gcs_event.content_type,
            "size": gcs_event.size,
        },
        cloudevent=cloudevent,
    )


def _modality_from_name(name: str) -> str | None:
    raw_prefix = _raw_prefix()
    prefix = f"{raw_prefix}/"
    if name.startswith(f"{prefix}docs/"):
        return "document"
    if name.startswith(f"{prefix}images/"):
        return "image"
    if name.startswith(f"{prefix}audio/"):
        return "audio"
    if name.startswith(f"{prefix}videos/"):
        return "video"
    return None
