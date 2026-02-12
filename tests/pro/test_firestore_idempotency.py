from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gcp_adapter import idempotency_firestore as idem


class _Snapshot:
    def __init__(self, data: dict | None):
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return dict(self._data or {})


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

    def get(self, transaction=None):
        return _Snapshot(self.store.get(self.doc_id))

    def update(self, data: dict) -> None:
        if self.doc_id not in self.store:
            raise RuntimeError("missing document")
        self.store[self.doc_id].update(data)

    def create(self, data: dict) -> None:
        if self.doc_id in self.store:
            raise RuntimeError("document exists")
        self.store[self.doc_id] = dict(data)


class _Collection:
    def __init__(self, store: dict):
        self.store = store

    def document(self, doc_id: str) -> _Document:
        return _Document(self.store, doc_id)

    def where(self, field: str, _op: str, value: object) -> _Query:
        return _Query(self.store, field, value)


class _Transaction:
    def __init__(self, store: dict):
        self.store = store

    def update(self, doc: _Document, data: dict) -> None:
        doc.update(data)

    def create(self, doc: _Document, data: dict) -> None:
        doc.create(data)


class _Client:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, _name: str) -> _Collection:
        return _Collection(self.store)

    def transaction(self) -> _Transaction:
        return _Transaction(self.store)


def _identity_transactional(func):
    def wrapper(transaction):
        return func(transaction)

    return wrapper


def test_firestore_idempotency_flow(monkeypatch):
    monkeypatch.setattr(idem.firestore, "transactional", _identity_transactional)

    client = _Client()
    store = idem.FirestoreIdempotency(
        client=client,
        collection="events",
        processing_ttl=timedelta(seconds=60),
        completed_ttl=timedelta(seconds=0),
    )

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 1

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "skip_processing"

    store.mark_completed(decision.doc_id)
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "skip_completed"


def test_firestore_idempotency_reprocess(monkeypatch):
    monkeypatch.setattr(idem.firestore, "transactional", _identity_transactional)

    client = _Client()
    store = idem.FirestoreIdempotency(
        client=client,
        collection="events",
        processing_ttl=timedelta(seconds=60),
        completed_ttl=timedelta(seconds=0),
    )

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v3.0",
    )
    store.mark_failed(decision.doc_id, "PERMANENT", "oops")

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 2


def test_firestore_idempotency_skip_processing_window(monkeypatch):
    monkeypatch.setattr(idem.firestore, "transactional", _identity_transactional)

    client = _Client()
    store = idem.FirestoreIdempotency(
        client=client,
        collection="events",
        processing_ttl=timedelta(seconds=60),
        completed_ttl=timedelta(seconds=0),
    )

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="3",
        size=123,
        pipeline_version="v3.0",
    )
    doc = client.store[decision.doc_id]
    doc["status"] = "PROCESSING"
    doc["updated_at"] = datetime.now(timezone.utc)

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="3",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "skip_processing"


def test_resolve_scope_key_checksum_scope():
    scope_key = idem.resolve_scope_key("org", "site", "stream")
    assert scope_key == "org:site:stream"
    assert idem.resolve_scope_key(None, None, None) == "-:-:-"
    assert (
        idem.resolve_checksum_scope("md5:abc", scope_key)
        == "org:site:stream:md5:abc"
    )
    assert (
        idem.resolve_content_hash_scope("sha256:abc", scope_key)
        == "org:site:stream:sha256:abc"
    )


def test_find_completed_by_checksum_scope_key():
    client = _Client()
    scope_key = idem.resolve_scope_key("org", "site", "stream")
    checksum = "md5:abc"
    checksum_scope = idem.resolve_checksum_scope(checksum, scope_key)
    client.store["doc-1"] = {
        "status": "COMPLETED",
        "checksum_scope": checksum_scope,
        "scope_key": scope_key,
        "manifest_uri": "gs://example/manifest.json",
    }
    result = idem.find_completed_by_checksum(
        client=client,
        collection="events",
        checksum=checksum,
        scope_key=scope_key,
    )
    assert result is not None
    assert result["doc_id"] == "doc-1"


def test_find_completed_by_checksum_signature_filters():
    client = _Client()
    checksum = "md5:abc"
    client.store["doc-1"] = {
        "status": "COMPLETED",
        "object_checksum": checksum,
        "object_size_bytes": 42,
        "object_content_type": "video/mp4",
        "object_duration_ms": 1200,
    }

    match = idem.find_completed_by_checksum(
        client=client,
        collection="events",
        checksum=checksum,
        size_bytes=42,
        content_type="video/mp4",
        duration_ms=1200,
    )
    assert match is not None
    assert match["doc_id"] == "doc-1"

    mismatch = idem.find_completed_by_checksum(
        client=client,
        collection="events",
        checksum=checksum,
        size_bytes=7,
        content_type="video/mp4",
    )
    assert mismatch is None


def test_find_completed_by_content_hash_scope_key():
    client = _Client()
    scope_key = idem.resolve_scope_key("org", "site", "stream")
    content_hash = "sha256:abc"
    content_scope = idem.resolve_content_hash_scope(content_hash, scope_key)
    client.store["doc-1"] = {
        "status": "COMPLETED",
        "content_hash_scope": content_scope,
        "content_hash_sha256": content_hash,
        "scope_key": scope_key,
        "manifest_uri": "gs://example/manifest.json",
        "pipeline_version": "v1",
    }
    result = idem.find_completed_by_content_hash(
        client=client,
        collection="events",
        content_hash=content_hash,
        scope_key=scope_key,
        pipeline_version="v1",
    )
    assert result is not None
    assert result["doc_id"] == "doc-1"


def test_find_completed_by_content_hash_filters():
    client = _Client()
    content_hash = "sha256:abc"
    client.store["doc-1"] = {
        "status": "COMPLETED",
        "content_hash_sha256": content_hash,
        "object_size_bytes": 42,
        "object_content_type": "video/mp4",
        "object_duration_ms": 1200,
        "pipeline_version": "v2",
    }

    match = idem.find_completed_by_content_hash(
        client=client,
        collection="events",
        content_hash=content_hash,
        size_bytes=42,
        content_type="video/mp4",
        duration_ms=1200,
        pipeline_version="v2",
    )
    assert match is not None
    assert match["doc_id"] == "doc-1"

    mismatch = idem.find_completed_by_content_hash(
        client=client,
        collection="events",
        content_hash=content_hash,
        size_bytes=7,
        content_type="video/mp4",
        pipeline_version="v2",
    )
    assert mismatch is None
