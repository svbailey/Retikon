from __future__ import annotations

import base64
import io
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import duckdb
from PIL import Image

from retikon_core.embeddings import (
    get_audio_text_embedder,
    get_image_embedder,
    get_image_text_embedder,
    get_text_embedder,
)
from retikon_core.logging import get_logger
from retikon_core.query_engine.warm_start import load_extensions
from retikon_core.tenancy.types import TenantScope

logger = get_logger(__name__)

_CONN_LOCAL = threading.local()


def _conn_cache() -> dict[str, tuple[int, int, duckdb.DuckDBPyConnection]]:
    cache = getattr(_CONN_LOCAL, "duckdb_conns", None)
    if cache is None:
        cache = {}
        _CONN_LOCAL.duckdb_conns = cache
    return cache


def _snapshot_signature(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _is_cached_conn(snapshot_path: str, conn: duckdb.DuckDBPyConnection) -> bool:
    cache = _conn_cache()
    cached = cache.get(snapshot_path)
    return cached is not None and cached[2] is conn


def _release_conn(snapshot_path: str, conn: duckdb.DuckDBPyConnection) -> None:
    if _is_cached_conn(snapshot_path, conn):
        return
    try:
        conn.close()
    except Exception:
        pass


def _normalize_modalities(modalities: Sequence[str] | None) -> set[str]:
    if modalities is None:
        return {"document", "transcript", "image", "audio"}
    return {modality.strip().lower() for modality in modalities if modality.strip()}


def _apply_duckdb_settings(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    settings: dict[str, str] = {}
    threads = os.getenv("DUCKDB_THREADS")
    if threads:
        conn.execute(f"PRAGMA threads={int(threads)}")
        settings["duckdb_threads"] = threads
    memory_limit = os.getenv("DUCKDB_MEMORY_LIMIT")
    if memory_limit:
        conn.execute(f"PRAGMA memory_limit='{memory_limit}'")
        settings["duckdb_memory_limit"] = memory_limit
    temp_dir = os.getenv("DUCKDB_TEMP_DIRECTORY")
    if temp_dir:
        conn.execute(f"PRAGMA temp_directory='{temp_dir}'")
        settings["duckdb_temp_directory"] = temp_dir
    return settings


@dataclass(frozen=True)
class QueryResult:
    modality: str
    uri: str
    snippet: str | None
    timestamp_ms: int | None
    thumbnail_uri: str | None
    score: float
    media_asset_id: str | None
    media_type: str | None


def _clamp_score(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _score_from_distance(distance: float) -> float:
    return _clamp_score(1.0 - float(distance))


def _decode_base64_image(payload: str) -> Image.Image:
    cleaned = payload.strip()
    if "," in cleaned and cleaned.split(",", 1)[0].lower().startswith("data:"):
        cleaned = cleaned.split(",", 1)[1]
    raw = base64.b64decode(cleaned, validate=True)
    with Image.open(io.BytesIO(raw)) as img:
        rgb = img.convert("RGB")
        return rgb.copy()


def _connect(snapshot_path: str) -> duckdb.DuckDBPyConnection:
    cache = _conn_cache()
    signature = _snapshot_signature(snapshot_path)
    cached = cache.get(snapshot_path)
    if cached is not None:
        cached_mtime, cached_size, cached_conn = cached
        if signature is None and cached_mtime == -1:
            return cached_conn
        if signature is not None:
            mtime_ns, size = signature
            if cached_mtime == mtime_ns and cached_size == size:
                return cached_conn
        try:
            cached_conn.close()
        except Exception:
            pass

    conn = duckdb.connect(snapshot_path, read_only=True)
    allow_install = os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1"
    load_extensions(conn, ("vss",), allow_install)
    if signature is None:
        cache[snapshot_path] = (-1, -1, conn)
    else:
        cache[snapshot_path] = (signature[0], signature[1], conn)
    return conn


def _query_rows(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Iterable[object],
) -> list[tuple]:
    return conn.execute(sql, list(params)).fetchall()


def _keyword_pattern(query_text: str) -> str:
    return f"%{query_text.strip()}%"


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


def _scope_filters(
    conn: duckdb.DuckDBPyConnection,
    scope: TenantScope | None,
    *,
    table: str = "media_assets",
    alias: str = "m",
) -> tuple[str, list[object]]:
    if scope is None or scope.is_empty():
        return "", []

    required: list[str] = []
    conditions: list[str] = []
    params: list[object] = []

    if scope.org_id:
        required.append("org_id")
        conditions.append(f"{alias}.org_id = ?")
        params.append(scope.org_id)
    if scope.site_id:
        required.append("site_id")
        conditions.append(f"{alias}.site_id = ?")
        params.append(scope.site_id)
    if scope.stream_id:
        required.append("stream_id")
        conditions.append(f"{alias}.stream_id = ?")
        params.append(scope.stream_id)

    missing = [col for col in required if not _table_has_column(conn, table, col)]
    if missing:
        raise ValueError(
            "Scope columns missing in snapshot: " + ", ".join(sorted(set(missing)))
        )

    if not conditions:
        return "", []
    return "WHERE " + " AND ".join(conditions), params


@lru_cache(maxsize=256)
def _cached_text_vector(text: str) -> tuple[float, ...]:
    return tuple(get_text_embedder(768).encode([text])[0])


@lru_cache(maxsize=256)
def _cached_image_text_vector(text: str) -> tuple[float, ...]:
    return tuple(get_image_text_embedder(512).encode([text])[0])


@lru_cache(maxsize=256)
def _cached_audio_text_vector(text: str) -> tuple[float, ...]:
    return tuple(get_audio_text_embedder(512).encode([text])[0])


def search_by_text(
    *,
    snapshot_path: str,
    query_text: str,
    top_k: int,
    modalities: Sequence[str] | None = None,
    scope: TenantScope | None = None,
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    modalities_set = _normalize_modalities(modalities)
    need_text = bool(modalities_set & {"document", "transcript"})
    need_image = "image" in modalities_set
    need_audio = "audio" in modalities_set

    text_vec = None
    if need_text:
        embed_start = time.monotonic()
        text_vec = list(_cached_text_vector(query_text))
        if trace is not None:
            trace["text_embed_ms"] = round(
                (time.monotonic() - embed_start) * 1000.0, 2
            )

    image_text_vec = None
    if need_image:
        image_embed_start = time.monotonic()
        image_text_vec = list(_cached_image_text_vector(query_text))
        if trace is not None:
            trace["image_text_embed_ms"] = round(
                (time.monotonic() - image_embed_start) * 1000.0, 2
            )

    audio_text_vec = None
    if need_audio:
        audio_embed_start = time.monotonic()
        audio_text_vec = list(_cached_audio_text_vector(query_text))
        if trace is not None:
            trace["audio_text_embed_ms"] = round(
                (time.monotonic() - audio_embed_start) * 1000.0, 2
            )

    results: list[QueryResult] = []
    connect_start = time.monotonic()
    conn = _connect(snapshot_path)
    if trace is not None:
        trace["duckdb_connect_ms"] = round(
            (time.monotonic() - connect_start) * 1000.0, 2
        )
        trace.update(_apply_duckdb_settings(conn))
    try:
        has_thumbnail = _table_has_column(conn, "image_assets", "thumbnail_uri")
        thumbnail_expr = "i.thumbnail_uri" if has_thumbnail else "NULL AS thumbnail_uri"
        scope_clause, scope_params = _scope_filters(conn, scope)

        doc_sql = f"""
            SELECT m.uri, m.media_type, d.media_asset_id, d.content,
                   (1.0 - list_cosine_similarity(d.text_vector, ?::FLOAT[])) AS distance
            FROM doc_chunks d
            JOIN media_assets m ON d.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        if need_text and text_vec is not None:
            doc_start = time.monotonic()
            doc_rows = _query_rows(conn, doc_sql, [text_vec, *scope_params])
            if trace is not None:
                trace["doc_query_ms"] = round(
                    (time.monotonic() - doc_start) * 1000.0, 2
                )
                trace["doc_rows"] = len(doc_rows)
            for uri, media_type, media_asset_id, content, distance in doc_rows:
                results.append(
                    QueryResult(
                        modality="document",
                        uri=uri,
                        snippet=content,
                        timestamp_ms=None,
                        thumbnail_uri=None,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                    )
                )

        transcript_sql = f"""
            SELECT m.uri, m.media_type, t.media_asset_id, t.content, t.start_ms,
                   (1.0 - list_cosine_similarity(
                       t.text_embedding, ?::FLOAT[]
                   )) AS distance
            FROM transcripts t
            JOIN media_assets m ON t.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        if need_text and text_vec is not None:
            transcript_start = time.monotonic()
            transcript_rows = _query_rows(
                conn,
                transcript_sql,
                [text_vec, *scope_params],
            )
            if trace is not None:
                trace["transcript_query_ms"] = round(
                    (time.monotonic() - transcript_start) * 1000.0, 2
                )
                trace["transcript_rows"] = len(transcript_rows)
            for uri, media_type, media_asset_id, content, start_ms, distance in (
                transcript_rows
            ):
                results.append(
                    QueryResult(
                        modality="transcript",
                        uri=uri,
                        snippet=content,
                        timestamp_ms=int(start_ms),
                        thumbnail_uri=None,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                    )
                )

        image_sql = f"""
            SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                   {thumbnail_expr},
                   (1.0 - list_cosine_similarity(i.clip_vector, ?::FLOAT[])) AS distance
            FROM image_assets i
            JOIN media_assets m ON i.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        if need_image and image_text_vec is not None:
            image_start = time.monotonic()
            image_rows = _query_rows(conn, image_sql, [image_text_vec, *scope_params])
            if trace is not None:
                trace["image_query_ms"] = round(
                    (time.monotonic() - image_start) * 1000.0, 2
                )
                trace["image_rows"] = len(image_rows)
            for (
                uri,
                media_type,
                media_asset_id,
                timestamp_ms,
                thumbnail_uri,
                distance,
            ) in image_rows:
                results.append(
                    QueryResult(
                        modality="image",
                        uri=uri,
                        snippet=None,
                        timestamp_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                        thumbnail_uri=thumbnail_uri,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                    )
                )

        audio_sql = f"""
            SELECT m.uri, m.media_type, a.media_asset_id,
                   (1.0 - list_cosine_similarity(
                       a.clap_embedding, ?::FLOAT[]
                   )) AS distance
            FROM audio_clips a
            JOIN media_assets m ON a.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        if need_audio and audio_text_vec is not None:
            audio_start = time.monotonic()
            audio_rows = _query_rows(conn, audio_sql, [audio_text_vec, *scope_params])
            if trace is not None:
                trace["audio_query_ms"] = round(
                    (time.monotonic() - audio_start) * 1000.0, 2
                )
                trace["audio_rows"] = len(audio_rows)
            for uri, media_type, media_asset_id, distance in audio_rows:
                results.append(
                    QueryResult(
                        modality="audio",
                        uri=uri,
                        snippet=None,
                        timestamp_ms=None,
                        thumbnail_uri=None,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                    )
                )
    finally:
        _release_conn(snapshot_path, conn)

    results.sort(key=lambda item: item.score, reverse=True)
    return results[: int(top_k)]


def search_by_keyword(
    *,
    snapshot_path: str,
    query_text: str,
    top_k: int,
    scope: TenantScope | None = None,
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    pattern = _keyword_pattern(query_text)

    connect_start = time.monotonic()
    conn = _connect(snapshot_path)
    if trace is not None:
        trace["duckdb_connect_ms"] = round(
            (time.monotonic() - connect_start) * 1000.0, 2
        )
        trace.update(_apply_duckdb_settings(conn))
    try:
        scope_clause, scope_params = _scope_filters(conn, scope)
        scope_filter = scope_clause.replace("WHERE ", "", 1) if scope_clause else ""
        scope_sql = f" AND {scope_filter}" if scope_filter else ""
        doc_sql = f"""
            SELECT m.uri, m.media_type, d.media_asset_id, d.content
            FROM doc_chunks d
            JOIN media_assets m ON d.media_asset_id = m.id
            WHERE d.content ILIKE ?{scope_sql}
            LIMIT {int(top_k)}
        """
        doc_start = time.monotonic()
        doc_rows = _query_rows(conn, doc_sql, [pattern, *scope_params])
        if trace is not None:
            trace["keyword_doc_query_ms"] = round(
                (time.monotonic() - doc_start) * 1000.0, 2
            )
            trace["keyword_doc_rows"] = len(doc_rows)
        for uri, media_type, media_asset_id, content in doc_rows:
            results.append(
                QueryResult(
                    modality="document",
                    uri=uri,
                    snippet=content,
                    timestamp_ms=None,
                    thumbnail_uri=None,
                    score=1.0,
                    media_asset_id=media_asset_id,
                    media_type=media_type,
                )
            )

        transcript_sql = f"""
            SELECT m.uri, m.media_type, t.media_asset_id, t.content, t.start_ms
            FROM transcripts t
            JOIN media_assets m ON t.media_asset_id = m.id
            WHERE t.content ILIKE ?{scope_sql}
            LIMIT {int(top_k)}
        """
        transcript_start = time.monotonic()
        transcript_rows = _query_rows(conn, transcript_sql, [pattern, *scope_params])
        if trace is not None:
            trace["keyword_transcript_query_ms"] = round(
                (time.monotonic() - transcript_start) * 1000.0, 2
            )
            trace["keyword_transcript_rows"] = len(transcript_rows)
        for uri, media_type, media_asset_id, content, start_ms in transcript_rows:
            results.append(
                QueryResult(
                    modality="transcript",
                    uri=uri,
                    snippet=content,
                    timestamp_ms=int(start_ms) if start_ms is not None else None,
                    thumbnail_uri=None,
                    score=1.0,
                    media_asset_id=media_asset_id,
                    media_type=media_type,
                )
            )
    finally:
        _release_conn(snapshot_path, conn)

    return results[: int(top_k)]


def search_by_metadata(
    *,
    snapshot_path: str,
    filters: dict[str, str],
    top_k: int,
    scope: TenantScope | None = None,
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    connect_start = time.monotonic()
    conn = _connect(snapshot_path)
    if trace is not None:
        trace["duckdb_connect_ms"] = round(
            (time.monotonic() - connect_start) * 1000.0, 2
        )
        trace.update(_apply_duckdb_settings(conn))
    try:
        allowed = {"uri", "media_type", "content_type"}
        conditions: list[str] = []
        params: list[object] = []
        for key, value in filters.items():
            if key not in allowed:
                raise ValueError(f"Unsupported metadata filter: {key}")
            if key == "uri":
                conditions.append("uri ILIKE ?")
                params.append(_keyword_pattern(value))
            elif key == "media_type":
                conditions.append("media_type = ?")
                params.append(value)
            elif key == "content_type":
                if not _table_has_column(conn, "media_assets", "content_type"):
                    raise ValueError("content_type is not available in snapshot")
                conditions.append("content_type = ?")
                params.append(value)

        scope_clause, scope_params = _scope_filters(conn, scope, alias="m")
        if scope_clause:
            conditions.append(scope_clause.replace("WHERE ", "", 1))
            params.extend(scope_params)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        sql = f"""
            SELECT m.id, m.uri, m.media_type
            FROM media_assets m
            {where_clause}
            LIMIT {int(top_k)}
        """
        query_start = time.monotonic()
        rows = _query_rows(conn, sql, params)
        if trace is not None:
            trace["metadata_query_ms"] = round(
                (time.monotonic() - query_start) * 1000.0, 2
            )
            trace["metadata_rows"] = len(rows)
        results = [
            QueryResult(
                modality="metadata",
                uri=uri,
                snippet=None,
                timestamp_ms=None,
                thumbnail_uri=None,
                score=1.0,
                media_asset_id=media_asset_id,
                media_type=media_type,
            )
            for media_asset_id, uri, media_type in rows
        ]
    finally:
        _release_conn(snapshot_path, conn)

    return results[: int(top_k)]


def search_by_image(
    *,
    snapshot_path: str,
    image_base64: str,
    top_k: int,
    scope: TenantScope | None = None,
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    try:
        decode_start = time.monotonic()
        image = _decode_base64_image(image_base64)
        if trace is not None:
            trace["image_decode_ms"] = round(
                (time.monotonic() - decode_start) * 1000.0, 2
            )
    except Exception as exc:
        raise ValueError("Invalid image_base64 payload") from exc
    embed_start = time.monotonic()
    vector = get_image_embedder(512).encode([image])[0]
    if trace is not None:
        trace["image_embed_ms"] = round((time.monotonic() - embed_start) * 1000.0, 2)

    connect_start = time.monotonic()
    conn = _connect(snapshot_path)
    if trace is not None:
        trace["duckdb_connect_ms"] = round(
            (time.monotonic() - connect_start) * 1000.0, 2
        )
        trace.update(_apply_duckdb_settings(conn))
    try:
        has_thumbnail = _table_has_column(conn, "image_assets", "thumbnail_uri")
        thumbnail_expr = "i.thumbnail_uri" if has_thumbnail else "NULL AS thumbnail_uri"
        scope_clause, scope_params = _scope_filters(conn, scope)

        image_sql = f"""
            SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                   {thumbnail_expr},
                   (1.0 - list_cosine_similarity(i.clip_vector, ?::FLOAT[])) AS distance
            FROM image_assets i
            JOIN media_assets m ON i.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        image_start = time.monotonic()
        image_rows = _query_rows(conn, image_sql, [vector, *scope_params])
        if trace is not None:
            trace["image_query_ms"] = round(
                (time.monotonic() - image_start) * 1000.0, 2
            )
            trace["image_rows"] = len(image_rows)
        results = [
            QueryResult(
                modality="image",
                uri=uri,
                snippet=None,
                timestamp_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                thumbnail_uri=thumbnail_uri,
                score=_score_from_distance(distance),
                media_asset_id=media_asset_id,
                media_type=media_type,
            )
            for (
                uri,
                media_type,
                media_asset_id,
                timestamp_ms,
                thumbnail_uri,
                distance,
            ) in image_rows
        ]
    finally:
        _release_conn(snapshot_path, conn)

    results.sort(key=lambda item: item.score, reverse=True)
    return results[: int(top_k)]
