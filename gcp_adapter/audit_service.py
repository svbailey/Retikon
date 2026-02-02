import csv
import io
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, Iterator

import duckdb
import fsspec
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from gcp_adapter.auth import authorize_request
from gcp_adapter.stores import abac_allowed, get_control_plane_stores, is_action_allowed
from retikon_core.auth import AuthContext
from retikon_core.auth.rbac import (
    ACTION_ACCESS_EXPORT,
    ACTION_AUDIT_EXPORT,
    ACTION_AUDIT_LOGS_READ,
)
from retikon_core.logging import configure_logging, get_logger
from retikon_core.privacy import (
    PrivacyContext,
    PrivacyPolicy,
    redact_text_for_context,
)
from retikon_core.query_engine.warm_start import get_secure_connection
from retikon_core.services.fastapi_scaffolding import (
    apply_cors_middleware,
    build_health_response,
)
from retikon_core.storage.paths import graph_root, join_uri, normalize_bucket_uri

SERVICE_NAME = "retikon-audit"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    base_uri = _graph_uri()
    healthcheck_uri = _healthcheck_uri(base_uri)
    if healthcheck_uri:
        conn = None
        start = time.monotonic()
        try:
            conn = _open_conn(base_uri)
        finally:
            if conn is not None:
                conn.close()
        logger.info(
            "DuckDB healthcheck completed",
            extra={"healthcheck_ms": int((time.monotonic() - start) * 1000)},
        )
    yield


app = FastAPI(lifespan=lifespan)
apply_cors_middleware(app)


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("AUDIT_REQUIRE_ADMIN", default) == "1"


def _diagnostics_enabled() -> bool:
    return os.getenv("AUDIT_DIAGNOSTICS", "0") == "1"


def _parquet_limit() -> int | None:
    raw = os.getenv("AUDIT_PARQUET_LIMIT", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _log_diag(message: str, *, extra: dict[str, object]) -> None:
    if _diagnostics_enabled():
        logger.info(message, extra={"timings": extra})


def _graph_uri() -> str:
    graph_uri = os.getenv("GRAPH_URI")
    if graph_uri:
        return graph_uri
    graph_bucket = os.getenv("GRAPH_BUCKET")
    graph_prefix = os.getenv("GRAPH_PREFIX", "")
    if graph_bucket:
        return graph_root(normalize_bucket_uri(graph_bucket, scheme="gs"), graph_prefix)
    local_root = os.getenv("LOCAL_GRAPH_ROOT")
    if local_root:
        return local_root
    raise HTTPException(status_code=500, detail="Missing GRAPH_URI or GRAPH_BUCKET")


def _healthcheck_uri(base_uri: str) -> str | None:
    override = os.getenv("DUCKDB_HEALTHCHECK_URI")
    if override:
        return override
    if base_uri.startswith("gs://"):
        return join_uri(base_uri, "healthcheck.parquet")
    return None


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=_require_admin(),
    )


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _enforce_access(
    action: str,
    auth_context: AuthContext | None,
) -> None:
    base_uri = _graph_uri()
    if _rbac_enabled() and not is_action_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")
    if _abac_enabled() and not abac_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")


def _open_conn(base_uri: str) -> duckdb.DuckDBPyConnection:
    conn, _ = get_secure_connection(healthcheck_uri=_healthcheck_uri(base_uri))
    return conn


def _glob_exists(uri_pattern: str) -> bool:
    fs, path = fsspec.core.url_to_fs(uri_pattern)
    return bool(fs.glob(path))


def _open_local_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def _resolve_parquet_files(
    uri_pattern: str,
) -> tuple[list[str], tempfile.TemporaryDirectory | None]:
    fs, path = fsspec.core.url_to_fs(uri_pattern)
    glob_start = time.monotonic()
    matches = sorted(fs.glob(path))
    glob_ms = int((time.monotonic() - glob_start) * 1000)
    original_count = len(matches)
    limit = _parquet_limit()
    if limit is not None:
        matches = matches[:limit]
    _log_diag(
        "Audit parquet globbed",
        extra={
            "glob_ms": glob_ms,
            "match_count": original_count,
            "limit": limit,
            "selected_count": len(matches),
        },
    )
    if not matches:
        return [], None

    protocol = fs.protocol
    if isinstance(protocol, (list, tuple, set)):
        protocol = next(iter(protocol), None)

    if protocol in {None, "file"}:
        return matches, None

    tmpdir = tempfile.TemporaryDirectory(prefix="retikon-audit-")
    local_paths: list[str] = []
    download_start = time.monotonic()
    for remote_path in matches:
        filename = os.path.basename(remote_path)
        local_path = os.path.join(tmpdir.name, filename)
        fs.get(remote_path, local_path)
        local_paths.append(local_path)
    download_ms = int((time.monotonic() - download_start) * 1000)
    _log_diag(
        "Audit parquet download completed",
        extra={"file_count": len(local_paths), "download_ms": download_ms},
    )
    return local_paths, tmpdir


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _serialize_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _redact_record(
    record: dict[str, object],
    *,
    policies: list[PrivacyPolicy] | None,
    context: PrivacyContext | None,
) -> dict[str, object]:
    if not policies or context is None:
        return record
    updated: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, str):
            updated[key] = redact_text_for_context(
                value,
                policies=policies,
                context=context,
            )
        else:
            updated[key] = value
    return updated


def _build_filters(
    *,
    org_id: str | None,
    site_id: str | None,
    stream_id: str | None,
    api_key_id: str | None,
    action: str | None,
    decision: str | None,
    since: datetime | None,
    until: datetime | None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    values: list[object] = []
    if org_id:
        clauses.append("org_id = ?")
        values.append(org_id)
    if site_id:
        clauses.append("site_id = ?")
        values.append(site_id)
    if stream_id:
        clauses.append("stream_id = ?")
        values.append(stream_id)
    if api_key_id:
        clauses.append("api_key_id = ?")
        values.append(api_key_id)
    if action:
        clauses.append("action = ?")
        values.append(action)
    if decision:
        clauses.append("decision = ?")
        values.append(decision)
    if since is not None:
        clauses.append("created_at >= ?")
        values.append(since)
    if until is not None:
        clauses.append("created_at <= ?")
        values.append(until)
    return clauses, values


def _query_rows(
    *,
    uri_pattern: str,
    where_clauses: list[str],
    values: list[object],
    limit: int | None,
) -> list[dict[str, object]]:
    local_paths, tmpdir = _resolve_parquet_files(uri_pattern)
    if not local_paths:
        return []
    conn = _open_local_conn()
    try:
        query = "SELECT * FROM read_parquet(?, union_by_name=true)"
        params: list[object] = [local_paths]
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
            params.extend(values)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        query_start = time.monotonic()
        cursor = conn.execute(query, params)
        query_ms = int((time.monotonic() - query_start) * 1000)
        description = cursor.description or []
        columns = [col[0] for col in description]
        rows = cursor.fetchall()
        _log_diag(
            "Audit parquet query completed",
            extra={
                "query_ms": query_ms,
                "file_count": len(local_paths),
                "row_count": len(rows),
                "limit": limit,
            },
        )
    finally:
        conn.close()
        if tmpdir is not None:
            tmpdir.cleanup()
    output: list[dict[str, object]] = []
    for row in rows:
        record = dict(zip(columns, row, strict=False))
        output.append({key: _serialize_value(value) for key, value in record.items()})
    return output


def _stream_query(
    *,
    uri_pattern: str,
    where_clauses: list[str],
    values: list[object],
    format: str,
    policies: list[PrivacyPolicy] | None = None,
    privacy_context: PrivacyContext | None = None,
) -> Iterator[str]:
    local_paths, tmpdir = _resolve_parquet_files(uri_pattern)
    if not local_paths:
        return iter(())
    conn = _open_local_conn()
    query = "SELECT * FROM read_parquet(?, union_by_name=true)"
    params: list[object] = [local_paths]
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
        params.extend(values)
    query += " ORDER BY created_at DESC"
    query_start = time.monotonic()
    cursor = conn.execute(query, params)
    query_ms = int((time.monotonic() - query_start) * 1000)
    _log_diag(
        "Audit parquet stream query started",
        extra={"query_ms": query_ms, "file_count": len(local_paths)},
    )
    description = cursor.description or []
    columns = [col[0] for col in description]

    def _write_csv_row(row: Iterable[object]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(row)
        return output.getvalue()

    def _iter_rows() -> Iterator[str]:
        try:
            if format == "csv":
                yield _write_csv_row(columns)
                while True:
                    batch = cursor.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        record = {
                            col: _serialize_value(value)
                            for col, value in zip(columns, row, strict=False)
                        }
                        redacted = _redact_record(
                            record,
                            policies=policies,
                            context=privacy_context,
                        )
                        yield _write_csv_row([redacted[col] for col in columns])
            else:
                while True:
                    batch = cursor.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        record = {
                            col: _serialize_value(value)
                            for col, value in zip(columns, row, strict=False)
                        }
                        redacted = _redact_record(
                            record,
                            policies=policies,
                            context=privacy_context,
                        )
                        yield json.dumps(redacted) + "\n"
        finally:
            conn.close()
            if tmpdir is not None:
                tmpdir.cleanup()

    return _iter_rows()


def _audit_pattern(base_uri: str) -> str:
    return join_uri(base_uri, "vertices", "AuditLog", "core", "*.parquet")


def _usage_pattern(base_uri: str) -> str:
    return join_uri(base_uri, "vertices", "UsageEvent", "core", "*.parquet")


def _privacy_context(
    auth_context: AuthContext | None,
    action: str,
) -> PrivacyContext:
    return PrivacyContext(
        action=action,
        scope=auth_context.scope if auth_context else None,
        is_admin=bool(auth_context and auth_context.is_admin),
    )


def _privacy_policies(base_uri: str) -> list[PrivacyPolicy]:
    try:
        return get_control_plane_stores(base_uri).privacy.load_policies()
    except Exception as exc:
        logger.warning(
            "Failed to load privacy policies",
            extra={"error_message": str(exc)},
        )
        return []

@app.get("/health")
async def health() -> dict[str, str]:
    return build_health_response(SERVICE_NAME).model_dump()


@app.get("/audit/logs")
async def audit_logs(
    request: Request,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    api_key_id: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_AUDIT_LOGS_READ, auth_context)
    base_uri = _graph_uri()
    limit = max(1, min(limit, 1000))
    where, values = _build_filters(
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        api_key_id=api_key_id,
        action=action,
        decision=decision,
        since=_parse_timestamp(since),
        until=_parse_timestamp(until),
    )
    rows = _query_rows(
        uri_pattern=_audit_pattern(base_uri),
        where_clauses=where,
        values=values,
        limit=limit,
    )
    return {"count": len(rows), "rows": rows}


@app.get("/audit/export")
async def audit_export(
    request: Request,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    api_key_id: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    since: str | None = None,
    until: str | None = None,
    format: str = "jsonl",
) -> StreamingResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_AUDIT_EXPORT, auth_context)
    base_uri = _graph_uri()
    privacy_policies = _privacy_policies(base_uri)
    privacy_ctx = _privacy_context(auth_context, "export")
    since_ts = _parse_timestamp(since)
    until_ts = _parse_timestamp(until)
    where, values = _build_filters(
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        api_key_id=api_key_id,
        action=action,
        decision=decision,
        since=since_ts,
        until=until_ts,
    )
    fmt = format.lower()
    if fmt not in {"jsonl", "csv"}:
        raise HTTPException(status_code=400, detail="format must be jsonl or csv")
    generator = _stream_query(
        uri_pattern=_audit_pattern(base_uri),
        where_clauses=where,
        values=values,
        format=fmt,
        policies=privacy_policies,
        privacy_context=privacy_ctx,
    )
    media_type = "application/json" if fmt == "jsonl" else "text/csv"
    return StreamingResponse(generator, media_type=media_type)


@app.get("/access/export")
async def access_export(
    request: Request,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    api_key_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    format: str = "jsonl",
) -> StreamingResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_ACCESS_EXPORT, auth_context)
    base_uri = _graph_uri()
    privacy_policies = _privacy_policies(base_uri)
    privacy_ctx = _privacy_context(auth_context, "export")
    since_ts = _parse_timestamp(since)
    until_ts = _parse_timestamp(until)
    where, values = _build_filters(
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        api_key_id=api_key_id,
        action=None,
        decision=None,
        since=since_ts,
        until=until_ts,
    )
    if event_type:
        where.append("event_type = ?")
        values.append(event_type)
    fmt = format.lower()
    if fmt not in {"jsonl", "csv"}:
        raise HTTPException(status_code=400, detail="format must be jsonl or csv")
    generator = _stream_query(
        uri_pattern=_usage_pattern(base_uri),
        where_clauses=where,
        values=values,
        format=fmt,
        policies=privacy_policies,
        privacy_context=privacy_ctx,
    )
    media_type = "application/json" if fmt == "jsonl" else "text/csv"
    return StreamingResponse(generator, media_type=media_type)
