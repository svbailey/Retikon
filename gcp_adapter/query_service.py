import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field

from retikon_core.auth import (
    ACTION_QUERY,
    AuthContext,
    abac_allowed,
    authorize_api_key,
    is_action_allowed,
)
from retikon_core.embeddings import (
    get_audio_text_embedder,
    get_image_embedder,
    get_image_text_embedder,
    get_text_embedder,
)
from retikon_core.errors import AuthError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.metering import record_usage
from retikon_core.query_engine import download_snapshot, get_secure_connection
from retikon_core.query_engine.query_runner import (
    QueryResult,
    search_by_image,
    search_by_keyword,
    search_by_metadata,
    search_by_text,
)
from retikon_core.storage.paths import graph_root

SERVICE_NAME = "retikon-query"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()

MAX_QUERY_BYTES = int(os.getenv("MAX_QUERY_BYTES", "4000000"))
MAX_IMAGE_BASE64_BYTES = int(os.getenv("MAX_IMAGE_BASE64_BYTES", "2000000"))
SLOW_QUERY_MS = int(os.getenv("SLOW_QUERY_MS", "2000"))
LOG_QUERY_TIMINGS = os.getenv("LOG_QUERY_TIMINGS", "0") == "1"
QUERY_WARMUP = os.getenv("QUERY_WARMUP", "1") == "1"
QUERY_WARMUP_TEXT = os.getenv("QUERY_WARMUP_TEXT", "retikon warmup")

ALLOWED_MODALITIES = {"document", "transcript", "image", "audio"}
ALLOWED_SEARCH_TYPES = {"vector", "keyword", "metadata"}


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


class QueryRequest(BaseModel):
    query_text: str | None = None
    image_base64: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str | None = None
    modalities: list[str] | None = None
    search_type: str | None = None
    metadata_filters: dict[str, str] | None = None


class QueryHit(BaseModel):
    modality: str
    uri: str
    snippet: str | None = None
    timestamp_ms: int | None = None
    thumbnail_uri: str | None = None
    score: float
    media_asset_id: str | None = None
    media_type: str | None = None


class QueryResponse(BaseModel):
    results: list[QueryHit]


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


def _resolve_modalities(payload: QueryRequest) -> set[str]:
    if payload.mode and payload.modalities:
        raise HTTPException(
            status_code=400,
            detail="Specify either mode or modalities, not both",
        )

    if payload.mode:
        mode = payload.mode.strip().lower()
        if mode == "text":
            return {"document", "transcript"}
        if mode == "all":
            return set(ALLOWED_MODALITIES)
        if mode == "image":
            return {"image"}
        if mode == "audio":
            return {"audio"}
        raise HTTPException(status_code=400, detail=f"Unsupported mode: {payload.mode}")

    if payload.modalities is None:
        return set(ALLOWED_MODALITIES)

    modalities = {modality.strip().lower() for modality in payload.modalities}
    if not modalities:
        raise HTTPException(status_code=400, detail="modalities cannot be empty")
    unknown = sorted(modalities - ALLOWED_MODALITIES)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown modalities: {', '.join(unknown)}",
        )
    return modalities


def _resolve_search_type(payload: QueryRequest) -> str:
    raw = payload.search_type or "vector"
    search_type = raw.strip().lower()
    if search_type not in ALLOWED_SEARCH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported search_type: {payload.search_type}",
        )
    return search_type


def _warm_query_models() -> None:
    if not QUERY_WARMUP:
        logger.info("Query model warmup skipped")
        return
    timings: dict[str, float] = {}
    try:
        start = time.monotonic()
        get_text_embedder(768).encode([QUERY_WARMUP_TEXT])
        timings["text_embed_ms"] = round((time.monotonic() - start) * 1000.0, 2)

        start = time.monotonic()
        get_image_text_embedder(512).encode([QUERY_WARMUP_TEXT])
        timings["image_text_embed_ms"] = round(
            (time.monotonic() - start) * 1000.0, 2
        )

        start = time.monotonic()
        get_audio_text_embedder(512).encode([QUERY_WARMUP_TEXT])
        timings["audio_text_embed_ms"] = round(
            (time.monotonic() - start) * 1000.0, 2
        )

        start = time.monotonic()
        dummy = Image.new("RGB", (1, 1), color=(0, 0, 0))
        get_image_embedder(512).encode([dummy])
        timings["image_embed_ms"] = round((time.monotonic() - start) * 1000.0, 2)

        logger.info("Query model warmup completed", extra={"timings": timings})
    except Exception as exc:
        logger.warning(
            "Query model warmup failed",
            extra={"error_message": str(exc), "timings": timings},
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


@app.on_event("startup")
async def startup() -> None:
    healthcheck_uri = os.getenv("DUCKDB_HEALTHCHECK_URI")
    if not healthcheck_uri:
        graph_bucket, graph_prefix = _graph_settings()
        healthcheck_uri = f"gs://{graph_bucket}/{graph_prefix}/healthcheck.parquet"

    conn = None
    healthcheck_start = time.monotonic()
    try:
        conn, _ = get_secure_connection(healthcheck_uri=healthcheck_uri)
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

    search_type = _resolve_search_type(payload)
    if (
        not payload.query_text
        and not payload.image_base64
        and search_type != "metadata"
    ):
        raise HTTPException(
            status_code=400,
            detail="query_text or image_base64 is required",
        )

    if payload.image_base64 and len(payload.image_base64) > MAX_IMAGE_BASE64_BYTES:
        raise HTTPException(status_code=413, detail="Image payload too large")
    modalities = _resolve_modalities(payload)
    if payload.image_base64 and "image" not in modalities:
        raise HTTPException(
            status_code=400,
            detail="image_base64 requires image modality",
        )
    if search_type != "vector" and payload.image_base64:
        raise HTTPException(
            status_code=400,
            detail="image_base64 is only supported for vector search",
        )
    if search_type == "keyword" and not payload.query_text:
        raise HTTPException(
            status_code=400,
            detail="query_text is required for keyword search",
        )
    if search_type == "metadata":
        if payload.query_text or payload.image_base64:
            raise HTTPException(
                status_code=400,
                detail="metadata search does not accept query_text or image_base64",
            )
        if not payload.metadata_filters:
            raise HTTPException(
                status_code=400,
                detail="metadata_filters is required for metadata search",
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

    timings: dict[str, float | int | str] = {}
    results: list[QueryResult] = []
    if search_type == "vector" and payload.query_text:
        results.extend(
            search_by_text(
                snapshot_path=snapshot_path,
                query_text=payload.query_text,
                top_k=payload.top_k,
                modalities=list(modalities),
                scope=scope,
                trace=timings,
            )
        )
    elif search_type == "keyword" and payload.query_text:
        results.extend(
            search_by_keyword(
                snapshot_path=snapshot_path,
                query_text=payload.query_text,
                top_k=payload.top_k,
                scope=scope,
                trace=timings,
            )
        )
    elif search_type == "metadata" and payload.metadata_filters:
        try:
            results.extend(
                search_by_metadata(
                    snapshot_path=snapshot_path,
                    filters=payload.metadata_filters,
                    top_k=payload.top_k,
                    scope=scope,
                    trace=timings,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.image_base64:
        try:
            results.extend(
                search_by_image(
                    snapshot_path=snapshot_path,
                    image_base64=payload.image_base64,
                    top_k=payload.top_k,
                    scope=scope,
                    trace=timings,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    results.sort(key=lambda item: item.score, reverse=True)
    trimmed = results[: payload.top_k]
    duration_ms = int((time.monotonic() - start_time) * 1000)
    if search_type == "metadata":
        modality = "metadata"
    elif search_type == "keyword":
        modality = "keyword"
    elif payload.query_text and payload.image_base64:
        modality = "text+image"
    elif payload.image_base64:
        modality = "image"
    else:
        modality = "text"
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
    return QueryResponse(
        results=[
            QueryHit(
                modality=item.modality,
                uri=item.uri,
                snippet=item.snippet,
                timestamp_ms=item.timestamp_ms,
                thumbnail_uri=item.thumbnail_uri,
                score=item.score,
                media_asset_id=item.media_asset_id,
                media_type=item.media_type,
            )
            for item in trimmed
        ]
    )


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
