from __future__ import annotations

import json
from datetime import datetime, timezone

from retikon_core.auth.rbac import ACTION_INGEST, ACTION_QUERY, is_action_allowed
from retikon_core.auth.types import AuthContext


def _write_bindings(path, bindings):
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "bindings": bindings,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_rbac_default_role(monkeypatch, tmp_path):
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "reader")
    auth = AuthContext(api_key_id="key-1", scope=None, is_admin=False)

    assert is_action_allowed(auth, ACTION_QUERY, tmp_path.as_posix())
    assert not is_action_allowed(auth, ACTION_INGEST, tmp_path.as_posix())


def test_rbac_bindings_override(monkeypatch, tmp_path):
    bindings_path = tmp_path / "rbac_bindings.json"
    _write_bindings(
        bindings_path,
        [{"api_key_id": "key-1", "roles": ["operator"]}],
    )
    monkeypatch.setenv("RBAC_BINDINGS_URI", bindings_path.as_posix())

    auth = AuthContext(api_key_id="key-1", scope=None, is_admin=False)
    assert is_action_allowed(auth, ACTION_QUERY, tmp_path.as_posix())
    assert is_action_allowed(auth, ACTION_INGEST, tmp_path.as_posix())


def test_rbac_admin_allows(monkeypatch, tmp_path):
    auth = AuthContext(api_key_id="key-1", scope=None, is_admin=True)
    assert is_action_allowed(auth, ACTION_QUERY, tmp_path.as_posix())
    assert is_action_allowed(auth, ACTION_INGEST, tmp_path.as_posix())
