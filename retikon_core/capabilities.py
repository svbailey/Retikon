from __future__ import annotations

import os
from typing import Iterable

EDITION_CORE = "core"
EDITION_PRO = "pro"

CORE_CAPABILITIES: tuple[str, ...] = (
    "ingestion",
    "pipelines",
    "query",
    "graphar",
    "sdk",
    "cli",
    "console",
    "local_runtime",
    "webhooks_basic",
)

PRO_CAPABILITIES: tuple[str, ...] = CORE_CAPABILITIES + (
    "streaming_ingest",
    "queue_dispatch",
    "compaction",
    "retention",
    "event_state",
    "webhooks_advanced",
    "multi_tenant",
    "metering",
    "fleet_ops",
    "observability",
    "data_factory",
    "governance",
)

_CAPABILITY_ORDER: tuple[str, ...] = (
    "ingestion",
    "pipelines",
    "query",
    "graphar",
    "sdk",
    "cli",
    "console",
    "local_runtime",
    "webhooks_basic",
    "streaming_ingest",
    "queue_dispatch",
    "compaction",
    "retention",
    "event_state",
    "webhooks_advanced",
    "multi_tenant",
    "metering",
    "fleet_ops",
    "observability",
    "data_factory",
    "governance",
)

_KNOWN_CAPABILITIES = set(_CAPABILITY_ORDER)


def _parse_list(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    items = [item.strip().lower() for item in raw.split(",")]
    cleaned = [item for item in items if item]
    if not cleaned:
        return None
    return tuple(cleaned)


def _validate_capabilities(capabilities: Iterable[str]) -> tuple[str, ...]:
    seen = []
    for item in capabilities:
        if item not in _KNOWN_CAPABILITIES:
            raise ValueError(f"Unknown capability: {item}")
        if item not in seen:
            seen.append(item)
    ordered = [cap for cap in _CAPABILITY_ORDER if cap in seen]
    return tuple(ordered)


def get_edition(value: str | None = None) -> str:
    edition = (value or os.getenv("RETIKON_EDITION", EDITION_CORE)).strip().lower()
    if edition not in {EDITION_CORE, EDITION_PRO}:
        raise ValueError(f"Unsupported RETIKON_EDITION: {edition}")
    return edition


def resolve_capabilities(
    *,
    edition: str | None = None,
    override: str | None = None,
) -> tuple[str, ...]:
    effective_edition = get_edition(edition)
    override_list = _parse_list(override or os.getenv("RETIKON_CAPABILITIES"))
    if override_list is not None:
        return _validate_capabilities(override_list)
    if effective_edition == EDITION_PRO:
        return PRO_CAPABILITIES
    return CORE_CAPABILITIES


def has_capability(name: str, capabilities: Iterable[str]) -> bool:
    return name in set(capabilities)
