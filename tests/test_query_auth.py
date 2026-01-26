from fastapi.testclient import TestClient

from gcp_adapter.query_service import app


def test_query_requires_api_key_in_prod(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("QUERY_API_KEY", "secret")
    client = TestClient(app)

    resp = client.post("/query", json={"query_text": "hello"})
    assert resp.status_code == 401

    resp = client.post(
        "/query",
        json={"query_text": "hello"},
        headers={"x-api-key": "wrong"},
    )
    assert resp.status_code == 401

    resp = client.post(
        "/query",
        json={"query_text": "hello"},
        headers={"x-api-key": "secret"},
    )
    assert resp.status_code == 200


def test_admin_requires_api_key(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("QUERY_API_KEY", "secret")
    client = TestClient(app)

    resp = client.post("/admin/reload-snapshot")
    assert resp.status_code == 401

    resp = client.post(
        "/admin/reload-snapshot",
        headers={"x-api-key": "secret"},
    )
    assert resp.status_code == 200
