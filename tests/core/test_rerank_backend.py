from retikon_core.embeddings.rerank_backend import (
    StubReranker,
    get_reranker,
    normalize_rerank_scores,
    reset_reranker_cache,
)


def test_stub_reranker_prefers_overlap():
    reranker = StubReranker()
    scores = reranker.score("alarm sound", ["alarm alarm", "cat photo"])
    assert scores[0] > scores[1]


def test_get_reranker_uses_stub_without_real_models(monkeypatch):
    monkeypatch.setenv("USE_REAL_MODELS", "0")
    monkeypatch.setenv("RERANK_BACKEND", "hf")
    reset_reranker_cache()
    reranker = get_reranker()
    assert reranker.backend == "stub"


def test_normalize_rerank_scores_handles_logits():
    normalized = normalize_rerank_scores([-2.0, 0.0, 2.0])
    assert normalized[0] < normalized[1] < normalized[2]
    assert all(0.0 <= value <= 1.0 for value in normalized)
