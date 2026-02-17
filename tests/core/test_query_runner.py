import base64
import os
from pathlib import Path

import pytest

from retikon_core.query_engine import query_runner
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


def test_id_like_query_heuristic_avoids_plain_text():
    assert query_runner._is_id_like_query("INV-2026-001") is True
    assert query_runner._is_id_like_query("error code 500") is False
    assert query_runner._is_id_like_query("video query") is False


def test_search_by_text_merges_fts_hits_for_id_like_query(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_query_rows(_conn, sql, _params):
        if "fts_main_doc_chunks.match_bm25" in sql:
            return [
                (
                    "gs://raw/images/id.jpg",
                    "image",
                    "asset-1",
                    "INV-2026-001",
                    "chunk-1",
                    "image",
                    None,
                    2.5,
                )
            ]
        if "FROM doc_chunks d" in sql:
            return []
        if "FROM transcripts t" in sql:
            return []
        if "FROM image_assets i" in sql:
            return []
        if "FROM audio_clips a" in sql:
            return []
        return []

    monkeypatch.setattr(query_runner, "_connect", lambda *_args, **_kwargs: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_text_vector", lambda _text: [0.0])
    monkeypatch.setattr(query_runner, "_fts_enabled", lambda: True)

    results = search_by_text(
        snapshot_path="/tmp/retikon-sprint2-test.duckdb",
        query_text="INV-2026-001",
        top_k=5,
        modalities=["document"],
    )

    assert len(results) == 1
    assert results[0].modality == "ocr"
    assert results[0].why
    assert results[0].why[0]["reason"] == "fts_hit"


def test_search_by_text_audio_segments_merge_adjacent_hits(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_has_column(_conn, table, column):
        if table == "audio_segments" and column in {
            "clap_embedding",
            "id",
            "start_ms",
            "end_ms",
        }:
            return True
        return False

    def fake_query_rows(_conn, sql, _params):
        if "FROM audio_segments a" in sql:
            return [
                ("gs://raw/a.wav", "audio", "asset-a", 0, 5000, "seg-a-1", 0.2),
                ("gs://raw/a.wav", "audio", "asset-a", 5000, 10000, "seg-a-2", 0.21),
                ("gs://raw/b.wav", "audio", "asset-b", 0, 5000, "seg-b-1", 0.1),
            ]
        return []

    monkeypatch.setattr(query_runner, "_connect", lambda *_args, **_kwargs: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", fake_has_column)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_audio_text_vector", lambda _text: [0.0])
    monkeypatch.setenv("AUDIO_SEGMENT_MERGE_GAP_MS", "500")

    results = search_by_text(
        snapshot_path="/tmp/retikon-sprint3-test.duckdb",
        query_text="alarm sound",
        top_k=5,
        modalities=["audio"],
    )

    assert len(results) == 2
    merged = next(item for item in results if item.media_asset_id == "asset-a")
    assert merged.start_ms == 0
    assert merged.end_ms == 10000
    assert any(
        item.get("source") == "audio_segment_merge" for item in merged.why
    )


def test_search_by_text_audio_segments_not_dropped_when_filling_with_audio_clips(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_has_column(_conn, table, column):
        if table == "audio_segments" and column in {
            "clap_embedding",
            "id",
            "start_ms",
            "end_ms",
        }:
            return True
        if table == "audio_clips" and column in {"clap_embedding"}:
            return True
        return False

    def fake_query_rows(_conn, sql, _params):
        if "FROM audio_segments a" in sql:
            # Distance is intentionally high so score is low; this segment should still
            # be preserved when audio clips are used to fill top_k.
            return [("gs://raw/seg.wav", "audio", "asset-seg", 0, 5000, "seg-1", 0.9)]
        if "FROM audio_clips a" in sql:
            return [
                ("gs://raw/clip1.wav", "audio", "asset-1", None, None, "asset-1", 0.0),
                ("gs://raw/clip2.wav", "audio", "asset-2", None, None, "asset-2", 0.0),
                ("gs://raw/clip3.wav", "audio", "asset-3", None, None, "asset-3", 0.0),
                ("gs://raw/clip4.wav", "audio", "asset-4", None, None, "asset-4", 0.0),
                ("gs://raw/clip5.wav", "audio", "asset-5", None, None, "asset-5", 0.0),
            ]
        return []

    monkeypatch.setattr(query_runner, "_connect", lambda *_args, **_kwargs: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", fake_has_column)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_audio_text_vector", lambda _text: [0.0])

    results = search_by_text(
        snapshot_path="/tmp/retikon-sprint3-test.duckdb",
        query_text="alarm sound",
        top_k=5,
        modalities=["audio"],
    )

    assert len(results) == 5
    assert any(item.primary_evidence_id == "seg-1" for item in results)
    segment = next(item for item in results if item.primary_evidence_id == "seg-1")
    assert segment.start_ms == 0
    assert segment.end_ms == 5000


def test_search_by_text_audio_segments_fallback_to_audio_clips(monkeypatch):
    class DummyConn:
        def close(self) -> None:
            return None

    def fake_has_column(_conn, table, column):
        if table == "audio_segments" and column in {
            "clap_embedding",
            "id",
            "start_ms",
            "end_ms",
        }:
            return True
        if table == "audio_clips" and column in {"clap_embedding"}:
            return True
        return False

    def fake_query_rows(_conn, sql, _params):
        if "FROM audio_segments a" in sql:
            return []
        if "FROM audio_clips a" in sql:
            return [("gs://raw/legacy.wav", "audio", "asset-legacy", None, None, "clip-1", 0.2)]
        return []

    monkeypatch.setattr(query_runner, "_connect", lambda *_args, **_kwargs: DummyConn())
    monkeypatch.setattr(query_runner, "_table_has_column", fake_has_column)
    monkeypatch.setattr(query_runner, "_query_rows", fake_query_rows)
    monkeypatch.setattr(query_runner, "_cached_audio_text_vector", lambda _text: [0.0])

    trace: dict[str, float | int | str] = {}
    results = search_by_text(
        snapshot_path="/tmp/retikon-sprint3-test.duckdb",
        query_text="alarm sound",
        top_k=5,
        modalities=["audio"],
        trace=trace,
    )

    assert len(results) == 1
    assert results[0].media_asset_id == "asset-legacy"
    assert results[0].source_type == "audio"
    assert trace["audio_clip_fallback_rows"] == 1
