from __future__ import annotations

from retikon_core.auth.abac import Policy
from retikon_core.stores import get_store_bundle


def test_store_bundle_json_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROL_PLANE_STORE", "json")
    base_uri = tmp_path.as_posix()
    stores = get_store_bundle(base_uri)

    policy = stores.privacy.register_policy(name="policy-1")
    assert stores.privacy.load_policies()[0].id == policy.id

    device = stores.fleet.register_device(name="device-1")
    assert stores.fleet.load_devices()[0].id == device.id

    bindings = {"key-1": ["reader"]}
    stores.rbac.save_role_bindings(bindings)
    assert stores.rbac.load_role_bindings() == bindings

    policies = [Policy(id="p1", effect="allow", conditions={"org_id": "org-1"})]
    stores.abac.save_policies(policies)
    loaded = stores.abac.load_policies()
    assert loaded[0].id == "p1"

    api_key = stores.api_keys.register_api_key(name="demo-key", key_hash="hash")
    loaded_keys = stores.api_keys.load_api_keys()
    assert loaded_keys[0].id == api_key.id
