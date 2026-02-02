from __future__ import annotations

import os
import uuid

import pytest
from google.cloud import firestore

from gcp_adapter import metering
from retikon_core.tenancy.types import TenantScope


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
def test_usage_metering_payload_schema():
    scope = TenantScope(org_id="org-1", site_id="site-1", stream_id="stream-1")
    payload = metering.build_usage_payload_for_test(
        event_type="query",
        scope=scope,
        api_key_id="key-1",
        modality="text",
        units=2,
        bytes_in=256,
        response_time_ms=123,
        tokens=42,
        pipeline_version="v1",
        schema_version="1",
    )
    assert payload["org_id"] == "org-1"
    assert payload["site_id"] == "site-1"
    assert payload["stream_id"] == "stream-1"
    assert payload["request_type"] == "query"
    assert payload["tokens"] == 42
    assert payload["bytes"] == 256
    assert payload["response_time"] == 123


@pytest.mark.pro
def test_usage_metering_firestore_write(monkeypatch, tmp_path):
    _require_firestore_emulator()
    prefix = _collection_prefix("test_usage")
    monkeypatch.setenv("METERING_FIRESTORE_ENABLED", "1")
    monkeypatch.setenv("METERING_FIRESTORE_COLLECTION", "usage_events")
    monkeypatch.setenv("METERING_COLLECTION_PREFIX", prefix)
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or "retikon-test"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_id)

    scope = TenantScope(org_id="org-1", site_id=None, stream_id=None)
    metering.record_usage(
        base_uri=tmp_path.as_posix(),
        event_type="query",
        scope=scope,
        api_key_id="key-1",
        modality="text",
        units=1,
        bytes_in=128,
        pipeline_version="v1",
        schema_version="1",
        response_time_ms=42,
    )

    client = firestore.Client(project=project_id)
    docs = list(client.collection(f"{prefix}usage_events").stream())
    assert len(docs) == 1
    payload = docs[0].to_dict()
    assert payload["org_id"] == "org-1"
    assert payload["request_type"] == "query"
    assert payload["response_time"] == 42
