from __future__ import annotations

import pytest

from retikon_core.embeddings import (
    StubTextEmbedder,
    get_embedding_backend,
    get_text_embedder,
    reset_embedding_cache,
)


def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("RETIKON_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("USE_REAL_MODELS", raising=False)
    reset_embedding_cache()


@pytest.mark.core
def test_default_backend_is_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset(monkeypatch)
    assert get_embedding_backend() == "stub"
    embedder = get_text_embedder(4)
    assert isinstance(embedder, StubTextEmbedder)


@pytest.mark.core
def test_backend_override_to_onnx_uses_stub_when_models_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("EMBEDDING_BACKEND", "onnx")
    embedder = get_text_embedder(4)
    assert isinstance(embedder, StubTextEmbedder)
