from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app


def test_ingest_accepts_cloudevent():
    client = TestClient(ingest_app)
    payload = {
        "id": "evt-1",
        "type": "google.cloud.storage.object.v1.finalized",
        "source": "//storage.googleapis.com/projects/_/buckets/test-raw",
        "specversion": "1.0",
        "data": {
            "bucket": "test-raw",
            "name": "raw/docs/sample.pdf",
            "generation": "1",
            "contentType": "application/pdf",
            "size": "123",
        },
    }
    resp = client.post("/ingest", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert "trace_id" in body


def test_query_requires_input():
    client = TestClient(query_app)
    resp = client.post("/query", json={})
    assert resp.status_code == 400


def test_query_accepts_text():
    client = TestClient(query_app)
    resp = client.post("/query", json={"query_text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
