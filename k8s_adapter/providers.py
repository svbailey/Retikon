from __future__ import annotations

import os
import time
from dataclasses import dataclass

from retikon_core.providers import (
    ObjectStoreProvider,
    QueueMessage,
    QueueProvider,
    SecretsProvider,
    StateStoreProvider,
)


@dataclass
class InMemoryStateStore(StateStoreProvider):
    _values: dict[str, tuple[str, float | None]]

    def __init__(self) -> None:
        self._values = {}

    def get(self, key: str) -> str | None:
        value = self._values.get(key)
        if value is None:
            return None
        payload, expires_at = value
        if expires_at is not None and expires_at <= time.time():
            self._values.pop(key, None)
            return None
        return payload

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = time.time() + ttl_seconds
        self._values[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class EnvSecretsProvider(SecretsProvider):
    def get_secret(self, name: str) -> str:
        env_key = f"RETIKON_SECRET_{name.upper().replace('-', '_')}"
        value = os.getenv(env_key)
        if value is None:
            raise KeyError(f"Missing secret env: {env_key}")
        return value


class UnsupportedObjectStore(ObjectStoreProvider):
    def read_bytes(self, uri: str) -> bytes:  # pragma: no cover
        raise NotImplementedError("Object store provider not configured")

    def write_bytes(
        self,
        uri: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:  # pragma: no cover
        raise NotImplementedError("Object store provider not configured")

    def exists(self, uri: str) -> bool:  # pragma: no cover
        raise NotImplementedError("Object store provider not configured")

    def list(self, prefix: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError("Object store provider not configured")


class UnsupportedQueue(QueueProvider):
    def publish(self, queue: str, message: QueueMessage) -> str:  # pragma: no cover
        raise NotImplementedError("Queue provider not configured")

    def pull(
        self,
        queue: str,
        max_messages: int = 1,
    ) -> list[QueueMessage]:  # pragma: no cover
        raise NotImplementedError("Queue provider not configured")
