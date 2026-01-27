from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebhookRegistration:
    id: str
    name: str
    url: str
    secret: str | None
    event_types: tuple[str, ...] | None
    enabled: bool
    created_at: str
    updated_at: str
    headers: dict[str, str] | None = None
    timeout_s: float | None = None


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]
    modality: str | None = None
    confidence: float | None = None
    tags: tuple[str, ...] | None = None
    source: str | None = None


def event_to_dict(event: WebhookEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "type": event.event_type,
        "created_at": event.created_at,
        "modality": event.modality,
        "confidence": event.confidence,
        "tags": list(event.tags) if event.tags else None,
        "source": event.source,
        "payload": event.payload,
    }
