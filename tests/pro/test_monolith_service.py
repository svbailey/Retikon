from fastapi.testclient import TestClient

from gcp_adapter.monolith_service import app


def test_monolith_health():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "retikon-pro-monolith"


def test_monolith_query_requires_input(jwt_headers):
    client = TestClient(app, headers=jwt_headers)
    resp = client.post("/query", json={})
    assert resp.status_code == 400
