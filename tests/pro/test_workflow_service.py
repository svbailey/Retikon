from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_workflow_service(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.workflow_service as service

    importlib.reload(service)

    client = TestClient(service.app)

    resp = client.get("/workflows")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post(
        "/workflows",
        json={
            "name": "Export",
            "steps": [
                {"name": "Notify", "kind": "webhook"},
            ],
        },
    )
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]

    resp = client.get("/workflows")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Export"

    resp = client.post(f"/workflows/{workflow_id}/runs", json={})
    assert resp.status_code == 201
    assert resp.json()["workflow_id"] == workflow_id

    resp = client.get(f"/workflows/runs?workflow_id={workflow_id}")
    assert resp.status_code == 200
    assert resp.json()[0]["workflow_id"] == workflow_id
