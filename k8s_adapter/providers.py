from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import fsspec
from fsspec.utils import _unstrip_protocol

from retikon_core.providers import (
    ObjectStoreProvider,
    QueueMessage,
    QueueProvider,
    SecretsProvider,
    StateStoreProvider,
)
from retikon_core.storage.paths import has_uri_scheme, join_uri

try:  # pragma: no cover - optional dependency for redis-backed providers
    import redis
except ImportError:  # pragma: no cover
    redis = None


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


class FileSecretsProvider(SecretsProvider):
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def get_secret(self, name: str) -> str:
        candidates = [
            name,
            name.replace("/", "_"),
            name.replace("-", "_"),
        ]
        candidates.extend([candidate.upper() for candidate in candidates])
        for candidate in candidates:
            path = self._base_dir / candidate
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        raise KeyError(f"Missing secret file for {name}")


@dataclass(frozen=True)
class ChainedSecretsProvider(SecretsProvider):
    providers: tuple[SecretsProvider, ...]

    def get_secret(self, name: str) -> str:
        last_exc: Exception | None = None
        for provider in self.providers:
            try:
                return provider.get_secret(name)
            except KeyError as exc:
                last_exc = exc
        raise KeyError(f"Missing secret {name}") from last_exc


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


class FsspecObjectStore(ObjectStoreProvider):
    def __init__(self, base_uri: str | None = None) -> None:
        self._base_uri = base_uri

    def _resolve(self, uri: str) -> str:
        if self._base_uri and not has_uri_scheme(uri) and not uri.startswith("/"):
            return join_uri(self._base_uri, uri)
        return uri

    def read_bytes(self, uri: str) -> bytes:
        resolved = self._resolve(uri)
        with fsspec.open(resolved, "rb") as handle:
            return handle.read()

    def write_bytes(
        self,
        uri: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        resolved = self._resolve(uri)
        fs, path = fsspec.core.url_to_fs(resolved)
        parent = os.path.dirname(path)
        if parent:
            try:
                fs.makedirs(parent, exist_ok=True)
            except Exception:
                pass
        with fs.open(path, "wb") as handle:
            handle.write(data)

    def exists(self, uri: str) -> bool:
        resolved = self._resolve(uri)
        fs, path = fsspec.core.url_to_fs(resolved)
        return fs.exists(path)

    def list(self, prefix: str) -> list[str]:
        resolved = self._resolve(prefix)
        fs, path = fsspec.core.url_to_fs(resolved)
        try:
            entries = fs.find(path)
        except FileNotFoundError:
            return []
        return [_unstrip_protocol(item, fs) for item in entries]


class InMemoryQueue(QueueProvider):
    def __init__(self) -> None:
        self._queues: dict[str, list[QueueMessage]] = {}

    def publish(self, queue: str, message: QueueMessage) -> str:
        self._queues.setdefault(queue, []).append(message)
        return f"mem-{uuid.uuid4()}"

    def pull(self, queue: str, max_messages: int = 1) -> list[QueueMessage]:
        messages = self._queues.get(queue, [])
        pulled = messages[:max_messages]
        self._queues[queue] = messages[max_messages:]
        return pulled


def _redis_client_from_env(prefix: str = "K8S_REDIS"):
    if redis is None:  # pragma: no cover
        raise RuntimeError("Redis backend requires the redis package")
    url = os.getenv(f"{prefix}_URL") or os.getenv("REDIS_URL")
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    host = os.getenv(f"{prefix}_HOST") or os.getenv("REDIS_HOST")
    if not host:
        return None
    port = int(os.getenv(f"{prefix}_PORT") or os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv(f"{prefix}_DB") or os.getenv("REDIS_DB", "0"))
    password = os.getenv(f"{prefix}_PASSWORD") or os.getenv("REDIS_PASSWORD")
    ssl = os.getenv(f"{prefix}_SSL") or os.getenv("REDIS_SSL", "0")
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        ssl=str(ssl) == "1",
        decode_responses=True,
    )


class RedisQueue(QueueProvider):
    def __init__(self, client, *, prefix: str | None = None) -> None:
        self._client = client
        self._prefix = prefix or ""

    def _queue_key(self, queue: str) -> str:
        if not self._prefix:
            return queue
        return f"{self._prefix}:{queue}"

    def publish(self, queue: str, message: QueueMessage) -> str:
        payload = {
            "body": message.body,
            "attributes": message.attributes or {},
        }
        message_id = f"redis-{uuid.uuid4()}"
        payload["message_id"] = message_id
        data = json.dumps(payload, ensure_ascii=True)
        self._client.rpush(self._queue_key(queue), data)
        return message_id

    def pull(self, queue: str, max_messages: int = 1) -> list[QueueMessage]:
        key = self._queue_key(queue)
        pulled: list[QueueMessage] = []
        for _ in range(max_messages):
            raw = self._client.lpop(key)
            if raw is None:
                break
            payload = json.loads(raw)
            pulled.append(
                QueueMessage(
                    body=payload.get("body", {}),
                    attributes=payload.get("attributes") or None,
                )
            )
        return pulled


class RedisStateStore(StateStoreProvider):
    def __init__(self, client, *, prefix: str | None = None) -> None:
        self._client = client
        self._prefix = prefix or ""

    def _key(self, key: str) -> str:
        if not self._prefix:
            return key
        return f"{self._prefix}:{key}"

    def get(self, key: str) -> str | None:
        value = self._client.get(self._key(key))
        if value is None:
            return None
        return str(value)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        redis_key = self._key(key)
        if ttl_seconds is None:
            self._client.set(redis_key, value)
        else:
            self._client.setex(redis_key, ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))


class FileStateStore(StateStoreProvider):
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("/", "_")
        return self._base_dir / safe_key

    def get(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        expires_at = payload.get("expires_at")
        if expires_at is not None and expires_at <= time.time():
            path.unlink(missing_ok=True)
            return None
        return payload.get("value")

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = time.time() + ttl_seconds
        payload = {"value": value, "expires_at": expires_at}
        content = json.dumps(payload, ensure_ascii=True)
        self._path(key).write_text(content, encoding="utf-8")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
