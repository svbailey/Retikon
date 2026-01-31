from __future__ import annotations

import os

from google.cloud import firestore

from retikon_core.stores import registry as core_registry
from retikon_core.stores.registry import StoreBundle
from retikon_gcp.stores.firestore_store import (
    FirestoreAbacStore,
    FirestoreApiKeyStore,
    FirestoreConnectorStore,
    FirestoreDataFactoryStore,
    FirestoreFleetStore,
    FirestorePrivacyStore,
    FirestoreRbacStore,
    FirestoreWorkflowStore,
)


def get_store_bundle(
    base_uri: str,
    *,
    client: firestore.Client | None = None,
    project_id: str | None = None,
    collection_prefix: str | None = None,
) -> StoreBundle:
    backend = os.getenv("CONTROL_PLANE_STORE", "json").strip().lower()
    if backend != "firestore":
        return core_registry.get_store_bundle(base_uri)
    firestore_client = client or firestore.Client(project=project_id)
    return StoreBundle(
        rbac=FirestoreRbacStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        abac=FirestoreAbacStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        privacy=FirestorePrivacyStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        fleet=FirestoreFleetStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        workflows=FirestoreWorkflowStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        data_factory=FirestoreDataFactoryStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        connectors=FirestoreConnectorStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
        api_keys=FirestoreApiKeyStore(
            firestore_client,
            collection_prefix=collection_prefix,
        ),
    )
