from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RoutingContext:
    has_text: bool = False
    has_image: bool = False
    has_audio: bool = False
    modalities: tuple[str, ...] | None = None
    search_type: str | None = None
    mode: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    tier: str
    reason: str
    target_url: str | None = None


def routing_mode() -> str:
    return os.getenv("QUERY_ROUTING_MODE", "cpu").strip().lower()


def default_query_tier() -> str:
    return os.getenv("QUERY_TIER_DEFAULT", "cpu").strip().lower()


def query_tier_override() -> str | None:
    override = os.getenv("QUERY_TIER_OVERRIDE")
    if override is None:
        return None
    cleaned = override.strip().lower()
    return cleaned or None


def select_query_tier(context: RoutingContext) -> RoutingDecision:
    override = query_tier_override()
    if override:
        return RoutingDecision(tier=override, reason="override")

    mode = routing_mode()
    if mode != "auto":
        return RoutingDecision(tier=default_query_tier(), reason="default")

    if _is_multimodal(context):
        return RoutingDecision(tier="gpu", reason="multimodal")

    return RoutingDecision(tier=default_query_tier(), reason="text-only")


def _is_multimodal(context: RoutingContext) -> bool:
    if context.has_image or context.has_audio:
        return True
    modalities = _normalize_modalities(context.modalities)
    if modalities and any(item in {"image", "audio"} for item in modalities):
        return True
    return False


def _normalize_modalities(values: Iterable[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None
    cleaned = [str(item).strip().lower() for item in values if str(item).strip()]
    return tuple(cleaned) if cleaned else None
