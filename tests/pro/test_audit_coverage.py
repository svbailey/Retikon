from __future__ import annotations

import glob
import importlib
import os

import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from retikon_core.config import get_config


def _setup_local(monkeypatch, tmp_path) -> str:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    monkeypatch.setenv("CONTROL_PLANE_STORE", "json")
    monkeypatch.setenv("AUDIT_LOGGING_ENABLED", "1")
    monkeypatch.setenv("AUDIT_BATCH_SIZE", "1")
    monkeypatch.setenv("AUDIT_BATCH_FLUSH_SECONDS", "0")
    get_config.cache_clear()
    return tmp_path.as_posix()


def _audit_rows(base_uri: str) -> list[dict[str, object]]:
    pattern = os.path.join(base_uri, "vertices", "AuditLog", "core", "*.parquet")
    rows: list[dict[str, object]] = []
    for path in glob.glob(pattern):
        table = pq.read_table(path)
        rows.extend(table.to_pylist())
    return rows


def _audit_actions(base_uri: str) -> list[str]:
    return [str(row.get("action", "")) for row in _audit_rows(base_uri)]


def test_privacy_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.privacy_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/privacy/policies")
    assert resp.status_code == 200

    resp = client.post(
        "/privacy/policies",
        json={
            "name": "pii",
            "modalities": ["text"],
            "contexts": ["query"],
            "redaction_types": ["pii"],
        },
    )
    assert resp.status_code == 201
    policy_id = resp.json()["id"]

    resp = client.put(
        f"/privacy/policies/{policy_id}",
        json={"name": "pii-updated"},
    )
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "privacy.policy.list" in actions
    assert "privacy.policy.create" in actions
    assert "privacy.policy.update" in actions
    row = next(
        item
        for item in _audit_rows(base_uri)
        if item["action"] == "privacy.policy.create"
    )
    assert row["actor_id"] == "user-1"
    assert row["org_id"] == "org-1"


def test_fleet_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.fleet_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/fleet/devices")
    assert resp.status_code == 200

    resp = client.post(
        "/fleet/devices",
        json={"name": "cam-1", "status": "active"},
    )
    assert resp.status_code == 201
    device_id = resp.json()["id"]

    resp = client.put(
        f"/fleet/devices/{device_id}/status",
        json={"status": "active"},
    )
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "fleet.device.list" in actions
    assert "fleet.device.create" in actions
    assert "fleet.device.status.update" in actions


def test_workflow_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.workflow_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/workflows")
    assert resp.status_code == 200

    resp = client.post("/workflows", json={"name": "wf"})
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]

    resp = client.put(f"/workflows/{workflow_id}", json={"name": "wf-2"})
    assert resp.status_code == 200

    resp = client.post(
        f"/workflows/{workflow_id}/runs",
        json={"execute": False},
    )
    assert resp.status_code == 201

    resp = client.get("/workflows/runs")
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "workflows.list" in actions
    assert "workflows.create" in actions
    assert "workflows.update" in actions
    assert "workflows.run.create" in actions
    assert "workflows.runs.list" in actions


def test_chaos_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.chaos_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/chaos/policies")
    assert resp.status_code == 200

    resp = client.post("/chaos/policies", json={"name": "policy"})
    assert resp.status_code == 201
    policy_id = resp.json()["id"]

    resp = client.put(
        f"/chaos/policies/{policy_id}",
        json={"name": "policy-2"},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/chaos/policies/{policy_id}/runs",
        json={"status": "queued"},
    )
    assert resp.status_code == 201

    resp = client.get("/chaos/runs")
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "chaos.policy.list" in actions
    assert "chaos.policy.create" in actions
    assert "chaos.policy.update" in actions
    assert "chaos.run.create" in actions
    assert "chaos.run.list" in actions


def test_data_factory_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.data_factory_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/data-factory/datasets")
    assert resp.status_code == 200

    resp = client.post(
        "/data-factory/datasets",
        json={"name": "Dataset 1"},
    )
    assert resp.status_code == 201

    resp = client.get("/data-factory/datasets")
    assert resp.status_code == 200
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

    resp = client.get("/data-factory/models")
    assert resp.status_code == 200

    resp = client.post(
        "/data-factory/models",
        json={"name": "Model", "version": "1"},
    )
    assert resp.status_code == 201
    model_id = resp.json()["id"]

    resp = client.post(
        "/data-factory/training",
        json={"dataset_id": dataset_id, "model_id": model_id},
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    resp = client.get("/data-factory/training/jobs")
    assert resp.status_code == 200

    resp = client.get(f"/data-factory/training/jobs/{job_id}")
    assert resp.status_code == 200

    resp = client.get("/data-factory/connectors")
    assert resp.status_code == 200

    resp = client.post(
        "/data-factory/ocr/connectors",
        json={"name": "ocr", "url": "https://ocr.example"},
    )
    assert resp.status_code == 200

    resp = client.get("/data-factory/ocr/connectors")
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "data_factory.dataset.list" in actions
    assert "data_factory.dataset.create" in actions
    assert "data_factory.annotation.list" in actions
    assert "data_factory.annotation.create" in actions
    assert "data_factory.model.list" in actions
    assert "data_factory.model.create" in actions
    assert "data_factory.training.create" in actions
    assert "data_factory.training.list" in actions
    assert "data_factory.training.read" in actions
    assert "data_factory.connectors.list" in actions
    assert "data_factory.ocr_connector.create" in actions
    assert "data_factory.ocr_connector.list" in actions


def test_webhook_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.webhook_service as service

    importlib.reload(service)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.get("/webhooks")
    assert resp.status_code == 200

    resp = client.post(
        "/webhooks",
        json={"name": "hook", "url": "https://example.com/hook"},
    )
    assert resp.status_code == 201

    resp = client.get("/alerts")
    assert resp.status_code == 200

    resp = client.post("/alerts", json={"name": "alert"})
    assert resp.status_code == 201

    resp = client.post(
        "/events",
        json={"event_type": "test", "payload": {}},
    )
    assert resp.status_code == 202

    actions = _audit_actions(base_uri)
    assert "webhooks.list" in actions
    assert "webhooks.create" in actions
    assert "alerts.list" in actions
    assert "alerts.create" in actions
    assert "events.dispatch" in actions


def test_dev_console_audit_logs(monkeypatch, tmp_path, jwt_headers):
    base_uri = _setup_local(monkeypatch, tmp_path)
    import gcp_adapter.dev_console_service as service

    class DummyBlob:
        def __init__(self) -> None:
            self.size = 0
            self.content_type = None
            self.generation = 1

        def upload_from_file(self, file_obj, content_type=None):
            data = file_obj.read()
            self.size = len(data)
            self.content_type = content_type

        def reload(self) -> None:
            return None

    class DummyBucket:
        def __init__(self) -> None:
            self._blobs: dict[str, DummyBlob] = {}

        def blob(self, name: str) -> DummyBlob:
            blob = DummyBlob()
            self._blobs[name] = blob
            return blob

    class DummyStorageClient:
        def __init__(self) -> None:
            self._buckets: dict[str, DummyBucket] = {}

        def bucket(self, name: str) -> DummyBucket:
            bucket = self._buckets.get(name)
            if bucket is None:
                bucket = DummyBucket()
                self._buckets[name] = bucket
            return bucket

    importlib.reload(service)
    dummy_client = DummyStorageClient()
    monkeypatch.setattr(service, "_storage_client", lambda: dummy_client)
    client = TestClient(service.app, headers=jwt_headers)

    resp = client.post(
        "/dev/upload",
        data={"category": "docs"},
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 200

    actions = _audit_actions(base_uri)
    assert "dev.upload.create" in actions
