import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from retikon_core.audit import record_audit_log
from retikon_core.auth import (
    ACTION_QUERY,
    AuthContext,
    abac_allowed,
    authorize_api_key,
    is_action_allowed,
)
from retikon_core.errors import AuthError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.metering import record_usage
from retikon_core.query_engine import download_snapshot, get_secure_connection
from retikon_core.services.query_service_core import (
    QueryRequest,
    QueryResponse,
    QueryValidationError,
    apply_privacy_redaction,
    build_query_response,
    describe_query_modality,
    resolve_modalities,
    resolve_search_type,
    run_query,
    validate_query_payload,
    warm_query_models,
)
from retikon_core.storage.paths import graph_root

SERVICE_NAME = "retikon-query"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    healthcheck_uri = os.getenv("DUCKDB_HEALTHCHECK_URI")
    if not healthcheck_uri:
        graph_bucket, graph_prefix = _graph_settings()
        healthcheck_uri = f"gs://{graph_bucket}/{graph_prefix}/healthcheck.parquet"

    conn = None
    healthcheck_start = time.monotonic()
    try:
        conn, _auth = get_secure_connection(healthcheck_uri=healthcheck_uri)
    finally:
        if conn is not None:
            conn.close()
    logger.info(
        "DuckDB healthcheck completed",
        extra={
            "healthcheck_ms": int((time.monotonic() - healthcheck_start) * 1000),
        },
    )

    _load_snapshot()
    _warm_query_models()
    yield


app = FastAPI(lifespan=lifespan)

MAX_QUERY_BYTES = int(os.getenv("MAX_QUERY_BYTES", "4000000"))
MAX_IMAGE_BASE64_BYTES = int(os.getenv("MAX_IMAGE_BASE64_BYTES", "2000000"))
SLOW_QUERY_MS = int(os.getenv("SLOW_QUERY_MS", "2000"))
LOG_QUERY_TIMINGS = os.getenv("LOG_QUERY_TIMINGS", "0") == "1"
QUERY_WARMUP = os.getenv("QUERY_WARMUP", "1") == "1"
QUERY_WARMUP_TEXT = os.getenv("QUERY_WARMUP_TEXT", "retikon warmup")
QUERY_WARMUP_STEPS = {
    step.strip().lower()
    for step in os.getenv(
        "QUERY_WARMUP_STEPS",
        "text,image_text,audio_text,image",
    ).split(",")
    if step.strip()
}


@dataclass
class SnapshotState:
    local_path: str | None = None
    metadata: dict | None = None
    loaded_at: datetime | None = None


STATE = SnapshotState()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


def _correlation_id(header_value: str | None) -> str:
    if header_value:
        return header_value
    return str(uuid.uuid4())


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    env = os.getenv("ENV", "dev").lower()
    if env in {"dev", "local", "test"}:
        return ["*"]
    return []


_cors = _cors_origins()
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    corr = _correlation_id(request.headers.get("x-correlation-id"))
    request.state.correlation_id = corr
    response = await call_next(request)
    response.headers["x-correlation-id"] = corr
    return response


def _api_key_required() -> bool:
    env = os.getenv("ENV", "dev").lower()
    return env not in {"dev", "local", "test"}


def _get_api_key() -> str | None:
    return os.getenv("QUERY_API_KEY")


def _graph_root_uri() -> str:
    graph_bucket, graph_prefix = _graph_settings()
    return graph_root(graph_bucket, graph_prefix)


def _authorize(request: Request) -> AuthContext | None:
    api_key = _get_api_key()
    raw_key = request.headers.get("x-api-key")
    try:
        context = authorize_api_key(
            base_uri=_graph_root_uri(),
            raw_key=raw_key,
            fallback_key=api_key,
            require=_api_key_required(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    return context


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _enforce_access(action: str, auth_context: AuthContext | None) -> None:
    base_uri = _graph_root_uri()
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


def _graph_settings() -> tuple[str, str]:
    graph_bucket = os.getenv("GRAPH_BUCKET")
    graph_prefix = os.getenv("GRAPH_PREFIX")
    missing = []
    if not graph_bucket:
        missing.append("GRAPH_BUCKET")
    if not graph_prefix:
        missing.append("GRAPH_PREFIX")
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    assert graph_bucket is not None
    assert graph_prefix is not None
    return graph_bucket, graph_prefix


def _load_snapshot() -> None:
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if not snapshot_uri:
        graph_bucket, graph_prefix = _graph_settings()
        snapshot_uri = f"gs://{graph_bucket}/{graph_prefix}/snapshots/retikon.duckdb"
    start = time.monotonic()
    snapshot = download_snapshot(snapshot_uri)
    load_ms = int((time.monotonic() - start) * 1000)
    STATE.local_path = snapshot.local_path
    STATE.metadata = snapshot.metadata
    STATE.loaded_at = datetime.now(timezone.utc)
    snapshot_size = None
    if snapshot.local_path:
        try:
            snapshot_size = os.path.getsize(snapshot.local_path)
        except OSError:
            snapshot_size = None
    logger.info(
        "Snapshot loaded",
        extra={
            "snapshot_path": STATE.local_path,
            "snapshot_loaded_at": STATE.loaded_at.isoformat()
            if STATE.loaded_at
            else None,
            "snapshot_metadata": STATE.metadata,
            "snapshot_load_ms": load_ms,
            "snapshot_size_bytes": snapshot_size,
        },
    )


def _warm_query_models() -> None:
    warm_query_models(
        enabled=QUERY_WARMUP,
        steps=QUERY_WARMUP_STEPS,
        warmup_text=QUERY_WARMUP_TEXT,
        logger=logger,
    )


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


@app.post("/query", response_model=QueryResponse)
async def query(
    request: Request,
    payload: QueryRequest,
    x_request_id: str | None = Header(default=None),
) -> QueryResponse:
    start_time = time.monotonic()
    if request.headers.get("content-length"):
        content_length = int(request.headers["content-length"])
        if content_length > MAX_QUERY_BYTES:
            raise HTTPException(status_code=413, detail="Request too large")

    auth_context = _authorize(request)
    _enforce_access(ACTION_QUERY, auth_context)
    scope = auth_context.scope if auth_context else None

    try:
        search_type = resolve_search_type(payload)
        modalities = resolve_modalities(payload)
        validate_query_payload(
            payload=payload,
            search_type=search_type,
            modalities=modalities,
            max_image_base64_bytes=MAX_IMAGE_BASE64_BYTES,
        )
    except QueryValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if (
        not payload.query_text
        and not payload.image_base64
        and search_type != "metadata"
    ):
        raise HTTPException(
            status_code=400,
            detail="query_text or image_base64 is required",
        )

    if STATE.local_path is None:
        try:
            _load_snapshot()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Snapshot not ready") from exc
    snapshot_path = STATE.local_path
    if snapshot_path is None:
        raise HTTPException(status_code=503, detail="Snapshot not ready")

    trace_id = x_request_id or str(uuid.uuid4())
    logger.info(
        "Received query",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
        },
    )
    if _audit_logging_enabled():
        try:
            record_audit_log(
                base_uri=_graph_root_uri(),
                action=ACTION_QUERY,
                decision="allow",
                auth_context=auth_context,
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

    timings: dict[str, float | int | str] = {}
    try:
        results = run_query(
            payload=payload,
            snapshot_path=snapshot_path,
            search_type=search_type,
            modalities=modalities,
            scope=scope,
            timings=timings,
        )
    except QueryValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    trimmed = apply_privacy_redaction(
        results=results[: payload.top_k],
        base_uri=_graph_root_uri(),
        scope=scope,
        is_admin=bool(auth_context and auth_context.is_admin),
        logger=logger,
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)
    modality = describe_query_modality(payload, search_type)
    logger.info(
        "Query completed",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
            "modality": modality,
            "processing_ms": duration_ms,
            "duration_ms": duration_ms,
        },
    )
    if _metering_enabled():
        payload_bytes = None
        if request.headers.get("content-length"):
            try:
                payload_bytes = int(request.headers["content-length"])
            except ValueError:
                payload_bytes = None
        if payload_bytes is None:
            payload_bytes = len(payload.model_dump_json().encode("utf-8"))
        try:
            record_usage(
                base_uri=_graph_root_uri(),
                event_type="query",
                scope=scope,
                api_key_id=auth_context.api_key_id if auth_context else None,
                modality=modality,
                units=1,
                bytes_in=payload_bytes,
                pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
                schema_version=_schema_version(),
            )
        except Exception as exc:
            logger.warning("Failed to record usage", extra={"error_message": str(exc)})
    if LOG_QUERY_TIMINGS or duration_ms >= SLOW_QUERY_MS:
        snapshot_age_s = None
        if STATE.loaded_at:
            snapshot_age_s = round(
                (datetime.now(timezone.utc) - STATE.loaded_at).total_seconds(), 2
            )
        log_fn = logger.warning if duration_ms >= SLOW_QUERY_MS else logger.info
        log_fn(
            "Slow query" if duration_ms >= SLOW_QUERY_MS else "Query timings",
            extra={
                "request_id": trace_id,
                "correlation_id": request.state.correlation_id,
                "modality": modality,
                "duration_ms": duration_ms,
                "top_k": payload.top_k,
                "snapshot_loaded_at": STATE.loaded_at.isoformat()
                if STATE.loaded_at
                else None,
                "snapshot_age_s": snapshot_age_s,
                "snapshot_path": snapshot_path,
                "timings": timings,
            },
        )
    return build_query_response(trimmed, payload.top_k)


@app.post("/admin/reload-snapshot", response_model=HealthResponse)
async def reload_snapshot(request: Request) -> HealthResponse:
    auth_context = _authorize(request)
    if auth_context and not auth_context.is_admin:
        raise HTTPException(status_code=403, detail="Admin API key required")

    try:
        _load_snapshot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=os.getenv("RETIKON_VERSION", "dev"),
        commit=os.getenv("GIT_COMMIT", "unknown"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
