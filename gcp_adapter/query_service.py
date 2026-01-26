import os
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from retikon_core.logging import configure_logging, get_logger
from retikon_core.query_engine import download_snapshot, get_secure_connection
from retikon_core.query_engine.query_runner import (
    QueryResult,
    search_by_image,
    search_by_text,
)

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


def _authorize(request: Request) -> None:
    api_key = _get_api_key()
    if not api_key:
        if _api_key_required():
            raise HTTPException(status_code=500, detail="QUERY_API_KEY is required")
        return
    header_key = request.headers.get("x-api-key")
    if not header_key or not secrets.compare_digest(header_key, api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    snapshot = download_snapshot(snapshot_uri)
    STATE.local_path = snapshot.local_path
    STATE.metadata = snapshot.metadata
    STATE.loaded_at = datetime.now(timezone.utc)
    logger.info(
        "Snapshot loaded",
        extra={
            "snapshot_path": STATE.local_path,
            "snapshot_loaded_at": STATE.loaded_at.isoformat()
            if STATE.loaded_at
            else None,
            "snapshot_metadata": STATE.metadata,
        },
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
    try:
        conn, _ = get_secure_connection(healthcheck_uri=healthcheck_uri)
    finally:
        if conn is not None:
            conn.close()

    _load_snapshot()


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

    _authorize(request)

    if not payload.query_text and not payload.image_base64:
        raise HTTPException(
            status_code=400,
            detail="query_text or image_base64 is required",
        )

    if payload.image_base64 and len(payload.image_base64) > MAX_IMAGE_BASE64_BYTES:
        raise HTTPException(status_code=413, detail="Image payload too large")

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

    results: list[QueryResult] = []
    if payload.query_text:
        results.extend(
            search_by_text(
                snapshot_path=snapshot_path,
                query_text=payload.query_text,
                top_k=payload.top_k,
            )
        )
    if payload.image_base64:
        try:
            results.extend(
                search_by_image(
                    snapshot_path=snapshot_path,
                    image_base64=payload.image_base64,
                    top_k=payload.top_k,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    results.sort(key=lambda item: item.score, reverse=True)
    trimmed = results[: payload.top_k]
    duration_ms = int((time.monotonic() - start_time) * 1000)
    if payload.query_text and payload.image_base64:
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
    _authorize(request)

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
