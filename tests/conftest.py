import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "test-raw")
    monkeypatch.setenv("GRAPH_BUCKET", "test-graph")
    monkeypatch.setenv("GRAPH_PREFIX", "retikon_v2")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("MAX_RAW_BYTES", "500000000")
    monkeypatch.setenv("MAX_VIDEO_SECONDS", "300")
    monkeypatch.setenv("MAX_AUDIO_SECONDS", "1200")
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "512")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "50")
    monkeypatch.setenv("INGESTION_DRY_RUN", "1")
