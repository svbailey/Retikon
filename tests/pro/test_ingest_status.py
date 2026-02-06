from fastapi.testclient import TestClient

import gcp_adapter.ingestion_service as service


def test_ingest_status_returns_firestore(monkeypatch, jwt_headers):
    class DummyBlob:
        def __init__(self, exists: bool = True):
            self._exists = exists
            self.generation = 1

        def exists(self) -> bool:
            return self._exists

        def reload(self) -> None:
            return None

    class DummyBucket:
        def blob(self, name: str) -> DummyBlob:
            return DummyBlob()

    class DummyStorage:
        def bucket(self, name: str) -> DummyBucket:
            return DummyBucket()

    class DummyDoc:
        def __init__(self, data: dict):
            self._data = data
            self.exists = True

        def to_dict(self) -> dict:
            return self._data

    class DummyDocRef:
        def __init__(self, data: dict):
            self._data = data

        def get(self) -> DummyDoc:
            return DummyDoc(self._data)

    class DummyCollection:
        def __init__(self, data: dict):
            self._data = data

        def document(self, doc_id: str) -> DummyDocRef:
            return DummyDocRef(self._data)

    class DummyFirestore:
        def __init__(self, data: dict):
            self._data = data

        def collection(self, name: str) -> DummyCollection:
            return DummyCollection(self._data)

    firestore_payload = {"status": "COMPLETED", "manifest_uri": "gs://demo/manifest.json"}
    monkeypatch.setattr(service, "_storage_client", lambda: DummyStorage())
    monkeypatch.setattr(service, "_firestore_client", lambda: DummyFirestore(firestore_payload))

    client = TestClient(service.app, headers=jwt_headers)
    resp = client.get(
        "/ingest/status",
        params={"uri": "gs://test-raw/raw/videos/sample.mp4"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["firestore"]["manifest_uri"] == "gs://demo/manifest.json"
