from __future__ import annotations

from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app

def test_query_accepts_jwt(jwt_factory):
    token = jwt_factory(roles=["reader"])
    client = TestClient(query_app)
    resp = client.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_jwt_rbac_enforced_for_ingest(monkeypatch, jwt_factory):
    monkeypatch.setenv("RBAC_ENFORCE", "1")

    token = jwt_factory(roles=["reader"])
    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    client_ingest = TestClient(ingest_app)
    resp = client_ingest.post(
        "/ingest",
        json={"specversion": "1.0", "data": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
