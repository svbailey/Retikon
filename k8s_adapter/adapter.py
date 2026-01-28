from __future__ import annotations

import os
from dataclasses import dataclass

from k8s_adapter.providers import (
    EnvSecretsProvider,
    InMemoryStateStore,
    UnsupportedObjectStore,
    UnsupportedQueue,
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
        object_store: ObjectStoreProvider = UnsupportedObjectStore()
        queue: QueueProvider = UnsupportedQueue()
        secrets: SecretsProvider = EnvSecretsProvider()
        state_store: StateStoreProvider = InMemoryStateStore()
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
