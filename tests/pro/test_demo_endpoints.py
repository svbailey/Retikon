import importlib
import json

from fastapi.testclient import TestClient

import gcp_adapter.query_service as service


def test_demo_datasets_returns_configured_list(monkeypatch, jwt_headers):
    payload = {
        "datasets": [
            {
                "id": "demo-1",
                "title": "Demo Dataset",
                "modality": "video",
                "summary": "Demo summary",
                "preview_uri": "gs://demo/preview.mp4",
                "source_uri": "gs://demo/source.mp4",
            }
        ]
    }
    monkeypatch.setenv("DEMO_DATASETS_JSON", json.dumps(payload))
    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get("/demo/datasets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["datasets"][0]["id"] == "demo-1"


def test_evidence_requires_uri(jwt_headers):
    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get("/evidence")
    assert resp.status_code == 400


def test_evidence_returns_placeholder(jwt_headers):
    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get("/evidence", params={"uri": "gs://demo/raw/video.mp4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["uri"] == "gs://demo/raw/video.mp4"


def test_evidence_returns_doc_snippets(jwt_headers):
    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get("/evidence", params={"uri": "gs://test/doc.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["doc_snippets"]
