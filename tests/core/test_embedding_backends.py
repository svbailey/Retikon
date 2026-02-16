from __future__ import annotations

import math

import pytest

from retikon_core.embeddings import (
    StubTextEmbedder,
    get_embedding_artifact,
    get_embedding_backend,
    get_runtime_embedding_backend,
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
    assert get_runtime_embedding_backend("text") == "stub"
    assert get_embedding_artifact("text") == "stub:deterministic"


@pytest.mark.core
def test_stub_vectors_are_l2_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset(monkeypatch)
    embedder = get_text_embedder(8)
    vector = embedder.encode(["retikon"])[0]
    norm = math.sqrt(sum(value * value for value in vector))
    assert norm == pytest.approx(1.0, rel=1e-6, abs=1e-6)
