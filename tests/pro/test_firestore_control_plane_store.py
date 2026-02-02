from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest
from google.cloud import firestore

from gcp_adapter.stores import get_control_plane_stores
from retikon_core.auth.abac import Policy
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
def test_firestore_fleet_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_fleet"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    device = stores.fleet.register_device(
        name="cam-1",
        org_id="org",
        status="active",
        tags=["edge"],
        metadata={"region": "us"},
    )
    devices = stores.fleet.load_devices()
    assert any(item.id == device.id for item in devices)
    updated = stores.fleet.update_device_status(
        device_id=device.id,
        status="disabled",
    )
    assert updated is not None
    assert updated.metadata == {"region": "us"}


@pytest.mark.pro
def test_firestore_data_factory_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_data_factory"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    model = stores.data_factory.register_model(
        name="model-1",
        version="1",
        org_id="org",
    )
    models = stores.data_factory.load_models()
    assert any(item.id == model.id for item in models)
    job = stores.data_factory.register_training_job(
        model_id=model.id,
        dataset_id="dataset-1",
        epochs=1,
    )
    fetched = stores.data_factory.get_training_job(job.id)
    assert fetched is not None
    jobs = stores.data_factory.list_training_jobs(limit=5)
    assert any(item.id == job.id for item in jobs)
    running = stores.data_factory.mark_training_job_running(job_id=job.id)
    assert running.status == "running"


@pytest.mark.pro
def test_firestore_connector_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_connectors"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    connector = stores.connectors.register_ocr_connector(
        name="OCR Primary",
        url="https://ocr.example.com/v1/extract",
        auth_type="bearer",
        token_env="OCR_TOKEN",
        enabled=True,
        is_default=True,
        org_id="org",
    )
    connectors = stores.connectors.load_ocr_connectors()
    assert any(item.id == connector.id for item in connectors)
    updated = stores.connectors.update_ocr_connector(connector=connector)
    assert updated.id == connector.id


@pytest.mark.pro
def test_firestore_api_key_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_api_keys"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    api_key = stores.api_keys.register_api_key(
        name="key-1",
        key_hash="hash",
        org_id="org",
    )
    keys = stores.api_keys.load_api_keys()
    assert any(item.id == api_key.id for item in keys)


@pytest.mark.pro
def test_firestore_rbac_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_rbac"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    bindings = {"principal-1": ["reader", "ingestor"]}
    stores.rbac.save_role_bindings(bindings)
    loaded = stores.rbac.load_role_bindings()
    assert loaded == bindings


@pytest.mark.pro
def test_firestore_abac_store_roundtrip(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_abac"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    policies = [
        Policy(id="policy-1", effect="allow", conditions={"org_id": "org"})
    ]
    stores.abac.save_policies(policies)
    loaded = stores.abac.load_policies()
    assert any(item.id == "policy-1" for item in loaded)


@pytest.mark.pro
def test_firestore_device_status_transaction(monkeypatch):
    _require_firestore_emulator()
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv(
        "CONTROL_PLANE_COLLECTION_PREFIX",
        _collection_prefix("test_fleet_tx"),
    )
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)
    stores = get_control_plane_stores("gs://test-bucket/retikon_v2")
    device = stores.fleet.register_device(
        name="cam-tx",
        org_id="org",
        status="active",
        metadata={"region": "us"},
    )

    barrier = threading.Barrier(3)

    def _update(status: str) -> None:
        barrier.wait()
        stores.fleet.update_device_status(device_id=device.id, status=status)

    t1 = threading.Thread(target=_update, args=("active",))
    t2 = threading.Thread(target=_update, args=("disabled",))
    t1.start()
    t2.start()
    barrier.wait()
    t1.join()
    t2.join()

    devices = stores.fleet.load_devices()
    refreshed = next(item for item in devices if item.id == device.id)
    assert refreshed.metadata == {"region": "us"}
    assert refreshed.status in {"active", "disabled"}


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
