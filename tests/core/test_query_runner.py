import base64
import os
from pathlib import Path

import pytest

from retikon_core.query_engine.query_runner import (
    QueryResult,
    fuse_results,
    rerank_text_candidates,
    search_by_image,
    search_by_keyword,
    search_by_metadata,
    search_by_text,
)
from retikon_core.errors import InferenceTimeoutError


def test_search_by_text_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_text(
        snapshot_path=snapshot_path,
        query_text="hello",
        top_k=3,
    )
    assert results


def test_search_by_image_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    payload = Path("tests/fixtures/sample.jpg").read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    data_url = f"data:image/jpeg;base64,{encoded}"
    results = search_by_image(
        snapshot_path=snapshot_path,
        image_base64=data_url,
        top_k=3,
    )
    assert results


def test_search_by_keyword_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_keyword(
        snapshot_path=snapshot_path,
        query_text="hello",
        top_k=3,
    )
    assert results


def test_search_by_metadata_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_metadata(
        snapshot_path=snapshot_path,
        filters={"media_type": "image"},
        top_k=3,
    )
    assert results


def test_fuse_results_weighted_rrf_merges_duplicate_evidence():
    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc",
            snippet="alpha",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.9,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        ),
        QueryResult(
            modality="document",
            uri="gs://doc",
            snippet="alpha",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.8,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        ),
    ]
    fused = fuse_results(rows)
    assert len(fused) == 1
    assert fused[0].score == pytest.approx(1.0)
    assert fused[0].why


def test_rerank_text_candidates_applies_scores(monkeypatch):
    class DummyReranker:
        def score(self, query, docs):
            assert query == "hello"
            return [0.9]

    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_MIN_CANDIDATES", "1")
    monkeypatch.setattr(
        "retikon_core.query_engine.query_runner.get_reranker",
        lambda: DummyReranker(),
    )

    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc",
            snippet="hello world",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.2,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        )
    ]
    ranked = rerank_text_candidates(query_text="hello", results=rows)
    assert ranked[0].score > 0.2
    assert any(item.get("source") == "rerank" for item in ranked[0].why)


def test_rerank_text_candidates_timeout_skips(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "1")

    def _timeout(kind, fn):
        raise InferenceTimeoutError("timed out")

    monkeypatch.setattr("retikon_core.query_engine.query_runner.run_inference", _timeout)
    monkeypatch.setattr(
        "retikon_core.query_engine.query_runner.get_reranker",
        lambda: object(),
    )
    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc",
            snippet="hello world",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.7,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        )
    ]
    ranked = rerank_text_candidates(query_text="hello", results=rows)
    assert ranked[0].score == pytest.approx(0.7)


def test_rerank_text_candidates_skips_for_small_candidate_set(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_MIN_CANDIDATES", "2")
    monkeypatch.setattr(
        "retikon_core.query_engine.query_runner.get_reranker",
        lambda: object(),
    )

    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc",
            snippet="hello world",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.55,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        )
    ]
    trace: dict[str, float | int | str] = {}
    ranked = rerank_text_candidates(query_text="hello", results=rows, trace=trace)
    assert ranked[0].score == pytest.approx(0.55)
    assert trace["rerank_status"] == "skipped_low_candidate_count"


def test_rerank_text_candidates_skips_when_top_hit_is_confident(monkeypatch):
    class DummyReranker:
        def score(self, query, docs):  # pragma: no cover - should not be called
            raise AssertionError("reranker should have been skipped")

    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_MIN_CANDIDATES", "2")
    monkeypatch.setenv("RERANK_SKIP_SCORE_GAP", "0.20")
    monkeypatch.setenv("RERANK_SKIP_MIN_SCORE", "0.70")
    monkeypatch.setattr(
        "retikon_core.query_engine.query_runner.get_reranker",
        lambda: DummyReranker(),
    )

    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc1",
            snippet="alpha candidate",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.91,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        ),
        QueryResult(
            modality="document",
            uri="gs://doc2",
            snippet="beta candidate",
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.55,
            media_asset_id="asset-2",
            media_type="document",
            primary_evidence_id="doc-2",
            evidence_refs=[{"doc_chunk_id": "doc-2"}],
        ),
    ]
    trace: dict[str, float | int | str] = {}
    ranked = rerank_text_candidates(query_text="hello", results=rows, trace=trace)
    assert ranked[0].score == pytest.approx(0.91)
    assert trace["rerank_status"] == "skipped_confident_top_result"


def test_rerank_text_candidates_respects_total_char_budget(monkeypatch):
    captured_docs: list[str] = []

    class DummyReranker:
        def score(self, query, docs):
            captured_docs.extend(docs)
            return [0.4 for _ in docs]

    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_MIN_CANDIDATES", "2")
    monkeypatch.setenv("RERANK_SKIP_SCORE_GAP", "10")
    monkeypatch.setenv("RERANK_MAX_TOTAL_CHARS", "30")
    monkeypatch.setattr(
        "retikon_core.query_engine.query_runner.get_reranker",
        lambda: DummyReranker(),
    )

    rows = [
        QueryResult(
            modality="document",
            uri="gs://doc1",
            snippet="a" * 20,
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.9,
            media_asset_id="asset-1",
            media_type="document",
            primary_evidence_id="doc-1",
            evidence_refs=[{"doc_chunk_id": "doc-1"}],
        ),
        QueryResult(
            modality="document",
            uri="gs://doc2",
            snippet="b" * 20,
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.8,
            media_asset_id="asset-2",
            media_type="document",
            primary_evidence_id="doc-2",
            evidence_refs=[{"doc_chunk_id": "doc-2"}],
        ),
        QueryResult(
            modality="document",
            uri="gs://doc3",
            snippet="c" * 20,
            start_ms=None,
            end_ms=None,
            thumbnail_uri=None,
            score=0.7,
            media_asset_id="asset-3",
            media_type="document",
            primary_evidence_id="doc-3",
            evidence_refs=[{"doc_chunk_id": "doc-3"}],
        ),
    ]

    rerank_text_candidates(query_text="hello", results=rows)
    assert len(captured_docs) == 2
