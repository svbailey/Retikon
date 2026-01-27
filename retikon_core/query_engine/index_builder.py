from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import duckdb
import fsspec

from retikon_core.logging import configure_logging, get_logger
from retikon_core.query_engine.warm_start import load_extensions
from retikon_core.storage.paths import graph_root, join_uri

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
    duckdb_version: str
    file_size_bytes: int


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


def _parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc:
        raise ValueError(f"Unsupported GCS URI: {uri}")
    bucket = parsed.netloc
    path = parsed.path.lstrip("/")
    return bucket, path


def _is_remote(uri: str) -> bool:
    parsed = urlparse(uri)
    return bool(parsed.scheme and parsed.netloc)


def _glob_files(pattern: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    if protocol in {"file", "local"}:
        return matches
    return [f"{protocol}://{match}" for match in matches]


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
    bucket: str,
    prefix: str,
) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or parsed.netloc != bucket:
        return uri
    object_path = parsed.path.lstrip("/")
    rel_path = _relative_object_path(object_path, bucket, prefix)
    return str(local_root / rel_path)


def _load_manifest_groups(
    base_uri: str,
    *,
    source_uri: str | None = None,
) -> tuple[dict[str, list[ManifestGroup]], list[str], bool]:
    manifest_glob = join_uri(base_uri, "manifests", "*", "manifest.json")
    manifest_uris = _glob_files(manifest_glob)
    if not manifest_uris:
        return {}, [], False

    local_root = Path(base_uri).resolve()
    map_to_local = source_uri is not None and not _is_remote(base_uri)
    source_bucket = ""
    source_prefix = ""
    if map_to_local:
        if source_uri is None:
            raise ValueError("source_uri is required when mapping manifests locally")
        source_bucket, source_prefix = _parse_uri(source_uri)

    groups: dict[str, list[ManifestGroup]] = {}
    counters: dict[str, int] = {}
    media_files: list[str] = []

    for manifest_uri in manifest_uris:
        manifest = _read_manifest(manifest_uri)
        by_vertex: dict[str, dict[str, str]] = {}
        for item in manifest.get("files", []):
            uri = item.get("uri")
            if not uri:
                continue
            normalized = _normalize_uri(uri)
            if map_to_local:
                normalized = _localize_manifest_uri(
                    normalized,
                    local_root=local_root,
                    bucket=source_bucket,
                    prefix=source_prefix,
                )
            info = _vertex_kind_from_uri(normalized)
            if not info:
                continue
            vertex_type, file_kind = info
            if vertex_type == "MediaAsset" and file_kind == "core":
                media_files.append(normalized)
            by_vertex.setdefault(vertex_type, {})[file_kind] = normalized

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

    return groups, sorted(set(media_files)), True


def _relative_object_path(path: str, bucket: str, prefix: str) -> str:
    if path.startswith(f"{bucket}/"):
        path = path[len(bucket) + 1 :]
    prefix = prefix.strip("/")
    if prefix and path.startswith(f"{prefix}/"):
        path = path[len(prefix) + 1 :]
    return path


def _copy_graph_to_local(base_uri: str, work_dir: str) -> str:
    bucket, prefix = _parse_uri(base_uri)
    local_root = Path(work_dir).resolve() / "graph"
    local_root.mkdir(parents=True, exist_ok=True)

    def copy_pattern(pattern: str) -> None:
        fs, path = fsspec.core.url_to_fs(pattern)
        for match in fs.glob(path):
            rel_path = _relative_object_path(match, bucket, prefix)
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


def _file_size_bytes(path: str) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return p.stat().st_size


def _write_report(report: IndexBuildReport, dest_path: str) -> None:
    Path(dest_path).write_text(json.dumps(report.__dict__, indent=2), encoding="utf-8")


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


def _sql_list(items: Iterable[str]) -> str:
    escaped = [item.replace("'", "''") for item in items]
    return "[" + ", ".join(f"'{item}'" for item in escaped) + "]"


def _configure_gcs_secret(
    conn: duckdb.DuckDBPyConnection,
    allow_install: bool,
) -> str:
    use_fallback = os.getenv("DUCKDB_GCS_FALLBACK", "0") == "1"
    conn.execute("DROP SECRET IF EXISTS retikon_gcs")
    if use_fallback:
        load_extensions(conn, ("gcs",), allow_install)
        return "gcs_extension"
    conn.execute("CREATE SECRET retikon_gcs (TYPE GCS, PROVIDER credential_chain)")
    return "credential_chain"


def build_snapshot(
    *,
    graph_uri: str,
    snapshot_uri: str,
    work_dir: str,
    copy_local: bool,
    fallback_local: bool,
    allow_install: bool,
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

    def build_with_base(
        base_uri: str,
        source_uri: str | None = None,
    ) -> tuple[IndexBuildReport, str]:
        conn = duckdb.connect(str(db_path))
        extensions = load_extensions(conn, ("httpfs", "vss"), allow_install)
        auth_path = _configure_gcs_secret(conn, allow_install)
        conn.execute("SET hnsw_enable_experimental_persistence=true")

        groups, media_files, has_manifests = _load_manifest_groups(
            base_uri,
            source_uri=source_uri,
        )
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
        tables["media_assets"] = {
            "rows": _create_table(
                conn,
                "media_assets",
                media_source,
                """
                CREATE TABLE media_assets AS
                SELECT id, uri, media_type, content_type
                FROM read_parquet(?, union_by_name=true)
                """,
                (
                    "CREATE TABLE media_assets "
                    "(id VARCHAR, uri VARCHAR, media_type VARCHAR, content_type VARCHAR)"
                ),
                [media_files],
            )
        }

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
                    (group.group_id, group.core, group.text, group.vector)
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
                JOIN doc_chunk_map m ON c.filename = m.core
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
                JOIN doc_chunk_map m ON t.filename = m.text
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
                JOIN doc_chunk_map m ON v.filename = m.vector
                """
            )
        tables["doc_chunks"] = {
            "rows": _create_table(
                conn,
                "doc_chunks",
                TableSource(
                    core=[group.core for group in doc_groups if group.core is not None]
                ),
                """
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
                """,
                """
                CREATE TABLE doc_chunks (
                  media_asset_id VARCHAR,
                  content VARCHAR,
                  text_vector FLOAT[768]
                )
                """,
                [],
            )
        }

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
                    (group.group_id, group.core, group.text, group.vector)
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
                JOIN transcript_map m ON c.filename = m.core
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
                JOIN transcript_map m ON t.filename = m.text
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
                JOIN transcript_map m ON v.filename = m.vector
                """
            )
        tables["transcripts"] = {
            "rows": _create_table(
                conn,
                "transcripts",
                TableSource(
                    core=[
                        group.core
                        for group in transcript_groups
                        if group.core is not None
                    ]
                ),
                """
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
                """,
                """
                CREATE TABLE transcripts (
                  media_asset_id VARCHAR,
                  content VARCHAR,
                  start_ms BIGINT,
                  text_embedding FLOAT[768]
                )
                """,
                [],
            )
        }

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
                    (group.group_id, group.core, group.vector)
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
                CREATE TEMP VIEW image_asset_core AS
                SELECT m.group_id,
                       c.file_row_number AS row_number,
                       c.media_asset_id,
                       c.timestamp_ms,
                       c.thumbnail_uri
                FROM read_parquet({_sql_list(core_files)},
                                  filename=true,
                                  file_row_number=true,
                                  union_by_name=true) AS c
                JOIN image_asset_map m ON c.filename = m.core
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
                JOIN image_asset_map m ON v.filename = m.vector
                """
            )
        tables["image_assets"] = {
            "rows": _create_table(
                conn,
                "image_assets",
                TableSource(
                    core=[
                        group.core
                        for group in image_groups
                        if group.core is not None
                    ]
                ),
                """
                CREATE TABLE image_assets AS
                SELECT core.media_asset_id,
                       core.timestamp_ms,
                       core.thumbnail_uri,
                       CAST(vector.clip_vector AS FLOAT[512]) AS clip_vector
                FROM image_asset_core AS core
                JOIN image_asset_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """,
                """
                CREATE TABLE image_assets (
                  media_asset_id VARCHAR,
                  timestamp_ms BIGINT,
                  thumbnail_uri VARCHAR,
                  clip_vector FLOAT[512]
                )
                """,
                [],
            )
        }

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
                    (group.group_id, group.core, group.vector)
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
                JOIN audio_clip_map m ON c.filename = m.core
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
                JOIN audio_clip_map m ON v.filename = m.vector
                """
            )
        tables["audio_clips"] = {
            "rows": _create_table(
                conn,
                "audio_clips",
                TableSource(
                    core=[
                        group.core
                        for group in audio_groups
                        if group.core is not None
                    ]
                ),
                """
                CREATE TABLE audio_clips AS
                SELECT core.media_asset_id,
                       CAST(vector.clap_embedding AS FLOAT[512]) AS clap_embedding
                FROM audio_clip_core AS core
                JOIN audio_clip_vector AS vector
                  ON core.group_id = vector.group_id
                 AND core.row_number = vector.row_number
                """,
                """
                CREATE TABLE audio_clips (
                  media_asset_id VARCHAR,
                  clap_embedding FLOAT[512]
                )
                """,
                [],
            )
        }

        conn.execute("CHECKPOINT")

        index_specs = [
            ("doc_chunks_text_vector", "doc_chunks", "text_vector"),
            ("transcripts_text_embedding", "transcripts", "text_embedding"),
            ("image_assets_clip_vector", "image_assets", "clip_vector"),
            ("audio_clips_clap_embedding", "audio_clips", "clap_embedding"),
        ]

        indexes: dict[str, dict[str, Any]] = {}
        prev_size = _file_size_bytes(str(db_path))

        for index_name, table, column in index_specs:
            conn.execute(
                f"CREATE INDEX {index_name} ON {table} USING HNSW ({column})"
            )
            conn.execute("CHECKPOINT")
            new_size = _file_size_bytes(str(db_path))
            indexes[index_name] = {
                "table": table,
                "column": column,
                "size_bytes": max(0, new_size - prev_size),
            }
            prev_size = new_size

        conn.execute("CHECKPOINT")
        conn.close()

        report = IndexBuildReport(
            graph_uri=base_uri,
            snapshot_uri=snapshot_uri,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(time.time() - start, 2),
            tables=tables,
            indexes=indexes,
            duckdb_version=duckdb.__version__,
            file_size_bytes=_file_size_bytes(str(db_path)),
        )
        logger.info(
            "DuckDB GCS auth initialized",
            extra={
                "duckdb_auth_path": auth_path,
                "duckdb_extension_loaded": ",".join(extensions),
                "duckdb_fallback_used": os.getenv("DUCKDB_GCS_FALLBACK", "0") == "1",
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
    _write_report(report, report_path)

    _upload_file(str(db_path), snapshot_uri)
    _upload_file(report_path, f"{snapshot_uri}.json")

    logger.info(
        "Index build complete",
        extra={
            "snapshot_uri": snapshot_uri,
            "duckdb_extensions": extensions,
            "tables": report.tables,
            "indexes": report.indexes,
        },
    )

    if cleanup_dir and cleanup_dir.exists():
        shutil.rmtree(cleanup_dir, ignore_errors=True)

    return report


def _config_from_env() -> dict[str, Any]:
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
            graph_uri = graph_root(graph_bucket, graph_prefix)
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if not snapshot_uri:
        raise ValueError("SNAPSHOT_URI is required")

    return {
        "graph_uri": graph_uri,
        "snapshot_uri": snapshot_uri,
        "work_dir": os.getenv("INDEX_BUILDER_WORK_DIR", "/tmp"),
        "copy_local": os.getenv("INDEX_BUILDER_COPY_LOCAL", "0") == "1",
        "fallback_local": os.getenv("INDEX_BUILDER_FALLBACK_LOCAL", "1") == "1",
        "allow_install": os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1",
    }


def main() -> None:
    configure_logging(
        service=SERVICE_NAME,
        env=os.getenv("ENV"),
        version=os.getenv("RETIKON_VERSION"),
    )
    config = _config_from_env()
    build_snapshot(**config)


if __name__ == "__main__":
    main()
