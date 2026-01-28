from __future__ import annotations

import importlib
import os

import pytest


@pytest.mark.pro
def test_gpu_query_entrypoint_sets_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUERY_TIER_OVERRIDE", raising=False)
    monkeypatch.delenv("EMBEDDING_DEVICE", raising=False)
    module = importlib.import_module("gcp_adapter.query_service_gpu")
    importlib.reload(module)
    assert os.getenv("QUERY_TIER_OVERRIDE") == "gpu"
    assert os.getenv("EMBEDDING_DEVICE") == "cuda"
    assert hasattr(module, "app")
