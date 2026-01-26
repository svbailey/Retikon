from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

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

logger = get_logger(__name__)


@dataclass(frozen=True)
class QueryResult:
    modality: str
    uri: str
    snippet: str | None
    timestamp_ms: int | None
    score: float
    media_asset_id: str | None


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
    conn = duckdb.connect(snapshot_path, read_only=True)
    allow_install = os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1"
    load_extensions(conn, ("vss",), allow_install)
    return conn


def _query_rows(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Iterable[object],
) -> list[tuple]:
    return conn.execute(sql, list(params)).fetchall()


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
) -> list[QueryResult]:
    text_vec = list(_cached_text_vector(query_text))
    image_text_vec = list(_cached_image_text_vector(query_text))
    audio_text_vec = list(_cached_audio_text_vector(query_text))

    results: list[QueryResult] = []
    conn = _connect(snapshot_path)
    try:
        doc_sql = f"""
            SELECT m.uri, d.media_asset_id, d.content,
                   list_cosine_distance(d.text_vector, ?::FLOAT[]) AS distance
            FROM doc_chunks d
            JOIN media_assets m ON d.media_asset_id = m.id
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        for uri, media_asset_id, content, distance in _query_rows(
            conn, doc_sql, [text_vec]
        ):
            results.append(
                QueryResult(
                    modality="document",
                    uri=uri,
                    snippet=content,
                    timestamp_ms=None,
                    score=_score_from_distance(distance),
                    media_asset_id=media_asset_id,
                )
            )

        transcript_sql = f"""
            SELECT m.uri, t.media_asset_id, t.content, t.start_ms,
                   list_cosine_distance(t.text_embedding, ?::FLOAT[]) AS distance
            FROM transcripts t
            JOIN media_assets m ON t.media_asset_id = m.id
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        for uri, media_asset_id, content, start_ms, distance in _query_rows(
            conn, transcript_sql, [text_vec]
        ):
            results.append(
                QueryResult(
                    modality="transcript",
                    uri=uri,
                    snippet=content,
                    timestamp_ms=int(start_ms),
                    score=_score_from_distance(distance),
                    media_asset_id=media_asset_id,
                )
            )

        image_sql = f"""
            SELECT m.uri, i.media_asset_id, i.timestamp_ms,
                   list_cosine_distance(i.clip_vector, ?::FLOAT[]) AS distance
            FROM image_assets i
            JOIN media_assets m ON i.media_asset_id = m.id
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        for uri, media_asset_id, timestamp_ms, distance in _query_rows(
            conn, image_sql, [image_text_vec]
        ):
            results.append(
                QueryResult(
                    modality="image",
                    uri=uri,
                    snippet=None,
                    timestamp_ms=(
                        int(timestamp_ms) if timestamp_ms is not None else None
                    ),
                    score=_score_from_distance(distance),
                    media_asset_id=media_asset_id,
                )
            )

        audio_sql = f"""
            SELECT m.uri, a.media_asset_id,
                   list_cosine_distance(a.clap_embedding, ?::FLOAT[]) AS distance
            FROM audio_clips a
            JOIN media_assets m ON a.media_asset_id = m.id
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        for uri, media_asset_id, distance in _query_rows(
            conn, audio_sql, [audio_text_vec]
        ):
            results.append(
                QueryResult(
                    modality="audio",
                    uri=uri,
                    snippet=None,
                    timestamp_ms=None,
                    score=_score_from_distance(distance),
                    media_asset_id=media_asset_id,
                )
            )
    finally:
        conn.close()

    results.sort(key=lambda item: item.score, reverse=True)
    return results[: int(top_k)]


def search_by_image(
    *,
    snapshot_path: str,
    image_base64: str,
    top_k: int,
) -> list[QueryResult]:
    try:
        image = _decode_base64_image(image_base64)
    except Exception as exc:
        raise ValueError("Invalid image_base64 payload") from exc
    vector = get_image_embedder(512).encode([image])[0]

    conn = _connect(snapshot_path)
    try:
        image_sql = f"""
            SELECT m.uri, i.media_asset_id, i.timestamp_ms,
                   list_cosine_distance(i.clip_vector, ?::FLOAT[]) AS distance
            FROM image_assets i
            JOIN media_assets m ON i.media_asset_id = m.id
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        results = [
            QueryResult(
                modality="image",
                uri=uri,
                snippet=None,
                timestamp_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                score=_score_from_distance(distance),
                media_asset_id=media_asset_id,
            )
            for uri, media_asset_id, timestamp_ms, distance in _query_rows(
                conn, image_sql, [vector]
            )
        ]
    finally:
        conn.close()

    results.sort(key=lambda item: item.score, reverse=True)
    return results[: int(top_k)]
