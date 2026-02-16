from retikon_core.services.query_config import QueryServiceConfig


def test_query_service_config_defaults(monkeypatch):
    monkeypatch.delenv("MAX_QUERY_BYTES", raising=False)
    monkeypatch.delenv("MAX_IMAGE_BASE64_BYTES", raising=False)
    monkeypatch.delenv("SLOW_QUERY_MS", raising=False)
    monkeypatch.delenv("LOG_QUERY_TIMINGS", raising=False)
    monkeypatch.delenv("QUERY_WARMUP", raising=False)
    monkeypatch.delenv("QUERY_WARMUP_TEXT", raising=False)
    monkeypatch.delenv("QUERY_WARMUP_STEPS", raising=False)
    monkeypatch.delenv("QUERY_TRACE_HITLISTS", raising=False)
    monkeypatch.delenv("QUERY_TRACE_HITLIST_SIZE", raising=False)
    monkeypatch.delenv("RERANK_ENABLED", raising=False)
    monkeypatch.delenv("RERANK_MODEL_NAME", raising=False)
    monkeypatch.delenv("RERANK_BACKEND", raising=False)
    monkeypatch.delenv("RERANK_TOP_N", raising=False)
    monkeypatch.delenv("RERANK_BATCH_SIZE", raising=False)
    monkeypatch.delenv("RERANK_QUERY_MAX_TOKENS", raising=False)
    monkeypatch.delenv("RERANK_DOC_MAX_TOKENS", raising=False)
    monkeypatch.delenv("RERANK_MIN_CANDIDATES", raising=False)
    monkeypatch.delenv("RERANK_MAX_TOTAL_CHARS", raising=False)
    monkeypatch.delenv("RERANK_SKIP_SCORE_GAP", raising=False)
    monkeypatch.delenv("RERANK_SKIP_MIN_SCORE", raising=False)
    monkeypatch.delenv("RERANK_TIMEOUT_S", raising=False)
    monkeypatch.delenv("RERANK_ONNX_MODEL_PATH", raising=False)
    monkeypatch.delenv("SEARCH_GROUP_BY_ENABLED", raising=False)
    monkeypatch.delenv("SEARCH_PAGINATION_ENABLED", raising=False)
    monkeypatch.delenv("SEARCH_FILTERS_V1_ENABLED", raising=False)
    monkeypatch.delenv("SEARCH_WHY_ENABLED", raising=False)
    monkeypatch.delenv("SEARCH_TYPED_ERRORS_ENABLED", raising=False)
    monkeypatch.delenv("QUERY_FUSION_RRF_K", raising=False)
    monkeypatch.delenv("QUERY_FUSION_WEIGHTS", raising=False)
    monkeypatch.delenv("QUERY_FUSION_WEIGHT_VERSION", raising=False)

    cfg = QueryServiceConfig.from_env()
    assert cfg.max_query_bytes == 4_000_000
    assert cfg.max_image_base64_bytes == 2_000_000
    assert cfg.slow_query_ms == 2000
    assert cfg.log_query_timings is False
    assert cfg.query_warmup is True
    assert cfg.query_warmup_text == "retikon warmup"
    assert "text" in cfg.query_warmup_steps
    assert "rerank" in cfg.query_warmup_steps
    assert cfg.query_trace_hitlists is True
    assert cfg.query_trace_hitlist_size == 5
    assert cfg.rerank_enabled is True
    assert cfg.rerank_model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert cfg.rerank_backend == "hf"
    assert cfg.rerank_top_n == 20
    assert cfg.rerank_batch_size == 8
    assert cfg.rerank_query_max_tokens == 32
    assert cfg.rerank_doc_max_tokens == 128
    assert cfg.rerank_min_candidates == 2
    assert cfg.rerank_max_total_chars == 6000
    assert cfg.rerank_skip_score_gap == 1.0
    assert cfg.rerank_skip_min_score == 0.7
    assert cfg.rerank_timeout_s == 2.0
    assert cfg.rerank_onnx_model_path is None
    assert cfg.search_group_by_enabled is True
    assert cfg.search_pagination_enabled is True
    assert cfg.search_filters_v1_enabled is True
    assert cfg.search_why_enabled is True
    assert cfg.search_typed_errors_enabled is True
    assert cfg.query_fusion_rrf_k == 60
    assert cfg.query_fusion_weights is None
    assert cfg.query_fusion_weight_version == "v1"


def test_query_service_config_overrides(monkeypatch):
    monkeypatch.setenv("MAX_QUERY_BYTES", "123")
    monkeypatch.setenv("MAX_IMAGE_BASE64_BYTES", "456")
    monkeypatch.setenv("SLOW_QUERY_MS", "789")
    monkeypatch.setenv("LOG_QUERY_TIMINGS", "1")
    monkeypatch.setenv("QUERY_WARMUP", "0")
    monkeypatch.setenv("QUERY_WARMUP_TEXT", "hello")
    monkeypatch.setenv("QUERY_WARMUP_STEPS", "text,image")
    monkeypatch.setenv("QUERY_TRACE_HITLISTS", "0")
    monkeypatch.setenv("QUERY_TRACE_HITLIST_SIZE", "12")
    monkeypatch.setenv("RERANK_ENABLED", "0")
    monkeypatch.setenv("RERANK_MODEL_NAME", "cross-encoder/ms-marco-TinyBERT-L2-v2")
    monkeypatch.setenv("RERANK_BACKEND", "onnx")
    monkeypatch.setenv("RERANK_TOP_N", "42")
    monkeypatch.setenv("RERANK_BATCH_SIZE", "8")
    monkeypatch.setenv("RERANK_QUERY_MAX_TOKENS", "48")
    monkeypatch.setenv("RERANK_DOC_MAX_TOKENS", "192")
    monkeypatch.setenv("RERANK_MIN_CANDIDATES", "3")
    monkeypatch.setenv("RERANK_MAX_TOTAL_CHARS", "4200")
    monkeypatch.setenv("RERANK_SKIP_SCORE_GAP", "0.4")
    monkeypatch.setenv("RERANK_SKIP_MIN_SCORE", "0.8")
    monkeypatch.setenv("RERANK_TIMEOUT_S", "1.25")
    monkeypatch.setenv("RERANK_ONNX_MODEL_PATH", "/tmp/reranker.onnx")
    monkeypatch.setenv("SEARCH_GROUP_BY_ENABLED", "0")
    monkeypatch.setenv("SEARCH_PAGINATION_ENABLED", "0")
    monkeypatch.setenv("SEARCH_FILTERS_V1_ENABLED", "0")
    monkeypatch.setenv("SEARCH_WHY_ENABLED", "0")
    monkeypatch.setenv("SEARCH_TYPED_ERRORS_ENABLED", "0")
    monkeypatch.setenv("QUERY_FUSION_RRF_K", "42")
    monkeypatch.setenv("QUERY_FUSION_WEIGHTS", "text=1.1,vision=0.9")
    monkeypatch.setenv("QUERY_FUSION_WEIGHT_VERSION", "vtest")

    cfg = QueryServiceConfig.from_env()
    assert cfg.max_query_bytes == 123
    assert cfg.max_image_base64_bytes == 456
    assert cfg.slow_query_ms == 789
    assert cfg.log_query_timings is True
    assert cfg.query_warmup is False
    assert cfg.query_warmup_text == "hello"
    assert cfg.query_warmup_steps == {"text", "image"}
    assert cfg.query_trace_hitlists is False
    assert cfg.query_trace_hitlist_size == 12
    assert cfg.rerank_enabled is False
    assert cfg.rerank_model_name == "cross-encoder/ms-marco-TinyBERT-L2-v2"
    assert cfg.rerank_backend == "onnx"
    assert cfg.rerank_top_n == 42
    assert cfg.rerank_batch_size == 8
    assert cfg.rerank_query_max_tokens == 48
    assert cfg.rerank_doc_max_tokens == 192
    assert cfg.rerank_min_candidates == 3
    assert cfg.rerank_max_total_chars == 4200
    assert cfg.rerank_skip_score_gap == 0.4
    assert cfg.rerank_skip_min_score == 0.8
    assert cfg.rerank_timeout_s == 1.25
    assert cfg.rerank_onnx_model_path == "/tmp/reranker.onnx"
    assert cfg.search_group_by_enabled is False
    assert cfg.search_pagination_enabled is False
    assert cfg.search_filters_v1_enabled is False
    assert cfg.search_why_enabled is False
    assert cfg.search_typed_errors_enabled is False
    assert cfg.query_fusion_rrf_k == 42
    assert cfg.query_fusion_weights == "text=1.1,vision=0.9"
    assert cfg.query_fusion_weight_version == "vtest"
