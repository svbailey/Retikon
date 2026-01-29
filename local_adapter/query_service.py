from __future__ import annotations

import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger
from retikon_core.query_engine import download_snapshot, get_secure_connection
from retikon_core.services.query_config import QueryServiceConfig
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
from retikon_core.storage.paths import join_uri

SERVICE_NAME = "retikon-local-query"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV", "local"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    healthcheck_uri = _default_healthcheck_uri()
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
            "healthcheck_uri": healthcheck_uri,
        },
    )

    _load_snapshot()
    _warm_query_models()
    yield


app = FastAPI(lifespan=lifespan)

QUERY_CONFIG = QueryServiceConfig.from_env()


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
    return ["*"]


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
    env = os.getenv("ENV", "local").lower()
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


def _is_local_uri(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme in {"", "file"}


def _default_snapshot_uri() -> str:
    config = get_config()
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if snapshot_uri:
        return snapshot_uri
    return join_uri(config.graph_root_uri(), "snapshots", "retikon.duckdb")


def _default_healthcheck_uri() -> str | None:
    config = get_config()
    healthcheck_uri = os.getenv("DUCKDB_HEALTHCHECK_URI")
    if healthcheck_uri:
        return healthcheck_uri
    candidate = join_uri(config.graph_root_uri(), "healthcheck.parquet")
    if _is_local_uri(candidate):
        candidate_path = Path(
            urlparse(candidate).path if candidate.startswith("file") else candidate
        )
        if not candidate_path.exists():
            logger.info(
                "Local healthcheck file missing; skipping",
                extra={"path": str(candidate_path)},
            )
            return None
    return candidate


def _load_snapshot() -> None:
    snapshot_uri = _default_snapshot_uri()
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
        enabled=QUERY_CONFIG.query_warmup,
        steps=QUERY_CONFIG.query_warmup_steps,
        warmup_text=QUERY_CONFIG.query_warmup_text,
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
        if content_length > QUERY_CONFIG.max_query_bytes:
            raise HTTPException(status_code=413, detail="Request too large")

    _authorize(request)

    try:
        search_type = resolve_search_type(payload)
        modalities = resolve_modalities(payload)
        validate_query_payload(
            payload=payload,
            search_type=search_type,
            modalities=modalities,
            max_image_base64_bytes=QUERY_CONFIG.max_image_base64_bytes,
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

    timings: dict[str, float | int | str] = {}
    try:
        results = run_query(
            payload=payload,
            snapshot_path=snapshot_path,
            search_type=search_type,
            modalities=modalities,
            timings=timings,
        )
    except QueryValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    trimmed = apply_privacy_redaction(
        results=results[: payload.top_k],
        base_uri=get_config().graph_root_uri(),
        scope=None,
        is_admin=False,
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
    if QUERY_CONFIG.log_query_timings or duration_ms >= QUERY_CONFIG.slow_query_ms:
        snapshot_age_s = None
        if STATE.loaded_at:
            snapshot_age_s = round(
                (datetime.now(timezone.utc) - STATE.loaded_at).total_seconds(), 2
            )
        log_fn = (
            logger.warning
            if duration_ms >= QUERY_CONFIG.slow_query_ms
            else logger.info
        )
        log_fn(
            "Slow query"
            if duration_ms >= QUERY_CONFIG.slow_query_ms
            else "Query timings",
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
