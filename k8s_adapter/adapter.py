from __future__ import annotations

import os
from dataclasses import dataclass

from k8s_adapter.providers import (
    ChainedSecretsProvider,
    EnvSecretsProvider,
    FileSecretsProvider,
    FileStateStore,
    FsspecObjectStore,
    InMemoryQueue,
    InMemoryStateStore,
    RedisQueue,
    RedisStateStore,
    UnsupportedObjectStore,
    UnsupportedQueue,
    _redis_client_from_env,
)
from retikon_core.providers import (
    ObjectStoreProvider,
    QueueProvider,
    SecretsProvider,
    StateStoreProvider,
)


@dataclass(frozen=True)
class K8sAdapter:
    namespace: str
    object_store: ObjectStoreProvider
    queue: QueueProvider
    secrets: SecretsProvider
    state_store: StateStoreProvider

    @classmethod
    def from_env(cls) -> "K8sAdapter":
        namespace = os.getenv("K8S_NAMESPACE", "default")
        object_store = _object_store_from_env()
        queue = _queue_from_env()
        secrets = _secrets_from_env()
        state_store = _state_store_from_env()
        return cls(
            namespace=namespace,
            object_store=object_store,
            queue=queue,
            secrets=secrets,
            state_store=state_store,
        )

    def health(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "object_store": type(self.object_store).__name__,
            "queue": type(self.queue).__name__,
            "secrets": type(self.secrets).__name__,
            "state_store": type(self.state_store).__name__,
        }


def _object_store_from_env() -> ObjectStoreProvider:
    backend = os.getenv("K8S_OBJECT_STORE_BACKEND", "fsspec").strip().lower()
    base_uri = os.getenv("K8S_OBJECT_STORE_URI") or os.getenv("K8S_OBJECT_STORE_ROOT")
    if backend in {"fsspec", "fs"}:
        return FsspecObjectStore(base_uri=base_uri)
    if backend in {"unsupported", "none"}:
        return UnsupportedObjectStore()
    raise ValueError(f"Unsupported K8S_OBJECT_STORE_BACKEND: {backend}")


def _queue_from_env() -> QueueProvider:
    backend = os.getenv("K8S_QUEUE_BACKEND", "").strip().lower()
    prefix = os.getenv("K8S_QUEUE_PREFIX", "retikon").strip()
    if not backend:
        backend = "redis" if _has_redis_env() else "memory"
    if backend in {"redis"}:
        client = _redis_client_from_env()
        if client is None:
            raise ValueError("Redis queue backend requires REDIS_HOST/URL")
        return RedisQueue(client, prefix=prefix)
    if backend in {"memory", "inmemory"}:
        return InMemoryQueue()
    if backend in {"unsupported", "none"}:
        return UnsupportedQueue()
    raise ValueError(f"Unsupported K8S_QUEUE_BACKEND: {backend}")


def _secrets_from_env() -> SecretsProvider:
    backend = os.getenv("K8S_SECRETS_BACKEND", "").strip().lower()
    secrets_dir = os.getenv("K8S_SECRETS_DIR", "/var/run/secrets/retikon")
    if backend in {"file", "filesystem"}:
        return FileSecretsProvider(secrets_dir)
    if backend in {"env", "environment"}:
        return EnvSecretsProvider()
    if backend in {"chain", "combined"}:
        return ChainedSecretsProvider(
            (FileSecretsProvider(secrets_dir), EnvSecretsProvider())
        )
    if os.path.isdir(secrets_dir):
        return ChainedSecretsProvider(
            (FileSecretsProvider(secrets_dir), EnvSecretsProvider())
        )
    return EnvSecretsProvider()


def _state_store_from_env() -> StateStoreProvider:
    backend = os.getenv("K8S_STATE_BACKEND", "").strip().lower()
    state_dir = os.getenv("K8S_STATE_DIR", "/var/run/retikon/state")
    prefix = os.getenv("K8S_STATE_PREFIX", "retikon").strip()
    if not backend:
        if _has_redis_env():
            backend = "redis"
        elif os.path.isdir(state_dir):
            backend = "file"
        else:
            backend = "memory"
    if backend in {"redis"}:
        client = _redis_client_from_env()
        if client is None:
            raise ValueError("Redis state backend requires REDIS_HOST/URL")
        return RedisStateStore(client, prefix=prefix)
    if backend in {"file", "filesystem"}:
        return FileStateStore(state_dir)
    if backend in {"memory", "inmemory"}:
        return InMemoryStateStore()
    raise ValueError(f"Unsupported K8S_STATE_BACKEND: {backend}")


def _has_redis_env() -> bool:
    if os.getenv("K8S_REDIS_URL") or os.getenv("REDIS_URL"):
        return True
    if os.getenv("K8S_REDIS_HOST") or os.getenv("REDIS_HOST"):
        return True
    return False
