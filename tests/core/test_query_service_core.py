import pytest

from retikon_core.query_engine.query_runner import QueryResult
from retikon_core.services.query_service_core import (
    QueryRequest,
    QueryValidationError,
    apply_filters,
    resolve_modalities,
    resolve_search_type,
    validate_query_payload,
)


def test_resolve_modalities_from_mode():
    payload = QueryRequest(mode="text")
    assert resolve_modalities(payload) == {"document", "transcript"}


def test_resolve_modalities_rejects_unknown():
    payload = QueryRequest(modalities=["document", "unknown"])
    with pytest.raises(QueryValidationError) as exc:
        resolve_modalities(payload)
    assert exc.value.status_code == 400


def test_resolve_modalities_modalities_override_mode():
    payload = QueryRequest(mode="text", modalities=["vision"])
    assert resolve_modalities(payload) == {"image"}


def test_resolve_modalities_from_env(monkeypatch):
    monkeypatch.setenv("QUERY_DEFAULT_MODALITIES", "image,audio")
    payload = QueryRequest()
    assert resolve_modalities(payload) == {"image", "audio"}


def test_resolve_search_type_rejects_unknown():
    payload = QueryRequest(search_type="weird")
    with pytest.raises(QueryValidationError) as exc:
        resolve_search_type(payload)
    assert exc.value.status_code == 400


def test_validate_query_payload_image_size():
    payload = QueryRequest(image_base64="x" * 10)
    with pytest.raises(QueryValidationError) as exc:
        validate_query_payload(
            payload=payload,
            search_type="vector",
            modalities={"image"},
            max_image_base64_bytes=1,
        )
    assert exc.value.status_code == 413


def test_validate_query_payload_page_limit_must_be_lte_top_k():
    payload = QueryRequest(query_text="hello", top_k=5, page_limit=6)
    with pytest.raises(QueryValidationError):
        validate_query_payload(
            payload=payload,
            search_type="vector",
            modalities={"document", "transcript"},
            max_image_base64_bytes=1024,
        )


def test_validate_query_payload_filter_validation():
    payload = QueryRequest(
        query_text="hello",
        filters={"field": "asset_id", "op": "bad_op", "value": "x"},
    )
    with pytest.raises(QueryValidationError):
        validate_query_payload(
            payload=payload,
            search_type="vector",
            modalities={"document", "transcript"},
            max_image_base64_bytes=1024,
        )


def test_apply_filters_supports_source_type_asset_id_and_time_range():
    rows = [
        QueryResult(
            modality="ocr",
            uri="gs://raw/video.mp4",
            snippet="BAY-12",
            start_ms=1200,
            end_ms=1200,
            thumbnail_uri=None,
            score=0.9,
            media_asset_id="asset-1",
            media_type="video",
            primary_evidence_id="chunk-1",
            source_type="keyframe",
            evidence_refs=[{"doc_chunk_id": "chunk-1"}],
        ),
        QueryResult(
            modality="ocr",
            uri="gs://raw/video.mp4",
            snippet="other",
            start_ms=8000,
            end_ms=8000,
            thumbnail_uri=None,
            score=0.8,
            media_asset_id="asset-2",
            media_type="video",
            primary_evidence_id="chunk-2",
            source_type="keyframe",
            evidence_refs=[{"doc_chunk_id": "chunk-2"}],
        ),
    ]
    filters = {
        "all": [
            {"field": "asset_type", "op": "eq", "value": "video"},
            {"field": "source_type", "op": "eq", "value": "keyframe"},
            {"field": "asset_id", "op": "eq", "value": "asset-1"},
            {"field": "start_ms", "op": "between", "value": [1000, 2000]},
        ]
    }
    filtered = apply_filters(results=rows, filters=filters)
    assert len(filtered) == 1
    assert filtered[0].media_asset_id == "asset-1"
