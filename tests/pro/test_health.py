from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app


def test_ingestion_health():
    client = TestClient(ingest_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "retikon-ingestion"


def test_query_health():
    client = TestClient(query_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "retikon-query"
