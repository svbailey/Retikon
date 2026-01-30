from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_privacy_service_crud(monkeypatch, tmp_path, jwt_headers):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.privacy_service as service

    importlib.reload(service)

    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get("/privacy/policies")
    assert resp.status_code == 200
    assert resp.json() == []

    create_payload = {
        "name": "PII Redaction",
        "modalities": ["document"],
        "contexts": ["query"],
        "redaction_types": ["pii"],
    }
    resp = client.post("/privacy/policies", json=create_payload)
    assert resp.status_code == 201
    policy = resp.json()
    assert policy["name"] == "PII Redaction"

    resp = client.get("/privacy/policies")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.put(
        f"/privacy/policies/{policy['id']}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
