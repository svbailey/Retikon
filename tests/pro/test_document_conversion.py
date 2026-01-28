from __future__ import annotations

import base64
import importlib

from fastapi.testclient import TestClient

from retikon_core.config import get_config


def test_document_conversion_stub(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.data_factory_service as service

    importlib.reload(service)

    client = TestClient(service.app)
    payload = {
        "filename": "example.doc",
        "content_base64": base64.b64encode(b"test").decode("utf-8"),
    }
    resp = client.post("/data-factory/convert-office", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stub"
    assert data["output_filename"].endswith(".pdf")
