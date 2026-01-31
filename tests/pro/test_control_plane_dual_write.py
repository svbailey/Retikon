from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import gcp_adapter.stores as stores
from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.stores.registry import StoreBundle


class _StubPrivacyStore:
    def __init__(self, policies: list[PrivacyPolicy] | None = None) -> None:
        self.policies = list(policies or [])

    def load_policies(self) -> list[PrivacyPolicy]:
        return list(self.policies)

    def save_policies(self, policies: list[PrivacyPolicy]) -> str:
        self.policies = list(policies)
        return "saved"

    def register_policy(self, **kwargs) -> PrivacyPolicy:
        now = datetime.now(timezone.utc).isoformat()
        policy = PrivacyPolicy(
            id=str(uuid.uuid4()),
            name=kwargs["name"],
            org_id=kwargs.get("org_id"),
            site_id=kwargs.get("site_id"),
            stream_id=kwargs.get("stream_id"),
            modalities=tuple(kwargs.get("modalities") or ()) or None,
            contexts=tuple(kwargs.get("contexts") or ()) or None,
            redaction_types=tuple(kwargs.get("redaction_types") or ("pii",)),
            enabled=kwargs.get("enabled", True),
            created_at=now,
            updated_at=now,
        )
        self.policies.append(policy)
        return policy

    def update_policy(self, *, policy: PrivacyPolicy) -> PrivacyPolicy:
        updated: list[PrivacyPolicy] = []
        found = False
        for existing in self.policies:
            if existing.id == policy.id:
                updated.append(policy)
                found = True
            else:
                updated.append(existing)
        if not found:
            updated.append(policy)
        self.policies = updated
        return policy


class _StubNoopStore:
    def load_role_bindings(self):
        return {}

    def save_role_bindings(self, _bindings):
        return "saved"

    def load_policies(self):
        return []

    def save_policies(self, _policies):
        return "saved"

    def load_devices(self):
        return []

    def save_devices(self, _devices):
        return "saved"

    def register_device(self, **_kwargs):
        raise AssertionError("not used")

    def update_device(self, _device):
        raise AssertionError("not used")

    def update_device_status(self, **_kwargs):
        raise AssertionError("not used")

    def load_workflows(self):
        return []

    def save_workflows(self, _workflows):
        return "saved"

    def register_workflow(self, **_kwargs):
        raise AssertionError("not used")

    def update_workflow(self, *, workflow):
        return workflow

    def load_workflow_runs(self):
        return []

    def save_workflow_runs(self, _runs):
        return "saved"

    def register_workflow_run(self, **_kwargs):
        raise AssertionError("not used")

    def update_workflow_run(self, *, run):
        return run

    def list_workflow_runs(self, **_kwargs):
        return []

    def load_models(self):
        return []

    def save_models(self, _models):
        return "saved"

    def register_model(self, **_kwargs):
        raise AssertionError("not used")

    def update_model(self, _model):
        raise AssertionError("not used")

    def load_training_jobs(self):
        return []

    def save_training_jobs(self, _jobs):
        return "saved"

    def register_training_job(self, **_kwargs):
        raise AssertionError("not used")

    def update_training_job(self, *, job):
        return job

    def get_training_job(self, _job_id):
        return None

    def list_training_jobs(self, **_kwargs):
        return []

    def mark_training_job_running(self, *, job_id):
        raise AssertionError("not used")

    def mark_training_job_completed(self, **_kwargs):
        raise AssertionError("not used")

    def mark_training_job_failed(self, **_kwargs):
        raise AssertionError("not used")

    def mark_training_job_canceled(self, *, job_id):
        raise AssertionError("not used")

    def load_ocr_connectors(self):
        return []

    def save_ocr_connectors(self, _connectors):
        return "saved"

    def register_ocr_connector(self, **_kwargs):
        raise AssertionError("not used")

    def update_ocr_connector(self, *, connector):
        return connector

    def load_api_keys(self):
        return []

    def save_api_keys(self, _api_keys):
        return "saved"

    def register_api_key(self, **_kwargs):
        raise AssertionError("not used")

    def update_api_key(self, _api_key):
        raise AssertionError("not used")


def _bundle(privacy_store: _StubPrivacyStore) -> StoreBundle:
    noop = _StubNoopStore()
    return StoreBundle(
        rbac=noop,
        abac=noop,
        privacy=privacy_store,
        fleet=noop,
        workflows=noop,
        data_factory=noop,
        connectors=noop,
        api_keys=noop,
    )


@pytest.mark.pro
def test_dual_write_privacy(monkeypatch):
    primary_privacy = _StubPrivacyStore()
    secondary_privacy = _StubPrivacyStore()
    monkeypatch.setattr(
        stores,
        "gcp_get_store_bundle",
        lambda _base_uri: _bundle(primary_privacy),
    )
    monkeypatch.setattr(
        stores,
        "core_get_store_bundle",
        lambda _base_uri: _bundle(secondary_privacy),
    )
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv("CONTROL_PLANE_WRITE_MODE", "dual")
    monkeypatch.setenv("CONTROL_PLANE_READ_MODE", "primary")
    monkeypatch.delenv("CONTROL_PLANE_FALLBACK_ON_EMPTY", raising=False)
    stores._STORE_BUNDLE = None
    stores._STORE_KEY = None

    bundle = stores.get_control_plane_stores("gs://bucket/retikon_v2")
    policy = bundle.privacy.register_policy(name="pii")

    assert len(primary_privacy.policies) == 1
    assert len(secondary_privacy.policies) == 1
    assert primary_privacy.policies[0].id == policy.id
    assert secondary_privacy.policies[0].id == policy.id


@pytest.mark.pro
def test_read_fallback_on_empty(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    secondary_privacy = _StubPrivacyStore(
        [
            PrivacyPolicy(
                id="policy-1",
                name="pii",
                org_id=None,
                site_id=None,
                stream_id=None,
                modalities=("text",),
                contexts=("query",),
                redaction_types=("pii",),
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        ]
    )
    primary_privacy = _StubPrivacyStore()
    monkeypatch.setattr(
        stores,
        "gcp_get_store_bundle",
        lambda _base_uri: _bundle(primary_privacy),
    )
    monkeypatch.setattr(
        stores,
        "core_get_store_bundle",
        lambda _base_uri: _bundle(secondary_privacy),
    )
    monkeypatch.setenv("CONTROL_PLANE_STORE", "firestore")
    monkeypatch.setenv("CONTROL_PLANE_READ_MODE", "fallback")
    monkeypatch.setenv("CONTROL_PLANE_WRITE_MODE", "single")
    monkeypatch.setenv("CONTROL_PLANE_FALLBACK_ON_EMPTY", "1")
    stores._STORE_BUNDLE = None
    stores._STORE_KEY = None

    bundle = stores.get_control_plane_stores("gs://bucket/retikon_v2")
    policies = bundle.privacy.load_policies()
    assert policies and policies[0].id == "policy-1"
