from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app


def test_rbac_enforced_for_query_and_ingest(monkeypatch, jwt_factory):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("RBAC_ENFORCE", "1")

    token = jwt_factory(roles=["reader"])
    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    client_ingest = TestClient(ingest_app)
    resp = client_ingest.post(
        "/ingest",
        json={"specversion": "1.0", "data": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_abac_denies_when_policy_matches(monkeypatch, tmp_path, jwt_factory):
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
    monkeypatch.setenv("ABAC_ENFORCE", "1")
    monkeypatch.setenv("ABAC_POLICY_URI", policy_path.as_posix())

    token = jwt_factory(org_id="org-1", roles=["reader"])
    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
