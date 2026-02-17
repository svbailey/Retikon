from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Iterable, Sequence

import duckdb
from PIL import Image

from retikon_core.embeddings import (
    get_audio_text_embedder,
    get_image_embedder,
    get_image_embedder_v2,
    get_image_text_embedder,
    get_image_text_embedder_v2,
    get_reranker,
    get_runtime_embedding_backend,
    get_text_embedder,
    normalize_rerank_scores,
)
from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import InferenceTimeoutError
from retikon_core.logging import get_logger
from retikon_core.query_engine.warm_start import load_extensions
from retikon_core.tenancy.types import TenantScope

logger = get_logger(__name__)

_CONN_LOCAL = threading.local()

_DEFAULT_MODALITY_BOOSTS: dict[str, float] = {
    "document": 1.0,
    "transcript": 1.0,
    "image": 1.05,
    "audio": 1.05,
}
_HINT_KEYWORDS: dict[str, set[str]] = {
    "video": {"image"},
    "frame": {"image"},
    "frames": {"image"},
    "clip": {"image"},
    "image": {"image"},
    "photo": {"image"},
    "visual": {"image"},
    "audio": {"audio"},
    "sound": {"audio"},
    "speech": {"audio", "transcript"},
    "podcast": {"audio"},
    "music": {"audio"},
}


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
    hnsw_ef_search = os.getenv("HNSW_EF_SEARCH")
    if hnsw_ef_search:
        try:
            value = int(hnsw_ef_search)
        except ValueError:
            value = None
        if value is not None and value > 0:
            conn.execute(f"SET hnsw_ef_search={value}")
            settings["hnsw_ef_search"] = str(value)
    return settings


@dataclass
class QueryResult:
    modality: str
    uri: str
    snippet: str | None
    start_ms: int | None
    end_ms: int | None
    thumbnail_uri: str | None
    score: float
    media_asset_id: str | None
    media_type: str | None
    primary_evidence_id: str
    source_type: str | None = None
    evidence_refs: list[dict[str, str]] = field(default_factory=list)
    why: list[dict[str, object]] = field(default_factory=list)
    embedding_model: str | None = None
    embedding_backend: str | None = None
    why_modality: str | None = None

    @property
    def timestamp_ms(self) -> int | None:
        # Backwards-compatible alias used by existing API/tests.
        return self.start_ms


def _clamp_score(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _score_from_distance(distance: float) -> float:
    return _clamp_score(1.0 - float(distance))


def _canonical_modality(modality: str) -> str:
    cleaned = modality.strip().lower()
    if cleaned in {"document", "transcript", "text"}:
        return "text"
    if cleaned in {"image", "vision"}:
        return "vision"
    if cleaned in {"audio"}:
        return "audio"
    if cleaned in {"ocr"}:
        return "ocr"
    if cleaned in {"video"}:
        return "video"
    if cleaned in {"fts"}:
        return "fts"
    return cleaned


def _evidence_refs_for(modality: str, evidence_id: str) -> list[dict[str, str]]:
    canonical = _canonical_modality(modality)
    if canonical == "text":
        if modality == "transcript":
            return [{"transcript_segment_id": evidence_id}]
        return [{"doc_chunk_id": evidence_id}]
    if canonical == "vision":
        return [{"image_asset_id": evidence_id}]
    if canonical == "audio":
        return [{"audio_segment_id": evidence_id}]
    if canonical == "video":
        return [{"video_clip_id": evidence_id}]
    if canonical == "ocr":
        return [{"doc_chunk_id": evidence_id}]
    return []


def _fusion_weights() -> dict[str, float]:
    defaults = {
        "text": 1.0,
        "ocr": 1.0,
        "vision": 0.8,
        "audio": 0.8,
        "video": 1.0,
        "fts": 1.2,
    }
    raw = os.getenv("QUERY_FUSION_WEIGHTS")
    if not raw:
        return defaults
    cleaned = raw.strip()
    if not cleaned:
        return defaults
    parsed: dict[str, float] = {}
    if cleaned.startswith("{"):
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return defaults
        if isinstance(payload, dict):
            for key, value in payload.items():
                try:
                    parsed[_canonical_modality(str(key))] = float(value)
                except (TypeError, ValueError):
                    continue
    else:
        for item in cleaned.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = _canonical_modality(key.strip())
            try:
                parsed[key] = float(value.strip())
            except ValueError:
                continue
    if not parsed:
        return defaults
    for key, value in defaults.items():
        parsed.setdefault(key, value)
    return parsed


def _fuse_k() -> int:
    raw = os.getenv("QUERY_FUSION_RRF_K", "60")
    try:
        value = int(raw)
    except ValueError:
        value = 60
    return max(1, value)


def _rerank_enabled() -> bool:
    return os.getenv("RERANK_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

def _vision_v2_enabled() -> bool:
    return os.getenv("VISION_V2_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _vision_v2_model_name() -> str:
    return os.getenv("VISION_V2_MODEL_NAME", "google/siglip2-base-patch16-224")


def _rerank_top_n() -> int:
    raw = os.getenv("RERANK_TOP_N", "20")
    try:
        value = int(raw)
    except ValueError:
        value = 20
    return max(1, value)


def _rerank_min_candidates() -> int:
    raw = os.getenv("RERANK_MIN_CANDIDATES", "2")
    try:
        value = int(raw)
    except ValueError:
        value = 2
    return max(1, value)


def _rerank_max_total_chars() -> int:
    raw = os.getenv("RERANK_MAX_TOTAL_CHARS", "6000")
    try:
        value = int(raw)
    except ValueError:
        value = 6000
    return max(0, value)


def _rerank_skip_score_gap() -> float:
    raw = os.getenv("RERANK_SKIP_SCORE_GAP", "1.0")
    try:
        value = float(raw)
    except ValueError:
        value = 1.0
    return max(0.0, value)


def _rerank_skip_min_score() -> float:
    raw = os.getenv("RERANK_SKIP_MIN_SCORE", "0.7")
    try:
        value = float(raw)
    except ValueError:
        value = 0.7
    return _clamp_score(value)


def _highlight_text(snippet: str | None, query_text: str | None) -> str | None:
    if not snippet:
        return None
    cleaned = " ".join(snippet.strip().split())
    if not cleaned:
        return None
    if not query_text:
        return cleaned[:240]
    query_terms = {
        token.lower()
        for token in query_text.split()
        if token.strip()
    }
    if not query_terms:
        return cleaned[:240]
    candidates = [piece.strip() for piece in cleaned.replace("\n", ". ").split(".")]
    candidates = [piece for piece in candidates if piece]
    if not candidates:
        return cleaned[:240]
    best = candidates[0]
    best_score = -1
    for candidate in candidates:
        words = {token.lower() for token in candidate.split() if token.strip()}
        score = len(words & query_terms)
        if score > best_score:
            best = candidate
            best_score = score
    return best[:240]


def _result_key(item: QueryResult) -> tuple[str, str, str, int | None, int | None]:
    return (
        item.media_asset_id or "",
        item.modality,
        item.primary_evidence_id,
        item.start_ms,
        item.end_ms,
    )


def _audio_segment_merge_gap_ms() -> int:
    raw = os.getenv("AUDIO_SEGMENT_MERGE_GAP_MS", "250")
    try:
        value = int(raw)
    except ValueError:
        value = 250
    return max(0, value)


def _merge_adjacent_audio_results(
    rows: Sequence[QueryResult],
    *,
    gap_ms: int,
) -> list[QueryResult]:
    if not rows:
        return []

    grouped: dict[str, list[QueryResult]] = {}
    passthrough: list[QueryResult] = []
    for row in rows:
        if row.start_ms is None or row.end_ms is None:
            passthrough.append(row)
            continue
        key = row.media_asset_id or row.uri
        grouped.setdefault(key, []).append(row)

    merged: list[QueryResult] = []
    for group_rows in grouped.values():
        ordered = sorted(
            group_rows,
            key=lambda item: (
                item.start_ms if item.start_ms is not None else -1,
                item.end_ms if item.end_ms is not None else -1,
            ),
        )
        cluster: list[QueryResult] = []
        cluster_start = 0
        cluster_end = 0

        def flush_cluster() -> None:
            nonlocal cluster, cluster_start, cluster_end
            if not cluster:
                return
            best = max(cluster, key=lambda item: item.score)
            merged_refs: list[dict[str, str]] = []
            seen_ref_ids: set[tuple[str, str]] = set()
            for item in cluster:
                for ref in item.evidence_refs:
                    if not isinstance(ref, dict):
                        continue
                    for key_name, key_value in ref.items():
                        marker = (str(key_name), str(key_value))
                        if marker in seen_ref_ids:
                            continue
                        seen_ref_ids.add(marker)
                        merged_refs.append({str(key_name): str(key_value)})

            merged_item = replace(best)
            merged_item.start_ms = cluster_start
            merged_item.end_ms = cluster_end
            merged_item.evidence_refs = merged_refs or list(best.evidence_refs)
            merged_item.why = list(best.why)
            if len(cluster) > 1:
                merged_item.why.append(
                    {
                        "modality": "audio",
                        "source": "audio_segment_merge",
                        "reason": "merged_adjacent_segments",
                        "raw_score": round(float(best.score), 6),
                    }
                )
            merged.append(merged_item)
            cluster = []

        for item in ordered:
            if not cluster:
                cluster = [item]
                cluster_start = int(item.start_ms or 0)
                cluster_end = int(item.end_ms or cluster_start)
                continue
            item_start = int(item.start_ms or 0)
            item_end = int(item.end_ms or item_start)
            if item_start <= (cluster_end + gap_ms):
                cluster.append(item)
                cluster_end = max(cluster_end, item_end)
                continue
            flush_cluster()
            cluster = [item]
            cluster_start = item_start
            cluster_end = item_end
        flush_cluster()

    merged.extend(passthrough)
    merged.sort(key=lambda item: item.score, reverse=True)
    return merged


def _safe_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_modality_boosts(raw: str | None) -> dict[str, float]:
    if not raw:
        return dict(_DEFAULT_MODALITY_BOOSTS)
    cleaned = raw.strip()
    if not cleaned:
        return dict(_DEFAULT_MODALITY_BOOSTS)
    boosts: dict[str, float] = {}
    if cleaned.startswith("{"):
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return dict(_DEFAULT_MODALITY_BOOSTS)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                try:
                    boosts[str(key).strip().lower()] = float(value)
                except (TypeError, ValueError):
                    continue
    else:
        for item in cleaned.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip().lower()
            try:
                boosts[key] = float(value.strip())
            except ValueError:
                continue
    if not boosts:
        return dict(_DEFAULT_MODALITY_BOOSTS)
    for key, value in _DEFAULT_MODALITY_BOOSTS.items():
        boosts.setdefault(key, value)
    return boosts


@lru_cache(maxsize=1)
def _modality_boosts() -> dict[str, float]:
    return _parse_modality_boosts(os.getenv("QUERY_MODALITY_BOOSTS"))


@lru_cache(maxsize=1)
def _modality_hint_boost() -> float:
    return _safe_float(os.getenv("QUERY_MODALITY_HINT_BOOST"), 1.15)


def _hinted_modalities(query_text: str) -> set[str]:
    lowered = query_text.lower()
    hinted: set[str] = set()
    for keyword, modalities in _HINT_KEYWORDS.items():
        if keyword in lowered:
            hinted.update(modalities)
    return hinted


def _boost_score(score: float, *, modality: str, query_text: str) -> float:
    multiplier = _modality_boosts().get(modality, 1.0)
    hint_boost = _modality_hint_boost()
    if hint_boost != 1.0 and query_text:
        if modality in _hinted_modalities(query_text):
            multiplier *= hint_boost
    return _clamp_score(score * multiplier)


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
    if _fts_enabled():
        try:
            load_extensions(conn, ("fts",), allow_install)
        except Exception as exc:
            logger.warning(
                "DuckDB optional extension load failed",
                extra={"extension": "fts", "error_message": str(exc)},
            )
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


def _trace_hitlists_enabled() -> bool:
    return os.getenv("QUERY_TRACE_HITLISTS", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _trace_hitlist_size() -> int:
    raw = os.getenv("QUERY_TRACE_HITLIST_SIZE", "5")
    try:
        value = int(raw)
    except ValueError:
        value = 5
    return max(1, value)


def _record_hitlist(
    trace: dict[str, float | int | str] | None,
    key: str,
    rows: Iterable[tuple],
    *,
    uri_index: int = 0,
    distance_index: int | None = None,
) -> None:
    if trace is None or not _trace_hitlists_enabled():
        return
    entries: list[dict[str, object]] = []
    limit = _trace_hitlist_size()
    for row in list(rows)[:limit]:
        if len(row) <= uri_index:
            continue
        uri = row[uri_index]
        if uri is None:
            continue
        item: dict[str, object] = {"uri": str(uri)}
        if distance_index is not None and len(row) > distance_index:
            distance = row[distance_index]
            if distance is not None:
                item["distance"] = round(float(distance), 6)
                item["score"] = round(_score_from_distance(float(distance)), 6)
        entries.append(item)
    trace[f"{key}_hitlist"] = json.dumps(
        entries,
        ensure_ascii=True,
        separators=(",", ":"),
    )


def rank_of_expected(results: Sequence[str], expected: Sequence[str]) -> int | None:
    expected_set = {uri for uri in expected if uri}
    if not expected_set:
        return None
    for idx, uri in enumerate(results, start=1):
        if uri in expected_set:
            return idx
    return None


def top_k_overlap(results: Sequence[str], expected: Sequence[str], top_k: int) -> float:
    expected_set = {uri for uri in expected if uri}
    if not expected_set:
        return 0.0
    seen = set(results[: max(0, int(top_k))])
    overlap = len(seen & expected_set)
    return overlap / float(len(expected_set))


def _keyword_pattern(query_text: str) -> str:
    return f"%{query_text.strip()}%"


def _fts_enabled() -> bool:
    return os.getenv("QUERY_FTS_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_id_like_query(query_text: str) -> bool:
    def _token_looks_like_id(token: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{3,}", token):
            return False
        has_digit = any(ch.isdigit() for ch in token)
        has_symbol = any(ch in "._:/-" for ch in token)
        if has_digit or has_symbol:
            return True
        # Uppercase alpha tokens are often reference codes.
        return token.isalpha() and token.isupper() and len(token) >= 6

    text = query_text.strip()
    if len(text) < 4 or len(text) > 128:
        return False
    if " " not in text:
        return _token_looks_like_id(text)

    tokens = [token for token in re.split(r"\s+", text) if token]
    if len(tokens) > 3:
        return False
    matching = [token for token in tokens if _token_looks_like_id(token)]
    return bool(matching) and len(matching) == len(tokens)


def _bm25_to_score(score: float) -> float:
    if score <= 0:
        return 0.0
    return _clamp_score(score / (score + 1.0))


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
    vector = run_inference(
        "text",
        lambda: get_text_embedder(768).encode([text])[0],
    )
    return tuple(vector)


@lru_cache(maxsize=256)
def _cached_image_text_vector(text: str) -> tuple[float, ...]:
    vector = run_inference(
        "image_text",
        lambda: get_image_text_embedder(512).encode([text])[0],
    )
    return tuple(vector)


@lru_cache(maxsize=256)
def _cached_vision_v2_text_vector(text: str) -> tuple[float, ...]:
    vector = run_inference(
        "vision_v2",
        lambda: get_image_text_embedder_v2(768).encode([text])[0],
    )
    return tuple(vector)


@lru_cache(maxsize=256)
def _cached_audio_text_vector(text: str) -> tuple[float, ...]:
    vector = run_inference(
        "audio_text",
        lambda: get_audio_text_embedder(512).encode([text])[0],
    )
    return tuple(vector)


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
        try:
            text_vec = list(_cached_text_vector(query_text))
        except InferenceTimeoutError:
            if trace is not None:
                trace["text_embed_timeout"] = 1
            raise
        if trace is not None:
            trace["text_embed_ms"] = round(
                (time.monotonic() - embed_start) * 1000.0, 2
            )

    image_text_vec = None
    if need_image:
        image_embed_start = time.monotonic()
        try:
            image_text_vec = list(_cached_image_text_vector(query_text))
        except InferenceTimeoutError:
            image_text_vec = None
            if trace is not None:
                trace["image_text_embed_timeout"] = 1
        if trace is not None:
            trace["image_text_embed_ms"] = round(
                (time.monotonic() - image_embed_start) * 1000.0, 2
            )

    audio_text_vec = None
    if need_audio:
        audio_embed_start = time.monotonic()
        try:
            audio_text_vec = list(_cached_audio_text_vector(query_text))
        except InferenceTimeoutError:
            audio_text_vec = None
            if trace is not None:
                trace["audio_text_embed_timeout"] = 1
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
        doc_has_id = _table_has_column(conn, "doc_chunks", "id")
        doc_has_chunk_index = _table_has_column(conn, "doc_chunks", "chunk_index")
        doc_has_source_type = _table_has_column(conn, "doc_chunks", "source_type")
        doc_has_source_time_ms = _table_has_column(conn, "doc_chunks", "source_time_ms")
        transcript_has_id = _table_has_column(conn, "transcripts", "id")
        transcript_has_end_ms = _table_has_column(conn, "transcripts", "end_ms")
        image_has_id = _table_has_column(conn, "image_assets", "id")
        has_vision_v2_vectors = (
            need_image
            and _vision_v2_enabled()
            and _table_has_column(conn, "image_assets", "vision_vector_v2")
        )
        has_audio_segments = _table_has_column(conn, "audio_segments", "clap_embedding")
        has_audio_clips = _table_has_column(conn, "audio_clips", "clap_embedding")
        audio_table = "audio_segments" if has_audio_segments else "audio_clips"
        audio_source_type = "audio_segment" if has_audio_segments else "audio"
        audio_has_id = _table_has_column(conn, audio_table, "id")
        audio_has_start_ms = _table_has_column(conn, audio_table, "start_ms")
        audio_has_end_ms = _table_has_column(conn, audio_table, "end_ms")

        doc_id_expr = "d.id" if doc_has_id else "CAST(d.media_asset_id AS VARCHAR)"
        if not doc_has_id and doc_has_chunk_index:
            doc_id_expr = (
                "CAST(d.media_asset_id AS VARCHAR) || ':doc:' || "
                "CAST(d.chunk_index AS VARCHAR)"
            )
        doc_source_type_expr = (
            "COALESCE(d.source_type, 'document')"
            if doc_has_source_type
            else "'document'"
        )
        doc_source_time_expr = (
            "d.source_time_ms"
            if doc_has_source_time_ms
            else "NULL"
        )
        transcript_id_expr = (
            "t.id"
            if transcript_has_id
            else "CAST(t.media_asset_id AS VARCHAR) || ':transcript:' || "
            "COALESCE(CAST(t.start_ms AS VARCHAR), '0')"
        )
        transcript_end_expr = "t.end_ms" if transcript_has_end_ms else "NULL AS end_ms"
        image_id_expr = (
            "i.id"
            if image_has_id
            else "CAST(i.media_asset_id AS VARCHAR) || ':image:' || "
            "COALESCE(CAST(i.timestamp_ms AS VARCHAR), '0')"
        )
        audio_id_expr = "a.id" if audio_has_id else "CAST(a.media_asset_id AS VARCHAR)"
        if not audio_has_id and audio_has_start_ms:
            audio_id_expr = (
                f"CAST(a.media_asset_id AS VARCHAR) || ':{audio_source_type}:' || "
                "COALESCE(CAST(a.start_ms AS VARCHAR), '0')"
            )
        audio_start_expr = "a.start_ms" if audio_has_start_ms else "NULL AS start_ms"
        audio_end_expr = "a.end_ms" if audio_has_end_ms else "NULL AS end_ms"
        scope_clause, scope_params = _scope_filters(conn, scope)
        image_text_vec_v2 = None
        if has_vision_v2_vectors:
            if scope_clause:
                probe_sql = (
                    "SELECT 1 FROM image_assets i "
                    "JOIN media_assets m ON i.media_asset_id = m.id "
                    f"{scope_clause} AND i.vision_vector_v2 IS NOT NULL "
                    "LIMIT 1"
                )
            else:
                probe_sql = (
                    "SELECT 1 FROM image_assets i "
                    "JOIN media_assets m ON i.media_asset_id = m.id "
                    "WHERE i.vision_vector_v2 IS NOT NULL "
                    "LIMIT 1"
                )
            has_vision_v2_vectors = bool(_query_rows(conn, probe_sql, scope_params))
        if has_vision_v2_vectors:
            image_v2_embed_start = time.monotonic()
            try:
                image_text_vec_v2 = list(_cached_vision_v2_text_vector(query_text))
            except InferenceTimeoutError:
                image_text_vec_v2 = None
                has_vision_v2_vectors = False
                if trace is not None:
                    trace["vision_v2_text_embed_timeout"] = 1
            if trace is not None:
                trace["vision_v2_text_embed_ms"] = round(
                    (time.monotonic() - image_v2_embed_start) * 1000.0, 2
                )

        doc_sql = f"""
            SELECT m.uri, m.media_type, d.media_asset_id, d.content,
                   {doc_id_expr} AS evidence_id,
                   {doc_source_type_expr} AS source_type,
                   {doc_source_time_expr} AS source_time_ms,
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
            _record_hitlist(
                trace,
                "document",
                doc_rows,
                uri_index=0,
                distance_index=7,
            )
            for row in doc_rows:
                if len(row) >= 8:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        content,
                        evidence_id,
                        source_type,
                        source_time_ms,
                        distance,
                    ) = row[:8]
                else:
                    uri, media_type, media_asset_id, content, distance = row[:5]
                    evidence_id = media_asset_id
                    source_type = "document"
                    source_time_ms = None
                source_type_text = str(source_type or "document").strip().lower()
                is_ocr = source_type_text in {"image", "keyframe", "pdf_page"}
                modality = "ocr" if is_ocr else "document"
                start_ms = (
                    int(source_time_ms)
                    if is_ocr and source_time_ms is not None
                    else None
                )
                score = _boost_score(
                    _score_from_distance(distance),
                    modality="document",
                    query_text=query_text,
                )
                results.append(
                    QueryResult(
                        modality=modality,
                        uri=uri,
                        snippet=content,
                        start_ms=start_ms,
                        end_ms=start_ms,
                        thumbnail_uri=None,
                        score=score,
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type=source_type_text,
                        evidence_refs=_evidence_refs_for(modality, str(evidence_id)),
                    )
                )

        if need_text and _fts_enabled() and _is_id_like_query(query_text):
            if not doc_has_id:
                if trace is not None:
                    trace["fts_status"] = "skipped_missing_doc_id"
            else:
                where_conditions = [
                    f"{doc_source_type_expr} IN ('image', 'keyframe', 'pdf_page')"
                ]
                if scope_clause:
                    where_conditions.append(scope_clause.replace("WHERE ", "", 1))
                where_sql = "WHERE " + " AND ".join(where_conditions)
                fts_sql = f"""
                    WITH ranked AS (
                        SELECT m.uri,
                               m.media_type,
                               d.media_asset_id,
                               d.content,
                               d.id AS evidence_id,
                               {doc_source_type_expr} AS source_type,
                               {doc_source_time_expr} AS source_time_ms,
                               fts_main_doc_chunks.match_bm25(d.id, ?) AS bm25
                        FROM doc_chunks d
                        JOIN media_assets m ON d.media_asset_id = m.id
                        {where_sql}
                    )
                    SELECT uri,
                           media_type,
                           media_asset_id,
                           content,
                           evidence_id,
                           source_type,
                           source_time_ms,
                           bm25
                    FROM ranked
                    WHERE bm25 IS NOT NULL
                    ORDER BY bm25 DESC
                    LIMIT {int(top_k)}
                """
                fts_start = time.monotonic()
                try:
                    fts_rows = _query_rows(conn, fts_sql, [query_text, *scope_params])
                except duckdb.Error:
                    if trace is not None:
                        trace["fts_status"] = "query_error"
                else:
                    if trace is not None:
                        trace["fts_query_ms"] = round(
                            (time.monotonic() - fts_start) * 1000.0, 2
                        )
                        trace["fts_rows"] = len(fts_rows)
                    _record_hitlist(
                        trace,
                        "fts_ocr",
                        fts_rows,
                        uri_index=0,
                    )
                    for row in fts_rows:
                        if len(row) >= 8:
                            (
                                uri,
                                media_type,
                                media_asset_id,
                                content,
                                evidence_id,
                                source_type,
                                source_time_ms,
                                bm25,
                            ) = row[:8]
                        elif len(row) >= 5:
                            uri, media_type, media_asset_id, content, bm25 = row[:5]
                            evidence_id = media_asset_id
                            source_type = "ocr"
                            source_time_ms = None
                        else:
                            continue
                        source_type_text = str(source_type or "ocr").strip().lower()
                        start_ms = (
                            int(source_time_ms)
                            if source_time_ms is not None
                            else None
                        )
                        results.append(
                            QueryResult(
                                modality="ocr",
                                uri=uri,
                                snippet=content,
                                start_ms=start_ms,
                                end_ms=start_ms,
                                thumbnail_uri=None,
                                score=_bm25_to_score(float(bm25)),
                                media_asset_id=media_asset_id,
                                media_type=media_type,
                                primary_evidence_id=str(evidence_id),
                                source_type=source_type_text,
                                evidence_refs=_evidence_refs_for("ocr", str(evidence_id)),
                                why=[
                                    {
                                        "modality": "fts",
                                        "source": "fts",
                                        "reason": "fts_hit",
                                        "raw_score": round(float(bm25), 6),
                                    }
                                ],
                            )
                        )
                    if trace is not None and "fts_status" not in trace:
                        trace["fts_status"] = "applied"

        transcript_sql = f"""
            SELECT m.uri, m.media_type, t.media_asset_id, t.content, t.start_ms,
                   {transcript_end_expr},
                   {transcript_id_expr} AS evidence_id,
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
            _record_hitlist(
                trace,
                "transcript",
                transcript_rows,
                uri_index=0,
                distance_index=7,
            )
            for row in transcript_rows:
                if len(row) >= 8:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        content,
                        start_ms,
                        end_ms,
                        evidence_id,
                        distance,
                    ) = row[:8]
                else:
                    uri, media_type, media_asset_id, content, start_ms, distance = row[:6]
                    end_ms = None
                    evidence_id = f"{media_asset_id}:transcript:{start_ms}"
                score = _boost_score(
                    _score_from_distance(distance),
                    modality="transcript",
                    query_text=query_text,
                )
                results.append(
                    QueryResult(
                        modality="transcript",
                        uri=uri,
                        snippet=content,
                        start_ms=int(start_ms) if start_ms is not None else None,
                        end_ms=int(end_ms) if end_ms is not None else None,
                        thumbnail_uri=None,
                        score=score,
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type="transcript",
                        evidence_refs=_evidence_refs_for("transcript", str(evidence_id)),
                    )
                )

        image_sql = f"""
            SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                   {thumbnail_expr},
                   {image_id_expr} AS evidence_id,
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
            _record_hitlist(
                trace,
                "image",
                image_rows,
                uri_index=0,
                distance_index=7,
            )
            for row in image_rows:
                if len(row) >= 7:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        evidence_id,
                        distance,
                    ) = row[:7]
                else:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        distance,
                    ) = row[:6]
                    evidence_id = f"{media_asset_id}:image:{timestamp_ms}"
                score = _boost_score(
                    _score_from_distance(distance),
                    modality="image",
                    query_text=query_text,
                )
                results.append(
                    QueryResult(
                        modality="image",
                        uri=uri,
                        snippet=None,
                        start_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                        end_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                        thumbnail_uri=thumbnail_uri,
                        score=score,
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type="keyframe" if timestamp_ms is not None else "image",
                        evidence_refs=_evidence_refs_for("image", str(evidence_id)),
                        embedding_model=os.getenv(
                            "IMAGE_MODEL_NAME",
                            "openai/clip-vit-base-patch32",
                        ),
                        embedding_backend=get_runtime_embedding_backend("image_text"),
                        why_modality="vision_v1",
                    )
                )

        if need_image and image_text_vec_v2 is not None:
            if scope_clause:
                image_scope_v2 = f"{scope_clause} AND i.vision_vector_v2 IS NOT NULL"
            else:
                image_scope_v2 = "WHERE i.vision_vector_v2 IS NOT NULL"
            image_sql_v2 = f"""
                SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                       {thumbnail_expr},
                       {image_id_expr} AS evidence_id,
                       (1.0 - list_cosine_similarity(
                           i.vision_vector_v2, ?::FLOAT[]
                       )) AS distance
                FROM image_assets i
                JOIN media_assets m ON i.media_asset_id = m.id
                {image_scope_v2}
                ORDER BY distance
                LIMIT {int(top_k)}
            """
            image_v2_start = time.monotonic()
            image_rows_v2 = _query_rows(conn, image_sql_v2, [image_text_vec_v2, *scope_params])
            if trace is not None:
                trace["vision_v2_query_ms"] = round(
                    (time.monotonic() - image_v2_start) * 1000.0, 2
                )
                trace["vision_v2_rows"] = len(image_rows_v2)
            _record_hitlist(
                trace,
                "vision_v2",
                image_rows_v2,
                uri_index=0,
                distance_index=7,
            )
            for row in image_rows_v2:
                if len(row) >= 7:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        evidence_id,
                        distance,
                    ) = row[:7]
                else:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        distance,
                    ) = row[:6]
                    evidence_id = f"{media_asset_id}:image:{timestamp_ms}"
                score = _boost_score(
                    _score_from_distance(distance),
                    modality="image",
                    query_text=query_text,
                )
                results.append(
                    QueryResult(
                        modality="image",
                        uri=uri,
                        snippet=None,
                        start_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                        end_ms=(
                            int(timestamp_ms) if timestamp_ms is not None else None
                        ),
                        thumbnail_uri=thumbnail_uri,
                        score=score,
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type="keyframe" if timestamp_ms is not None else "image",
                        evidence_refs=_evidence_refs_for("image", str(evidence_id)),
                        embedding_model=_vision_v2_model_name(),
                        embedding_backend=get_runtime_embedding_backend("vision_v2"),
                        why_modality="vision_v2",
                    )
                )

        audio_sql = f"""
            SELECT m.uri, m.media_type, a.media_asset_id,
                   {audio_start_expr},
                   {audio_end_expr},
                   {audio_id_expr} AS evidence_id,
                   (1.0 - list_cosine_similarity(
                       a.clap_embedding, ?::FLOAT[]
                   )) AS distance
            FROM {audio_table} a
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
                trace["audio_source"] = audio_table
            _record_hitlist(
                trace,
                "audio",
                audio_rows,
                uri_index=0,
                distance_index=6,
            )
            audio_results: list[QueryResult] = []
            for row in audio_rows:
                if len(row) >= 7:
                    (
                        uri,
                        media_type,
                        media_asset_id,
                        start_ms,
                        end_ms,
                        evidence_id,
                        distance,
                    ) = row[:7]
                else:
                    uri, media_type, media_asset_id, distance = row[:4]
                    start_ms = None
                    end_ms = None
                    evidence_id = media_asset_id
                score = _boost_score(
                    _score_from_distance(distance),
                    modality="audio",
                    query_text=query_text,
                )
                audio_results.append(
                    QueryResult(
                        modality="audio",
                        uri=uri,
                        snippet=None,
                        start_ms=int(start_ms) if start_ms is not None else None,
                        end_ms=int(end_ms) if end_ms is not None else None,
                        thumbnail_uri=None,
                        score=score,
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type=audio_source_type,
                        evidence_refs=_evidence_refs_for("audio", str(evidence_id)),
                    )
                )
            if has_audio_segments:
                merge_gap_ms = _audio_segment_merge_gap_ms()
                merged_audio_results = _merge_adjacent_audio_results(
                    audio_results,
                    gap_ms=merge_gap_ms,
                )
                if trace is not None:
                    trace["audio_rows_merged"] = len(merged_audio_results)
                    trace["audio_merge_gap_ms"] = merge_gap_ms
                audio_results = merged_audio_results
            if has_audio_segments and has_audio_clips and len(audio_results) < int(top_k):
                clip_has_id = _table_has_column(conn, "audio_clips", "id")
                clip_has_start_ms = _table_has_column(conn, "audio_clips", "start_ms")
                clip_has_end_ms = _table_has_column(conn, "audio_clips", "end_ms")
                clip_id_expr = (
                    "a.id"
                    if clip_has_id
                    else "CAST(a.media_asset_id AS VARCHAR)"
                )
                if not clip_has_id and clip_has_start_ms:
                    clip_id_expr = (
                        "CAST(a.media_asset_id AS VARCHAR) || ':audio:' || "
                        "COALESCE(CAST(a.start_ms AS VARCHAR), '0')"
                    )
                clip_start_expr = (
                    "a.start_ms" if clip_has_start_ms else "NULL AS start_ms"
                )
                clip_end_expr = "a.end_ms" if clip_has_end_ms else "NULL AS end_ms"
                audio_asset_ids = {
                    row.media_asset_id for row in audio_results if row.media_asset_id
                }
                fill_limit = max(0, int(top_k) - len(audio_results))
                # Overfetch slightly to account for skipping clip rows that belong to
                # assets already represented by audio segment results.
                clip_limit = fill_limit + len(audio_asset_ids)
                clip_sql = f"""
                    SELECT m.uri, m.media_type, a.media_asset_id,
                           {clip_start_expr},
                           {clip_end_expr},
                           {clip_id_expr} AS evidence_id,
                           (1.0 - list_cosine_similarity(
                               a.clap_embedding, ?::FLOAT[]
                           )) AS distance
                    FROM audio_clips a
                    JOIN media_assets m ON a.media_asset_id = m.id
                    {scope_clause}
                    ORDER BY distance
                    LIMIT {int(clip_limit)}
                """
                clip_rows = _query_rows(conn, clip_sql, [audio_text_vec, *scope_params])
                if trace is not None:
                    trace["audio_clip_fallback_rows"] = len(clip_rows)
                for row in clip_rows:
                    if len(audio_results) >= int(top_k):
                        break
                    if len(row) >= 7:
                        (
                            uri,
                            media_type,
                            media_asset_id,
                            start_ms,
                            end_ms,
                            evidence_id,
                            distance,
                        ) = row[:7]
                    else:
                        uri, media_type, media_asset_id, distance = row[:4]
                        start_ms = None
                        end_ms = None
                        evidence_id = media_asset_id
                    if media_asset_id in audio_asset_ids:
                        continue
                    score = _boost_score(
                        _score_from_distance(distance),
                        modality="audio",
                        query_text=query_text,
                    )
                    audio_results.append(
                        QueryResult(
                            modality="audio",
                            uri=uri,
                            snippet=None,
                            start_ms=int(start_ms) if start_ms is not None else None,
                            end_ms=int(end_ms) if end_ms is not None else None,
                            thumbnail_uri=None,
                            score=score,
                            media_asset_id=media_asset_id,
                            media_type=media_type,
                            primary_evidence_id=str(evidence_id),
                            source_type="audio",
                            evidence_refs=_evidence_refs_for("audio", str(evidence_id)),
                        )
                    )
            results.extend(audio_results)
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
        doc_has_id = _table_has_column(conn, "doc_chunks", "id")
        doc_has_chunk_index = _table_has_column(conn, "doc_chunks", "chunk_index")
        doc_has_source_type = _table_has_column(conn, "doc_chunks", "source_type")
        doc_has_source_time_ms = _table_has_column(conn, "doc_chunks", "source_time_ms")
        transcript_has_id = _table_has_column(conn, "transcripts", "id")
        transcript_has_end_ms = _table_has_column(conn, "transcripts", "end_ms")

        doc_id_expr = "d.id" if doc_has_id else "CAST(d.media_asset_id AS VARCHAR)"
        if not doc_has_id and doc_has_chunk_index:
            doc_id_expr = (
                "CAST(d.media_asset_id AS VARCHAR) || ':doc:' || "
                "CAST(d.chunk_index AS VARCHAR)"
            )
        doc_source_type_expr = (
            "COALESCE(d.source_type, 'document')"
            if doc_has_source_type
            else "'document'"
        )
        doc_source_time_expr = (
            "d.source_time_ms"
            if doc_has_source_time_ms
            else "NULL"
        )
        transcript_id_expr = (
            "t.id"
            if transcript_has_id
            else "CAST(t.media_asset_id AS VARCHAR) || ':transcript:' || "
            "COALESCE(CAST(t.start_ms AS VARCHAR), '0')"
        )
        transcript_end_expr = "t.end_ms" if transcript_has_end_ms else "NULL AS end_ms"

        scope_clause, scope_params = _scope_filters(conn, scope)
        scope_filter = scope_clause.replace("WHERE ", "", 1) if scope_clause else ""
        scope_sql = f" AND {scope_filter}" if scope_filter else ""
        doc_sql = f"""
            SELECT m.uri, m.media_type, d.media_asset_id, d.content,
                   {doc_id_expr} AS evidence_id,
                   {doc_source_type_expr} AS source_type,
                   {doc_source_time_expr} AS source_time_ms
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
        _record_hitlist(
            trace,
            "keyword_document",
            doc_rows,
            uri_index=0,
        )
        for (
            uri,
            media_type,
            media_asset_id,
            content,
            evidence_id,
            source_type,
            source_time_ms,
        ) in doc_rows:
            source_type_text = str(source_type or "document").strip().lower()
            is_ocr = source_type_text in {"image", "keyframe", "pdf_page"}
            modality = "ocr" if is_ocr else "document"
            start_ms = (
                int(source_time_ms)
                if is_ocr and source_time_ms is not None
                else None
            )
            results.append(
                QueryResult(
                    modality=modality,
                    uri=uri,
                    snippet=content,
                    start_ms=start_ms,
                    end_ms=start_ms,
                    thumbnail_uri=None,
                    score=1.0,
                    media_asset_id=media_asset_id,
                    media_type=media_type,
                    primary_evidence_id=str(evidence_id),
                    source_type=source_type_text,
                    evidence_refs=_evidence_refs_for(modality, str(evidence_id)),
                )
            )

        transcript_sql = f"""
            SELECT m.uri, m.media_type, t.media_asset_id, t.content, t.start_ms,
                   {transcript_end_expr},
                   {transcript_id_expr} AS evidence_id
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
        _record_hitlist(
            trace,
            "keyword_transcript",
            transcript_rows,
            uri_index=0,
        )
        for (
            uri,
            media_type,
            media_asset_id,
            content,
            start_ms,
            end_ms,
            evidence_id,
        ) in transcript_rows:
            results.append(
                QueryResult(
                    modality="transcript",
                    uri=uri,
                    snippet=content,
                    start_ms=int(start_ms) if start_ms is not None else None,
                    end_ms=int(end_ms) if end_ms is not None else None,
                    thumbnail_uri=None,
                    score=1.0,
                    media_asset_id=media_asset_id,
                    media_type=media_type,
                    primary_evidence_id=str(evidence_id),
                    source_type="transcript",
                    evidence_refs=_evidence_refs_for("transcript", str(evidence_id)),
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
        _record_hitlist(
            trace,
            "metadata",
            rows,
            uri_index=1,
        )
        results = [
            QueryResult(
                modality="metadata",
                uri=uri,
                snippet=None,
                start_ms=None,
                end_ms=None,
                thumbnail_uri=None,
                score=1.0,
                media_asset_id=media_asset_id,
                media_type=media_type,
                primary_evidence_id=str(media_asset_id),
                source_type="metadata",
                evidence_refs=[],
                why=[
                    {
                        "modality": "fts",
                        "source": "metadata",
                        "reason": "metadata_filter",
                    }
                ],
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
    vector = None
    embed_start = time.monotonic()
    try:
        vector = run_inference(
            "image",
            lambda: get_image_embedder(512).encode([image])[0],
        )
    except InferenceTimeoutError:
        if trace is not None:
            trace["image_embed_timeout"] = 1
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
        has_image_id = _table_has_column(conn, "image_assets", "id")
        thumbnail_expr = "i.thumbnail_uri" if has_thumbnail else "NULL AS thumbnail_uri"
        image_id_expr = (
            "i.id"
            if has_image_id
            else "CAST(i.media_asset_id AS VARCHAR) || ':image:' || "
            "COALESCE(CAST(i.timestamp_ms AS VARCHAR), '0')"
        )
        scope_clause, scope_params = _scope_filters(conn, scope)
        has_vision_v2_vectors = _vision_v2_enabled() and _table_has_column(
            conn,
            "image_assets",
            "vision_vector_v2",
        )
        vector_v2 = None
        if has_vision_v2_vectors:
            if scope_clause:
                probe_sql = (
                    "SELECT 1 FROM image_assets i "
                    "JOIN media_assets m ON i.media_asset_id = m.id "
                    f"{scope_clause} AND i.vision_vector_v2 IS NOT NULL "
                    "LIMIT 1"
                )
            else:
                probe_sql = (
                    "SELECT 1 FROM image_assets i "
                    "JOIN media_assets m ON i.media_asset_id = m.id "
                    "WHERE i.vision_vector_v2 IS NOT NULL "
                    "LIMIT 1"
                )
            has_vision_v2_vectors = bool(_query_rows(conn, probe_sql, scope_params))
        if has_vision_v2_vectors:
            embed_v2_start = time.monotonic()
            try:
                vector_v2 = run_inference(
                    "vision_v2",
                    lambda: get_image_embedder_v2(768).encode([image])[0],
                )
            except InferenceTimeoutError:
                vector_v2 = None
                if trace is not None:
                    trace["vision_v2_embed_timeout"] = 1
            if trace is not None:
                trace["vision_v2_embed_ms"] = round(
                    (time.monotonic() - embed_v2_start) * 1000.0, 2
                )

        image_sql = f"""
            SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                   {thumbnail_expr},
                   {image_id_expr} AS evidence_id,
                   (1.0 - list_cosine_similarity(i.clip_vector, ?::FLOAT[])) AS distance
            FROM image_assets i
            JOIN media_assets m ON i.media_asset_id = m.id
            {scope_clause}
            ORDER BY distance
            LIMIT {int(top_k)}
        """
        results: list[QueryResult] = []
        if vector is not None:
            image_start = time.monotonic()
            image_rows = _query_rows(conn, image_sql, [vector, *scope_params])
            if trace is not None:
                trace["image_query_ms"] = round(
                    (time.monotonic() - image_start) * 1000.0, 2
                )
                trace["image_rows"] = len(image_rows)
            _record_hitlist(
                trace,
                "image",
                image_rows,
                uri_index=0,
                distance_index=6,
            )
            results.extend(
                [
                    QueryResult(
                        modality="image",
                        uri=uri,
                        snippet=None,
                        start_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                        end_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                        thumbnail_uri=thumbnail_uri,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type="keyframe" if timestamp_ms is not None else "image",
                        evidence_refs=_evidence_refs_for("image", str(evidence_id)),
                        embedding_model=os.getenv(
                            "IMAGE_MODEL_NAME",
                            "openai/clip-vit-base-patch32",
                        ),
                        embedding_backend=get_runtime_embedding_backend("image"),
                        why_modality="vision_v1",
                    )
                    for (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        evidence_id,
                        distance,
                    ) in image_rows
                ]
            )
        if vector_v2 is not None:
            if scope_clause:
                image_scope_v2 = f"{scope_clause} AND i.vision_vector_v2 IS NOT NULL"
            else:
                image_scope_v2 = "WHERE i.vision_vector_v2 IS NOT NULL"
            image_sql_v2 = f"""
                SELECT m.uri, m.media_type, i.media_asset_id, i.timestamp_ms,
                       {thumbnail_expr},
                       {image_id_expr} AS evidence_id,
                       (1.0 - list_cosine_similarity(
                           i.vision_vector_v2, ?::FLOAT[]
                       )) AS distance
                FROM image_assets i
                JOIN media_assets m ON i.media_asset_id = m.id
                {image_scope_v2}
                ORDER BY distance
                LIMIT {int(top_k)}
            """
            image_v2_start = time.monotonic()
            image_rows_v2 = _query_rows(conn, image_sql_v2, [vector_v2, *scope_params])
            if trace is not None:
                trace["vision_v2_query_ms"] = round(
                    (time.monotonic() - image_v2_start) * 1000.0, 2
                )
                trace["vision_v2_rows"] = len(image_rows_v2)
            _record_hitlist(
                trace,
                "vision_v2",
                image_rows_v2,
                uri_index=0,
                distance_index=6,
            )
            results.extend(
                [
                    QueryResult(
                        modality="image",
                        uri=uri,
                        snippet=None,
                        start_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                        end_ms=int(timestamp_ms) if timestamp_ms is not None else None,
                        thumbnail_uri=thumbnail_uri,
                        score=_score_from_distance(distance),
                        media_asset_id=media_asset_id,
                        media_type=media_type,
                        primary_evidence_id=str(evidence_id),
                        source_type="keyframe" if timestamp_ms is not None else "image",
                        evidence_refs=_evidence_refs_for("image", str(evidence_id)),
                        embedding_model=_vision_v2_model_name(),
                        embedding_backend=get_runtime_embedding_backend("vision_v2"),
                        why_modality="vision_v2",
                    )
                    for (
                        uri,
                        media_type,
                        media_asset_id,
                        timestamp_ms,
                        thumbnail_uri,
                        evidence_id,
                        distance,
                    ) in image_rows_v2
                ]
            )
    finally:
        _release_conn(snapshot_path, conn)

    if not results:
        raise InferenceTimeoutError("image query produced no embeddings")

    results.sort(key=lambda item: item.score, reverse=True)
    return results[: int(top_k)]


def fuse_results(
    results: Sequence[QueryResult],
    *,
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    if not results:
        return []

    k = _fuse_k()
    weights = _fusion_weights()
    ranked_by_modality: dict[str, list[QueryResult]] = {}
    for item in results:
        ranked_by_modality.setdefault(item.modality, []).append(item)

    for values in ranked_by_modality.values():
        values.sort(key=lambda row: row.score, reverse=True)

    merged: dict[tuple[str, str, str, int | None, int | None], QueryResult] = {}
    for modality, rows in ranked_by_modality.items():
        canonical = _canonical_modality(modality)
        weight = float(weights.get(canonical, 1.0))
        for idx, row in enumerate(rows, start=1):
            contribution = weight / float(k + idx)
            key = _result_key(row)
            why_modality = row.why_modality or canonical
            existing = merged.get(key)
            detail = {
                "modality": why_modality,
                "source": "vector",
                "rank": idx,
                "weight": round(weight, 6),
                "contribution": round(contribution, 8),
                "raw_score": round(float(row.score), 6),
            }
            if row.embedding_model:
                detail["model"] = row.embedding_model
            if row.embedding_backend:
                detail["backend"] = row.embedding_backend
            if existing is None:
                item = replace(row)
                item.score = contribution
                item.why = list(item.why) + [detail]
                merged[key] = item
            else:
                existing.score += contribution
                existing.why.append(detail)
                if row.snippet and not existing.snippet:
                    existing.snippet = row.snippet

    fused = list(merged.values())
    max_score = max(item.score for item in fused) if fused else 1.0
    if max_score > 0:
        for item in fused:
            item.score = _clamp_score(item.score / max_score)

    fused.sort(key=lambda row: row.score, reverse=True)
    if trace is not None:
        trace["fusion_method"] = "weighted_rrf"
        trace["fusion_weight_version"] = os.getenv("QUERY_FUSION_WEIGHT_VERSION", "v1")
    return fused


def rerank_text_candidates(
    *,
    query_text: str | None,
    results: Sequence[QueryResult],
    trace: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    if not results:
        return []
    if not query_text or not query_text.strip():
        return list(results)
    if not _rerank_enabled():
        if trace is not None:
            trace["rerank_status"] = "disabled"
        return list(results)

    text_candidates = [
        (idx, row)
        for idx, row in enumerate(results)
        if row.snippet and _canonical_modality(row.modality) in {"text", "ocr"}
    ]
    if not text_candidates:
        if trace is not None:
            trace["rerank_status"] = "skipped_no_text_candidates"
        return list(results)

    top_n = _rerank_top_n()
    text_candidates.sort(key=lambda pair: pair[1].score, reverse=True)
    min_candidates = _rerank_min_candidates()
    max_total_chars = _rerank_max_total_chars()
    selected: list[tuple[int, QueryResult]] = []
    selected_chars = 0
    for pair in text_candidates:
        if len(selected) >= top_n:
            break
        candidate_len = len(pair[1].snippet or "")
        if (
            max_total_chars > 0
            and len(selected) >= min_candidates
            and (selected_chars + candidate_len) > max_total_chars
        ):
            break
        selected.append(pair)
        selected_chars += candidate_len

    if len(selected) < min_candidates:
        if trace is not None:
            trace["rerank_status"] = "skipped_low_candidate_count"
            trace["rerank_candidates"] = len(selected)
        return list(results)

    if len(selected) >= 2:
        top_score = float(selected[0][1].score)
        runner_up_score = float(selected[1][1].score)
        score_gap = top_score - runner_up_score
        gap_threshold = _rerank_skip_score_gap()
        min_score = _rerank_skip_min_score()
        if top_score >= min_score and score_gap >= gap_threshold:
            if trace is not None:
                trace["rerank_status"] = "skipped_confident_top_result"
                trace["rerank_candidates"] = len(selected)
                trace["rerank_selected_chars"] = selected_chars
                trace["rerank_score_gap"] = round(score_gap, 6)
            return list(results)
    selected_docs = [row.snippet or "" for _, row in selected]

    rerank_start = time.monotonic()
    try:
        raw_scores = run_inference(
            "rerank",
            lambda: get_reranker().score(query_text, selected_docs),
        )
    except InferenceTimeoutError:
        if trace is not None:
            trace["rerank_status"] = "timeout_skip"
            trace["rerank_candidates"] = len(selected)
        return list(results)
    except Exception:
        if trace is not None:
            trace["rerank_status"] = "error_skip"
            trace["rerank_candidates"] = len(selected)
        return list(results)

    scores = normalize_rerank_scores(raw_scores)
    reranked = list(results)
    for (result_idx, row), rerank_score in zip(selected, scores, strict=False):
        base = float(row.score)
        blended = (0.5 * base) + (0.5 * float(rerank_score))
        updated = replace(row)
        updated.score = _clamp_score(blended)
        updated.why = list(updated.why) + [
            {
                "modality": _canonical_modality(row.modality),
                "source": "rerank",
                "model": os.getenv("RERANK_MODEL_NAME", ""),
                "backend": os.getenv("RERANK_BACKEND", ""),
                "raw_score": round(float(rerank_score), 6),
                "base_score": round(base, 6),
                "blended_score": round(updated.score, 6),
            }
        ]
        reranked[result_idx] = updated

    if trace is not None:
        trace["rerank_status"] = "applied"
        trace["rerank_candidates"] = len(selected)
        trace["rerank_selected_chars"] = selected_chars
        trace["rerank_ms"] = round((time.monotonic() - rerank_start) * 1000.0, 2)

    reranked.sort(key=lambda row: row.score, reverse=True)
    return reranked


def highlight_for_result(item: QueryResult, query_text: str | None) -> str | None:
    return _highlight_text(item.snippet, query_text)
