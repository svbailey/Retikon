from __future__ import annotations

import time
from dataclasses import replace
from typing import Iterable

from PIL import Image
from pydantic import BaseModel, Field

from retikon_core.embeddings import (
    get_audio_text_embedder,
    get_image_embedder,
    get_image_text_embedder,
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
    search_by_image,
    search_by_keyword,
    search_by_metadata,
    search_by_text,
)
from retikon_core.tenancy.types import TenantScope

ALLOWED_MODALITIES = {"document", "transcript", "image", "audio"}
ALLOWED_SEARCH_TYPES = {"vector", "keyword", "metadata"}


class QueryValidationError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class QueryRequest(BaseModel):
    query_text: str | None = None
    image_base64: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str | None = None
    modalities: list[str] | None = None
    search_type: str | None = None
    metadata_filters: dict[str, str] | None = None


class QueryHit(BaseModel):
    modality: str
    uri: str
    snippet: str | None = None
    timestamp_ms: int | None = None
    thumbnail_uri: str | None = None
    score: float
    media_asset_id: str | None = None
    media_type: str | None = None


class QueryResponse(BaseModel):
    results: list[QueryHit]


def resolve_modalities(payload: QueryRequest) -> set[str]:
    if payload.mode and payload.modalities:
        raise QueryValidationError("Specify either mode or modalities, not both")

    if payload.mode:
        mode = payload.mode.strip().lower()
        if mode == "text":
            return {"document", "transcript"}
        if mode == "all":
            return set(ALLOWED_MODALITIES)
        if mode == "image":
            return {"image"}
        if mode == "audio":
            return {"audio"}
        raise QueryValidationError(f"Unsupported mode: {payload.mode}")

    if payload.modalities is None:
        return set(ALLOWED_MODALITIES)

    modalities = {modality.strip().lower() for modality in payload.modalities}
    if not modalities:
        raise QueryValidationError("modalities cannot be empty")
    unknown = sorted(modalities - ALLOWED_MODALITIES)
    if unknown:
        raise QueryValidationError(f"Unknown modalities: {', '.join(unknown)}")
    return modalities


def resolve_search_type(payload: QueryRequest) -> str:
    raw = payload.search_type or "vector"
    search_type = raw.strip().lower()
    if search_type not in ALLOWED_SEARCH_TYPES:
        raise QueryValidationError(f"Unsupported search_type: {payload.search_type}")
    return search_type


def validate_query_payload(
    *,
    payload: QueryRequest,
    search_type: str,
    modalities: set[str],
    max_image_base64_bytes: int,
) -> None:
    if (
        not payload.query_text
        and not payload.image_base64
        and search_type != "metadata"
    ):
        raise QueryValidationError("query_text or image_base64 is required")

    if payload.image_base64 and len(payload.image_base64) > max_image_base64_bytes:
        raise QueryValidationError("Image payload too large", status_code=413)
    if payload.image_base64 and "image" not in modalities:
        raise QueryValidationError("image_base64 requires image modality")
    if search_type != "vector" and payload.image_base64:
        raise QueryValidationError("image_base64 is only supported for vector search")
    if search_type == "keyword" and not payload.query_text:
        raise QueryValidationError("query_text is required for keyword search")
    if search_type == "metadata":
        if payload.query_text or payload.image_base64:
            raise QueryValidationError(
                "metadata search does not accept query_text or image_base64"
            )
        if not payload.metadata_filters:
            raise QueryValidationError(
                "metadata_filters is required for metadata search"
            )


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
    elif search_type == "metadata" and payload.metadata_filters:
        try:
            results.extend(
                search_by_metadata(
                    snapshot_path=snapshot_path,
                    filters=payload.metadata_filters,
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

    results.sort(key=lambda item: item.score, reverse=True)
    return results


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


def build_query_response(results: Iterable[QueryResult], top_k: int) -> QueryResponse:
    trimmed = list(results)[:top_k]
    return QueryResponse(
        results=[
            QueryHit(
                modality=item.modality,
                uri=item.uri,
                snippet=item.snippet,
                timestamp_ms=item.timestamp_ms,
                thumbnail_uri=item.thumbnail_uri,
                score=item.score,
                media_asset_id=item.media_asset_id,
                media_type=item.media_type,
            )
            for item in trimmed
        ]
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

    extra = {"timings": timings, "warmup_steps": sorted(steps)}
    if errors:
        extra["errors"] = errors
        logger.warning("Query model warmup completed with errors", extra=extra)
    else:
        logger.info("Query model warmup completed", extra=extra)
