from __future__ import annotations

import importlib
import json

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def _setup_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("RBAC_ENFORCE", "1")
    monkeypatch.setenv("ABAC_ENFORCE", "0")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    monkeypatch.setenv("GRAPH_URI", tmp_path.as_posix())
    monkeypatch.setenv("CONTROL_PLANE_STORE", "json")
    get_config.cache_clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_rbac_privacy(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.privacy_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/privacy/policies",
        json={"name": "pii", "modalities": ["text"], "contexts": ["query"]},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/privacy/policies",
        json={"name": "pii", "modalities": ["text"], "contexts": ["query"]},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_fleet(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.fleet_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/fleet/devices",
        json={"name": "cam-1", "status": "active"},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/fleet/devices",
        json={"name": "cam-1", "status": "active"},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_workflows(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.workflow_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/workflows",
        json={"name": "wf"},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/workflows",
        json={"name": "wf"},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_chaos(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.chaos_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/chaos/policies",
        json={"name": "policy"},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/chaos/policies",
        json={"name": "policy"},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_data_factory(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.data_factory_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/data-factory/datasets",
        json={"name": "Dataset 1"},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/data-factory/datasets",
        json={"name": "Dataset 1"},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_webhooks(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.webhook_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/webhooks",
        json={"name": "hook", "url": "https://example.com/hook"},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/webhooks",
        json={"name": "hook", "url": "https://example.com/hook"},
        headers=_headers(admin),
    )
    assert resp.status_code == 201


def test_rbac_audit(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.audit_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.get("/audit/logs", headers=_headers(reader))
    assert resp.status_code == 403

    resp = client.get("/audit/logs", headers=_headers(admin))
    assert resp.status_code == 200


def test_rbac_dev_console(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
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
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/dev/upload",
        data={"category": "docs"},
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/dev/upload",
        data={"category": "docs"},
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers=_headers(admin),
    )
    assert resp.status_code == 200


def test_rbac_edge_gateway(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    import gcp_adapter.edge_gateway_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    reader = jwt_factory(roles=["reader"])
    admin = jwt_factory(roles=["admin"])

    resp = client.post(
        "/edge/config",
        json={"buffer_max_bytes": 1024},
        headers=_headers(reader),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/edge/config",
        json={"buffer_max_bytes": 1024},
        headers=_headers(admin),
    )
    assert resp.status_code == 200


def test_abac_org_scope(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    policy_path = tmp_path / "abac_policies.json"
    payload = {
        "updated_at": "now",
        "policies": [
            {"id": "deny-org", "effect": "deny", "conditions": {"org_id": "org-1"}}
        ],
    }
    policy_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ABAC_ENFORCE", "1")
    monkeypatch.setenv("ABAC_POLICY_URI", policy_path.as_posix())
    import gcp_adapter.fleet_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    admin = jwt_factory(roles=["admin"], org_id="org-1")
    resp = client.get("/fleet/devices", headers=_headers(admin))
    assert resp.status_code == 403


def test_abac_site_scope(monkeypatch, tmp_path, jwt_factory):
    _setup_env(monkeypatch, tmp_path)
    policy_path = tmp_path / "abac_policies.json"
    payload = {
        "updated_at": "now",
        "policies": [
            {"id": "deny-site", "effect": "deny", "conditions": {"site_id": "site-1"}}
        ],
    }
    policy_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ABAC_ENFORCE", "1")
    monkeypatch.setenv("ABAC_POLICY_URI", policy_path.as_posix())
    import gcp_adapter.workflow_service as service

    importlib.reload(service)
    client = TestClient(service.app)
    admin = jwt_factory(roles=["admin"], site_id="site-1")
    resp = client.get("/workflows", headers=_headers(admin))
    assert resp.status_code == 403
