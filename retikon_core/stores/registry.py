from __future__ import annotations

import os
from dataclasses import dataclass

from retikon_core.stores.interfaces import (
    AbacStore,
    ApiKeyStore,
    ConnectorStore,
    DataFactoryStore,
    FleetStore,
    PrivacyStore,
    RbacStore,
    WorkflowStore,
)
from retikon_core.stores.json_store import (
    JsonAbacStore,
    JsonApiKeyStore,
    JsonConnectorStore,
    JsonDataFactoryStore,
    JsonFleetStore,
    JsonPrivacyStore,
    JsonRbacStore,
    JsonWorkflowStore,
)


@dataclass(frozen=True)
class StoreBundle:
    rbac: RbacStore
    abac: AbacStore
    privacy: PrivacyStore
    fleet: FleetStore
    workflows: WorkflowStore
    data_factory: DataFactoryStore
    connectors: ConnectorStore
    api_keys: ApiKeyStore


def get_store_bundle(base_uri: str) -> StoreBundle:
    backend = os.getenv("CONTROL_PLANE_STORE", "json").strip().lower()
    if backend != "json":
        raise ValueError(f"Unsupported control-plane store backend: {backend}")
    return StoreBundle(
        rbac=JsonRbacStore(base_uri),
        abac=JsonAbacStore(base_uri),
        privacy=JsonPrivacyStore(base_uri),
        fleet=JsonFleetStore(base_uri),
        workflows=JsonWorkflowStore(base_uri),
        data_factory=JsonDataFactoryStore(base_uri),
        connectors=JsonConnectorStore(base_uri),
        api_keys=JsonApiKeyStore(base_uri),
    )
