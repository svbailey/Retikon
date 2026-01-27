import base64
import os
from pathlib import Path

from fastapi.testclient import TestClient

import gcp_adapter.query_service as query_service
import retikon_core.query_engine.query_runner as query_runner


def _client() -> TestClient:
    query_service.STATE.local_path = os.getenv("SNAPSHOT_URI", "/tmp/retikon-test.duckdb")
    return TestClient(query_service.app)


def test_query_mode_text_limits_modalities(monkeypatch):
    captured = {}

    def fake_search_by_text(*, snapshot_path, query_text, top_k, modalities, trace):
        captured["modalities"] = modalities
        return []

    monkeypatch.setattr(query_service, "search_by_text", fake_search_by_text)
    monkeypatch.setattr(query_service, "search_by_image", lambda **kwargs: [])

    client = _client()
    resp = client.post("/query", json={"query_text": "hello", "mode": "text"})
    assert resp.status_code == 200
    assert set(captured["modalities"]) == {"document", "transcript"}


def test_query_modalities_reject_unknown():
    client = _client()
    resp = client.post(
        "/query",
        json={"query_text": "hello", "modalities": ["document", "unknown"]},
    )
    assert resp.status_code == 400


def test_query_rejects_unknown_search_type():
    client = _client()
    resp = client.post(
        "/query",
        json={"query_text": "hello", "search_type": "bogus"},
    )
    assert resp.status_code == 400


def test_query_keyword_search():
    client = _client()
    resp = client.post(
        "/query",
        json={"query_text": "hello", "search_type": "keyword"},
    )
    assert resp.status_code == 200


def test_query_metadata_search():
    client = _client()
    resp = client.post(
        "/query",
        json={
            "search_type": "metadata",
            "metadata_filters": {"media_type": "image"},
        },
    )
    assert resp.status_code == 200


def test_query_image_requires_image_modality():
    payload = Path("tests/fixtures/sample.jpg").read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    client = _client()
    resp = client.post(
        "/query",
        json={"query_text": "hello", "image_base64": encoded, "mode": "text"},
    )
    assert resp.status_code == 400


def test_search_by_text_skips_unused_embeddings(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    monkeypatch.setattr(query_runner, "_connect", lambda snapshot_path: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", lambda *args, **kwargs: False)
    monkeypatch.setattr(query_runner, "_query_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(query_runner, "_cached_text_vector", lambda text: [0.0])
    monkeypatch.setattr(
        query_runner,
        "_cached_image_text_vector",
        lambda text: (_ for _ in ()).throw(AssertionError("image embed called")),
    )
    monkeypatch.setattr(
        query_runner,
        "_cached_audio_text_vector",
        lambda text: (_ for _ in ()).throw(AssertionError("audio embed called")),
    )

    results = query_runner.search_by_text(
        snapshot_path="/tmp/retikon-test.duckdb",
        query_text="hello",
        top_k=3,
        modalities=["document", "transcript"],
    )
    assert results == []
