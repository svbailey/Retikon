import pytest

from retikon_core.config import get_config
from retikon_core.errors import PermanentError
from retikon_core.ingestion.storage_event import StorageEvent
from retikon_core.ingestion.router import (
    _check_size,
    _ensure_allowed,
    _modality_for_name,
)


def test_router_modality():
    assert _modality_for_name("raw/docs/sample.pdf") == "document"
    assert _modality_for_name("raw/images/sample.jpg") == "image"
    assert _modality_for_name("raw/audio/sample.mp3") == "audio"
    assert _modality_for_name("raw/videos/sample.mp4") == "video"


def test_allowlist_rejects_extension():
    config = get_config()
    event = StorageEvent(
        bucket="test",
        name="raw/docs/sample.exe",
        generation="1",
        content_type="application/octet-stream",
        size=10,
        md5_hash=None,
        crc32c=None,
    )
    with pytest.raises(PermanentError):
        _ensure_allowed(event, config, "document")


def test_allowlist_rejects_legacy_doc():
    config = get_config()
    event = StorageEvent(
        bucket="test",
        name="raw/docs/sample.doc",
        generation="1",
        content_type="application/msword",
        size=10,
        md5_hash=None,
        crc32c=None,
    )
    with pytest.raises(PermanentError):
        _ensure_allowed(event, config, "document")


def test_allowlist_rejects_legacy_ppt():
    config = get_config()
    event = StorageEvent(
        bucket="test",
        name="raw/docs/sample.ppt",
        generation="1",
        content_type="application/vnd.ms-powerpoint",
        size=10,
        md5_hash=None,
        crc32c=None,
    )
    with pytest.raises(PermanentError):
        _ensure_allowed(event, config, "document")


def test_content_type_mismatch_rejected():
    config = get_config()
    event = StorageEvent(
        bucket="test",
        name="raw/docs/sample.pdf",
        generation="1",
        content_type="image/jpeg",
        size=10,
        md5_hash=None,
        crc32c=None,
    )
    with pytest.raises(PermanentError):
        _ensure_allowed(event, config, "document")


def test_size_guard():
    config = get_config()
    event = StorageEvent(
        bucket="test",
        name="raw/docs/sample.pdf",
        generation="1",
        content_type="application/pdf",
        size=config.max_raw_bytes + 1,
        md5_hash=None,
        crc32c=None,
    )
    with pytest.raises(PermanentError):
        _check_size(event, config)
