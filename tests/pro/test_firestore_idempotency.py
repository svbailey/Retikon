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
