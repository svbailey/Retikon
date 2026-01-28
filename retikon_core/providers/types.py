from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class QueueMessage:
    body: dict[str, object]
    attributes: dict[str, str] | None = None


@runtime_checkable
class ObjectStoreProvider(Protocol):
    def read_bytes(self, uri: str) -> bytes: ...

    def write_bytes(
        self,
        uri: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None: ...

    def exists(self, uri: str) -> bool: ...

    def list(self, prefix: str) -> list[str]: ...


@runtime_checkable
class QueueProvider(Protocol):
    def publish(self, queue: str, message: QueueMessage) -> str: ...

    def pull(self, queue: str, max_messages: int = 1) -> list[QueueMessage]: ...


@runtime_checkable
class SecretsProvider(Protocol):
    def get_secret(self, name: str) -> str: ...


@runtime_checkable
class StateStoreProvider(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...
