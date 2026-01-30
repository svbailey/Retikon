from __future__ import annotations

import base64
import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def _load_service(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.data_factory_service as service

    importlib.reload(service)
    return service


def test_document_conversion_inline(monkeypatch, tmp_path, jwt_headers):
    monkeypatch.setenv("OFFICE_CONVERSION_BACKEND", "stub")
    monkeypatch.setenv("OFFICE_CONVERSION_MODE", "inline")
    service = _load_service(monkeypatch, tmp_path)

    client = TestClient(service.app, headers=jwt_headers)
    payload = {
        "filename": "example.doc",
        "content_base64": base64.b64encode(b"test").decode("utf-8"),
    }
    resp = client.post("/data-factory/convert-office", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["output_filename"].endswith(".pdf")
    assert data["content_base64"]
    assert data["job_id"]
    assert data["output_uri"]
    decoded = base64.b64decode(data["content_base64"].encode("utf-8"))
    assert decoded.startswith(b"%PDF-1.4")

    resp = client.get(f"/data-factory/convert-office/{data['job_id']}")
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "completed"
    assert Path(job["output_uri"]).exists()


def test_document_conversion_queue_worker_and_dlq(monkeypatch, tmp_path, jwt_headers):
    published = []

    class FakePublisher:
        def publish_json(self, *, topic, payload, attributes=None):
            published.append({"topic": topic, "payload": payload})
            return "msg-1"

    monkeypatch.setenv("OFFICE_CONVERSION_BACKEND", "stub")
    monkeypatch.setenv("OFFICE_CONVERSION_MODE", "queue")
    monkeypatch.setenv("OFFICE_CONVERSION_TOPIC", "projects/dev/topics/office")
    monkeypatch.setenv("OFFICE_CONVERSION_DLQ_TOPIC", "projects/dev/topics/dlq")
    service = _load_service(monkeypatch, tmp_path)
    import gcp_adapter.office_conversion as office_conversion

    monkeypatch.setattr(office_conversion, "PubSubPublisher", FakePublisher)

    client = TestClient(service.app, headers=jwt_headers)
    payload = {
        "filename": "example.ppt",
        "content_base64": base64.b64encode(b"test").decode("utf-8"),
    }
    resp = client.post("/data-factory/convert-office", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["job_id"]
    assert published and published[0]["topic"].endswith("office")

    published.clear()
    job_payload = {
        "job_id": data["job_id"],
        "filename": payload["filename"],
        "content_base64": payload["content_base64"],
    }
    body = {
        "message": {
            "data": base64.b64encode(json.dumps(job_payload).encode("utf-8")).decode(
                "utf-8"
            ),
            "attributes": {},
        }
    }
    resp = client.post("/data-factory/convert-office/worker", json=body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    resp = client.get(f"/data-factory/convert-office/{data['job_id']}")
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "completed"
    assert Path(job["output_uri"]).exists()

    published.clear()
    bad_payload = {
        "job_id": data["job_id"],
        "filename": payload["filename"],
        "content_base64": "not-base64",
    }
    bad_body = {
        "message": {
            "data": base64.b64encode(
                json.dumps(bad_payload).encode("utf-8")
            ).decode("utf-8"),
            "attributes": {},
        }
    }
    resp = client.post("/data-factory/convert-office/worker", json=bad_body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "dlq"
    assert published and published[0]["topic"].endswith("dlq")
