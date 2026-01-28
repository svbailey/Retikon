from __future__ import annotations

import json
from datetime import datetime, timezone

from retikon_core.auth.abac import is_allowed
from retikon_core.auth.types import AuthContext
from retikon_core.tenancy.types import TenantScope


def _write_policies(path, policies):
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policies": policies,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_abac_allow_policy(monkeypatch, tmp_path):
    policies_path = tmp_path / "abac_policies.json"
    _write_policies(
        policies_path,
        [
            {
                "id": "allow-org",
                "effect": "allow",
                "conditions": {"org_id": "org-1", "action": "query:read"},
            }
        ],
    )
    monkeypatch.setenv("ABAC_POLICY_URI", policies_path.as_posix())
    monkeypatch.setenv("ABAC_DEFAULT_ALLOW", "0")

    scope = TenantScope(org_id="org-1", site_id=None, stream_id=None)
    auth = AuthContext(api_key_id="key-1", scope=scope, is_admin=False)
    assert is_allowed(auth, "query:read", tmp_path.as_posix())


def test_abac_deny_overrides_allow(monkeypatch, tmp_path):
    policies_path = tmp_path / "abac_policies.json"
    _write_policies(
        policies_path,
        [
            {
                "id": "allow-org",
                "effect": "allow",
                "conditions": {"org_id": "org-1"},
            },
            {
                "id": "deny-stream",
                "effect": "deny",
                "conditions": {"stream_id": "stream-1"},
            },
        ],
    )
    monkeypatch.setenv("ABAC_POLICY_URI", policies_path.as_posix())
    monkeypatch.setenv("ABAC_DEFAULT_ALLOW", "1")

    scope = TenantScope(org_id="org-1", site_id=None, stream_id="stream-1")
    auth = AuthContext(api_key_id="key-1", scope=scope, is_admin=False)
    assert not is_allowed(auth, "query:read", tmp_path.as_posix())


def test_abac_default_allow(monkeypatch, tmp_path):
    monkeypatch.setenv("ABAC_DEFAULT_ALLOW", "1")
    auth = AuthContext(api_key_id="key-1", scope=None, is_admin=False)
    assert is_allowed(auth, "query:read", tmp_path.as_posix())
