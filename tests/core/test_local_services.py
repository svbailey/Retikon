from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from local_adapter import ingestion_service, query_service
from retikon_core.config import get_config


def test_local_ingestion_service(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    monkeypatch.setenv("RAW_BUCKET", "local")
    monkeypatch.setenv("USE_REAL_MODELS", "0")
    get_config.cache_clear()

    client = TestClient(ingestion_service.app)
    response = client.post(
        "/ingest",
        json={"path": "tests/fixtures/sample.csv", "content_type": "text/csv"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["manifest_uri"]
    assert Path(payload["manifest_uri"]).exists()
    get_config.cache_clear()


def test_local_query_service_keyword(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()
    query_service.STATE.local_path = None
    query_service.STATE.loaded_at = None

    client = TestClient(query_service.app)
    health = client.get("/health")
    assert health.status_code == 200

    response = client.post(
        "/query",
        json={"query_text": "hello", "search_type": "keyword"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    get_config.cache_clear()
