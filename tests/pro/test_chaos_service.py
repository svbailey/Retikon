from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_chaos_service(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.chaos_service as service

    importlib.reload(service)

    client = TestClient(service.app)

    resp = client.get("/chaos/policies")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post(
        "/chaos/policies",
        json={
            "name": "Delay queries",
            "steps": [
                {"name": "Delay", "kind": "delay", "duration_seconds": 5},
            ],
        },
    )
    assert resp.status_code == 201
    policy_id = resp.json()["id"]

    resp = client.get("/chaos/policies")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Delay queries"

    resp = client.post(f"/chaos/policies/{policy_id}/runs", json={})
    assert resp.status_code == 201
    assert resp.json()["policy_id"] == policy_id

    resp = client.get(f"/chaos/runs?policy_id={policy_id}")
    assert resp.status_code == 200
    assert resp.json()[0]["policy_id"] == policy_id
