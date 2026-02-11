from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import duckdb
import fsspec

from retikon_core.logging import configure_logging, get_logger
from retikon_core.query_engine.duckdb_auth import (
    DuckDBAuthContext,
    load_duckdb_auth_provider,
)
from retikon_core.query_engine.uri_signer import load_duckdb_uri_signer
from retikon_core.query_engine.warm_start import load_extensions
from retikon_core.storage.paths import (
    backend_scheme,
    graph_root,
    has_uri_scheme,
    join_uri,
    normalize_bucket_uri,
)

SERVICE_NAME = "retikon-index-builder"

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndexBuildReport:
    graph_uri: str
    snapshot_uri: str
    started_at: str
    completed_at: str
    duration_seconds: float
    tables: dict[str, dict[str, Any]]
    indexes: dict[str, dict[str, Any]]
    manifest_fingerprint: str | None
    manifest_count: int
    duckdb_version: str
    file_size_bytes: int
    rows_added: int | None = None
    total_rows: int | None = None
    percent_changed: float | None = None
    rows_added_by_table: dict[str, int] | None = None
    snapshot_download_seconds: float | None = None
    snapshot_upload_seconds: float | None = None
    snapshot_report_upload_seconds: float | None = None
    load_snapshot_seconds: float | None = None
    apply_deltas_seconds: float | None = None
    build_vectors_seconds: float | None = None
    hnsw_build_seconds: float | None = None
    write_snapshot_seconds: float | None = None
    upload_seconds: float | None = None
    compaction_manifest_count: int | None = None
    latest_compaction_duration_seconds: float | None = None
    manifest_uris: list[str] | None = None
    new_manifest_count: int | None = None
    index_size_delta_bytes: int | None = None
    vectors_added: int | None = None
    total_vectors: int | None = None
    snapshot_manifest_count: int | None = None
    index_queue_length: int | None = None
    skipped: bool = False


@dataclass(frozen=True)
class TableSource:
    core: list[str]
    text: list[str] | None = None
    vector: list[str] | None = None

    def ready(self) -> bool:
        if not self.core:
            return False
        if self.text is not None and not self.text:
            return False
        if self.vector is not None and not self.vector:
            return False
        return True


@dataclass(frozen=True)
class ManifestGroup:
    group_id: int
    core: str | None = None
    text: str | None = None
    vector: str | None = None


@dataclass(frozen=True)
class ManifestEntry:
    uri: str
    run_id: str
    completed_at: datetime
    is_compaction: bool
    content_hash: str
    files: tuple[dict[str, Any], ...]


def _parse_remote_uri(uri: str) -> tuple[str, str, str]:
    parsed = urlparse(uri)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Unsupported remote URI: {uri}")
    scheme = parsed.scheme
    container = parsed.netloc
    path = parsed.path.lstrip("/")
    return scheme, container, path


def _is_remote(uri: str) -> bool:
    parsed = urlparse(uri)
    return bool(parsed.scheme and parsed.netloc)


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _run_id_from_manifest_uri(uri: str) -> str:
    parsed = urlparse(uri)
    path = parsed.path if parsed.scheme else uri
    parts = path.strip("/").split("/")
    if "manifests" in parts:
        idx = parts.index("manifests")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    return "unknown"


def _manifest_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _manifest_fingerprint(entries: Iterable[ManifestEntry]) -> str | None:
    parts = sorted(f"{entry.run_id}:{entry.content_hash}" for entry in entries)
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


_TABLE_BY_VERTEX: dict[str, str] = {
    "DocChunk": "doc_chunks",
    "Transcript": "transcripts",
    "ImageAsset": "image_assets",
    "AudioClip": "audio_clips",
    "MediaAsset": "media_assets",
}


def _rows_added_by_table(manifest_uris: Iterable[str]) -> dict[str, int]:
    rows_by_table: dict[str, int] = {}
    for uri in manifest_uris:
        manifest = _read_manifest(uri)
        files = manifest.get("files")
        if not isinstance(files, list):
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            file_uri = item.get("uri")
            if not file_uri:
                continue
            info = _vertex_kind_from_uri(str(file_uri))
            if not info:
                continue
            vertex_type, file_kind = info
            if file_kind != "core":
                continue
            table = _TABLE_BY_VERTEX.get(vertex_type)
            if not table:
                continue
            rows = item.get("rows")
            if rows is None:
                continue
            try:
                rows_value = int(rows)
            except (TypeError, ValueError):
                continue
            rows_by_table[table] = rows_by_table.get(table, 0) + rows_value
    return rows_by_table


def _compaction_metrics(
    manifest_uris: Iterable[str],
) -> tuple[int, float | None]:
    count = 0
    latest_completed: datetime | None = None
    latest_duration: float | None = None
    for uri in manifest_uris:
        run_id = _run_id_from_manifest_uri(uri)
        if not run_id.startswith("compaction-"):
            continue
        count += 1
        manifest = _read_manifest(uri)
        started_at = _parse_iso(str(manifest.get("started_at") or ""))
        completed_at = _parse_iso(str(manifest.get("completed_at") or ""))
        duration = max(0.0, (completed_at - started_at).total_seconds())
        if latest_completed is None or completed_at > latest_completed:
            latest_completed = completed_at
            latest_duration = duration
    return count, latest_duration


def _select_manifest_entries(
    entries: list[ManifestEntry],
    *,
    use_latest_compaction: bool,
) -> list[ManifestEntry]:
    if not use_latest_compaction:
        return entries
    compactions = [entry for entry in entries if entry.is_compaction]
    if not compactions:
        return entries
    latest = max(compactions, key=lambda entry: entry.completed_at)
    cutoff = latest.completed_at
    return [entry for entry in entries if entry.completed_at >= cutoff]


def _glob_files(pattern: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    if protocol in {"file", "local"}:
        return matches
    return [f"{protocol}://{match}" for match in matches]


def _uri_exists(uri: str) -> bool:
    fs, path = fsspec.core.url_to_fs(uri)
    return fs.exists(path)


def _normalize_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return str(Path(parsed.path).resolve())
    if not parsed.scheme:
        return str(Path(uri).resolve())
    return uri


def _vertex_kind_from_uri(uri: str) -> tuple[str, str] | None:
    parsed = urlparse(uri)
    path = parsed.path if parsed.scheme else uri
    parts = path.strip("/").split("/")
    if "vertices" not in parts:
        return None
    idx = parts.index("vertices")
    if len(parts) <= idx + 2:
        return None
    return parts[idx + 1], parts[idx + 2]


def _read_manifest(uri: str) -> dict[str, Any]:
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "rb") as handle:
        return json.load(handle)


def _localize_manifest_uri(
    uri: str,
    *,
    local_root: Path,
    scheme: str,
    container: str,
    prefix: str,
) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != scheme or parsed.netloc != container:
        return uri
    object_path = parsed.path.lstrip("/")
    rel_path = _relative_object_path(object_path, container, prefix)
    return str(local_root / rel_path)


def _load_manifest_groups(
    base_uri: str,
    *,
    source_uri: str | None = None,
    use_latest_compaction: bool = False,
    manifest_uris: list[str] | None = None,
    skip_missing_files: bool = False,
) -> tuple[dict[str, list[ManifestGroup]], list[str], bool, str | None, int, list[str]]:
    if manifest_uris is None:
        manifest_glob = join_uri(base_uri, "manifests", "*", "manifest.json")
        manifest_uris = _glob_files(manifest_glob)
    if not manifest_uris:
        return {}, [], False, None, 0, []

    local_root = Path(base_uri).resolve()
    map_to_local = source_uri is not None and not _is_remote(base_uri)
    source_scheme = ""
    source_container = ""
    source_prefix = ""
    if map_to_local:
        if source_uri is None:
            raise ValueError("source_uri is required when mapping manifests locally")
        source_scheme, source_container, source_prefix = _parse_remote_uri(source_uri)

    entries: list[ManifestEntry] = []
    for manifest_uri in manifest_uris:
        manifest = _read_manifest(manifest_uri)
        files_raw = manifest.get("files")
        files = (
            tuple(item for item in files_raw if isinstance(item, dict))
            if isinstance(files_raw, list)
            else tuple()
        )
        run_id = _run_id_from_manifest_uri(manifest_uri)
        completed_at = _parse_iso(
            str(manifest.get("completed_at") or manifest.get("started_at") or "")
        )
        entries.append(
            ManifestEntry(
                uri=manifest_uri,
                run_id=run_id,
                completed_at=completed_at,
                is_compaction=run_id.startswith("compaction-"),
                content_hash=_manifest_hash(manifest),
                files=files,
            )
        )

    selected_entries = _select_manifest_entries(
        entries,
        use_latest_compaction=use_latest_compaction,
    )
    manifest_fingerprint = _manifest_fingerprint(selected_entries)
    manifest_count = len(selected_entries)
    selected_uris = [entry.uri for entry in selected_entries]

    groups: dict[str, list[ManifestGroup]] = {}
    counters: dict[str, int] = {}
    media_files: list[str] = []
    missing_files: list[str] = []

    for entry in selected_entries:
        by_vertex: dict[str, dict[str, str]] = {}
        for item in entry.files:
            uri = item.get("uri")
            if not uri:
                continue
            normalized = _normalize_uri(uri)
            if map_to_local:
                normalized = _localize_manifest_uri(
                    normalized,
                    local_root=local_root,
                    scheme=source_scheme,
                    container=source_container,
                    prefix=source_prefix,
                )
            if skip_missing_files and not _uri_exists(normalized):
                missing_files.append(normalized)
                continue
            duckdb_uri = _rewrite_duckdb_uri(normalized)
            info = _vertex_kind_from_uri(duckdb_uri)
            if not info:
                continue
            vertex_type, file_kind = info
            if vertex_type == "MediaAsset" and file_kind == "core":
                media_files.append(duckdb_uri)
            by_vertex.setdefault(vertex_type, {})[file_kind] = duckdb_uri

        for vertex_type, files in by_vertex.items():
            if vertex_type == "MediaAsset":
                continue
            counters[vertex_type] = counters.get(vertex_type, 0) + 1
            groups.setdefault(vertex_type, []).append(
                ManifestGroup(
                    group_id=counters[vertex_type],
                    core=files.get("core"),
                    text=files.get("text"),
                    vector=files.get("vector"),
                )
            )

    if missing_files:
        logger.warning(
            "Skipping missing GraphAr files referenced by manifests.",
            extra={
                "missing_count": len(missing_files),
                "missing_sample": missing_files[:5],
            },
        )
    return (
        groups,
        sorted(set(media_files)),
        bool(selected_entries),
        manifest_fingerprint,
        manifest_count,
        selected_uris,
    )


def _relative_object_path(path: str, container: str, prefix: str) -> str:
    if path.startswith(f"{container}/"):
        path = path[len(container) + 1 :]
    prefix = prefix.strip("/")
    if prefix and path.startswith(f"{prefix}/"):
        path = path[len(prefix) + 1 :]
    return path


def _copy_graph_to_local(base_uri: str, work_dir: str) -> str:
    _, container, prefix = _parse_remote_uri(base_uri)
    local_root = Path(work_dir).resolve() / "graph"
    local_root.mkdir(parents=True, exist_ok=True)

    def copy_pattern(pattern: str) -> None:
        fs, path = fsspec.core.url_to_fs(pattern)
        for match in fs.glob(path):
            rel_path = _relative_object_path(match, container, prefix)
            if not rel_path:
                continue
            dest = local_root / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            fs.get(match, str(dest))

    patterns = [
        join_uri(base_uri, "manifests", "*", "manifest.json"),
        join_uri(base_uri, "vertices", "DocChunk", "core", "*.parquet"),
        join_uri(base_uri, "vertices", "DocChunk", "text", "*.parquet"),
        join_uri(base_uri, "vertices", "DocChunk", "vector", "*.parquet"),
        join_uri(base_uri, "vertices", "Transcript", "core", "*.parquet"),
        join_uri(base_uri, "vertices", "Transcript", "text", "*.parquet"),
        join_uri(base_uri, "vertices", "Transcript", "vector", "*.parquet"),
        join_uri(base_uri, "vertices", "ImageAsset", "core", "*.parquet"),
        join_uri(base_uri, "vertices", "ImageAsset", "vector", "*.parquet"),
        join_uri(base_uri, "vertices", "AudioClip", "core", "*.parquet"),
        join_uri(base_uri, "vertices", "AudioClip", "vector", "*.parquet"),
        join_uri(base_uri, "vertices", "MediaAsset", "core", "*.parquet"),
    ]

    for pattern in patterns:
        copy_pattern(pattern)

    return str(local_root)


def _table_sources(base_uri: str) -> dict[str, TableSource]:
    return {
        "doc_chunks": TableSource(
            core=_glob_files(
                join_uri(base_uri, "vertices", "DocChunk", "core", "*.parquet")
            ),
            text=_glob_files(
                join_uri(base_uri, "vertices", "DocChunk", "text", "*.parquet")
            ),
            vector=_glob_files(
                join_uri(base_uri, "vertices", "DocChunk", "vector", "*.parquet")
            ),
        ),
        "transcripts": TableSource(
            core=_glob_files(
                join_uri(base_uri, "vertices", "Transcript", "core", "*.parquet")
            ),
            text=_glob_files(
                join_uri(base_uri, "vertices", "Transcript", "text", "*.parquet")
            ),
            vector=_glob_files(
                join_uri(base_uri, "vertices", "Transcript", "vector", "*.parquet")
            ),
        ),
        "image_assets": TableSource(
            core=_glob_files(
                join_uri(base_uri, "vertices", "ImageAsset", "core", "*.parquet")
            ),
            vector=_glob_files(
                join_uri(base_uri, "vertices", "ImageAsset", "vector", "*.parquet")
            ),
        ),
        "audio_clips": TableSource(
            core=_glob_files(
                join_uri(base_uri, "vertices", "AudioClip", "core", "*.parquet")
            ),
            vector=_glob_files(
                join_uri(base_uri, "vertices", "AudioClip", "vector", "*.parquet")
            ),
        ),
        "media_assets": TableSource(
            core=_glob_files(
                join_uri(base_uri, "vertices", "MediaAsset", "core", "*.parquet")
            )
        ),
    }


def _create_table(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    source: TableSource,
    sql: str,
    empty_sql: str,
    params: Iterable[object],
) -> int:
    if not source.ready():
        conn.execute(empty_sql)
        return 0
    conn.execute(sql, list(params))
    row = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _create_table_from_base(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    empty_sql: str,
) -> int:
    if _table_exists(conn, "base", table):
        conn.execute(f"CREATE TABLE {table} AS SELECT * FROM base.{table}")
    else:
        conn.execute(empty_sql)
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row is not None else 0


def _append_table_from_select(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    source: TableSource,
    create_sql: str,
) -> int:
    if not source.ready():
        return 0
    temp_table = f"{table}_new"
    marker = f"CREATE TABLE {table} AS"
    create_temp_sql = create_sql.replace(
        marker,
        f"CREATE TEMP TABLE {temp_table} AS",
        1,
    )
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(create_temp_sql)
    conn.execute(f"INSERT INTO {table} SELECT * FROM {temp_table}")
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    conn.execute(f"DROP TABLE {temp_table}")
    return int(row[0]) if row is not None else 0


def _file_size_bytes(path: str) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return p.stat().st_size


def _table_exists(
    conn: duckdb.DuckDBPyConnection,
    catalog: str,
    table: str,
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_catalog = ? AND table_name = ? LIMIT 1",
        [catalog, table],
    ).fetchone()
    return row is not None


def _download_snapshot(snapshot_uri: str, work_dir: str) -> str | None:
    parsed = urlparse(snapshot_uri)
    if not parsed.scheme or not parsed.netloc:
        path = Path(snapshot_uri)
        return str(path) if path.exists() else None
    fs, path = fsspec.core.url_to_fs(snapshot_uri)
    if not fs.exists(path):
        return None
    dest = Path(work_dir) / "base_snapshot.duckdb"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fs.get(path, str(dest))
    return str(dest)


def _write_report(report: IndexBuildReport, dest_path: str) -> None:
    Path(dest_path).write_text(json.dumps(report.__dict__, indent=2), encoding="utf-8")


def _read_snapshot_report(snapshot_uri: str) -> dict[str, Any] | None:
    meta_uri = f"{snapshot_uri}.json"
    fs, path = fsspec.core.url_to_fs(meta_uri)
    if not fs.exists(path):
        return None
    try:
        with fs.open(path, "rb") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _snapshot_manifest_count_from_report(payload: dict[str, Any]) -> int | None:
    value = payload.get("snapshot_manifest_count")
    if value is None:
        value = payload.get("manifest_count")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    uris = payload.get("manifest_uris")
    if isinstance(uris, list):
        return len(uris)
    return None


def _report_from_existing(
    payload: dict[str, Any],
    *,
    graph_uri: str,
    snapshot_uri: str,
    manifest_fingerprint: str | None,
    manifest_count: int,
) -> IndexBuildReport:
    snapshot_manifest_count = _snapshot_manifest_count_from_report(payload)
    index_queue_length = None
    if snapshot_manifest_count is not None:
        index_queue_length = max(0, manifest_count - snapshot_manifest_count)
    return IndexBuildReport(
        graph_uri=str(payload.get("graph_uri") or graph_uri),
        snapshot_uri=str(payload.get("snapshot_uri") or snapshot_uri),
        started_at=str(payload.get("started_at") or datetime.now(timezone.utc).isoformat()),
        completed_at=str(
            payload.get("completed_at") or datetime.now(timezone.utc).isoformat()
        ),
        duration_seconds=float(payload.get("duration_seconds") or 0.0),
        tables=payload.get("tables") or {},
        indexes=payload.get("indexes") or {},
        manifest_fingerprint=manifest_fingerprint or payload.get("manifest_fingerprint"),
        manifest_count=manifest_count or int(payload.get("manifest_count") or 0),
        duckdb_version=str(payload.get("duckdb_version") or duckdb.__version__),
        file_size_bytes=int(payload.get("file_size_bytes") or 0),
        rows_added=payload.get("rows_added"),
        total_rows=payload.get("total_rows"),
        percent_changed=payload.get("percent_changed"),
        rows_added_by_table=payload.get("rows_added_by_table"),
        snapshot_download_seconds=payload.get("snapshot_download_seconds"),
        snapshot_upload_seconds=payload.get("snapshot_upload_seconds"),
        snapshot_report_upload_seconds=payload.get("snapshot_report_upload_seconds"),
        load_snapshot_seconds=payload.get("load_snapshot_seconds"),
        apply_deltas_seconds=payload.get("apply_deltas_seconds"),
        build_vectors_seconds=payload.get("build_vectors_seconds"),
        hnsw_build_seconds=payload.get("hnsw_build_seconds"),
        write_snapshot_seconds=payload.get("write_snapshot_seconds"),
        upload_seconds=payload.get("upload_seconds"),
        compaction_manifest_count=payload.get("compaction_manifest_count"),
        latest_compaction_duration_seconds=payload.get("latest_compaction_duration_seconds"),
        manifest_uris=payload.get("manifest_uris"),
        new_manifest_count=payload.get("new_manifest_count"),
        index_size_delta_bytes=payload.get("index_size_delta_bytes"),
        vectors_added=payload.get("vectors_added"),
        total_vectors=payload.get("total_vectors"),
        snapshot_manifest_count=snapshot_manifest_count,
        index_queue_length=index_queue_length,
        skipped=True,
    )


def _upload_file(src_path: str, dest_uri: str) -> None:
    parsed = urlparse(dest_uri)
    if not parsed.scheme or not parsed.netloc:
        dest = Path(dest_uri)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest)
        return
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    fs.put(src_path, path)


def _rewrite_duckdb_uri(uri: str) -> str:
    signer = load_duckdb_uri_signer()
    signed = signer(uri)
    if signed != uri:
        return signed
    scheme = os.getenv("DUCKDB_GCS_URI_SCHEME")
    if scheme and uri.startswith("gs://"):
        return f"{scheme}://{uri[len('gs://'):]}"
    return uri


def _sql_list(items: Iterable[str]) -> str:
    escaped = [_rewrite_duckdb_uri(item).replace("'", "''") for item in items]
    return "[" + ", ".join(f"'{item}'" for item in escaped) + "]"


def _uri_basename(uri: str) -> str:
    parsed = urlparse(uri)
    path = parsed.path if parsed.scheme else uri
    return Path(path).name


def _filename_basename_sql(column: str) -> str:
    return f"regexp_extract({column}, '(?:.*/)?([^/?]+)(?:\\\\?.*)?$', 1)"


def _table_has_column(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    except duckdb.Error:
        return False
    return any(row[1] == column for row in rows)


def _table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    except duckdb.Error:
        return []
    return [row[1] for row in rows]


def _apply_duckdb_settings(
    conn: duckdb.DuckDBPyConnection,
    work_dir: str,
) -> dict[str, str]:
    settings: dict[str, str] = {}
    threads = os.getenv("INDEX_BUILDER_DUCKDB_THREADS") or os.getenv("DUCKDB_THREADS")
    if threads:
        conn.execute(f"PRAGMA threads={int(threads)}")
        settings["duckdb_threads"] = threads
    memory_limit = os.getenv("INDEX_BUILDER_DUCKDB_MEMORY_LIMIT") or os.getenv(
        "DUCKDB_MEMORY_LIMIT"
    )
    if memory_limit:
        conn.execute(f"PRAGMA memory_limit='{memory_limit}'")
        settings["duckdb_memory_limit"] = memory_limit
    temp_dir = os.getenv("INDEX_BUILDER_DUCKDB_TEMP_DIRECTORY") or os.getenv(
        "DUCKDB_TEMP_DIRECTORY"
    )
    if temp_dir:
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        conn.execute(f"PRAGMA temp_directory='{temp_dir}'")
        settings["duckdb_temp_directory"] = temp_dir
    return settings


def _env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _media_scope_defaults() -> dict[str, str | None]:
    return {
        "org_id": _env_optional("DEFAULT_ORG_ID"),
        "site_id": _env_optional("DEFAULT_SITE_ID"),
        "stream_id": _env_optional("DEFAULT_STREAM_ID"),
    }


def _media_assets_select(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    defaults: dict[str, str | None],
) -> str:
    columns = _table_columns(conn, table)
    select_parts: list[str] = []
    for column in columns:
        default_value = defaults.get(column)
        if default_value is not None:
            select_parts.append(
                f"COALESCE({column}, {_sql_literal(default_value)}) AS {column}"
            )
        else:
            select_parts.append(column)
    for column, default_value in defaults.items():
        if column in columns:
            continue
        if default_value is not None:
            expr = _sql_literal(default_value)
        else:
            expr = "CAST(NULL AS VARCHAR)"
        select_parts.append(f"{expr} AS {column}")
    return ", ".join(select_parts)


def build_snapshot(
    *,
    graph_uri: str,
    snapshot_uri: str,
    work_dir: str,
    copy_local: bool,
    fallback_local: bool,
    allow_install: bool,
    skip_if_unchanged: bool = False,
    use_latest_compaction: bool = False,
    incremental: bool = False,
    incremental_max_new_manifests: int | None = None,
    incremental_min_new_manifests: int | None = None,
    skip_missing_files: bool = False,
) -> IndexBuildReport:
    start = time.time()
    started_at = datetime.now(timezone.utc).isoformat()

    local_graph_uri = graph_uri
    cleanup_dir: Path | None = None
    if _is_remote(graph_uri) and copy_local:
        local_graph_uri = _copy_graph_to_local(graph_uri, work_dir)
        cleanup_dir = Path(local_graph_uri)

    db_path = Path(work_dir) / "retikon.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    prior_report = _read_snapshot_report(snapshot_uri) if (skip_if_unchanged or incremental) else None

    def build_with_base(
        base_uri: str,
        source_uri: str | None = None,
    ) -> tuple[IndexBuildReport, str]:
        (
            groups,
            media_files,
            has_manifests,
            manifest_fingerprint,
            manifest_count,
            manifest_uris,
        ) = _load_manifest_groups(
            base_uri,
            source_uri=source_uri,
            use_latest_compaction=use_latest_compaction,
            skip_missing_files=skip_missing_files,
        )
        snapshot_manifest_count = None
        index_queue_length = None
        if prior_report:
            snapshot_manifest_count = _snapshot_manifest_count_from_report(prior_report)
            if snapshot_manifest_count is not None:
                index_queue_length = max(0, manifest_count - snapshot_manifest_count)
        if skip_if_unchanged and manifest_fingerprint and prior_report:
            if prior_report.get("manifest_fingerprint") == manifest_fingerprint:
                logger.info(
                    "Index build skipped; manifests unchanged.",
                    extra={
                        "manifest_fingerprint": manifest_fingerprint,
                        "manifest_count": manifest_count,
                    },
                )
                return (
                    _report_from_existing(
                        prior_report,
                        graph_uri=base_uri,
                        snapshot_uri=snapshot_uri,
                        manifest_fingerprint=manifest_fingerprint,
                        manifest_count=manifest_count,
                    ),
                    "",
                )

        incremental_enabled = incremental
        new_manifest_uris: list[str] | None = None
        new_manifest_count: int | None = None
        if incremental_enabled and use_latest_compaction:
            if any("compaction-" in uri for uri in manifest_uris):
                incremental_enabled = False
        if incremental_enabled and prior_report:
            prior_uris = set(prior_report.get("manifest_uris") or [])
            if prior_uris:
                new_manifest_uris = [uri for uri in manifest_uris if uri not in prior_uris]
                new_manifest_count = len(new_manifest_uris)
                if new_manifest_count == 0:
                    logger.info(
                        "Index build skipped; no new manifests.",
                        extra={
                            "manifest_fingerprint": manifest_fingerprint,
                            "manifest_count": manifest_count,
                        },
                    )
                    report = _report_from_existing(
                        prior_report,
                        graph_uri=base_uri,
                        snapshot_uri=snapshot_uri,
                        manifest_fingerprint=manifest_fingerprint,
                        manifest_count=manifest_count,
                    )
                    return (replace(report, manifest_uris=manifest_uris, new_manifest_count=0), "")
                if (
                    incremental_min_new_manifests is not None
                    and incremental_min_new_manifests > 0
                    and new_manifest_count < incremental_min_new_manifests
                ):
                    logger.info(
                        "Index build deferred; new manifests below minimum.",
                        extra={
                            "new_manifest_count": new_manifest_count,
                            "min_new_manifests": incremental_min_new_manifests,
                            "manifest_count": manifest_count,
                        },
                    )
                    report = _report_from_existing(
                        prior_report,
                        graph_uri=base_uri,
                        snapshot_uri=snapshot_uri,
                        manifest_fingerprint=manifest_fingerprint,
                        manifest_count=manifest_count,
                    )
                    return (
                        replace(
                            report,
                            manifest_uris=manifest_uris,
                            new_manifest_count=new_manifest_count,
                        ),
                        "",
                    )
                if (
                    incremental_max_new_manifests is not None
                    and incremental_max_new_manifests > 0
                    and new_manifest_count > incremental_max_new_manifests
                ):
                    logger.info(
                        "Incremental index build disabled; too many new manifests.",
                        extra={
                            "new_manifest_count": new_manifest_count,
                            "manifest_count": manifest_count,
                        },
                    )
                    new_manifest_uris = None
                    new_manifest_count = None

        base_snapshot_path: str | None = None
        snapshot_download_seconds: float | None = None
        load_snapshot_seconds: float | None = None
        load_snapshot_start: float | None = None
        if new_manifest_uris:
            load_snapshot_start = time.monotonic()
            download_start = time.monotonic()
            base_snapshot_path = _download_snapshot(snapshot_uri, work_dir)
            snapshot_download_seconds = round(time.monotonic() - download_start, 2)
            if not base_snapshot_path:
                logger.warning("Incremental index build disabled; base snapshot missing.")
                new_manifest_uris = None
                new_manifest_count = None
        if new_manifest_uris:
            (
                groups,
                media_files,
                has_manifests,
                _,
                _,
                _,
            ) = _load_manifest_groups(
                base_uri,
                source_uri=source_uri,
                use_latest_compaction=use_latest_compaction,
                manifest_uris=new_manifest_uris,
                skip_missing_files=skip_missing_files,
            )

        conn = duckdb.connect(str(db_path))
        if base_snapshot_path:
            conn.execute(f"ATTACH '{base_snapshot_path}' AS base (READ_ONLY)")
            if load_snapshot_start is not None:
                load_snapshot_seconds = round(time.monotonic() - load_snapshot_start, 2)
        incremental_mode = base_snapshot_path is not None
        settings = _apply_duckdb_settings(conn, work_dir)
        if settings:
            logger.info("DuckDB settings applied.", extra=settings)
        extensions = load_extensions(conn, ("httpfs", "vss"), allow_install)
        provider = load_duckdb_auth_provider()
        context = DuckDBAuthContext(
            uris=tuple(uri for uri in (base_uri, source_uri) if uri),
            allow_install=allow_install,
        )
        auth_path, fallback_used = provider.configure(conn, context)
        conn.execute("SET hnsw_enable_experimental_persistence=true")

        apply_deltas_start = time.monotonic()
        sources = _table_sources(base_uri)
        if not has_manifests:
            if any(
                source.ready()
                for name, source in sources.items()
                if name != "media_assets"
            ):
                raise RuntimeError(
                    "No GraphAr manifests found. "
                    "Unable to align core/text/vector files."
                )
            media_files = sources["media_assets"].core
        elif not media_files:
            media_files = sources["media_assets"].core
        tables: dict[str, dict[str, Any]] = {}

        media_source = TableSource(core=media_files)
        media_rows = 0
        media_assets_empty_sql = (
            "CREATE TABLE media_assets "
            "(id VARCHAR, uri VARCHAR, media_type VARCHAR, "
            "content_type VARCHAR, org_id VARCHAR, site_id VARCHAR, "
            "stream_id VARCHAR)"
        )
        if incremental_mode:
            media_rows = _create_table_from_base(
                conn,
                "media_assets",
                media_assets_empty_sql,
            )
            if media_source.ready():
                conn.execute(
                    f"""
                    CREATE TEMP VIEW media_assets_src AS
                    SELECT *
                    FROM read_parquet({_sql_list(media_files)}, union_by_name=true)
                    """
                )
                select_list = _media_assets_select(
                    conn,
                    "media_assets_src",
                    _media_scope_defaults(),
                )
                conn.execute(
                    f"""
                    INSERT INTO media_assets
                    SELECT {select_list}
                    FROM media_assets_src
                    """
                )
                row = conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()
                if row is not None:
                    media_rows = int(row[0])
        else:
            if media_source.ready():
                conn.execute(
                    f"""
                    CREATE TEMP VIEW media_assets_src AS
                    SELECT *
                    FROM read_parquet({_sql_list(media_files)}, union_by_name=true)
                    """
                )
                select_list = _media_assets_select(
                    conn,
                    "media_assets_src",
                    _media_scope_defaults(),
                )
                conn.execute(
                    f"""
                    CREATE TABLE media_assets AS
                    SELECT {select_list}
                    FROM media_assets_src
                    """
                )
                row = conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()
                if row is not None:
                    media_rows = int(row[0])
            else:
                conn.execute(media_assets_empty_sql)
        tables["media_assets"] = {"rows": media_rows}

        doc_groups = [
            group
            for group in groups.get("DocChunk", [])
            if group.core and group.text and group.vector
        ]
        if doc_groups:
            conn.execute(
                "CREATE TEMP TABLE doc_chunk_map "
                "(group_id INTEGER, core VARCHAR, text VARCHAR, vector VARCHAR)"
            )
            conn.executemany(
                "INSERT INTO doc_chunk_map VALUES (?, ?, ?, ?)",
                [
                    (
                        group.group_id,
                        _uri_basename(group.core),
                        _uri_basename(group.text),
                        _uri_basename(group.vector),
                    )
                    for group in doc_groups
                ],
            )
            core_files = [group.core for group in doc_groups if group.core is not None]
            text_files = [group.text for group in doc_groups if group.text is not None]
            vector_files = [
                group.vector for group in doc_groups if group.vector is not None
            ]
            conn.execute(
                f"""
                CREATE TEMP VIEW doc_chunk_core AS
                SELECT m.group_id,
                       c.file_row_number AS row_number,
                       c.media_asset_id
                FROM read_parquet({_sql_list(core_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS c
                JOIN doc_chunk_map m
                  ON {_filename_basename_sql('c.filename')} = m.core
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW doc_chunk_text AS
                SELECT m.group_id,
                       t.file_row_number AS row_number,
                       t.content
                FROM read_parquet({_sql_list(text_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS t
                JOIN doc_chunk_map m
                  ON {_filename_basename_sql('t.filename')} = m.text
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW doc_chunk_vector AS
                SELECT m.group_id,
                       v.file_row_number AS row_number,
                       v.text_vector
                FROM read_parquet({_sql_list(vector_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS v
                JOIN doc_chunk_map m
                  ON {_filename_basename_sql('v.filename')} = m.vector
                """
            )
        doc_chunks_source = TableSource(
            core=[group.core for group in doc_groups if group.core is not None]
        )
        doc_chunks_create_sql = """
                CREATE TABLE doc_chunks AS
                SELECT core.media_asset_id,
                       text.content,
                       CAST(vector.text_vector AS FLOAT[768]) AS text_vector
                FROM doc_chunk_core AS core
                JOIN doc_chunk_text AS text
                  ON core.group_id = text.group_id
                 AND core.row_number = text.row_number
                JOIN doc_chunk_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """
        doc_chunks_empty_sql = """
                CREATE TABLE doc_chunks (
                  media_asset_id VARCHAR,
                  content VARCHAR,
                  text_vector FLOAT[768]
                )
                """
        if incremental_mode:
            doc_chunks_rows = _create_table_from_base(
                conn,
                "doc_chunks",
                doc_chunks_empty_sql,
            )
            appended_rows = _append_table_from_select(
                conn,
                "doc_chunks",
                doc_chunks_source,
                doc_chunks_create_sql,
            )
            if appended_rows:
                doc_chunks_rows = appended_rows
        else:
            doc_chunks_rows = _create_table(
                conn,
                "doc_chunks",
                doc_chunks_source,
                doc_chunks_create_sql,
                doc_chunks_empty_sql,
                [],
            )
        tables["doc_chunks"] = {"rows": doc_chunks_rows}

        transcript_groups = [
            group
            for group in groups.get("Transcript", [])
            if group.core and group.text and group.vector
        ]
        if transcript_groups:
            conn.execute(
                "CREATE TEMP TABLE transcript_map "
                "(group_id INTEGER, core VARCHAR, text VARCHAR, vector VARCHAR)"
            )
            conn.executemany(
                "INSERT INTO transcript_map VALUES (?, ?, ?, ?)",
                [
                    (
                        group.group_id,
                        _uri_basename(group.core),
                        _uri_basename(group.text),
                        _uri_basename(group.vector),
                    )
                    for group in transcript_groups
                ],
            )
            core_files = [
                group.core for group in transcript_groups if group.core is not None
            ]
            text_files = [
                group.text for group in transcript_groups if group.text is not None
            ]
            vector_files = [
                group.vector
                for group in transcript_groups
                if group.vector is not None
            ]
            conn.execute(
                f"""
                CREATE TEMP VIEW transcript_core AS
                SELECT m.group_id,
                       c.file_row_number AS row_number,
                       c.media_asset_id,
                       c.start_ms
                FROM read_parquet({_sql_list(core_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS c
                JOIN transcript_map m
                  ON {_filename_basename_sql('c.filename')} = m.core
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW transcript_text AS
                SELECT m.group_id,
                       t.file_row_number AS row_number,
                       t.content
                FROM read_parquet({_sql_list(text_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS t
                JOIN transcript_map m
                  ON {_filename_basename_sql('t.filename')} = m.text
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW transcript_vector AS
                SELECT m.group_id,
                       v.file_row_number AS row_number,
                       v.text_embedding
                FROM read_parquet({_sql_list(vector_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS v
                JOIN transcript_map m
                  ON {_filename_basename_sql('v.filename')} = m.vector
                """
            )
        transcript_source = TableSource(
            core=[group.core for group in transcript_groups if group.core is not None]
        )
        transcript_create_sql = """
                CREATE TABLE transcripts AS
                SELECT core.media_asset_id,
                       text.content,
                       core.start_ms,
                       CAST(vector.text_embedding AS FLOAT[768]) AS text_embedding
                FROM transcript_core AS core
                JOIN transcript_text AS text
                  ON core.group_id = text.group_id
                 AND core.row_number = text.row_number
                JOIN transcript_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """
        transcript_empty_sql = """
                CREATE TABLE transcripts (
                  media_asset_id VARCHAR,
                  content VARCHAR,
                  start_ms BIGINT,
                  text_embedding FLOAT[768]
                )
                """
        if incremental_mode:
            transcript_rows = _create_table_from_base(
                conn,
                "transcripts",
                transcript_empty_sql,
            )
            appended_rows = _append_table_from_select(
                conn,
                "transcripts",
                transcript_source,
                transcript_create_sql,
            )
            if appended_rows:
                transcript_rows = appended_rows
        else:
            transcript_rows = _create_table(
                conn,
                "transcripts",
                transcript_source,
                transcript_create_sql,
                transcript_empty_sql,
                [],
            )
        tables["transcripts"] = {"rows": transcript_rows}

        image_groups = [
            group
            for group in groups.get("ImageAsset", [])
            if group.core and group.vector
        ]
        if image_groups:
            conn.execute(
                "CREATE TEMP TABLE image_asset_map "
                "(group_id INTEGER, core VARCHAR, vector VARCHAR)"
            )
            conn.executemany(
                "INSERT INTO image_asset_map VALUES (?, ?, ?)",
                [
                    (
                        group.group_id,
                        _uri_basename(group.core),
                        _uri_basename(group.vector),
                    )
                    for group in image_groups
                ],
            )
            core_files = [
                group.core for group in image_groups if group.core is not None
            ]
            vector_files = [
                group.vector for group in image_groups if group.vector is not None
            ]
            conn.execute(
                f"""
                CREATE TEMP TABLE image_asset_core_raw AS
                SELECT *
                FROM read_parquet({_sql_list(core_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS c
                """
            )
            thumbnail_expr = (
                "c.thumbnail_uri"
                if _table_has_column(conn, "image_asset_core_raw", "thumbnail_uri")
                else "NULL AS thumbnail_uri"
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW image_asset_core AS
                SELECT m.group_id,
                       c.file_row_number AS row_number,
                       c.media_asset_id,
                       c.timestamp_ms,
                       {thumbnail_expr}
                FROM image_asset_core_raw AS c
                JOIN image_asset_map m
                  ON {_filename_basename_sql('c.filename')} = m.core
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW image_asset_vector AS
                SELECT m.group_id,
                       v.file_row_number AS row_number,
                       v.clip_vector
                FROM read_parquet({_sql_list(vector_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS v
                JOIN image_asset_map m
                  ON {_filename_basename_sql('v.filename')} = m.vector
                """
            )
        image_source = TableSource(
            core=[group.core for group in image_groups if group.core is not None]
        )
        image_create_sql = """
                CREATE TABLE image_assets AS
                SELECT core.media_asset_id,
                       core.timestamp_ms,
                       core.thumbnail_uri,
                       CAST(vector.clip_vector AS FLOAT[512]) AS clip_vector
                FROM image_asset_core AS core
                JOIN image_asset_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """
        image_empty_sql = """
                CREATE TABLE image_assets (
                  media_asset_id VARCHAR,
                  timestamp_ms BIGINT,
                  thumbnail_uri VARCHAR,
                  clip_vector FLOAT[512]
                )
                """
        if incremental_mode:
            image_rows = _create_table_from_base(
                conn,
                "image_assets",
                image_empty_sql,
            )
            appended_rows = _append_table_from_select(
                conn,
                "image_assets",
                image_source,
                image_create_sql,
            )
            if appended_rows:
                image_rows = appended_rows
        else:
            image_rows = _create_table(
                conn,
                "image_assets",
                image_source,
                image_create_sql,
                image_empty_sql,
                [],
            )
        tables["image_assets"] = {"rows": image_rows}

        audio_groups = [
            group
            for group in groups.get("AudioClip", [])
            if group.core and group.vector
        ]
        if audio_groups:
            conn.execute(
                "CREATE TEMP TABLE audio_clip_map "
                "(group_id INTEGER, core VARCHAR, vector VARCHAR)"
            )
            conn.executemany(
                "INSERT INTO audio_clip_map VALUES (?, ?, ?)",
                [
                    (
                        group.group_id,
                        _uri_basename(group.core),
                        _uri_basename(group.vector),
                    )
                    for group in audio_groups
                ],
            )
            core_files = [
                group.core for group in audio_groups if group.core is not None
            ]
            vector_files = [
                group.vector for group in audio_groups if group.vector is not None
            ]
            conn.execute(
                f"""
                CREATE TEMP VIEW audio_clip_core AS
                SELECT m.group_id,
                       c.file_row_number AS row_number,
                       c.media_asset_id
                FROM read_parquet({_sql_list(core_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS c
                JOIN audio_clip_map m
                  ON {_filename_basename_sql('c.filename')} = m.core
                """
            )
            conn.execute(
                f"""
                CREATE TEMP VIEW audio_clip_vector AS
                SELECT m.group_id,
                       v.file_row_number AS row_number,
                       v.clap_embedding
                FROM read_parquet({_sql_list(vector_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS v
                JOIN audio_clip_map m
                  ON {_filename_basename_sql('v.filename')} = m.vector
                """
            )
        audio_source = TableSource(
            core=[group.core for group in audio_groups if group.core is not None]
        )
        audio_create_sql = """
                CREATE TABLE audio_clips AS
                SELECT core.media_asset_id,
                       CAST(vector.clap_embedding AS FLOAT[512]) AS clap_embedding
                FROM audio_clip_core AS core
                JOIN audio_clip_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """
        audio_empty_sql = """
                CREATE TABLE audio_clips (
                  media_asset_id VARCHAR,
                  clap_embedding FLOAT[512]
                )
                """
        if incremental_mode:
            audio_rows = _create_table_from_base(
                conn,
                "audio_clips",
                audio_empty_sql,
            )
            appended_rows = _append_table_from_select(
                conn,
                "audio_clips",
                audio_source,
                audio_create_sql,
            )
            if appended_rows:
                audio_rows = appended_rows
        else:
            audio_rows = _create_table(
                conn,
                "audio_clips",
                audio_source,
                audio_create_sql,
                audio_empty_sql,
                [],
            )
        tables["audio_clips"] = {"rows": audio_rows}

        conn.execute("CHECKPOINT")
        apply_deltas_seconds = round(time.monotonic() - apply_deltas_start, 2)

        index_specs = [
            ("doc_chunks_text_vector", "doc_chunks", "text_vector"),
            ("transcripts_text_embedding", "transcripts", "text_embedding"),
            ("image_assets_clip_vector", "image_assets", "clip_vector"),
            ("audio_clips_clap_embedding", "audio_clips", "clap_embedding"),
        ]

        indexes: dict[str, dict[str, Any]] = {}
        prev_size = _file_size_bytes(str(db_path))
        build_vectors_start = time.monotonic()
        hnsw_build_seconds = 0.0
        index_size_delta_bytes = 0

        for index_name, table, column in index_specs:
            index_start = time.monotonic()
            conn.execute(
                f"CREATE INDEX {index_name} ON {table} USING HNSW ({column})"
            )
            conn.execute("CHECKPOINT")
            index_seconds = round(time.monotonic() - index_start, 2)
            new_size = _file_size_bytes(str(db_path))
            size_delta = max(0, new_size - prev_size)
            indexes[index_name] = {
                "table": table,
                "column": column,
                "size_bytes": size_delta,
                "build_seconds": index_seconds,
            }
            hnsw_build_seconds += index_seconds
            index_size_delta_bytes += size_delta
            prev_size = new_size

        build_vectors_seconds = round(time.monotonic() - build_vectors_start, 2)

        write_snapshot_start = time.monotonic()
        conn.execute("CHECKPOINT")
        conn.close()
        write_snapshot_seconds = round(time.monotonic() - write_snapshot_start, 2)

        rows_added_by_table = _rows_added_by_table(new_manifest_uris or manifest_uris)
        if not rows_added_by_table:
            rows_added_by_table = {
                table: int(info.get("rows") or 0) for table, info in tables.items()
            }
        rows_added = sum(rows_added_by_table.values())
        total_rows = sum(int(info.get("rows") or 0) for info in tables.values())
        percent_changed = (
            round((rows_added / total_rows) * 100.0, 2) if total_rows else 0.0
        )
        vector_tables = ("doc_chunks", "transcripts", "image_assets", "audio_clips")
        total_vectors = sum(
            int(tables.get(table, {}).get("rows") or 0) for table in vector_tables
        )
        vectors_added = None
        if rows_added_by_table:
            vectors_added = sum(
                int(rows_added_by_table.get(table, 0) or 0)
                for table in vector_tables
            )
        compaction_count, latest_compaction_duration = _compaction_metrics(manifest_uris)

        report = IndexBuildReport(
            graph_uri=base_uri,
            snapshot_uri=snapshot_uri,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(time.time() - start, 2),
            tables=tables,
            indexes=indexes,
            manifest_fingerprint=manifest_fingerprint,
            manifest_count=manifest_count,
            duckdb_version=duckdb.__version__,
            file_size_bytes=_file_size_bytes(str(db_path)),
            rows_added=rows_added,
            total_rows=total_rows,
            percent_changed=percent_changed,
            rows_added_by_table=rows_added_by_table,
            snapshot_download_seconds=snapshot_download_seconds,
            load_snapshot_seconds=load_snapshot_seconds,
            apply_deltas_seconds=apply_deltas_seconds,
            build_vectors_seconds=build_vectors_seconds,
            hnsw_build_seconds=round(hnsw_build_seconds, 2),
            write_snapshot_seconds=write_snapshot_seconds,
            compaction_manifest_count=compaction_count,
            latest_compaction_duration_seconds=latest_compaction_duration,
            manifest_uris=manifest_uris,
            new_manifest_count=new_manifest_count,
            index_size_delta_bytes=index_size_delta_bytes,
            vectors_added=vectors_added,
            total_vectors=total_vectors,
            snapshot_manifest_count=snapshot_manifest_count,
            index_queue_length=index_queue_length,
        )
        logger.info(
            "DuckDB auth initialized",
            extra={
                "duckdb_auth_path": auth_path,
                "duckdb_extension_loaded": ",".join(extensions),
                "duckdb_fallback_used": fallback_used,
            },
        )
        return report, ",".join(extensions)

    try:
        source_for_manifest = graph_uri if _is_remote(graph_uri) else None
        report, extensions = build_with_base(
            local_graph_uri,
            source_uri=source_for_manifest,
        )
    except Exception as exc:
        if _is_remote(graph_uri) and fallback_local and not copy_local:
            logger.warning(
                "Graph read failed; copying GraphAr data locally and retrying.",
                extra={"error": str(exc)},
            )
            local_graph_uri = _copy_graph_to_local(graph_uri, work_dir)
            cleanup_dir = Path(local_graph_uri)
            report, extensions = build_with_base(
                local_graph_uri,
                source_uri=graph_uri,
            )
        else:
            raise

    report_path = str(Path(work_dir) / "retikon.duckdb.json")
    if report.skipped:
        if cleanup_dir and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        return report
    _write_report(report, report_path)

    snapshot_upload_start = time.monotonic()
    _upload_file(str(db_path), snapshot_uri)
    snapshot_upload_seconds = round(time.monotonic() - snapshot_upload_start, 2)
    report = replace(
        report,
        snapshot_upload_seconds=snapshot_upload_seconds,
        upload_seconds=snapshot_upload_seconds,
    )
    _write_report(report, report_path)

    report_upload_start = time.monotonic()
    _upload_file(report_path, f"{snapshot_uri}.json")
    snapshot_report_upload_seconds = round(time.monotonic() - report_upload_start, 2)
    report = replace(
        report,
        snapshot_report_upload_seconds=snapshot_report_upload_seconds,
    )
    _write_report(report, report_path)
    _upload_file(report_path, f"{snapshot_uri}.json")

    logger.info(
        "Index build complete",
        extra={
            "snapshot_uri": snapshot_uri,
            "duckdb_extensions": extensions,
            "tables": report.tables,
            "indexes": report.indexes,
            "manifest_count": report.manifest_count,
            "new_manifest_count": report.new_manifest_count,
            "snapshot_upload_seconds": report.snapshot_upload_seconds,
            "snapshot_report_upload_seconds": report.snapshot_report_upload_seconds,
        },
    )

    if cleanup_dir and cleanup_dir.exists():
        shutil.rmtree(cleanup_dir, ignore_errors=True)

    return report


def _config_from_env() -> dict[str, Any]:
    storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    graph_uri = os.getenv("GRAPH_URI")
    if not graph_uri:
        local_graph_root = os.getenv("LOCAL_GRAPH_ROOT")
        if local_graph_root:
            graph_uri = local_graph_root
        else:
            graph_bucket = os.getenv("GRAPH_BUCKET")
            graph_prefix = os.getenv("GRAPH_PREFIX", "")
            if not graph_bucket:
                raise ValueError("GRAPH_BUCKET is required")
            scheme = backend_scheme(storage_backend)
            if scheme is None and not has_uri_scheme(graph_bucket):
                raise ValueError(
                    "GRAPH_BUCKET must include a URI scheme when STORAGE_BACKEND="
                    f"{storage_backend} (example: s3://bucket)"
                )
            graph_uri = graph_root(
                normalize_bucket_uri(graph_bucket, scheme=scheme),
                graph_prefix,
            )
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if not snapshot_uri:
        raise ValueError("SNAPSHOT_URI is required")

    incremental_max = os.getenv("INDEX_BUILDER_INCREMENTAL_MAX_NEW_MANIFESTS")
    incremental_max_value: int | None = None
    if incremental_max and incremental_max.isdigit():
        incremental_max_value = int(incremental_max)
    incremental_min = os.getenv("INDEX_BUILDER_MIN_NEW_MANIFESTS")
    incremental_min_value: int | None = None
    if incremental_min and incremental_min.isdigit():
        incremental_min_value = int(incremental_min)
    return {
        "graph_uri": graph_uri,
        "snapshot_uri": snapshot_uri,
        "work_dir": os.getenv("INDEX_BUILDER_WORK_DIR", "/tmp"),
        "copy_local": os.getenv("INDEX_BUILDER_COPY_LOCAL", "0") == "1",
        "fallback_local": os.getenv("INDEX_BUILDER_FALLBACK_LOCAL", "1") == "1",
        "allow_install": os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1",
        "skip_if_unchanged": os.getenv("INDEX_BUILDER_SKIP_IF_UNCHANGED", "0") == "1",
        "use_latest_compaction": os.getenv("INDEX_BUILDER_USE_LATEST_COMPACTION", "0")
        == "1",
        "incremental": os.getenv("INDEX_BUILDER_INCREMENTAL", "0") == "1",
        "incremental_max_new_manifests": incremental_max_value,
        "incremental_min_new_manifests": incremental_min_value,
        "skip_missing_files": os.getenv("INDEX_BUILDER_SKIP_MISSING_FILES", "0")
        == "1",
    }


def _reload_snapshot_if_requested(report: IndexBuildReport) -> None:
    if os.getenv("INDEX_BUILDER_RELOAD_SNAPSHOT", "0") != "1":
        return
    query_url = os.getenv("QUERY_SERVICE_URL", "").strip()
    if not query_url:
        logger.warning("Snapshot reload skipped; QUERY_SERVICE_URL not set.")
        return
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except Exception as exc:
        logger.warning(
            "Snapshot reload skipped; google-auth unavailable.",
            extra={"error_message": str(exc)},
        )
        return
    try:
        req = google_requests.Request()
        token = google_id_token.fetch_id_token(req, query_url)
    except Exception as exc:
        logger.warning(
            "Snapshot reload skipped; failed to fetch ID token.",
            extra={"error_message": str(exc)},
        )
        return
    if not token:
        logger.warning("Snapshot reload skipped; empty ID token.")
        return
    reload_url = f"{query_url.rstrip('/')}/admin/reload-snapshot"
    request = urllib.request.Request(
        reload_url,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            resp.read()
        logger.info(
            "Snapshot reload requested.",
            extra={
                "query_url": query_url,
                "snapshot_uri": report.snapshot_uri,
                "manifest_count": report.manifest_count,
            },
        )
    except Exception as exc:
        logger.warning(
            "Snapshot reload failed.",
            extra={"query_url": query_url, "error_message": str(exc)},
        )


def main() -> None:
    configure_logging(
        service=SERVICE_NAME,
        env=os.getenv("ENV"),
        version=os.getenv("RETIKON_VERSION"),
    )
    config = _config_from_env()
    report = build_snapshot(**config)
    _reload_snapshot_if_requested(report)


if __name__ == "__main__":
    main()
