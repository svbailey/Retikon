from __future__ import annotations

import pytest

from k8s_adapter import K8sAdapter
from retikon_core.providers import QueueMessage


@pytest.mark.pro
def test_k8s_adapter_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("K8S_NAMESPACE", "retikon")
    monkeypatch.setenv("K8S_QUEUE_BACKEND", "memory")
    monkeypatch.setenv("K8S_STATE_BACKEND", "memory")
    monkeypatch.setenv("K8S_OBJECT_STORE_URI", tmp_path.as_uri())

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "auth-token").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("K8S_SECRETS_BACKEND", "file")
    monkeypatch.setenv("K8S_SECRETS_DIR", str(secrets_dir))

    adapter = K8sAdapter.from_env()
    assert adapter.namespace == "retikon"
    assert adapter.secrets.get_secret("auth-token") == "secret"

    adapter.object_store.write_bytes("sample.txt", b"data")
    assert adapter.object_store.read_bytes("sample.txt") == b"data"
    assert adapter.object_store.exists("sample.txt")
    assert any(
        entry.endswith("sample.txt") for entry in adapter.object_store.list("")
    )

    adapter.queue.publish("default", QueueMessage(body={"ok": True}))
    pulled = adapter.queue.pull("default")
    assert pulled[0].body == {"ok": True}

    adapter.state_store.set("k", "v")
    assert adapter.state_store.get("k") == "v"

    health = adapter.health()
    assert health["namespace"] == "retikon"
