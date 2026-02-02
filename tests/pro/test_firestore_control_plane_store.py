from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from google.cloud import firestore

from gcp_adapter.stores import get_control_plane_stores
from retikon_core.privacy.types import PrivacyPolicy


def _require_firestore_emulator() -> None:
    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        return
    if os.getenv("FIRESTORE_ALLOW_REAL") == "1":
        return
    pytest.skip("Set FIRESTORE_EMULATOR_HOST or FIRESTORE_ALLOW_REAL=1")


def _collection_prefix(label: str) -> str:
    if os.getenv("FIRESTORE_ALLOW_REAL") == "1":
        return os.getenv("FIRESTORE_TEST_PREFIX", "test_")
    return f"{label}_{uuid.uuid4().hex}_"


@pytest.mark.pro
def test_firestore_privacy_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_privacy"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    policy = stores.privacy.register_policy(
        name="pii",
        org_id="org",
        site_id=None,
        stream_id=None,
        modalities=["text"],
        contexts=["query"],
        redaction_types=["pii"],
        enabled=True,
    )
    policies = stores.privacy.load_policies()
    assert any(item.id == policy.id for item in policies)
    updated = PrivacyPolicy(
        id=policy.id,
        name="pii-updated",
        org_id=policy.org_id,
        site_id=policy.site_id,
        stream_id=policy.stream_id,
        modalities=policy.modalities,
        contexts=policy.contexts,
        redaction_types=policy.redaction_types,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    stores.privacy.update_policy(policy=updated)
    policies = stores.privacy.load_policies()
    refreshed = next(item for item in policies if item.id == policy.id)
    assert refreshed.name == "pii-updated"


@pytest.mark.pro
def test_firestore_workflow_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_workflow"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    workflow = stores.workflows.register_workflow(
        name="wf",
        description=None,
        org_id="org",
        site_id=None,
        stream_id=None,
        schedule=None,
        enabled=True,
        steps=(),
    )
    run = stores.workflows.register_workflow_run(
        workflow_id=workflow.id,
        status="queued",
        triggered_by="test",
    )
    runs = stores.workflows.list_workflow_runs(workflow_id=workflow.id, limit=5)
    assert any(item.id == run.id for item in runs)


@pytest.mark.pro
def test_firestore_composite_index_query(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    prefix = _collection_prefix("test_index")
    monkeypatch.setenv("CONTROL_PLANE_COLLECTION_PREFIX", prefix)
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    base_uri = "gs://test-bucket/retikon_v2"
    stores = get_control_plane_stores(base_uri)

    workflow = stores.workflows.register_workflow(
        name="wf-index",
        description=None,
        org_id="org",
        site_id=None,
        stream_id=None,
        schedule=None,
        enabled=True,
        steps=(),
    )
    run = stores.workflows.register_workflow_run(
        workflow_id=workflow.id,
        status="queued",
        triggered_by="test",
        org_id="org",
    )

    client = firestore.Client(project=project_id)
    query = (
        client.collection(f"{prefix}workflow_runs")
        .where("org_id", "==", "org")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(10)
    )
    results = list(query.stream())
    assert any(doc.id == run.id for doc in results)
