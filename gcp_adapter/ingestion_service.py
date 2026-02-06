import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from google.cloud import firestore
from google.cloud import storage
from pydantic import BaseModel

from gcp_adapter.auth import authorize_request
from gcp_adapter.dlq_pubsub import PubSubDlqPublisher
from gcp_adapter.eventarc import parse_cloudevent
from gcp_adapter.idempotency_firestore import (
    FirestoreIdempotency,
    find_completed_by_checksum,
    resolve_checksum,
    update_object_metadata,
)
from gcp_adapter.metering import record_usage
from gcp_adapter.stores import abac_allowed, is_action_allowed
from retikon_core.audit import record_audit_log
from retikon_core.auth import ACTION_INGEST, AuthContext
from retikon_core.config import Config, get_config
from retikon_core.errors import PermanentError, RecoverableError, ValidationError
from retikon_core.ingestion import process_event
from retikon_core.ingestion.idempotency import build_doc_id
from retikon_core.ingestion.rate_limit import (
    RateLimitBackendError,
    RateLimitExceeded,
    enforce_rate_limit,
)
from retikon_core.ingestion.router import pipeline_version
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
                return None
            raise
    return authorize_request(
        request=request,
        require_admin=False,
    )


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


def _storage_client() -> storage.Client:
    return storage.Client()


def _firestore_client() -> firestore.Client:
    return firestore.Client()


def _apply_checksum_dedupe(
    *,
    client: firestore.Client,
    collection: str,
    doc_id: str,
    bucket: str,
    name: str,
    checksum: str | None,
) -> bool:
    if not checksum:
        return False
    try:
        match = find_completed_by_checksum(
            client=client,
            collection=collection,
            checksum=checksum,
            bucket=bucket,
            name=name,
        )
    except Exception as exc:
        logger.warning(
            "Checksum dedupe lookup failed",
            extra={
                "bucket": bucket,
                "name": name,
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
                scope=auth_context.scope if auth_context else _default_scope(config),
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
                scope=auth_context.scope if auth_context else _default_scope(config),
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
    modality = _modality_from_name(gcs_event.name)
    if modality is None:
        raise HTTPException(status_code=400, detail="Unsupported modality")
    scope = auth_context.scope if auth_context else _default_scope(config)

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

    try:
        try:
            if _apply_checksum_dedupe(
                client=firestore_client,
                collection=config.firestore_collection,
                doc_id=decision.doc_id,
                bucket=gcs_event.bucket,
                name=gcs_event.name,
                checksum=checksum,
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
            enforce_rate_limit(modality, config=config, scope=scope)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except RateLimitBackendError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        outcome = process_event(
            event=gcs_event,
            config=config,
            rate_limit_scope=scope,
            skip_rate_limit=True,
        )
        idempotency.mark_completed(decision.doc_id)
        firestore_client.collection(config.firestore_collection).document(
            decision.doc_id
        ).update(
            {
                "manifest_uri": outcome.manifest_uri,
                "media_asset_id": outcome.media_asset_id,
                "counts": outcome.counts,
            }
        )
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
        if _metering_enabled():
            scope = auth_context.scope if auth_context else _default_scope(config)
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
    if name.startswith("raw/docs/"):
        return "document"
    if name.startswith("raw/images/"):
        return "image"
    if name.startswith("raw/audio/"):
        return "audio"
    if name.startswith("raw/videos/"):
        return "video"
    return None
