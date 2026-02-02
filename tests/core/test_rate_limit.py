import pytest

from retikon_core.ingestion.rate_limit import (
    RateLimitBackendError,
    RateLimitExceeded,
    enforce_rate_limit,
    reset_rate_limit_state,
)
from retikon_core.tenancy.types import TenantScope


def test_local_rate_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_rate_limit_state()
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "local")
    monkeypatch.setenv("RATE_LIMIT_DOC_PER_MIN", "1")
    scope = TenantScope(org_id="org-1")
    enforce_rate_limit("document", config=None, scope=scope)
    with pytest.raises(RateLimitExceeded):
        enforce_rate_limit("document", config=None, scope=scope)


def test_rate_limit_backend_none(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_rate_limit_state()
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "none")
    enforce_rate_limit("document", config=None, scope=TenantScope(org_id="org-1"))


def test_redis_backend_requires_host(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_rate_limit_state()
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_HOST", raising=False)
    with pytest.raises(RateLimitBackendError):
        enforce_rate_limit("document", config=None, scope=TenantScope(org_id="org-1"))
