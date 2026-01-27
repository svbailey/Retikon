import json
import logging

import pytest

from retikon_core.capabilities import (
    CORE_CAPABILITIES,
    EDITION_CORE,
    EDITION_PRO,
    get_edition,
    resolve_capabilities,
)
from retikon_core.logging import JsonFormatter


def test_default_edition_is_core(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETIKON_EDITION", raising=False)
    monkeypatch.delenv("RETIKON_CAPABILITIES", raising=False)
    assert get_edition() == EDITION_CORE
    assert resolve_capabilities() == CORE_CAPABILITIES


def test_pro_edition_sets_pro_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETIKON_EDITION", EDITION_PRO)
    monkeypatch.delenv("RETIKON_CAPABILITIES", raising=False)
    caps = resolve_capabilities()
    assert "compaction" in caps
    assert "query" in caps


def test_capability_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETIKON_CAPABILITIES", "query,ingestion")
    caps = resolve_capabilities()
    assert caps == ("ingestion", "query")


def test_invalid_capability_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETIKON_CAPABILITIES", "not-a-capability")
    with pytest.raises(ValueError):
        resolve_capabilities()


def test_json_formatter_includes_capabilities() -> None:
    record = logging.LogRecord(
        name="retikon.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.edition = EDITION_CORE
    record.capabilities = ["query", "ingestion"]
    payload = json.loads(JsonFormatter().format(record))
    assert payload["edition"] == EDITION_CORE
    assert payload["capabilities"] == ["query", "ingestion"]
