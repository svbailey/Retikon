from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertDestination:
    kind: str
    target: str
    attributes: dict[str, str] | None = None


@dataclass(frozen=True)
class AlertRule:
    id: str
    name: str
    event_types: tuple[str, ...] | None
    modalities: tuple[str, ...] | None
    min_confidence: float | None
    tags: tuple[str, ...] | None
    destinations: tuple[AlertDestination, ...]
    enabled: bool
    created_at: str
    updated_at: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class AlertMatch:
    rule_id: str
    event_id: str
    destinations: tuple[AlertDestination, ...]
