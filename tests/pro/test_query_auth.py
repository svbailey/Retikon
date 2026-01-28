import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from gcp_adapter.query_service import app
from retikon_core.auth.store import hash_key


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


def test_query_accepts_scoped_registry_key(monkeypatch, tmp_path):
    registry_path = tmp_path / "api_keys.json"
    raw_key = "scoped-key"
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_keys": [
            {
                "id": "key-1",
                "name": "scoped",
                "key_hash": hash_key(raw_key),
                "org_id": "org-1",
                "site_id": None,
                "stream_id": None,
                "enabled": True,
                "is_admin": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("API_KEY_REGISTRY_URI", registry_path.as_posix())
    monkeypatch.delenv("QUERY_API_KEY", raising=False)
    client = TestClient(app)

    resp = client.post(
        "/query",
        json={
            "search_type": "metadata",
            "metadata_filters": {"media_type": "document"},
        },
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["results"][0]["media_asset_id"] == "asset-doc"

    resp = client.post(
        "/admin/reload-snapshot",
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 403
