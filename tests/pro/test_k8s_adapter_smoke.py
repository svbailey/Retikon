from __future__ import annotations

import pytest

from k8s_adapter import K8sAdapter


@pytest.mark.pro
def test_k8s_adapter_from_env(monkeypatch):
    monkeypatch.setenv("K8S_NAMESPACE", "retikon")
    monkeypatch.setenv("RETIKON_SECRET_API_KEY", "secret")

    adapter = K8sAdapter.from_env()
    assert adapter.namespace == "retikon"
    assert adapter.secrets.get_secret("api-key") == "secret"
    health = adapter.health()
    assert health["namespace"] == "retikon"
