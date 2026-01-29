from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

MEDIA_MODALITIES = ("image", "video", "audio")

IMAGE_REDACTION_TYPES = ("face", "plate", "logo", "text")
VIDEO_REDACTION_TYPES = ("face", "plate", "logo", "text")
AUDIO_REDACTION_TYPES = ("voice", "audio_pii")

_TYPE_GROUPS = {
    "pii": ("face", "plate", "voice", "audio_pii"),
    "all": (
        "face",
        "plate",
        "logo",
        "text",
        "voice",
        "audio_pii",
    ),
}


@dataclass(frozen=True)
class RedactionRegion:
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True)
class RedactionOperation:
    kind: str
    target: str
    region: RedactionRegion | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class RedactionPlan:
    modality: str
    requested_types: tuple[str, ...]
    resolved_types: tuple[str, ...]
    applied: bool
    operations: tuple[RedactionOperation, ...]
    reason: str | None = None


def media_redaction_enabled() -> bool:
    return os.getenv("MEDIA_REDACTION_ENABLED", "0") == "1"


def resolve_media_types(
    modality: str,
    redaction_types: Iterable[str] | None,
) -> tuple[str, ...]:
    requested = _normalize_types(redaction_types)
    supported = _supported_types(modality)
    resolved: list[str] = []
    for item in requested:
        expanded = _TYPE_GROUPS.get(item, (item,))
        for entry in expanded:
            if entry in supported and entry not in resolved:
                resolved.append(entry)
    return tuple(resolved)


def plan_media_redaction(
    *,
    modality: str,
    redaction_types: Iterable[str] | None,
    enabled: bool | None = None,
) -> RedactionPlan:
    normalized_modality = modality.strip().lower()
    requested = _normalize_types(redaction_types)
    resolved = resolve_media_types(normalized_modality, redaction_types)
    is_enabled = media_redaction_enabled() if enabled is None else enabled
    if normalized_modality not in MEDIA_MODALITIES:
        return RedactionPlan(
            modality=normalized_modality,
            requested_types=requested,
            resolved_types=resolved,
            applied=False,
            operations=(),
            reason="unsupported_modality",
        )
    if not is_enabled:
        return RedactionPlan(
            modality=normalized_modality,
            requested_types=requested,
            resolved_types=resolved,
            applied=False,
            operations=(),
            reason="disabled",
        )
    if not resolved:
        return RedactionPlan(
            modality=normalized_modality,
            requested_types=requested,
            resolved_types=resolved,
            applied=False,
            operations=(),
            reason="no_types",
        )
    return RedactionPlan(
        modality=normalized_modality,
        requested_types=requested,
        resolved_types=resolved,
        applied=False,
        operations=(),
        reason="stub",
    )


def redact_media_payload(
    payload: bytes | None,
    *,
    modality: str,
    redaction_types: Iterable[str] | None,
    enabled: bool | None = None,
) -> tuple[bytes | None, RedactionPlan]:
    plan = plan_media_redaction(
        modality=modality,
        redaction_types=redaction_types,
        enabled=enabled,
    )
    return payload, plan


def _supported_types(modality: str) -> tuple[str, ...]:
    if modality == "image":
        return IMAGE_REDACTION_TYPES
    if modality == "video":
        return VIDEO_REDACTION_TYPES
    if modality == "audio":
        return AUDIO_REDACTION_TYPES
    return ()


def _normalize_types(values: Iterable[str] | None) -> tuple[str, ...]:
    if not values:
        return ("pii",)
    cleaned = [str(value).strip().lower() for value in values]
    cleaned = [value for value in cleaned if value]
    return tuple(cleaned) if cleaned else ("pii",)
