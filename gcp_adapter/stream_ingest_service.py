import asyncio
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from google.cloud import firestore
from pydantic import BaseModel

from gcp_adapter.dlq_pubsub import PubSubDlqPublisher
from gcp_adapter.idempotency_firestore import (
    FirestoreIdempotency,
    find_completed_by_checksum,
    resolve_checksum,
    resolve_scope_key,
    update_object_metadata,
)
from gcp_adapter.queue_pubsub import PubSubPublisher, parse_pubsub_push
from retikon_core.config import get_config
from retikon_core.errors import PermanentError, RecoverableError, ValidationError
from retikon_core.ingestion import process_event
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
    }
    for key in ("manifest_uri", "media_asset_id", "counts"):
        if key in match:
            payload[key] = match[key]
    client.collection(collection).document(doc_id).update(payload)
    return True


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
        scope_key = resolve_scope_key(event.org_id, event.site_id, event.stream_id)
        storage_event = event.to_storage_event()
        checksum = resolve_checksum(storage_event.md5_hash, storage_event.crc32c)
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
            if _apply_checksum_dedupe(
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
            outcome = process_event(event=storage_event, config=config)
            idempotency.mark_completed(decision.doc_id)
            update_payload = {
                "manifest_uri": outcome.manifest_uri,
                "media_asset_id": outcome.media_asset_id,
                "counts": outcome.counts,
            }
            if outcome.duration_ms is not None:
                update_payload["object_duration_ms"] = outcome.duration_ms
            firestore_client.collection(config.firestore_collection).document(
                decision.doc_id
            ).update(update_payload)
            processed += 1
        except PermanentError as exc:
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
            idempotency.mark_failed(decision.doc_id, "VALIDATION", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
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
