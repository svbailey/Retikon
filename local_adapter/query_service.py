from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from retikon_core.auth.jwt import auth_context_from_claims, decode_jwt
from retikon_core.config import get_config
from retikon_core.errors import AuthError, InferenceTimeoutError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.query_engine import download_snapshot, get_secure_connection
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    add_correlation_id_middleware,
    apply_cors_middleware,
    build_health_response,
)
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


def _typed_errors_enabled() -> bool:
    return QUERY_CONFIG.search_typed_errors_enabled


def _error_code_for_status(status_code: int) -> str:
    mapping = {
        400: "VALIDATION_ERROR",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "TASK_NOT_FOUND",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        504: "TIMEOUT",
    }
    return mapping.get(status_code, "INTERNAL_ERROR")


def _typed_error_payload(
    *,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        }
    }


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
os.environ["QUERY_TRACE_HITLISTS"] = "1" if QUERY_CONFIG.query_trace_hitlists else "0"
os.environ["QUERY_TRACE_HITLIST_SIZE"] = str(QUERY_CONFIG.query_trace_hitlist_size)
os.environ["RERANK_ENABLED"] = "1" if QUERY_CONFIG.rerank_enabled else "0"
os.environ["RERANK_MODEL_NAME"] = QUERY_CONFIG.rerank_model_name
os.environ["RERANK_BACKEND"] = QUERY_CONFIG.rerank_backend
os.environ["RERANK_TOP_N"] = str(QUERY_CONFIG.rerank_top_n)
os.environ["RERANK_BATCH_SIZE"] = str(QUERY_CONFIG.rerank_batch_size)
os.environ["RERANK_QUERY_MAX_TOKENS"] = str(QUERY_CONFIG.rerank_query_max_tokens)
os.environ["RERANK_DOC_MAX_TOKENS"] = str(QUERY_CONFIG.rerank_doc_max_tokens)
os.environ["RERANK_MIN_CANDIDATES"] = str(QUERY_CONFIG.rerank_min_candidates)
os.environ["RERANK_MAX_TOTAL_CHARS"] = str(QUERY_CONFIG.rerank_max_total_chars)
os.environ["RERANK_SKIP_SCORE_GAP"] = str(QUERY_CONFIG.rerank_skip_score_gap)
os.environ["RERANK_SKIP_MIN_SCORE"] = str(QUERY_CONFIG.rerank_skip_min_score)
os.environ["RERANK_TIMEOUT_S"] = str(QUERY_CONFIG.rerank_timeout_s)
# Make rerank timeout effective with run_inference("rerank", ...).
os.environ["MODEL_INFERENCE_RERANK_TIMEOUT_S"] = str(QUERY_CONFIG.rerank_timeout_s)
if QUERY_CONFIG.rerank_onnx_model_path:
    os.environ["RERANK_ONNX_MODEL_PATH"] = QUERY_CONFIG.rerank_onnx_model_path
else:
    os.environ.pop("RERANK_ONNX_MODEL_PATH", None)
os.environ["SEARCH_GROUP_BY_ENABLED"] = (
    "1" if QUERY_CONFIG.search_group_by_enabled else "0"
)
os.environ["SEARCH_PAGINATION_ENABLED"] = (
    "1" if QUERY_CONFIG.search_pagination_enabled else "0"
)
os.environ["SEARCH_FILTERS_V1_ENABLED"] = (
    "1" if QUERY_CONFIG.search_filters_v1_enabled else "0"
)
os.environ["SEARCH_WHY_ENABLED"] = "1" if QUERY_CONFIG.search_why_enabled else "0"
os.environ["SEARCH_TYPED_ERRORS_ENABLED"] = (
    "1" if QUERY_CONFIG.search_typed_errors_enabled else "0"
)
os.environ["QUERY_FUSION_RRF_K"] = str(QUERY_CONFIG.query_fusion_rrf_k)
if QUERY_CONFIG.query_fusion_weights:
    os.environ["QUERY_FUSION_WEIGHTS"] = QUERY_CONFIG.query_fusion_weights
else:
    os.environ.pop("QUERY_FUSION_WEIGHTS", None)
os.environ["QUERY_FUSION_WEIGHT_VERSION"] = QUERY_CONFIG.query_fusion_weight_version


@dataclass
class SnapshotState:
    local_path: str | None = None
    metadata: dict | None = None
    loaded_at: datetime | None = None


STATE = SnapshotState()


apply_cors_middleware(app, default_allow_all=True)
add_correlation_id_middleware(app)


@app.exception_handler(RequestValidationError)
async def _request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    if not _typed_errors_enabled():
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    details: list[dict[str, object]] = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err.get("loc", []))
        details.append(
            {
                "field": location or "request",
                "reason": str(err.get("type", "validation_error")),
                "expected": None,
                "actual": err.get("input"),
            }
        )
    return JSONResponse(
        status_code=422,
        content=_typed_error_payload(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details or None,
        ),
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    if not _typed_errors_enabled():
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        error_payload = detail.get("error")
        if isinstance(error_payload, dict) and "details" not in error_payload:
            error_payload["details"] = []
        return JSONResponse(status_code=exc.status_code, content=detail)

    message = str(detail) if detail is not None else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_typed_error_payload(
            code=_error_code_for_status(exc.status_code),
            message=message,
        ),
    )


def _extract_bearer_tokens(request: Request) -> list[str]:
    tokens: list[str] = []
    for header_name in (
        "authorization",
        "x-forwarded-authorization",
        "x-original-authorization",
    ):
        header = request.headers.get(header_name)
        token = _parse_bearer_token(header)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _parse_bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _authorize(request: Request) -> None:
    tokens = _extract_bearer_tokens(request)
    if not tokens:
        raise HTTPException(status_code=401, detail="Unauthorized")
    last_exc: AuthError | None = None
    for token in tokens:
        try:
            claims = decode_jwt(token)
            auth_context_from_claims(claims)
            return
        except AuthError as exc:
            last_exc = exc
            continue
    raise HTTPException(status_code=401, detail="Unauthorized") from last_exc


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


def _snapshot_marker() -> str:
    metadata = STATE.metadata or {}
    for key in (
        "manifest_fingerprint",
        "snapshot_manifest_count",
        "manifest_count",
        "snapshot_uri",
    ):
        value = metadata.get(key)
        if value not in {None, ""}:
            return str(value)
    if STATE.loaded_at:
        return STATE.loaded_at.isoformat()
    return "unknown"


def _warm_query_models() -> None:
    warm_query_models(
        enabled=QUERY_CONFIG.query_warmup,
        steps=QUERY_CONFIG.query_warmup_steps,
        warmup_text=QUERY_CONFIG.query_warmup_text,
        logger=logger,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


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
        raise HTTPException(
            status_code=exc.status_code,
            detail=_typed_error_payload(
                code=exc.code,
                message=exc.detail,
                details=exc.details or None,
            ),
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
    except InferenceTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except QueryValidationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=_typed_error_payload(
                code=exc.code,
                message=exc.detail,
                details=exc.details or None,
            ),
        ) from exc

    trimmed = apply_privacy_redaction(
        results=results,
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
    try:
        return build_query_response(
            trimmed,
            payload=payload,
            snapshot_marker=_snapshot_marker(),
            trace_id=trace_id,
        )
    except QueryValidationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=_typed_error_payload(
                code=exc.code,
                message=exc.detail,
                details=exc.details or None,
            ),
        ) from exc


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
