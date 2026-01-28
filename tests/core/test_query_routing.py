from __future__ import annotations

import pytest

from retikon_core.query_engine import RoutingContext, select_query_tier


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUERY_ROUTING_MODE", raising=False)
    monkeypatch.delenv("QUERY_TIER_DEFAULT", raising=False)
    monkeypatch.delenv("QUERY_TIER_OVERRIDE", raising=False)


@pytest.mark.core
def test_default_routing_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    decision = select_query_tier(RoutingContext(has_text=True))
    assert decision.tier == "cpu"
    assert decision.reason == "default"


@pytest.mark.core
def test_auto_routes_multimodal_to_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("QUERY_ROUTING_MODE", "auto")
    decision = select_query_tier(
        RoutingContext(has_text=True, has_image=True, modalities=("image",))
    )
    assert decision.tier == "gpu"
    assert decision.reason == "multimodal"


@pytest.mark.core
def test_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("QUERY_TIER_OVERRIDE", "gpu")
    decision = select_query_tier(RoutingContext(has_text=True))
    assert decision.tier == "gpu"
    assert decision.reason == "override"
