from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_data_factory_service(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.data_factory_service as service

    importlib.reload(service)

    client = TestClient(service.app)

    resp = client.get("/data-factory/datasets")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post("/data-factory/datasets", json={"name": "Dataset 1"})
    assert resp.status_code == 201

    resp = client.get("/data-factory/datasets")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Dataset 1"
    dataset_id = resp.json()[0]["id"]

    resp = client.post(
        "/data-factory/annotations",
        json={
            "dataset_id": dataset_id,
            "media_asset_id": "asset-1",
            "label": "person",
        },
    )
    assert resp.status_code == 201

    resp = client.get("/data-factory/annotations")
    assert resp.status_code == 200
    assert resp.json()[0]["label"] == "person"

    resp = client.post(
        "/data-factory/models",
        json={"name": "Model", "version": "1"},
    )
    assert resp.status_code == 201

    resp = client.get("/data-factory/models")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Model"

    resp = client.get("/data-factory/connectors")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
