import os

from fastapi.testclient import TestClient

import gcp_adapter.query_service as query_service
from retikon_core.query_engine.query_runner import QueryResult


def _client(headers: dict[str, str]) -> TestClient:
    snapshot_uri = os.getenv("SNAPSHOT_URI", "/tmp/retikon-test.duckdb")
    query_service.STATE.local_path = snapshot_uri
    query_service.STATE.metadata = {
        "manifest_fingerprint": "snapshot-test-fp",
        "snapshot_uri": snapshot_uri,
    }
    return TestClient(query_service.app, headers=headers)


def _mk_result(
    *,
    asset_id: str,
    evidence_id: str,
    score: float,
    start_ms: int | None = None,
    modality: str = "document",
    snippet: str | None = "hello world",
) -> QueryResult:
    refs = [{"doc_chunk_id": evidence_id}] if modality in {"document", "transcript"} else []
    return QueryResult(
        modality=modality,
        uri=f"gs://{asset_id}",
        snippet=snippet,
        start_ms=start_ms,
        end_ms=start_ms,
        thumbnail_uri=None,
        score=score,
        media_asset_id=asset_id,
        media_type="video" if start_ms is not None else "document",
        primary_evidence_id=evidence_id,
        evidence_refs=refs,
        why=[{"modality": "text", "source": "vector", "raw_score": score}],
    )


def test_modalities_override_mode(monkeypatch, jwt_headers):
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
        captured["modalities"] = set(modalities)
        return []

    monkeypatch.setattr(query_service, "run_query", fake_run_query)

    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={"query_text": "hello", "mode": "text", "modalities": ["vision"]},
    )
    assert resp.status_code == 200
    assert captured["modalities"] == {"image"}


def test_query_response_has_meta_highlight_and_why(monkeypatch, jwt_headers):
    def fake_run_query(
        *,
        payload,
        snapshot_path,
        search_type,
        modalities,
        scope,
        timings,
    ):
        return [_mk_result(asset_id="asset-1", evidence_id="doc-1", score=0.8)]

    monkeypatch.setattr(query_service, "run_query", fake_run_query)

    client = _client(jwt_headers)
    resp = client.post("/query", json={"query_text": "hello", "top_k": 10, "page_limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["fusion_method"] == "weighted_rrf"
    assert body["meta"]["snapshot_marker"] == "snapshot-test-fp"
    assert body["results"][0]["highlight_text"]
    assert body["results"][0]["why"]


def test_query_pagination_deterministic(monkeypatch, jwt_headers):
    rows = [
        _mk_result(asset_id="asset-a", evidence_id="doc-1", score=0.9, start_ms=10),
        _mk_result(asset_id="asset-a", evidence_id="doc-2", score=0.8, start_ms=20),
        _mk_result(asset_id="asset-b", evidence_id="doc-3", score=0.7, start_ms=30),
        _mk_result(asset_id="asset-c", evidence_id="doc-4", score=0.6, start_ms=40),
    ]

    def fake_run_query(
        *,
        payload,
        snapshot_path,
        search_type,
        modalities,
        scope,
        timings,
    ):
        return rows

    monkeypatch.setattr(query_service, "run_query", fake_run_query)

    client = _client(jwt_headers)
    payload = {"query_text": "hello", "top_k": 10, "page_limit": 2}

    first = client.post("/query", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    first_ids = [item["primary_evidence_id"] for item in first_body["results"]]
    token = first_body["next_page_token"]
    assert token

    repeat = client.post("/query", json=payload)
    assert repeat.status_code == 200
    repeat_body = repeat.json()
    repeat_ids = [item["primary_evidence_id"] for item in repeat_body["results"]]
    assert repeat_ids == first_ids
    assert repeat_body["next_page_token"] == token

    second = client.post("/query", json={**payload, "page_token": token})
    assert second.status_code == 200
    second_ids = [item["primary_evidence_id"] for item in second.json()["results"]]
    assert second_ids != first_ids

    mismatch = client.post(
        "/query",
        json={"query_text": "different", "top_k": 10, "page_limit": 2, "page_token": token},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "VALIDATION_ERROR"


def test_query_grouping_shape(monkeypatch, jwt_headers):
    rows = [
        _mk_result(asset_id="asset-a", evidence_id="doc-1", score=0.9, start_ms=10),
        _mk_result(asset_id="asset-a", evidence_id="doc-2", score=0.8, start_ms=20),
        _mk_result(asset_id="asset-a", evidence_id="doc-3", score=0.7, start_ms=30),
        _mk_result(asset_id="asset-b", evidence_id="doc-4", score=0.6, start_ms=40),
    ]

    def fake_run_query(
        *,
        payload,
        snapshot_path,
        search_type,
        modalities,
        scope,
        timings,
    ):
        return rows

    monkeypatch.setattr(query_service, "run_query", fake_run_query)

    client = _client(jwt_headers)
    resp = client.post(
        "/query",
        json={
            "query_text": "hello",
            "top_k": 20,
            "group_by": "video",
            "sort_by": "clip_count",
            "page_limit": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    grouping = body["grouping"]
    assert grouping["total_videos"] == 2
    assert grouping["total_moments"] == 4
    assert len(grouping["videos"]) == 1
    assert grouping["videos"][0]["clip_count"] == 3
    assert body["next_page_token"]


def test_typed_errors_for_validation(jwt_headers):
    client = _client(jwt_headers)

    bad_mode = client.post("/query", json={"query_text": "hello", "mode": "bogus"})
    assert bad_mode.status_code == 400
    assert bad_mode.json()["error"]["code"] == "UNSUPPORTED_MODE"

    unknown_field = client.post("/query", json={"query_text": "hello", "unknown_field": 1})
    assert unknown_field.status_code == 422
    assert unknown_field.json()["error"]["code"] == "VALIDATION_ERROR"
