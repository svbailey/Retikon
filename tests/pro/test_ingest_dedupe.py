from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest

os.environ.setdefault("STREAM_INGEST_TOPIC", "projects/test/topics/stream")

from gcp_adapter import idempotency_firestore as idem
from gcp_adapter import ingestion_service as ingest
from gcp_adapter import stream_ingest_service as stream


class _QuerySnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data

    def to_dict(self) -> dict:
        return dict(self._data or {})


class _Query:
    def __init__(self, store: dict, field: str, value: object):
        self.store = store
        self.field = field
        self.value = value
        self._limit: int | None = None

    def limit(self, limit: int) -> "_Query":
        self._limit = limit
        return self

    def stream(self):
        count = 0
        for doc_id, data in self.store.items():
            if data.get(self.field) == self.value:
                yield _QuerySnapshot(doc_id, data)
                count += 1
                if self._limit is not None and count >= self._limit:
                    break


class _Document:
    def __init__(self, store: dict, doc_id: str):
        self.store = store
        self.doc_id = doc_id

    def update(self, data: dict) -> None:
        if self.doc_id not in self.store:
            raise RuntimeError("missing document")
        self.store[self.doc_id].update(data)


class _Collection:
    def __init__(self, store: dict):
        self.store = store

    def document(self, doc_id: str) -> _Document:
        return _Document(self.store, doc_id)

    def where(self, field: str, _op: str, value: object) -> _Query:
        return _Query(self.store, field, value)


class _Client:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, _name: str) -> _Collection:
        return _Collection(self.store)


@pytest.mark.parametrize(
    "dedupe_func",
    [ingest._apply_checksum_dedupe, stream._apply_checksum_dedupe],
)
def test_checksum_dedupe_updates_signature_metadata(dedupe_func):
    client = _Client()
    scope_key = idem.resolve_scope_key("org", "site", "stream")
    checksum = "md5:abc"
    checksum_scope = idem.resolve_checksum_scope(checksum, scope_key)
    client.store["existing"] = {
        "status": "COMPLETED",
        "checksum_scope": checksum_scope,
        "scope_key": scope_key,
        "object_checksum": checksum,
        "object_size_bytes": 42,
        "object_content_type": "video/mp4",
        "object_duration_ms": 1200,
        "manifest_uri": "gs://example/manifest.json",
        "media_asset_id": "media-1",
        "metrics": {"stage_timings_ms": {"decode_ms": 1.0}, "pipe_ms": 1.0},
    }
    client.store["new"] = {
        "status": "PROCESSING",
        "updated_at": datetime.now(timezone.utc),
    }

    result = dedupe_func(
        client=client,
        collection="events",
        doc_id="new",
        bucket="raw-bucket",
        name="raw/other.mp4",
        scope_key=scope_key,
        checksum=checksum,
        size_bytes=42,
        content_type="video/mp4",
        duration_ms=None,
    )

    assert result is True
    updated = client.store["new"]
    assert updated["status"] == "COMPLETED"
    assert updated["dedupe_source_doc_id"] == "existing"
    assert updated["object_size_bytes"] == 42
    assert updated["object_content_type"] == "video/mp4"
    assert updated["object_duration_ms"] == 1200
