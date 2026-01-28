from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_fleet_service_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.fleet_service as service

    importlib.reload(service)

    client = TestClient(service.app)

    resp = client.get("/fleet/devices")
    assert resp.status_code == 200
    assert resp.json() == []

    create_payload = {"name": "Edge 1", "status": "online"}
    resp = client.post("/fleet/devices", json=create_payload)
    assert resp.status_code == 201
    device = resp.json()
    assert device["name"] == "Edge 1"

    resp = client.put(
        f"/fleet/devices/{device['id']}/status",
        json={"status": "offline"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "offline"

    resp = client.post("/fleet/rollouts/plan", json={"stage_percentages": [50, 100]})
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["total_devices"] == 1
    assert plan["stages"]

    resp = client.post("/fleet/security/check", json={"device_id": device["id"]})
    assert resp.status_code == 200
    assert resp.json()["status"] in {"pass", "fail"}
