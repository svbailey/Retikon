from datetime import datetime, timezone

from fastapi.testclient import TestClient

from gcp_adapter.audit_service import app
from retikon_core.audit import record_audit_log
from retikon_core.auth.types import AuthContext
from retikon_core.metering import record_usage
from retikon_core.tenancy.types import TenantScope


def _seed_audit_data(base_uri: str) -> None:
    scope = TenantScope(org_id="org-1", site_id="site-1", stream_id="stream-1")
    auth_context = AuthContext(api_key_id="key-1", scope=scope, is_admin=True)
    record_audit_log(
        base_uri=base_uri,
        action="query:read",
        decision="allow",
        auth_context=auth_context,
        resource="/query",
        request_id="req-1",
        pipeline_version="v1",
        schema_version="1",
        created_at=datetime.now(timezone.utc),
    )
    record_usage(
        base_uri=base_uri,
        event_type="query",
        scope=scope,
        api_key_id="key-1",
        modality="text",
        units=1,
        bytes_in=128,
        pipeline_version="v1",
        schema_version="1",
    )


def test_audit_logs_endpoint(monkeypatch, tmp_path, jwt_headers):
    base_uri = tmp_path.as_posix()
    _seed_audit_data(base_uri)

    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("GRAPH_URI", base_uri)

    client = TestClient(app, headers=jwt_headers)
    resp = client.get("/audit/logs?limit=5")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["rows"][0]["action"] == "query:read"


def test_access_export(monkeypatch, tmp_path, jwt_headers):
    base_uri = tmp_path.as_posix()
    _seed_audit_data(base_uri)

    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("GRAPH_URI", base_uri)

    client = TestClient(app, headers=jwt_headers)
    resp = client.get("/access/export?format=jsonl")
    assert resp.status_code == 200
    content = resp.text
    assert "\"event_type\": \"query\"" in content
