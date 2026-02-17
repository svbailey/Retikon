from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryServiceConfig:
    max_query_bytes: int
    max_image_base64_bytes: int
    slow_query_ms: int
    log_query_timings: bool
    query_warmup: bool
    query_warmup_text: str
    query_warmup_steps: set[str]
    query_trace_hitlists: bool
    query_trace_hitlist_size: int
    rerank_enabled: bool
    rerank_model_name: str
    rerank_backend: str
    rerank_top_n: int
    rerank_batch_size: int
    rerank_query_max_tokens: int
    rerank_doc_max_tokens: int
    rerank_min_candidates: int
    rerank_max_total_chars: int
    rerank_skip_score_gap: float
    rerank_skip_min_score: float
    rerank_timeout_s: float
    rerank_onnx_model_path: str | None
    search_group_by_enabled: bool
    search_pagination_enabled: bool
    search_filters_v1_enabled: bool
    search_why_enabled: bool
    search_typed_errors_enabled: bool
    query_fusion_rrf_k: int
    query_fusion_weights: str | None
    query_fusion_weight_version: str

    @classmethod
    def from_env(cls) -> "QueryServiceConfig":
        def _parse_int(name: str, default: int, *, minimum: int | None = None) -> int:
            raw = os.getenv(name, str(default))
            try:
                value = int(raw)
            except ValueError:
                value = default
            if minimum is not None and value < minimum:
                return minimum
            return value

        def _parse_float(
            name: str,
            default: float,
            *,
            minimum: float | None = None,
        ) -> float:
            raw = os.getenv(name, str(default))
            try:
                value = float(raw)
            except ValueError:
                value = default
            if minimum is not None and value < minimum:
                return minimum
            return value

        trace_size_raw = os.getenv("QUERY_TRACE_HITLIST_SIZE", "5")
        try:
            trace_size = int(trace_size_raw)
        except ValueError:
            trace_size = 5
        if trace_size < 1:
            trace_size = 1
        return cls(
            max_query_bytes=int(os.getenv("MAX_QUERY_BYTES", "4000000")),
            max_image_base64_bytes=int(os.getenv("MAX_IMAGE_BASE64_BYTES", "2000000")),
            slow_query_ms=int(os.getenv("SLOW_QUERY_MS", "2000")),
            log_query_timings=os.getenv("LOG_QUERY_TIMINGS", "0") == "1",
            query_warmup=os.getenv("QUERY_WARMUP", "1") == "1",
            query_warmup_text=os.getenv("QUERY_WARMUP_TEXT", "retikon warmup"),
            query_warmup_steps={
                step.strip().lower()
                for step in os.getenv(
                    "QUERY_WARMUP_STEPS",
                    "text,image_text,audio_text,image,vision_v2_text,vision_v2_image,rerank",
                ).split(",")
                if step.strip()
            },
            query_trace_hitlists=os.getenv("QUERY_TRACE_HITLISTS", "1") == "1",
            query_trace_hitlist_size=trace_size,
            rerank_enabled=os.getenv("RERANK_ENABLED", "1") == "1",
            rerank_model_name=os.getenv(
                "RERANK_MODEL_NAME",
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
            ),
            rerank_backend=os.getenv("RERANK_BACKEND", "hf").strip().lower(),
            rerank_top_n=_parse_int("RERANK_TOP_N", 20, minimum=1),
            rerank_batch_size=_parse_int("RERANK_BATCH_SIZE", 8, minimum=1),
            rerank_query_max_tokens=_parse_int("RERANK_QUERY_MAX_TOKENS", 32, minimum=1),
            rerank_doc_max_tokens=_parse_int("RERANK_DOC_MAX_TOKENS", 128, minimum=1),
            rerank_min_candidates=_parse_int("RERANK_MIN_CANDIDATES", 2, minimum=1),
            rerank_max_total_chars=_parse_int("RERANK_MAX_TOTAL_CHARS", 6000, minimum=0),
            rerank_skip_score_gap=_parse_float(
                "RERANK_SKIP_SCORE_GAP",
                1.0,
                minimum=0.0,
            ),
            rerank_skip_min_score=min(
                1.0,
                _parse_float(
                    "RERANK_SKIP_MIN_SCORE",
                    0.7,
                    minimum=0.0,
                ),
            ),
            rerank_timeout_s=_parse_float("RERANK_TIMEOUT_S", 2.0, minimum=0.0),
            rerank_onnx_model_path=(
                os.getenv("RERANK_ONNX_MODEL_PATH", "").strip() or None
            ),
            search_group_by_enabled=os.getenv("SEARCH_GROUP_BY_ENABLED", "1") == "1",
            search_pagination_enabled=os.getenv("SEARCH_PAGINATION_ENABLED", "1") == "1",
            search_filters_v1_enabled=os.getenv("SEARCH_FILTERS_V1_ENABLED", "1") == "1",
            search_why_enabled=os.getenv("SEARCH_WHY_ENABLED", "1") == "1",
            search_typed_errors_enabled=os.getenv("SEARCH_TYPED_ERRORS_ENABLED", "1")
            == "1",
            query_fusion_rrf_k=_parse_int("QUERY_FUSION_RRF_K", 60, minimum=1),
            query_fusion_weights=(
                os.getenv("QUERY_FUSION_WEIGHTS", "").strip() or None
            ),
            query_fusion_weight_version=os.getenv(
                "QUERY_FUSION_WEIGHT_VERSION",
                "v1",
            ).strip()
            or "v1",
        )
