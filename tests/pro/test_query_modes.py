import base64
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

import gcp_adapter.query_service as query_service
import retikon_core.query_engine.query_runner as query_runner


def _client(headers: dict[str, str]) -> TestClient:
    snapshot_uri = os.getenv("SNAPSHOT_URI", "/tmp/retikon-test.duckdb")
    query_service.STATE.local_path = snapshot_uri
    return TestClient(query_service.app, headers=headers)


def test_query_mode_text_limits_modalities(monkeypatch, jwt_headers):
    captured = {}

    def fake_run_query(
        *,
        payload,
        snapshot_path,
        search_type,
        modalities,
        scope,
        timings,
    ):
        captured["modalities"] = modalities
        return []

    monkeypatch.setattr(query_service, "run_query", fake_run_query)

    client = _client(jwt_headers)
    resp = client.post("/query", json={"query_text": "hello", "mode": "text"})
    assert resp.status_code == 200
    assert set(captured["modalities"]) == {"document", "transcript"}


def test_query_modalities_reject_unknown(jwt_headers):
    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={"query_text": "hello", "modalities": ["document", "unknown"]},
    )
    assert resp.status_code == 400


def test_query_rejects_unknown_search_type(jwt_headers):
    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={"query_text": "hello", "search_type": "bogus"},
    )
    assert resp.status_code == 400


def test_query_keyword_search(jwt_headers):
    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={"query_text": "hello", "search_type": "keyword"},
    )
    assert resp.status_code == 200


def test_query_metadata_search(jwt_headers):
    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={
            "search_type": "metadata",
            "metadata_filters": {"media_type": "image"},
        },
    )
    assert resp.status_code == 200


def test_query_image_requires_image_modality(jwt_headers):
    payload = Path("tests/fixtures/sample.jpg").read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    client = _client(jwt_headers)
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
    monkeypatch.setattr(
        query_runner,
        "_table_has_column",
        lambda *args, **kwargs: False,
    )
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


def test_search_by_text_applies_modality_boosts(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_query_rows(_conn, sql, _params):
        if "FROM doc_chunks" in sql:
            return [("gs://doc", "document", "doc-id", "doc text", 0.05)]
        if "FROM image_assets" in sql:
            return [("gs://img", "video", "img-id", 1000, "gs://thumb", 0.06)]
        return []

    monkeypatch.setattr(query_runner, "_connect", lambda snapshot_path: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", lambda *args, **kwargs: True)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_text_vector", lambda text: [0.0])
    monkeypatch.setattr(query_runner, "_cached_image_text_vector", lambda text: [0.0])

    monkeypatch.setenv(
        "QUERY_MODALITY_BOOSTS",
        "document=1.0,transcript=1.0,image=1.2,audio=1.0",
    )
    monkeypatch.setenv("QUERY_MODALITY_HINT_BOOST", "1.0")
    query_runner._modality_boosts.cache_clear()
    query_runner._modality_hint_boost.cache_clear()

    results = query_runner.search_by_text(
        snapshot_path="/tmp/retikon-test.duckdb",
        query_text="video query",
        top_k=2,
        modalities=["document", "image"],
    )
    assert results[0].modality == "image"


def test_search_by_text_emits_hitlists(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_query_rows(_conn, sql, _params):
        if "FROM doc_chunks" in sql:
            return [
                ("gs://doc-1", "document", "doc-1", "one", 0.1),
                ("gs://doc-2", "document", "doc-2", "two", 0.2),
                ("gs://doc-3", "document", "doc-3", "three", 0.3),
            ]
        return []

    monkeypatch.setenv("QUERY_TRACE_HITLISTS", "1")
    monkeypatch.setenv("QUERY_TRACE_HITLIST_SIZE", "2")
    monkeypatch.setattr(query_runner, "_connect", lambda snapshot_path: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", lambda *args, **kwargs: False)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_text_vector", lambda text: [0.0])

    trace: dict[str, float | int | str] = {}
    query_runner.search_by_text(
        snapshot_path="/tmp/retikon-test.duckdb",
        query_text="hello",
        top_k=3,
        modalities=["document"],
        trace=trace,
    )
    payload = json.loads(str(trace["document_hitlist"]))
    assert len(payload) == 2
    assert payload[0]["uri"] == "gs://doc-1"
