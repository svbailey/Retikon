import pytest

from retikon_core.services.query_service_core import (
    QueryRequest,
    QueryValidationError,
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
