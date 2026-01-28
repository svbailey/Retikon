from __future__ import annotations

import pytest

from retikon_core.connectors import list_connectors


@pytest.mark.core
def test_connectors_filter_by_edition():
    core = list_connectors(edition="core")
    assert core
    ids = {item.id for item in core}
    assert "http_webhook" in ids


@pytest.mark.core
def test_connectors_filter_by_streaming():
    streaming = list_connectors(streaming=True)
    assert all(item.streaming for item in streaming)
