from retikon_core.services.query_config import QueryServiceConfig


def test_query_service_config_defaults(monkeypatch):
    monkeypatch.delenv("MAX_QUERY_BYTES", raising=False)
    monkeypatch.delenv("MAX_IMAGE_BASE64_BYTES", raising=False)
    monkeypatch.delenv("SLOW_QUERY_MS", raising=False)
    monkeypatch.delenv("LOG_QUERY_TIMINGS", raising=False)
    monkeypatch.delenv("QUERY_WARMUP", raising=False)
    monkeypatch.delenv("QUERY_WARMUP_TEXT", raising=False)
    monkeypatch.delenv("QUERY_WARMUP_STEPS", raising=False)

    cfg = QueryServiceConfig.from_env()
    assert cfg.max_query_bytes == 4_000_000
    assert cfg.max_image_base64_bytes == 2_000_000
    assert cfg.slow_query_ms == 2000
    assert cfg.log_query_timings is False
    assert cfg.query_warmup is True
    assert cfg.query_warmup_text == "retikon warmup"
    assert "text" in cfg.query_warmup_steps


def test_query_service_config_overrides(monkeypatch):
    monkeypatch.setenv("MAX_QUERY_BYTES", "123")
    monkeypatch.setenv("MAX_IMAGE_BASE64_BYTES", "456")
    monkeypatch.setenv("SLOW_QUERY_MS", "789")
    monkeypatch.setenv("LOG_QUERY_TIMINGS", "1")
    monkeypatch.setenv("QUERY_WARMUP", "0")
    monkeypatch.setenv("QUERY_WARMUP_TEXT", "hello")
    monkeypatch.setenv("QUERY_WARMUP_STEPS", "text,image")

    cfg = QueryServiceConfig.from_env()
    assert cfg.max_query_bytes == 123
    assert cfg.max_image_base64_bytes == 456
    assert cfg.slow_query_ms == 789
    assert cfg.log_query_timings is True
    assert cfg.query_warmup is False
    assert cfg.query_warmup_text == "hello"
    assert cfg.query_warmup_steps == {"text", "image"}
