from __future__ import annotations

import pytest

from retikon_core.connectors.ocr import load_ocr_connectors, register_ocr_connector


def test_register_and_load_ocr_connector(tmp_path):
    base_uri = tmp_path.as_posix()
    connector = register_ocr_connector(
        base_uri=base_uri,
        name="OCR Primary",
        url="https://ocr.example.com/v1/extract",
        auth_type="bearer",
        token_env="OCR_TOKEN",
        enabled=True,
        is_default=True,
        max_pages=5,
        timeout_s=12.5,
    )
    loaded = load_ocr_connectors(base_uri)
    assert len(loaded) == 1
    assert loaded[0].id == connector.id
    assert loaded[0].is_default is True


def test_ocr_connector_validation(tmp_path):
    base_uri = tmp_path.as_posix()
    with pytest.raises(ValueError):
        register_ocr_connector(
            base_uri=base_uri,
            name="Bad URL",
            url="ftp://example.com",
        )
    with pytest.raises(ValueError):
        register_ocr_connector(
            base_uri=base_uri,
            name="Missing Header",
            url="https://ocr.example.com/v1/extract",
            auth_type="header",
            token_env="OCR_TOKEN",
        )
    with pytest.raises(ValueError):
        register_ocr_connector(
            base_uri=base_uri,
            name="Missing Token",
            url="https://ocr.example.com/v1/extract",
            auth_type="bearer",
        )
