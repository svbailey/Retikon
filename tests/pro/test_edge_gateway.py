from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _make_client(tmp_path, monkeypatch, force_buffer: bool, jwt_headers):
    raw_dir = tmp_path / "raw"
    buffer_dir = tmp_path / "buffer"
    monkeypatch.setenv("EDGE_RAW_URI", raw_dir.as_posix())
    monkeypatch.setenv("EDGE_BUFFER_DIR", buffer_dir.as_posix())
    monkeypatch.setenv("EDGE_FORCE_BUFFER", "1" if force_buffer else "0")

    import gcp_adapter.edge_gateway_service as service

    importlib.reload(service)
    return TestClient(service.app, headers=jwt_headers), service, raw_dir


def test_edge_gateway_upload_writes_file(tmp_path, monkeypatch, jwt_headers):
    client, _service, raw_dir = _make_client(
        tmp_path, monkeypatch, force_buffer=False, jwt_headers=jwt_headers
    )

    resp = client.post(
        "/edge/upload",
        files={"file": ("sample.csv", b"id,name\n1,Retikon\n", "text/csv")},
        data={"modality": "document", "device_id": "edge-1"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "stored"
    uri = payload["uri"]
    assert uri
    assert Path(uri).exists()


def test_edge_gateway_buffer_and_replay(tmp_path, monkeypatch, jwt_headers):
    client, service, raw_dir = _make_client(
        tmp_path, monkeypatch, force_buffer=True, jwt_headers=jwt_headers
    )

    resp = client.post(
        "/edge/upload",
        files={"file": ("sample.csv", b"id,name\n2,Buffer\n", "text/csv")},
        data={"modality": "document", "device_id": "edge-2"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "buffered"

    status = client.get("/edge/buffer/status")
    assert status.status_code == 200
    assert status.json()["count"] == 1

    monkeypatch.setenv("EDGE_FORCE_BUFFER", "0")
    replay = client.post("/edge/buffer/replay")
    assert replay.status_code == 200
    assert replay.json()["success"] == 1

    status = client.get("/edge/buffer/status")
    assert status.json()["count"] == 0
    assert raw_dir.exists()
