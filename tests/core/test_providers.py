from __future__ import annotations

import pytest

from retikon_core.providers import (
    ObjectStoreProvider,
    QueueMessage,
    QueueProvider,
    SecretsProvider,
    StateStoreProvider,
)


class DummyObjectStore:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    def read_bytes(self, uri: str) -> bytes:
        return self.items[uri]

    def write_bytes(
        self,
        uri: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        self.items[uri] = data

    def exists(self, uri: str) -> bool:
        return uri in self.items

    def list(self, prefix: str) -> list[str]:
        return [key for key in self.items if key.startswith(prefix)]


class DummyQueue:
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []

    def publish(self, queue: str, message: QueueMessage) -> str:
        self.messages.append(message)
        return "msg-1"

    def pull(self, queue: str, max_messages: int = 1) -> list[QueueMessage]:
        pulled = self.messages[:max_messages]
        self.messages = self.messages[max_messages:]
        return pulled


class DummySecrets:
    def __init__(self) -> None:
        self.values = {"token": "secret"}

    def get_secret(self, name: str) -> str:
        return self.values[name]


class DummyStateStore:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.mark.core
def test_provider_protocols():
    object_store = DummyObjectStore()
    queue = DummyQueue()
    secrets = DummySecrets()
    state = DummyStateStore()

    assert isinstance(object_store, ObjectStoreProvider)
    assert isinstance(queue, QueueProvider)
    assert isinstance(secrets, SecretsProvider)
    assert isinstance(state, StateStoreProvider)

    object_store.write_bytes("gs://bucket/path", b"data")
    assert object_store.exists("gs://bucket/path")
    assert object_store.read_bytes("gs://bucket/path") == b"data"

    queue.publish("default", QueueMessage(body={"ok": True}))
    pulled = queue.pull("default")
    assert pulled[0].body == {"ok": True}

    assert secrets.get_secret("token") == "secret"

    state.set("k", "v")
    assert state.get("k") == "v"
    state.delete("k")
    assert state.get("k") is None
