import asyncio
import contextlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import fsspec
from fastapi import FastAPI, Header, HTTPException, Request
from google.cloud import firestore
from google.cloud import storage
from pydantic import BaseModel

from gcp_adapter.dlq_pubsub import PubSubDlqPublisher
from gcp_adapter.idempotency_firestore import (
    FirestoreIdempotency,
    find_completed_by_checksum,
    find_completed_by_content_hash,
    resolve_checksum,
    resolve_content_hash_scope,
    resolve_scope_key,
    update_object_metadata,
)
from gcp_adapter.queue_pubsub import PubSubPublisher, parse_pubsub_push
from retikon_core.config import get_config
from retikon_core.errors import PermanentError, RecoverableError, ValidationError
from retikon_core.ingestion import process_event
from retikon_core.ingestion.download import cleanup_tmp, download_to_tmp
from retikon_core.ingestion.router import pipeline_version
from retikon_core.ingestion.streaming import (
    StreamBackpressureError,
    StreamBatcher,
    StreamEvent,
    StreamIngestPipeline,
    decode_stream_batch,
    stream_event_from_dict,
)
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    add_correlation_id_middleware,
    build_health_response,
)

SERVICE_NAME = "retikon-stream-ingest"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
add_correlation_id_middleware(app)

_dlq_publisher: PubSubDlqPublisher | None = None
_flush_task: asyncio.Task | None = None


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


class StreamIngestResponse(BaseModel):
    status: str
    accepted: int
    queued: int
    backlog: int
    batch_published: bool
    message_ids: list[str]
    trace_id: str


class StreamStatusResponse(BaseModel):
    backlog: int
    batch_max: int
    batch_latency_ms: int
    backlog_max: int
    queue_topic: str


def _stream_topic() -> str:
    topic = os.getenv("STREAM_INGEST_TOPIC")
    if not topic:
        raise RuntimeError("STREAM_INGEST_TOPIC is required")
    return topic


def _batch_max() -> int:
    return int(os.getenv("STREAM_BATCH_MAX", "50"))


def _batch_latency_ms() -> int:
    return int(os.getenv("STREAM_BATCH_MAX_DELAY_MS", "2000"))


def _backlog_max() -> int:
    return int(os.getenv("STREAM_BACKLOG_MAX", "1000"))


def _flush_interval_s() -> float:
    latency_s = _batch_latency_ms() / 1000.0
    if latency_s <= 0:
        return 0.5
    return max(0.25, latency_s / 2.0)


def _init_pipeline() -> StreamIngestPipeline:
    batcher = StreamBatcher(
        max_batch_size=_batch_max(),
        max_latency_s=_batch_latency_ms() / 1000.0,
        max_backlog=_backlog_max(),
    )
    publisher = PubSubPublisher()
    return StreamIngestPipeline(
        publisher=publisher,
        topic=_stream_topic(),
        batcher=batcher,
    )


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
    match_metrics = match.get("metrics")
    if isinstance(match_metrics, dict):
        pipeline_metrics = match_metrics.get("pipeline")
        if pipeline_metrics is not None:
            metrics_payload["pipeline"] = pipeline_metrics
        stage_timings = match_metrics.get("stage_timings_ms")
        if not isinstance(stage_timings, dict) and isinstance(pipeline_metrics, dict):
            stage_timings = pipeline_metrics.get("stage_timings_ms")
        if isinstance(stage_timings, dict):
            metrics_payload["stage_timings_ms"] = stage_timings
        pipe_ms = match_metrics.get("pipe_ms")
        if not isinstance(pipe_ms, (int, float)) and isinstance(pipeline_metrics, dict):
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
    wall_ms: float | None = None,
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
    match_metrics = match.get("metrics")
    if isinstance(match_metrics, dict):
        pipeline_metrics = match_metrics.get("pipeline")
        if pipeline_metrics is not None:
            metrics_payload["pipeline"] = pipeline_metrics
        stage_timings = match_metrics.get("stage_timings_ms")
        if not isinstance(stage_timings, dict) and isinstance(pipeline_metrics, dict):
            stage_timings = pipeline_metrics.get("stage_timings_ms")
        if isinstance(stage_timings, dict):
            metrics_payload["stage_timings_ms"] = stage_timings
        pipe_ms = match_metrics.get("pipe_ms")
        if not isinstance(pipe_ms, (int, float)) and isinstance(pipeline_metrics, dict):
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
    if queue_wait_ms is not None:
        metrics_payload["queue_wait_ms"] = queue_wait_ms
    if wall_ms is not None:
        metrics_payload["wall_ms"] = round(float(wall_ms), 2)
    if metrics_payload:
        payload["metrics"] = metrics_payload
    client.collection(collection).document(doc_id).update(payload)
    return True


def _storage_client() -> storage.Client:
    return storage.Client()


def _queue_wait_ms(bucket: str, name: str) -> float | None:
    try:
        blob = _storage_client().bucket(bucket).blob(name)
        blob.reload()
    except Exception as exc:
        logger.warning(
            "Queue wait lookup failed",
            extra={"bucket": bucket, "name": name, "error_message": str(exc)},
        )
        return None
    created_at = blob.time_created
    if created_at is None:
        return None
    created_at = created_at.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    return round((now - created_at).total_seconds() * 1000.0, 2)


PIPELINE = _init_pipeline()


async def _flush_loop() -> None:
    interval = _flush_interval_s()
    while True:
        await asyncio.sleep(interval)
        try:
            message_ids = PIPELINE.flush()
        except Exception:
            logger.exception("Stream batch flush failed")
            continue
        if message_ids:
            logger.info(
                "Stream batch flushed",
                extra={
                    "published": len(message_ids),
                    "backlog": PIPELINE.batcher.backlog,
                },
            )


@app.on_event("startup")
async def _start_flush_loop() -> None:
    global _flush_task
    if _flush_task is None:
        _flush_task = asyncio.create_task(_flush_loop())


@app.on_event("shutdown")
async def _stop_flush_loop() -> None:
    global _flush_task
    if _flush_task is None:
        return
    _flush_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _flush_task
    _flush_task = None


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/ingest/stream/status", response_model=StreamStatusResponse)
async def stream_status() -> StreamStatusResponse:
    return StreamStatusResponse(
        backlog=PIPELINE.batcher.backlog,
        batch_max=_batch_max(),
        batch_latency_ms=_batch_latency_ms(),
        backlog_max=_backlog_max(),
        queue_topic=_stream_topic(),
    )


@app.post("/ingest/stream", response_model=StreamIngestResponse, status_code=202)
async def ingest_stream(
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> StreamIngestResponse:
    trace_id = x_request_id or str(uuid.uuid4())
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    events = _parse_stream_events(body)
    if not events:
        raise HTTPException(status_code=400, detail="No stream events provided")

    if not PIPELINE.batcher.can_accept(len(events)):
        raise HTTPException(status_code=429, detail="Stream backlog exceeded")

    try:
        result = PIPELINE.enqueue_events(events)
    except StreamBackpressureError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Stream enqueue failed",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
            },
        )
        raise HTTPException(status_code=500, detail="Queue dispatch failed") from exc

    logger.info(
        "Stream enqueue accepted",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
            "accepted": result.accepted,
            "backlog": result.backlog,
        },
    )
    return StreamIngestResponse(
        status="accepted",
        accepted=result.accepted,
        queued=result.queued,
        backlog=result.backlog,
        batch_published=result.batch_published,
        message_ids=list(result.message_ids),
        trace_id=trace_id,
    )


@app.post("/ingest/stream/push")
async def ingest_stream_push(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    try:
        envelope = parse_pubsub_push(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        events = decode_stream_batch(envelope.message.data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not events:
        return {"status": "ok", "processed": 0, "skipped": 0}

    try:
        config = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if config.ingestion_dry_run:
        return {"status": "accepted", "processed": 0, "skipped": len(events)}

    firestore_client = firestore.Client()
    idempotency = FirestoreIdempotency(
        firestore_client,
        config.firestore_collection,
        processing_ttl=timedelta(seconds=config.idempotency_ttl_seconds),
        completed_ttl=timedelta(seconds=config.idempotency_completed_ttl_seconds),
    )
    dlq_publisher = _get_dlq_publisher(config.dlq_topic)

    processed = 0
    skipped = 0
    for event in events:
        start_time = time.monotonic()
        scope_key = resolve_scope_key(event.org_id, event.site_id, event.stream_id)
        storage_event = event.to_storage_event()
        checksum = resolve_checksum(storage_event.md5_hash, storage_event.crc32c)
        download = None
        content_hash = None
        decision = idempotency.begin(
            bucket=storage_event.bucket,
            name=storage_event.name,
            generation=storage_event.generation,
            size=storage_event.size,
            pipeline_version=pipeline_version(),
        )
        attempt_count = decision.attempt_count
        if decision.action == "skip_completed":
            skipped += 1
            continue
        if decision.action == "skip_processing":
            skipped += 1
            continue
        try:
            update_object_metadata(
                client=firestore_client,
                collection=config.firestore_collection,
                doc_id=decision.doc_id,
                bucket=storage_event.bucket,
                name=storage_event.name,
                generation=storage_event.generation,
                checksum=checksum,
                content_type=storage_event.content_type,
                size_bytes=storage_event.size,
                scope_key=scope_key,
                scope_org_id=event.org_id,
                scope_site_id=event.site_id,
                scope_stream_id=event.stream_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update idempotency metadata",
                extra={
                    "modality": event.modality,
                    "attempt_count": attempt_count,
                    "error_message": str(exc),
                },
            )
        if (
            config.max_ingest_attempts > 0
            and attempt_count >= config.max_ingest_attempts
        ):
            _publish_dlq(
                dlq_publisher,
                error_code="MAX_ATTEMPTS",
                error_message="Max ingest attempts exceeded",
                attempt_count=attempt_count,
                storage_event=storage_event,
                stream_event=event,
            )
            idempotency.mark_dlq(
                decision.doc_id,
                "MAX_ATTEMPTS",
                "Max ingest attempts exceeded",
            )
            skipped += 1
            continue

        try:
            if config.dedupe_cache_enabled and _apply_checksum_dedupe(
                client=firestore_client,
                collection=config.firestore_collection,
                doc_id=decision.doc_id,
                bucket=storage_event.bucket,
                name=storage_event.name,
                scope_key=scope_key,
                checksum=checksum,
                size_bytes=storage_event.size,
                content_type=storage_event.content_type,
            ):
                skipped += 1
                continue
            object_uri = config.raw_object_uri(
                storage_event.name,
                bucket=storage_event.bucket,
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
                bucket=storage_event.bucket,
                name=storage_event.name,
                scope_key=scope_key,
                content_hash=content_hash,
                size_bytes=storage_event.size,
                content_type=storage_event.content_type,
                pipeline_version_value=pipeline_version(),
                queue_wait_ms=_queue_wait_ms(
                    storage_event.bucket,
                    storage_event.name,
                ),
                wall_ms=(time.monotonic() - start_time) * 1000.0,
            ):
                cleanup_tmp(download.path)
                skipped += 1
                continue
            outcome = process_event(
                event=storage_event,
                config=config,
                download=download,
            )
            download = None
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
            if outcome.metrics:
                metrics_payload["pipeline"] = outcome.metrics
                stage_timings = outcome.metrics.get("stage_timings_ms")
                if isinstance(stage_timings, dict):
                    metrics_payload["stage_timings_ms"] = stage_timings
                pipe_ms = outcome.metrics.get("pipe_ms")
                if isinstance(pipe_ms, (int, float)):
                    metrics_payload["pipe_ms"] = round(float(pipe_ms), 2)
            queue_wait_ms = _queue_wait_ms(
                storage_event.bucket,
                storage_event.name,
            )
            if queue_wait_ms is not None:
                metrics_payload["queue_wait_ms"] = queue_wait_ms
            metrics_payload["wall_ms"] = round(
                (time.monotonic() - start_time) * 1000.0,
                2,
            )
            if metrics_payload:
                update_payload["metrics"] = metrics_payload
            firestore_client.collection(config.firestore_collection).document(
                decision.doc_id
            ).update(update_payload)
            processed += 1
        except PermanentError as exc:
            if download is not None:
                cleanup_tmp(download.path)
            _publish_dlq(
                dlq_publisher,
                error_code="PERMANENT",
                error_message=str(exc),
                attempt_count=attempt_count,
                storage_event=storage_event,
                stream_event=event,
            )
            idempotency.mark_dlq(decision.doc_id, "PERMANENT", str(exc))
            skipped += 1
        except RecoverableError as exc:
            if download is not None:
                cleanup_tmp(download.path)
            idempotency.mark_failed(decision.doc_id, "RECOVERABLE", str(exc))
            logger.exception(
                "Stream ingest failed (recoverable)",
                extra={
                    "modality": event.modality,
                    "attempt_count": attempt_count,
                    "error_message": str(exc),
                },
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ValidationError as exc:
            if download is not None:
                cleanup_tmp(download.path)
            idempotency.mark_failed(decision.doc_id, "VALIDATION", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            if download is not None:
                cleanup_tmp(download.path)
            idempotency.mark_failed(decision.doc_id, "UNKNOWN", str(exc))
            logger.exception("Stream ingest failed (unexpected)")
            raise HTTPException(status_code=500, detail="Unexpected error") from exc

    return {"status": "ok", "processed": processed, "skipped": skipped}


def _parse_stream_events(body: Any) -> list[StreamEvent]:
    if isinstance(body, dict):
        try:
            if "events" in body:
                raw_events = body.get("events")
                if not isinstance(raw_events, list):
                    raise HTTPException(status_code=400, detail="events must be a list")
                return [stream_event_from_dict(item) for item in raw_events]
            if "event" in body:
                raw_event = body.get("event")
                if not isinstance(raw_event, dict):
                    raise HTTPException(
                        status_code=400,
                        detail="event must be an object",
                    )
                return [stream_event_from_dict(raw_event)]
            return [stream_event_from_dict(body)]
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="Invalid stream payload")


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
    storage_event: Any,
    stream_event: StreamEvent,
) -> None:
    if publisher is None:
        return
    publisher.publish(
        error_code=error_code,
        error_message=error_message,
        attempt_count=attempt_count,
        modality=stream_event.modality,
        gcs_event={
            "bucket": storage_event.bucket,
            "name": storage_event.name,
            "generation": storage_event.generation,
            "content_type": storage_event.content_type,
            "size": storage_event.size,
        },
        cloudevent={
            "stream_id": stream_event.stream_id,
            "org_id": stream_event.org_id,
            "device_id": stream_event.device_id,
            "site_id": stream_event.site_id,
        },
    )
