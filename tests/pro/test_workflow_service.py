from __future__ import annotations

import base64
import importlib
import json

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_workflow_service_inline(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    monkeypatch.setenv("WORKFLOW_RUN_MODE", "inline")
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
                {"name": "Noop", "kind": "noop"},
            ],
        },
    )
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]

    resp = client.get("/workflows")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Export"

    resp = client.post(f"/workflows/{workflow_id}/runs", json={"execute": True})
    assert resp.status_code == 201
    assert resp.json()["workflow_id"] == workflow_id
    assert resp.json()["status"] == "completed"
    assert resp.json()["output"]["steps"][0]["status"] == "completed"

    resp = client.get(f"/workflows/runs?workflow_id={workflow_id}")
    assert resp.status_code == 200
    assert resp.json()[0]["workflow_id"] == workflow_id

    resp = client.post(
        "/workflows",
        json={
            "name": "Failure",
            "steps": [
                {"name": "Bad", "kind": "webhook", "retries": 1},
            ],
        },
    )
    assert resp.status_code == 201
    failing_id = resp.json()["id"]
    resp = client.post(f"/workflows/{failing_id}/runs", json={"execute": True})
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["status"] == "failed"
    assert payload["output"]["steps"][0]["attempts"] == 2


def test_workflow_service_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    monkeypatch.setenv("WORKFLOW_RUN_MODE", "queue")
    monkeypatch.setenv("WORKFLOW_QUEUE_TOPIC", "projects/test/topics/workflows")
    monkeypatch.setenv("WORKFLOW_RUNNER_TOKEN", "secret-token")
    get_config.cache_clear()

    import gcp_adapter.workflow_service as service

    importlib.reload(service)

    class DummyPublisher:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def publish_json(
            self,
            *,
            topic: str,
            payload: dict[str, object],
            attributes=None,
        ) -> str:
            self.payloads.append(payload)
            return "message-1"

    dummy = DummyPublisher()
    monkeypatch.setattr(service, "_queue_publisher_instance", lambda: dummy)

    client = TestClient(service.app)

    resp = client.post(
        "/workflows",
        json={"name": "Queued", "steps": [{"name": "Noop", "kind": "noop"}]},
    )
    workflow_id = resp.json()["id"]

    resp = client.post(f"/workflows/{workflow_id}/runs", json={"execute": True})
    assert resp.status_code == 201
    assert resp.json()["status"] == "queued"
    assert dummy.payloads
    payload = dummy.payloads[0]
    data = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    body = {"message": {"data": data, "attributes": {}}, "subscription": "test"}
    resp = client.post("/workflows/runner", json=body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
