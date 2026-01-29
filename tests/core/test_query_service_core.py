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
