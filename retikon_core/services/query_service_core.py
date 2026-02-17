from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Mapping

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from retikon_core.embeddings import (
    get_audio_text_embedder,
    get_image_embedder,
    get_image_text_embedder,
    get_image_embedder_v2,
    get_image_text_embedder_v2,
    get_reranker,
    get_text_embedder,
)
from retikon_core.embeddings.timeout import run_inference
from retikon_core.privacy import (
    PrivacyContext,
    load_privacy_policies,
    redact_text_for_context,
)
from retikon_core.query_engine.query_runner import (
    QueryResult,
    fuse_results,
    highlight_for_result,
    rerank_text_candidates,
    search_by_image,
    search_by_keyword,
    search_by_metadata,
    search_by_text,
)
from retikon_core.tenancy.types import TenantScope

ALLOWED_SEARCH_TYPES = {"vector", "keyword", "metadata"}
_ALLOWED_GROUP_BY = {"none", "video"}
_ALLOWED_SORT_BY = {"score", "clip_count"}
_ALLOWED_FILTER_OPS = {
    "eq",
    "neq",
    "in",
    "nin",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "exists",
}
_SYSTEM_FILTER_FIELDS = {
    "asset_id",
    "asset_type",
    "duration_ms",
    "created_at",
    "source_type",
    "start_ms",
    "end_ms",
}

_CANONICAL_MODALITIES = {"text", "ocr", "vision", "audio", "video"}
_MODE_TO_CANONICAL = {
    "text": {"text", "ocr"},
    "image": {"vision"},
    "audio": {"audio"},
    "video": {"video", "vision", "audio", "text", "ocr"},
    "all": set(_CANONICAL_MODALITIES),
}


class QueryValidationError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 400,
        code: str = "VALIDATION_ERROR",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.details = details or []


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str | None = None
    image_base64: str | None = None
    top_k: int = Field(default=100, ge=1, le=500)
    page_limit: int | None = Field(default=None, ge=1, le=200)
    page_token: str | None = None
    mode: str | None = None
    modalities: list[str] | None = None
    search_type: str | None = None
    metadata_filters: dict[str, str] | None = None
    filters: dict[str, Any] | None = None
    group_by: str = "none"
    sort_by: str = "score"


class WhyContribution(BaseModel):
    modality: str
    source: str
    rank: int | None = None
    weight: float | None = None
    contribution: float | None = None
    raw_score: float | None = None
    reason: str | None = None
    model: str | None = None
    backend: str | None = None
    base_score: float | None = None
    blended_score: float | None = None


class QueryHit(BaseModel):
    asset_id: str
    asset_type: str
    start_ms: int | None = None
    end_ms: int | None = None
    score: float
    modality: str
    highlight_text: str | None = None
    primary_evidence_id: str
    evidence_refs: list[dict[str, str]] = Field(default_factory=list)
    why: list[WhyContribution] = Field(default_factory=list)

    # Backwards-compatible fields still consumed by eval harness/legacy clients.
    uri: str | None = None
    snippet: str | None = None
    timestamp_ms: int | None = None
    thumbnail_uri: str | None = None
    media_asset_id: str | None = None
    media_type: str | None = None


class GroupedVideo(BaseModel):
    asset_id: str
    clip_count: int
    best_score: float
    top_moments: list[QueryHit] = Field(default_factory=list)


class QueryGrouping(BaseModel):
    total_videos: int
    total_moments: int
    videos: list[GroupedVideo] = Field(default_factory=list)


class QueryMeta(BaseModel):
    fusion_method: str
    weight_version: str
    snapshot_marker: str
    request_id: str | None = None
    trace_id: str | None = None


class QueryResponse(BaseModel):
    results: list[QueryHit]
    next_page_token: str | None = None
    grouping: QueryGrouping | None = None
    meta: QueryMeta | None = None


def _canonical_modality(modality: str) -> str:
    value = modality.strip().lower()
    if value in {"document", "transcript", "text"}:
        return "text"
    if value in {"image", "vision"}:
        return "vision"
    if value in {"audio"}:
        return "audio"
    if value in {"ocr"}:
        return "ocr"
    if value in {"video"}:
        return "video"
    return value


def _expand_to_retrieval_modalities(canonical: set[str]) -> set[str]:
    retrieval: set[str] = set()
    for item in canonical:
        if item in {"text", "ocr"}:
            retrieval.update({"document", "transcript"})
        elif item in {"vision", "video"}:
            retrieval.add("image")
        elif item in {"audio", "video"}:
            retrieval.add("audio")
    return retrieval


def resolve_modalities(payload: QueryRequest) -> set[str]:
    if payload.modalities:
        canonical: set[str] = set()
        for raw in payload.modalities:
            cleaned = raw.strip().lower()
            if cleaned in {"document", "transcript"}:
                canonical.add("text")
                continue
            if cleaned == "image":
                canonical.add("vision")
                continue
            if cleaned in _CANONICAL_MODALITIES:
                canonical.add(cleaned)
                continue
            raise QueryValidationError(
                f"Unsupported modality: {raw}",
                code="UNSUPPORTED_MODALITY",
            )
        return _expand_to_retrieval_modalities(canonical)

    if payload.mode:
        mode = payload.mode.strip().lower()
        canonical = _MODE_TO_CANONICAL.get(mode)
        if canonical is None:
            raise QueryValidationError(
                f"Unsupported mode: {payload.mode}",
                code="UNSUPPORTED_MODE",
            )
        return _expand_to_retrieval_modalities(set(canonical))

    default_raw = os.getenv("QUERY_DEFAULT_MODALITIES", "all")
    cleaned_default = default_raw.strip().lower()
    if cleaned_default == "all":
        return _expand_to_retrieval_modalities(set(_CANONICAL_MODALITIES))

    canonical_default: set[str] = set()
    for raw in default_raw.split(","):
        candidate = raw.strip().lower()
        if not candidate:
            continue
        if candidate in {"document", "transcript"}:
            canonical_default.add("text")
        elif candidate == "image":
            canonical_default.add("vision")
        elif candidate in _CANONICAL_MODALITIES:
            canonical_default.add(candidate)
    if not canonical_default:
        canonical_default = set(_CANONICAL_MODALITIES)
    return _expand_to_retrieval_modalities(canonical_default)


def resolve_search_type(payload: QueryRequest) -> str:
    raw = payload.search_type or "vector"
    search_type = raw.strip().lower()
    if search_type not in ALLOWED_SEARCH_TYPES:
        raise QueryValidationError(
            f"Unsupported search_type: {payload.search_type}",
            code="UNSUPPORTED_MODE",
        )
    return search_type


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _validate_filter_leaf(node: Mapping[str, Any], path: str) -> None:
    field = node.get("field")
    op = node.get("op")
    if not isinstance(field, str) or not field.strip():
        raise QueryValidationError(
            "Filter leaf requires field",
            details=[{"field": path, "reason": "missing_field"}],
        )
    if not isinstance(op, str) or op.strip().lower() not in _ALLOWED_FILTER_OPS:
        raise QueryValidationError(
            "Unsupported filter operator",
            details=[{"field": path, "reason": "unsupported_operator", "actual": op}],
        )

    field_name = field.strip()
    if field_name not in _SYSTEM_FILTER_FIELDS and not field_name.startswith("metadata."):
        raise QueryValidationError(
            "Unknown filter field",
            details=[{"field": path, "reason": "unknown_field", "actual": field_name}],
        )

    normalized_op = op.strip().lower()
    if normalized_op == "exists":
        return
    if "value" not in node:
        raise QueryValidationError(
            "Filter leaf requires value",
            details=[{"field": path, "reason": "missing_value"}],
        )
    if normalized_op in {"in", "nin"} and not isinstance(node["value"], list):
        raise QueryValidationError(
            "Filter value for in/nin must be a list",
            details=[{"field": path, "reason": "invalid_value_type"}],
        )
    if normalized_op == "between":
        value = node["value"]
        if not isinstance(value, list) or len(value) != 2:
            raise QueryValidationError(
                "Filter value for between must be [lower, upper]",
                details=[{"field": path, "reason": "invalid_between_value"}],
            )


def _validate_filter_node(node: Any, path: str) -> None:
    if not isinstance(node, Mapping):
        raise QueryValidationError(
            "Filter node must be an object",
            details=[{"field": path, "reason": "invalid_node"}],
        )

    allowed = {"all", "any", "not", "field", "op", "value"}
    unknown = sorted(set(node.keys()) - allowed)
    if unknown:
        raise QueryValidationError(
            "Unknown filter node fields",
            details=[{"field": path, "reason": "unknown_keys", "actual": unknown}],
        )

    if "all" in node:
        items = node["all"]
        if not isinstance(items, list) or not items:
            raise QueryValidationError(
                "all must be a non-empty list",
                details=[{"field": path, "reason": "invalid_all"}],
            )
        for idx, child in enumerate(items):
            _validate_filter_node(child, f"{path}.all[{idx}]")
        return

    if "any" in node:
        items = node["any"]
        if not isinstance(items, list) or not items:
            raise QueryValidationError(
                "any must be a non-empty list",
                details=[{"field": path, "reason": "invalid_any"}],
            )
        for idx, child in enumerate(items):
            _validate_filter_node(child, f"{path}.any[{idx}]")
        return

    if "not" in node:
        _validate_filter_node(node["not"], f"{path}.not")
        return

    _validate_filter_leaf(node, path)


def _has_metadata_filter(node: Any) -> bool:
    if isinstance(node, Mapping):
        field = node.get("field")
        if isinstance(field, str) and field.startswith("metadata."):
            return True
        if "all" in node and isinstance(node["all"], list):
            return any(_has_metadata_filter(item) for item in node["all"])
        if "any" in node and isinstance(node["any"], list):
            return any(_has_metadata_filter(item) for item in node["any"])
        if "not" in node:
            return _has_metadata_filter(node["not"])
    return False


def validate_query_payload(
    *,
    payload: QueryRequest,
    search_type: str,
    modalities: set[str],
    max_image_base64_bytes: int,
) -> None:
    if payload.page_limit is not None and payload.page_limit > payload.top_k:
        raise QueryValidationError(
            "page_limit must be <= top_k",
            details=[
                {
                    "field": "page_limit",
                    "reason": "page_limit_gt_top_k",
                    "expected": f"<= {payload.top_k}",
                    "actual": payload.page_limit,
                }
            ],
        )

    group_by = payload.group_by.strip().lower()
    if group_by not in _ALLOWED_GROUP_BY:
        raise QueryValidationError(
            f"Unsupported group_by: {payload.group_by}",
            code="UNSUPPORTED_MODE",
        )
    if group_by == "video" and not _parse_bool_env("SEARCH_GROUP_BY_ENABLED", True):
        raise QueryValidationError(
            "group_by=video is disabled",
            code="UNSUPPORTED_MODE",
        )

    sort_by = payload.sort_by.strip().lower()
    if sort_by not in _ALLOWED_SORT_BY:
        raise QueryValidationError(
            f"Unsupported sort_by: {payload.sort_by}",
            code="UNSUPPORTED_MODE",
        )

    if payload.page_token and not _parse_bool_env("SEARCH_PAGINATION_ENABLED", True):
        raise QueryValidationError(
            "Pagination is disabled",
            code="UNSUPPORTED_MODE",
        )

    if (
        not payload.query_text
        and not payload.image_base64
        and search_type != "metadata"
    ):
        raise QueryValidationError("query_text or image_base64 is required")

    if payload.image_base64 and len(payload.image_base64) > max_image_base64_bytes:
        raise QueryValidationError(
            "Image payload too large",
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
        )

    if payload.image_base64 and "image" not in modalities:
        raise QueryValidationError("image_base64 requires image modality")

    if search_type != "vector" and payload.image_base64:
        raise QueryValidationError(
            "image_base64 is only supported for vector search"
        )

    if search_type == "keyword" and not payload.query_text:
        raise QueryValidationError("query_text is required for keyword search")

    if search_type == "metadata":
        if payload.query_text or payload.image_base64:
            raise QueryValidationError(
                "metadata search does not accept query_text or image_base64"
            )
        if not payload.metadata_filters and not payload.filters:
            raise QueryValidationError(
                "metadata_filters or filters is required for metadata search"
            )

    if payload.filters is not None:
        if not _parse_bool_env("SEARCH_FILTERS_V1_ENABLED", True):
            raise QueryValidationError(
                "filters are disabled",
                code="UNSUPPORTED_MODE",
            )
        _validate_filter_node(payload.filters, "filters")
        if _has_metadata_filter(payload.filters):
            raise QueryValidationError(
                "metadata.<key> filters require control-plane metadata integration",
                code="UNSUPPORTED_MODE",
            )


def _coerce_rfc3339(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _extract_filter_value(item: QueryResult, field: str) -> Any:
    if field == "asset_id":
        return item.media_asset_id
    if field == "asset_type":
        return item.media_type
    if field == "source_type":
        if item.source_type:
            return item.source_type
        return _canonical_modality(item.modality)
    if field == "start_ms":
        return item.start_ms
    if field == "end_ms":
        return item.end_ms
    if field == "duration_ms":
        if item.start_ms is None or item.end_ms is None:
            return None
        return max(0, item.end_ms - item.start_ms)
    if field == "created_at":
        return None
    return None


def _compare_filter(op: str, left: Any, right: Any) -> bool:
    normalized = op.lower()
    if normalized == "exists":
        return left is not None
    if normalized == "eq":
        return left == right
    if normalized == "neq":
        return left != right
    if normalized == "in":
        return isinstance(right, list) and left in right
    if normalized == "nin":
        return isinstance(right, list) and left not in right

    if left is None:
        return False

    left_value = left
    right_value = right
    if isinstance(left, str):
        left_dt = _coerce_rfc3339(left)
        right_dt = _coerce_rfc3339(right)
        if left_dt is not None and right_dt is not None:
            left_value = left_dt
            right_value = right_dt

    if normalized == "gt":
        return left_value > right_value
    if normalized == "gte":
        return left_value >= right_value
    if normalized == "lt":
        return left_value < right_value
    if normalized == "lte":
        return left_value <= right_value
    if normalized == "between":
        if not isinstance(right, list) or len(right) != 2:
            return False
        lower = right[0]
        upper = right[1]
        return left_value >= lower and left_value <= upper
    return False


def _evaluate_filter(node: Mapping[str, Any], item: QueryResult) -> bool:
    if "all" in node:
        entries = node.get("all")
        return isinstance(entries, list) and all(
            _evaluate_filter(child, item) for child in entries if isinstance(child, Mapping)
        )
    if "any" in node:
        entries = node.get("any")
        return isinstance(entries, list) and any(
            _evaluate_filter(child, item) for child in entries if isinstance(child, Mapping)
        )
    if "not" in node:
        child = node.get("not")
        return not _evaluate_filter(child, item) if isinstance(child, Mapping) else False

    field = str(node.get("field", "")).strip()
    op = str(node.get("op", "")).strip().lower()
    value = node.get("value")
    left = _extract_filter_value(item, field)
    return _compare_filter(op, left, value)


def apply_filters(
    *,
    results: list[QueryResult],
    filters: Mapping[str, Any] | None,
) -> list[QueryResult]:
    if not filters:
        return results
    return [item for item in results if _evaluate_filter(filters, item)]


def run_query(
    *,
    payload: QueryRequest,
    snapshot_path: str,
    search_type: str,
    modalities: set[str],
    scope: TenantScope | None = None,
    timings: dict[str, float | int | str] | None = None,
) -> list[QueryResult]:
    trace = timings if timings is not None else {}
    results: list[QueryResult] = []

    if search_type == "vector" and payload.query_text:
        results.extend(
            search_by_text(
                snapshot_path=snapshot_path,
                query_text=payload.query_text,
                top_k=payload.top_k,
                modalities=list(modalities),
                scope=scope,
                trace=trace,
            )
        )
    elif search_type == "keyword" and payload.query_text:
        results.extend(
            search_by_keyword(
                snapshot_path=snapshot_path,
                query_text=payload.query_text,
                top_k=payload.top_k,
                scope=scope,
                trace=trace,
            )
        )
    elif search_type == "metadata":
        metadata_filters = payload.metadata_filters
        if metadata_filters is None and payload.filters:
            metadata_filters = _leaf_filters_to_legacy_dict(payload.filters)
        if metadata_filters:
            try:
                results.extend(
                    search_by_metadata(
                        snapshot_path=snapshot_path,
                        filters=metadata_filters,
                        top_k=payload.top_k,
                        scope=scope,
                        trace=trace,
                    )
                )
            except ValueError as exc:
                raise QueryValidationError(str(exc)) from exc

    if payload.image_base64:
        try:
            results.extend(
                search_by_image(
                    snapshot_path=snapshot_path,
                    image_base64=payload.image_base64,
                    top_k=payload.top_k,
                    scope=scope,
                    trace=trace,
                )
            )
        except ValueError as exc:
            raise QueryValidationError(str(exc)) from exc

    results = apply_filters(results=results, filters=payload.filters)

    fused = fuse_results(results, trace=trace)
    reranked = rerank_text_candidates(
        query_text=payload.query_text,
        results=fused,
        trace=trace,
    )
    return reranked


def _leaf_filters_to_legacy_dict(filters: Mapping[str, Any]) -> dict[str, str] | None:
    # Legacy bridge for metadata search until full FilterSpec pushdown is implemented.
    if "field" in filters and "op" in filters and "value" in filters:
        field = str(filters["field"])
        op = str(filters["op"]).lower()
        value = filters.get("value")
        if op == "eq" and isinstance(value, str):
            if field in {"asset_type", "source_type"}:
                if field == "asset_type":
                    return {"media_type": value}
                return None
            if field == "asset_id":
                return {"uri": value}
        return None
    return None


def apply_privacy_redaction(
    *,
    results: list[QueryResult],
    base_uri: str,
    scope: TenantScope | None,
    is_admin: bool,
    logger,
) -> list[QueryResult]:
    try:
        policies = load_privacy_policies(base_uri)
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


def describe_query_modality(payload: QueryRequest, search_type: str) -> str:
    if search_type == "metadata":
        return "metadata"
    if search_type == "keyword":
        return "keyword"
    if payload.query_text and payload.image_base64:
        return "text+image"
    if payload.image_base64:
        return "image"
    return "text"


def _result_sort_tuple(item: QueryHit, sort_by: str) -> tuple[Any, ...]:
    score_key = -float(item.score)
    asset_key = item.asset_id or ""
    start_key = item.start_ms if item.start_ms is not None else -1
    evidence_key = item.primary_evidence_id or ""
    if sort_by == "clip_count":
        return (asset_key,)
    return (score_key, asset_key, start_key, evidence_key)


def _sorted_hits(hits: list[QueryHit]) -> list[QueryHit]:
    return sorted(
        hits,
        key=lambda item: (
            -float(item.score),
            item.asset_id or "",
            item.start_ms if item.start_ms is not None else -1,
            item.primary_evidence_id or "",
        ),
    )


def _encode_cursor(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(token: str) -> dict[str, Any]:
    padded = token + ("=" * ((4 - len(token) % 4) % 4))
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    payload = json.loads(raw.decode("ascii"))
    if not isinstance(payload, dict):
        raise ValueError("Cursor payload must be an object")
    return payload


def _query_fingerprint(payload: QueryRequest) -> str:
    body = payload.model_dump(exclude_none=True, exclude={"page_token"})
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_hit(item: QueryResult, query_text: str | None) -> QueryHit:
    canonical = _canonical_modality(item.modality)
    highlight = highlight_for_result(item, query_text)
    why_enabled = _parse_bool_env("SEARCH_WHY_ENABLED", True)
    why_items = [WhyContribution.model_validate(entry) for entry in item.why] if why_enabled else []

    return QueryHit(
        asset_id=item.media_asset_id or item.uri,
        asset_type=item.media_type or "unknown",
        start_ms=item.start_ms,
        end_ms=item.end_ms,
        score=round(float(item.score), 6),
        modality=canonical,
        highlight_text=highlight,
        primary_evidence_id=item.primary_evidence_id,
        evidence_refs=list(item.evidence_refs),
        why=why_items,
        uri=item.uri,
        snippet=item.snippet,
        timestamp_ms=item.start_ms,
        thumbnail_uri=item.thumbnail_uri,
        media_asset_id=item.media_asset_id,
        media_type=item.media_type,
    )


def build_query_response(
    results: Iterable[QueryResult],
    *,
    payload: QueryRequest,
    snapshot_marker: str,
    trace_id: str | None = None,
) -> QueryResponse:
    page_limit = payload.page_limit or payload.top_k
    page_limit = max(1, min(int(page_limit), payload.top_k))

    query_hash = _query_fingerprint(payload)
    sort_by = payload.sort_by.strip().lower()
    group_by = payload.group_by.strip().lower()

    hits = [_build_hit(item, payload.query_text) for item in results]
    hits = _sorted_hits(hits)

    cursor_offset = 0
    if payload.page_token:
        try:
            cursor = _decode_cursor(payload.page_token)
        except Exception as exc:
            raise QueryValidationError(
                "Invalid page_token",
                details=[{"field": "page_token", "reason": "invalid_cursor"}],
            ) from exc
        if cursor.get("query_fingerprint") != query_hash:
            raise QueryValidationError(
                "page_token does not match query",
                details=[{"field": "page_token", "reason": "query_mismatch"}],
            )
        if str(cursor.get("snapshot_marker")) != str(snapshot_marker):
            raise QueryValidationError(
                "page_token snapshot mismatch",
                details=[{"field": "page_token", "reason": "snapshot_mismatch"}],
            )
        try:
            cursor_offset = int(cursor.get("offset") or 0)
        except (TypeError, ValueError):
            cursor_offset = 0
        cursor_offset = max(0, cursor_offset)

    next_page_token: str | None = None
    grouping: QueryGrouping | None = None

    if group_by == "video":
        grouped: dict[str, list[QueryHit]] = {}
        for hit in hits:
            grouped.setdefault(hit.asset_id, []).append(hit)

        groups: list[GroupedVideo] = []
        for asset_id, members in grouped.items():
            members_sorted = _sorted_hits(members)
            groups.append(
                GroupedVideo(
                    asset_id=asset_id,
                    clip_count=len(members_sorted),
                    best_score=round(float(members_sorted[0].score), 6),
                    top_moments=members_sorted[:3],
                )
            )

        if sort_by == "clip_count":
            groups.sort(
                key=lambda row: (
                    -row.clip_count,
                    row.asset_id,
                    -row.best_score,
                )
            )
        else:
            groups.sort(
                key=lambda row: (
                    -row.best_score,
                    row.asset_id,
                    -row.clip_count,
                )
            )

        paged_groups = groups[cursor_offset : cursor_offset + page_limit]
        paged_hits: list[QueryHit] = []
        for row in paged_groups:
            paged_hits.extend(_sorted_hits(grouped.get(row.asset_id, [])))
        paged_hits = _sorted_hits(paged_hits)

        next_offset = cursor_offset + page_limit
        if next_offset < len(groups):
            last_tuple = None
            if paged_groups:
                last = paged_groups[-1]
                last_tuple = [last.clip_count, last.asset_id, last.best_score]
            next_page_token = _encode_cursor(
                {
                    "query_fingerprint": query_hash,
                    "snapshot_marker": snapshot_marker,
                    "offset": next_offset,
                    "last_sort_tuple": last_tuple,
                    "cursor_type": "group",
                }
            )

        grouping = QueryGrouping(
            total_videos=len(groups),
            total_moments=len(hits),
            videos=paged_groups,
        )
        selected_hits = paged_hits
    else:
        selected_hits = hits[cursor_offset : cursor_offset + page_limit]
        next_offset = cursor_offset + page_limit
        if next_offset < len(hits):
            last_tuple = None
            if selected_hits:
                last = selected_hits[-1]
                last_tuple = list(_result_sort_tuple(last, sort_by="score"))
            next_page_token = _encode_cursor(
                {
                    "query_fingerprint": query_hash,
                    "snapshot_marker": snapshot_marker,
                    "offset": next_offset,
                    "last_sort_tuple": last_tuple,
                    "cursor_type": "moment",
                }
            )

    meta = QueryMeta(
        fusion_method="weighted_rrf",
        weight_version=os.getenv("QUERY_FUSION_WEIGHT_VERSION", "v1"),
        snapshot_marker=snapshot_marker,
        request_id=trace_id,
        trace_id=trace_id,
    )

    return QueryResponse(
        results=selected_hits,
        next_page_token=next_page_token,
        grouping=grouping,
        meta=meta,
    )


def warm_query_models(
    *,
    enabled: bool,
    steps: set[str],
    warmup_text: str,
    logger,
) -> None:
    if not enabled:
        logger.info("Query model warmup skipped")
        return
    if not steps:
        logger.info("Query model warmup skipped (no steps configured)")
        return

    timings: dict[str, float] = {}
    errors: dict[str, str] = {}
    step_timings = {
        "text": "text_embed_ms",
        "image_text": "image_text_embed_ms",
        "audio_text": "audio_text_embed_ms",
        "image": "image_embed_ms",
        "vision_v2_text": "vision_v2_text_embed_ms",
        "vision_v2_image": "vision_v2_image_embed_ms",
        "rerank": "rerank_warmup_ms",
    }

    def _run_step(step: str, fn) -> None:
        if step not in steps:
            return
        start = time.monotonic()
        try:
            fn()
        except Exception as exc:
            errors[step] = str(exc)
        else:
            timings[step_timings[step]] = round(
                (time.monotonic() - start) * 1000.0,
                2,
            )

    _run_step(
        "text",
        lambda: run_inference(
            "text",
            lambda: get_text_embedder(768).encode([warmup_text]),
        ),
    )
    _run_step(
        "image_text",
        lambda: run_inference(
            "image_text",
            lambda: get_image_text_embedder(512).encode([warmup_text]),
        ),
    )
    _run_step(
        "audio_text",
        lambda: run_inference(
            "audio_text",
            lambda: get_audio_text_embedder(512).encode([warmup_text]),
        ),
    )
    _run_step(
        "image",
        lambda: run_inference(
            "image",
            lambda: get_image_embedder(512).encode(
                [Image.new("RGB", (1, 1), color=(0, 0, 0))]
            ),
        ),
    )
    if os.getenv("VISION_V2_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
        _run_step(
            "vision_v2_text",
            lambda: run_inference(
                "warmup_vision_v2",
                lambda: get_image_text_embedder_v2(768).encode([warmup_text]),
            ),
        )
        _run_step(
            "vision_v2_image",
            lambda: run_inference(
                "warmup_vision_v2",
                lambda: get_image_embedder_v2(768).encode(
                    [Image.new("RGB", (1, 1), color=(0, 0, 0))]
                ),
            ),
        )
    if os.getenv("RERANK_ENABLED", "0") == "1":
        _run_step(
            "rerank",
            lambda: get_reranker().score(warmup_text, [warmup_text]),
        )

    extra = {"timings": timings, "warmup_steps": sorted(steps)}
    if errors:
        extra["errors"] = errors
        logger.warning("Query model warmup completed with errors", extra=extra)
    else:
        logger.info("Query model warmup completed", extra=extra)
