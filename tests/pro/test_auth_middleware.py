from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app
from retikon_core.auth.store import hash_key


def _write_registry(path, raw_key, org_id=None):
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_keys": [
            {
                "id": "key-1",
                "name": "test",
                "key_hash": hash_key(raw_key),
                "org_id": org_id,
                "site_id": None,
                "stream_id": None,
                "enabled": True,
                "is_admin": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_rbac_enforced_for_query_and_ingest(monkeypatch, tmp_path):
    registry_path = tmp_path / "api_keys.json"
    raw_key = "rbac-key"
    _write_registry(registry_path, raw_key)

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("API_KEY_REGISTRY_URI", registry_path.as_posix())
    monkeypatch.setenv("RBAC_ENFORCE", "1")
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "reader")

    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 200

    client_ingest = TestClient(ingest_app)
    resp = client_ingest.post(
        "/ingest",
        json={"specversion": "1.0", "data": {}},
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 403


def test_abac_denies_when_policy_matches(monkeypatch, tmp_path):
    registry_path = tmp_path / "api_keys.json"
    raw_key = "abac-key"
    _write_registry(registry_path, raw_key, org_id="org-1")

    policy_path = tmp_path / "abac_policies.json"
    policy_payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policies": [
            {
                "id": "deny-org",
                "effect": "deny",
                "conditions": {"org_id": "org-1"},
            }
        ],
    }
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("API_KEY_REGISTRY_URI", registry_path.as_posix())
    monkeypatch.setenv("ABAC_ENFORCE", "1")
    monkeypatch.setenv("ABAC_POLICY_URI", policy_path.as_posix())

    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 403
