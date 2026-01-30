from fastapi.testclient import TestClient

from gcp_adapter.query_service import app


def test_query_requires_jwt(jwt_factory):
    client = TestClient(app)
    resp = client.post("/query", json={"query_text": "hello"})
    assert resp.status_code == 401

    token = jwt_factory(roles=["reader"])
    resp = client.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_admin_requires_admin_role(jwt_factory):
    client = TestClient(app)

    token = jwt_factory(roles=["reader"])
    resp = client.post(
        "/admin/reload-snapshot",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    admin_token = jwt_factory(roles=["admin"])
    resp = client.post(
        "/admin/reload-snapshot",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
