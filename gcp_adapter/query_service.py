import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import fsspec
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from gcp_adapter.auth import authorize_internal_service_account, authorize_request
from gcp_adapter.duckdb_uri_signer import sign_gcs_uri
from gcp_adapter.metering import record_usage
from gcp_adapter.stores import (
    abac_allowed,
    get_control_plane_stores,
    is_action_allowed,
)
from retikon_core.audit import record_audit_log
from retikon_core.auth import ACTION_QUERY, AuthContext
from retikon_core.errors import InferenceTimeoutError
from retikon_core.ingestion.rate_limit import (
    RateLimitBackendError,
    RateLimitExceeded,
    enforce_rate_limit,
)
from retikon_core.logging import configure_logging, get_logger
from retikon_core.privacy import PrivacyContext, redact_text_for_context
from retikon_core.query_engine import (
    QueryResult,
    download_snapshot,
    get_secure_connection,
)
from retikon_core.query_engine.query_runner import (
    _connect as _duckdb_connect,
    _release_conn,
    _scope_filters,
    _table_has_column,
)
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
    build_query_response,
    describe_query_modality,
    resolve_modalities,
    resolve_search_type,
    run_query,
    validate_query_payload,
    warm_query_models,
)
from retikon_core.storage.paths import graph_root, join_uri, normalize_bucket_uri

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

QUERY_CONFIG = QueryServiceConfig.from_env()


@dataclass
class SnapshotState:
    local_path: str | None = None
    metadata: dict | None = None
    loaded_at: datetime | None = None


STATE = SnapshotState()


class DemoDataset(BaseModel):
    id: str
    title: str
    modality: str
    summary: str
    preview_uri: str | None = None
    source_uri: str | None = None


class DemoDatasetsResponse(BaseModel):
    datasets: list[DemoDataset]


class EvidenceFrame(BaseModel):
    uri: str | None = None
    thumbnail_uri: str | None = None
    timestamp_ms: int | None = None


class EvidenceSnippet(BaseModel):
    text: str
    uri: str | None = None
    timestamp_ms: int | None = None


class EvidenceLink(BaseModel):
    source: str
    target: str
    relation: str | None = None


class EvidenceResponse(BaseModel):
    uri: str | None = None
    signed_uri: str | None = None
    media_asset_id: str | None = None
    frames: list[EvidenceFrame] = Field(default_factory=list)
    transcript_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    doc_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    graph_links: list[EvidenceLink] = Field(default_factory=list)
    status: str = "pending"


apply_cors_middleware(app)
add_correlation_id_middleware(app)


def _graph_root_uri() -> str:
    graph_bucket, graph_prefix = _graph_settings()
    return graph_root(normalize_bucket_uri(graph_bucket, scheme="gs"), graph_prefix)


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=False,
    )


def _snapshot_reload_allow_internal_sa() -> bool:
    return os.getenv("SNAPSHOT_RELOAD_ALLOW_INTERNAL_SA", "0") == "1"


def _manifest_count(metadata: dict | None) -> int | None:
    if not metadata:
        return None
    if "manifest_count" in metadata:
        try:
            return int(metadata["manifest_count"])
        except (TypeError, ValueError):
            return None
    manifest_uris = metadata.get("manifest_uris")
    if isinstance(manifest_uris, list):
        return len({str(uri) for uri in manifest_uris})
    return None


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


def _apply_privacy_redaction(
    *,
    results: list[QueryResult],
    base_uri: str,
    scope,
    is_admin: bool,
) -> list[QueryResult]:
    try:
        policies = get_control_plane_stores(base_uri).privacy.load_policies()
    except Exception as exc:
        logger.warning(
            "Failed to load privacy policies",
            extra={"error_message": str(exc)},
        )
        return results
    if not policies:
        return results
    context = PrivacyContext(action="query", scope=scope, is_admin=is_admin)
    redacted: list[QueryResult] = []
    for item in results:
        if item.snippet is None:
            redacted.append(item)
            continue
        snippet = redact_text_for_context(
            item.snippet,
            policies=policies,
            context=context.with_modality(item.modality),
        )
        if snippet == item.snippet:
            redacted.append(item)
        else:
            redacted.append(replace(item, snippet=snippet))
    return redacted


def _metering_enabled() -> bool:
    return os.getenv("METERING_ENABLED", "0") == "1"


def _audit_logging_enabled() -> bool:
    return os.getenv("AUDIT_LOGGING_ENABLED", "1") == "1"


def _schema_version() -> str:
    return os.getenv("SCHEMA_VERSION", "1")


def _rate_limit_modality(modality: str) -> str:
    if modality in {"image", "text+image"}:
        return "image"
    if modality == "audio":
        return "audio"
    if modality == "video":
        return "video"
    return "document"


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


def _glob_files(pattern: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    if protocol in {"file", "local"}:
        return matches
    return [f"{protocol}://{match}" for match in matches]


def _manifest_uris() -> list[str]:
    graph_bucket, graph_prefix = _graph_settings()
    base_uri = graph_root(normalize_bucket_uri(graph_bucket, scheme="gs"), graph_prefix)
    manifest_glob = join_uri(base_uri, "manifests", "*", "manifest.json")
    return _glob_files(manifest_glob)


def _read_snapshot_report(snapshot_uri: str) -> dict[str, object] | None:
    meta_uri = f"{snapshot_uri}.json"
    fs, path = fsspec.core.url_to_fs(meta_uri)
    if not fs.exists(path):
        return None
    try:
        with fs.open(path, "rb") as handle:
            payload = json.loads(handle.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _index_queue_status(snapshot_uri: str | None) -> tuple[int | None, int | None, int | None]:
    try:
        manifest_count = len(_manifest_uris())
    except Exception:
        return None, None, None
    snapshot_manifest_count: int | None = None
    if snapshot_uri:
        report = _read_snapshot_report(snapshot_uri)
        if report:
            report_uris = report.get("manifest_uris")
            if isinstance(report_uris, list):
                snapshot_manifest_count = len({str(uri) for uri in report_uris})
            else:
                report_count = report.get("manifest_count")
                if report_count is not None:
                    snapshot_manifest_count = int(report_count)
    index_queue_length: int | None = None
    if snapshot_manifest_count is not None:
        index_queue_length = max(0, manifest_count - snapshot_manifest_count)
    return manifest_count, snapshot_manifest_count, index_queue_length


def _default_demo_datasets() -> list[DemoDataset]:
    return [
        DemoDataset(
            id="safety-video",
            title="Safety Training Video",
            modality="video",
            summary="Keyframes, transcript highlights, and linked incidents.",
            preview_uri=None,
            source_uri=None,
        ),
        DemoDataset(
            id="support-audio",
            title="Customer Support Call",
            modality="audio",
            summary="Speaker turns, topic clusters, and sentiment cues.",
            preview_uri=None,
            source_uri=None,
        ),
        DemoDataset(
            id="incident-docs",
            title="Security Incident Docs",
            modality="document",
            summary="Policy, log, and incident evidence stitched together.",
            preview_uri=None,
            source_uri=None,
        ),
    ]


def _load_demo_datasets() -> list[DemoDataset]:
    raw_json = os.getenv("DEMO_DATASETS_JSON")
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Invalid DEMO_DATASETS_JSON",
                extra={"error_message": str(exc)},
            )
            return _default_demo_datasets()
    else:
        path = os.getenv("DEMO_DATASETS_PATH")
        payload = None
        if path:
            candidate = Path(path)
            if candidate.exists():
                try:
                    payload = json.loads(candidate.read_text())
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Invalid DEMO_DATASETS_PATH payload",
                        extra={"error_message": str(exc)},
                    )
                    payload = None
        if payload is None:
            return _default_demo_datasets()

    if isinstance(payload, dict) and "datasets" in payload:
        payload = payload["datasets"]
    if not isinstance(payload, list):
        logger.warning(
            "Demo datasets payload must be a list",
            extra={"payload_type": type(payload).__name__},
        )
        return _default_demo_datasets()
    datasets: list[DemoDataset] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            datasets.append(DemoDataset(**item))
        except Exception as exc:
            logger.warning(
                "Skipping invalid demo dataset entry",
                extra={"error_message": str(exc)},
            )
    return datasets or _default_demo_datasets()


def _safe_query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[object],
) -> list[tuple]:
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def _apply_scope_filters(
    conn: duckdb.DuckDBPyConnection,
    scope,
    *,
    alias: str = "m",
) -> tuple[str, list[object]]:
    if scope is None or scope.is_empty():
        return "", []
    try:
        clause, params = _scope_filters(conn, scope, alias=alias)
    except ValueError:
        return "", []
    if not clause:
        return "", []
    return clause.replace("WHERE ", " AND ", 1), params


def _sign_optional(uri: str | None) -> str | None:
    if not uri:
        return None
    try:
        return sign_gcs_uri(uri)
    except Exception as exc:
        logger.warning(
            "Failed to sign GCS URI",
            extra={"error_message": str(exc), "uri": uri},
        )
        return uri


def _thumbnail_fallback_frames(
    media_asset_id: str,
    *,
    limit: int = 12,
) -> list["EvidenceFrame"]:
    graph_root_uri = _graph_root_uri()
    prefix = join_uri(graph_root_uri, "thumbnails", media_asset_id)
    try:
        fs, path = fsspec.core.url_to_fs(prefix)
        if not fs.exists(path):
            return []
        entries = fs.ls(path)
    except Exception as exc:
        logger.warning(
            "Failed to list thumbnail frames",
            extra={"error_message": str(exc), "prefix": prefix},
        )
        return []

    uris: list[str] = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else str(entry)
        if not name or name.endswith("/"):
            continue
        if name.startswith("gs://"):
            uris.append(name)
        elif prefix.startswith("gs://"):
            uris.append(f"gs://{name}")
        else:
            uris.append(name)

    uris = sorted(uris)[:limit]
    frames: list[EvidenceFrame] = []
    for uri in uris:
        frames.append(
            EvidenceFrame(
                uri=None,
                thumbnail_uri=_sign_optional(uri),
                timestamp_ms=None,
            )
        )
    return frames


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
        enabled=QUERY_CONFIG.query_warmup,
        steps=QUERY_CONFIG.query_warmup_steps,
        warmup_text=QUERY_CONFIG.query_warmup_text,
        logger=logger,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/ready")
async def ready() -> dict[str, object]:
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if not snapshot_uri:
        graph_bucket, graph_prefix = _graph_settings()
        snapshot_uri = f"gs://{graph_bucket}/{graph_prefix}/snapshots/retikon.duckdb"
    manifest_count, snapshot_manifest_count, index_queue_length = _index_queue_status(
        snapshot_uri
    )
    status = "ready"
    if snapshot_manifest_count is None:
        status = "not_ready"
    return {
        "status": status,
        "snapshot_uri": snapshot_uri,
        "snapshot_loaded_at": STATE.loaded_at.isoformat() if STATE.loaded_at else None,
        "manifest_count": manifest_count,
        "snapshot_manifest_count": snapshot_manifest_count,
        "index_queue_length": index_queue_length,
    }


@app.get("/demo/datasets", response_model=DemoDatasetsResponse)
async def demo_datasets(request: Request) -> DemoDatasetsResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_QUERY, auth_context)
    return DemoDatasetsResponse(datasets=_load_demo_datasets())


@app.get("/evidence", response_model=EvidenceResponse)
async def evidence(
    request: Request,
    uri: str | None = None,
    result_id: str | None = None,
    media_asset_id: str | None = None,
) -> EvidenceResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_QUERY, auth_context)
    target_uri = uri or result_id
    if not target_uri and not media_asset_id:
        raise HTTPException(status_code=400, detail="uri or result_id is required")
    if STATE.local_path is None:
        try:
            _load_snapshot()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Snapshot not ready") from exc
    snapshot_path = STATE.local_path
    if snapshot_path is None:
        raise HTTPException(status_code=503, detail="Snapshot not ready")

    conn = _duckdb_connect(snapshot_path)
    try:
        scope_clause, scope_params = _apply_scope_filters(
            conn,
            auth_context.scope if auth_context else None,
            alias="m",
        )
        resolved_media_asset_id = media_asset_id
        if not resolved_media_asset_id and target_uri:
            media_rows = _safe_query(
                conn,
                "SELECT id FROM media_assets m WHERE m.uri = ?" + scope_clause + " LIMIT 1",
                [target_uri, *scope_params],
            )
            if media_rows:
                resolved_media_asset_id = media_rows[0][0]

        frames: list[EvidenceFrame] = []
        transcript_snippets: list[EvidenceSnippet] = []
        doc_snippets: list[EvidenceSnippet] = []
        graph_links: list[EvidenceLink] = []

        if _table_has_column(conn, "image_assets", "media_asset_id"):
            if resolved_media_asset_id:
                image_rows = _safe_query(
                    conn,
                    "SELECT thumbnail_uri, timestamp_ms FROM image_assets "
                    "WHERE media_asset_id = ? ORDER BY timestamp_ms LIMIT 12",
                    [resolved_media_asset_id],
                )
            elif target_uri:
                image_rows = _safe_query(
                    conn,
                    "SELECT i.thumbnail_uri, i.timestamp_ms "
                    "FROM image_assets i "
                    "JOIN media_assets m ON i.media_asset_id = m.id "
                    "WHERE m.uri = ?" + scope_clause + " "
                    "ORDER BY i.timestamp_ms LIMIT 12",
                    [target_uri, *scope_params],
                )
            else:
                image_rows = []
            for thumbnail_uri, timestamp_ms in image_rows:
                frames.append(
                    EvidenceFrame(
                        uri=None,
                        thumbnail_uri=_sign_optional(thumbnail_uri),
                        timestamp_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                    )
                )
        if not frames and resolved_media_asset_id:
            frames = _thumbnail_fallback_frames(resolved_media_asset_id)

        if _table_has_column(conn, "transcripts", "media_asset_id"):
            if resolved_media_asset_id:
                transcript_rows = _safe_query(
                    conn,
                    "SELECT content, start_ms FROM transcripts "
                    "WHERE media_asset_id = ? LIMIT 8",
                    [resolved_media_asset_id],
                )
            elif target_uri:
                transcript_rows = _safe_query(
                    conn,
                    "SELECT t.content, t.start_ms "
                    "FROM transcripts t "
                    "JOIN media_assets m ON t.media_asset_id = m.id "
                    "WHERE m.uri = ?" + scope_clause + " LIMIT 8",
                    [target_uri, *scope_params],
                )
            else:
                transcript_rows = []
            for content, start_ms in transcript_rows:
                transcript_snippets.append(
                    EvidenceSnippet(
                        text=str(content),
                        uri=_sign_optional(target_uri),
                        timestamp_ms=int(start_ms) if start_ms is not None else None,
                    )
                )

        if _table_has_column(conn, "doc_chunks", "media_asset_id"):
            if resolved_media_asset_id:
                doc_rows = _safe_query(
                    conn,
                    "SELECT content FROM doc_chunks WHERE media_asset_id = ? LIMIT 6",
                    [resolved_media_asset_id],
                )
            elif target_uri:
                doc_rows = _safe_query(
                    conn,
                    "SELECT d.content "
                    "FROM doc_chunks d "
                    "JOIN media_assets m ON d.media_asset_id = m.id "
                    "WHERE m.uri = ?" + scope_clause + " LIMIT 6",
                    [target_uri, *scope_params],
                )
            else:
                doc_rows = []
            for (content,) in doc_rows:
                doc_snippets.append(
                    EvidenceSnippet(
                        text=str(content),
                        uri=_sign_optional(target_uri),
                        timestamp_ms=None,
                    )
                )
    finally:
        _release_conn(snapshot_path, conn)

    status = (
        "ready"
        if frames or transcript_snippets or doc_snippets or graph_links
        else "pending"
    )
    return EvidenceResponse(
        uri=target_uri,
        signed_uri=_sign_optional(target_uri),
        media_asset_id=resolved_media_asset_id,
        frames=frames,
        transcript_snippets=transcript_snippets,
        doc_snippets=doc_snippets,
        graph_links=graph_links,
        status=status,
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

    rate_limit_modality = _rate_limit_modality(
        describe_query_modality(payload, search_type)
    )
    try:
        enforce_rate_limit(
            rate_limit_modality,
            config=None,
            scope=scope,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RateLimitBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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
    except InferenceTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except QueryValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    trimmed = _apply_privacy_redaction(
        results=results[: payload.top_k],
        base_uri=_graph_root_uri(),
        scope=scope,
        is_admin=bool(auth_context and auth_context.is_admin),
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
                response_time_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("Failed to record usage", extra={"error_message": str(exc)})
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
    auth_context = None
    try:
        auth_context = _authorize(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    if auth_context is None and _snapshot_reload_allow_internal_sa():
        auth_context = authorize_internal_service_account(request)
    if auth_context is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not auth_context.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    graph_bucket, graph_prefix = _graph_settings()
    snapshot_uri = os.getenv("SNAPSHOT_URI") or (
        f"gs://{graph_bucket}/{graph_prefix}/snapshots/retikon.duckdb"
    )
    reload_start = time.monotonic()
    try:
        _load_snapshot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    load_ms = int((time.monotonic() - reload_start) * 1000)
    logger.info(
        "Snapshot reload complete",
        extra={
            "snapshot_uri": snapshot_uri,
            "snapshot_load_ms": load_ms,
            "manifest_count": _manifest_count(STATE.metadata),
        },
    )

    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=os.getenv("RETIKON_VERSION", "dev"),
        commit=os.getenv("GIT_COMMIT", "unknown"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
