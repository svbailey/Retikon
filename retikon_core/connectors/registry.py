from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

REGISTRY_PATH = Path(__file__).with_name("registry.yml")


@dataclass(frozen=True)
class ConnectorSpec:
    id: str
    name: str
    category: str
    tier: str
    edition: str
    direction: tuple[str, ...]
    auth_methods: tuple[str, ...]
    incremental: bool
    streaming: bool
    modalities: tuple[str, ...]
    status: str
    notes: str | None


def load_registry(path: Path | None = None) -> list[ConnectorSpec]:
    registry_path = path or REGISTRY_PATH
    payload = yaml.safe_load(registry_path.read_text())
    items = payload.get("connectors", []) if isinstance(payload, dict) else []
    results: list[ConnectorSpec] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_connector_from_dict(item))
    return results


def list_connectors(
    *,
    edition: str | None = None,
    category: str | None = None,
    streaming: bool | None = None,
) -> list[ConnectorSpec]:
    connectors = load_registry()
    results: list[ConnectorSpec] = []
    for connector in connectors:
        if edition and connector.edition != edition:
            continue
        if category and connector.category != category:
            continue
        if streaming is not None and connector.streaming != streaming:
            continue
        results.append(connector)
    return results


def _normalize_list(values: Iterable[object] | None) -> tuple[str, ...]:
    if not values:
        return ()
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return tuple(cleaned)


def _coerce_iterable(value: object) -> Iterable[object] | None:
    if isinstance(value, (list, tuple, set)):
        return value
    return None


def _connector_from_dict(payload: dict[str, object]) -> ConnectorSpec:
    return ConnectorSpec(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        category=str(payload.get("category", "")),
        tier=str(payload.get("tier", "")),
        edition=str(payload.get("edition", "core")),
        direction=_normalize_list(_coerce_iterable(payload.get("direction"))),
        auth_methods=_normalize_list(_coerce_iterable(payload.get("auth_methods"))),
        incremental=bool(payload.get("incremental", False)),
        streaming=bool(payload.get("streaming", False)),
        modalities=_normalize_list(_coerce_iterable(payload.get("modalities"))),
        status=str(payload.get("status", "")),
        notes=str(payload.get("notes")) if payload.get("notes") is not None else None,
    )
