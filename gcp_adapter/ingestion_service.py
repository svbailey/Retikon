import json
import os
import time
import uuid
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from google.cloud import firestore, storage
from pydantic import BaseModel

from retikon_core.config import get_config
from retikon_core.errors import PermanentError, RecoverableError, ValidationError
from retikon_core.ingestion import FirestoreIdempotency, parse_cloudevent, process_event
from retikon_core.ingestion.dlq import DlqPublisher
from retikon_core.ingestion.router import pipeline_version
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-ingestion"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()

_dlq_publisher: DlqPublisher | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


class IngestResponse(BaseModel):
    status: str
    trace_id: str


def _correlation_id(header_value: str | None) -> str:
    if header_value:
        return header_value
    return str(uuid.uuid4())


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    corr = _correlation_id(request.headers.get("x-correlation-id"))
    request.state.correlation_id = corr
    response = await call_next(request)
    response.headers["x-correlation-id"] = corr
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    version = os.getenv("RETIKON_VERSION", "dev")
    commit = os.getenv("GIT_COMMIT", "unknown")
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=version,
        commit=commit,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest(
    request: Request,
    x_request_id: str | None = Header(default=None),
) -> IngestResponse:
    start_time = time.monotonic()
    try:
        config = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    trace_id = x_request_id or str(uuid.uuid4())
    logger.info(
        "Received ingest event",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
        },
    )

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if config.ingestion_dry_run:
        return IngestResponse(status="accepted", trace_id=trace_id)

    cloudevent_payload = _coerce_cloudevent(request, body)
    try:
        gcs_event = parse_cloudevent(cloudevent_payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage_client = storage.Client()
    firestore_client = firestore.Client()
    idempotency = FirestoreIdempotency(
        firestore_client,
        config.firestore_collection,
        processing_ttl=timedelta(seconds=config.idempotency_ttl_seconds),
    )
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
    if config.max_ingest_attempts > 0 and attempt_count >= config.max_ingest_attempts:
        logger.warning(
            "Ingest skipped: max attempts reached",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": _modality_from_name(gcs_event.name),
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

    try:
        outcome = process_event(
            event=gcs_event,
            config=config,
            storage_client=storage_client,
        )
        idempotency.mark_completed(decision.doc_id)
        duration_ms = int((time.monotonic() - start_time) * 1000)
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
            },
        )
        return IngestResponse(status=outcome.status, trace_id=trace_id)
    except PermanentError as exc:
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

    return {
        "id": header("ce-id"),
        "type": header("ce-type"),
        "source": header("ce-source"),
        "specversion": header("ce-specversion") or "1.0",
        "time": header("ce-time"),
        "subject": header("ce-subject"),
        "data": body if isinstance(body, dict) else None,
    }


def _get_dlq_publisher(topic: str | None) -> DlqPublisher | None:
    global _dlq_publisher
    if not topic:
        return None
    if _dlq_publisher is None:
        _dlq_publisher = DlqPublisher(topic)
    return _dlq_publisher


def _publish_dlq(
    publisher: DlqPublisher | None,
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
    if name.startswith("raw/docs/"):
        return "document"
    if name.startswith("raw/images/"):
        return "image"
    if name.startswith("raw/audio/"):
        return "audio"
    if name.startswith("raw/videos/"):
        return "video"
    return None
