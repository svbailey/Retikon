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

    resp = client.post(
        "/data-factory/training",
        json={
            "dataset_id": dataset_id,
            "model_id": resp.json()[0]["id"],
            "epochs": 2,
        },
    )
    assert resp.status_code == 201
    job = resp.json()
    assert job["status"] in {"completed", "queued"}
    assert job["spec"]["epochs"] == 2

    resp = client.get("/data-factory/training/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp = client.get(f"/data-factory/training/jobs/{job['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job["id"]

    resp = client.get("/data-factory/connectors")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp = client.post(
        "/data-factory/ocr/connectors",
        json={
            "name": "OCR Primary",
            "url": "https://ocr.example.com/v1/extract",
            "auth_type": "header",
            "auth_header": "X-API-Key",
            "token_env": "OCR_API_KEY",
            "enabled": True,
            "is_default": True,
            "max_pages": 5,
            "timeout_s": 30,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "OCR Primary"
    assert body["is_default"] is True

    resp = client.get("/data-factory/ocr/connectors")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
