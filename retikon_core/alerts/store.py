from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.alerts.types import AlertDestination, AlertRule
from retikon_core.storage.paths import join_uri


def alert_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "alerts.json")


def load_alerts(base_uri: str) -> list[AlertRule]:
    uri = alert_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("rules", []) if isinstance(payload, dict) else []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_rule_from_dict(item))
    return results


def save_alerts(base_uri: str, rules: Iterable[AlertRule]) -> str:
    uri = alert_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rules": [asdict(rule) for rule in rules],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_alert(
    *,
    base_uri: str,
    name: str,
    event_types: Iterable[str] | None,
    modalities: Iterable[str] | None,
    min_confidence: float | None,
    tags: Iterable[str] | None,
    destinations: Iterable[AlertDestination],
    enabled: bool,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    status: str = "active",
) -> AlertRule:
    now = datetime.now(timezone.utc).isoformat()
    rule = AlertRule(
        id=str(uuid.uuid4()),
        name=name,
        event_types=_normalize_list(event_types),
        modalities=_normalize_list(modalities),
        min_confidence=min_confidence,
        tags=_normalize_list(tags),
        destinations=tuple(destinations),
        enabled=enabled,
        created_at=now,
        updated_at=now,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        status=status,
    )
    rules = load_alerts(base_uri)
    rules.append(rule)
    save_alerts(base_uri, rules)
    return rule


def update_alert(*, base_uri: str, rule: AlertRule) -> AlertRule:
    rules = load_alerts(base_uri)
    updated = []
    for existing in rules:
        if existing.id == rule.id:
            updated.append(rule)
        else:
            updated.append(existing)
    save_alerts(base_uri, updated)
    return rule


def _normalize_list(items: Iterable[object] | None) -> tuple[str, ...] | None:
    if not items:
        return None
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return None
    return tuple(cleaned)


def _rule_from_dict(payload: dict[str, object]) -> AlertRule:
    event_types = _normalize_list(_coerce_iterable(payload.get("event_types")))
    modalities = _normalize_list(_coerce_iterable(payload.get("modalities")))
    tags = _normalize_list(_coerce_iterable(payload.get("tags")))
    destinations_raw = payload.get("destinations")
    destinations = _normalize_destinations(destinations_raw)
    return AlertRule(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        event_types=event_types,
        modalities=modalities,
        min_confidence=_coerce_float(payload.get("min_confidence")),
        tags=tags,
        destinations=destinations,
        enabled=bool(payload.get("enabled", True)),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        status=str(payload.get("status", "active")),
    )


def _normalize_destinations(raw: object) -> tuple[AlertDestination, ...]:
    if not isinstance(raw, list):
        return ()
    destinations: list[AlertDestination] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        target = str(item.get("target", ""))
        if not kind or not target:
            continue
        attrs = (
            item.get("attributes")
            if isinstance(item.get("attributes"), dict)
            else None
        )
        destinations.append(
            AlertDestination(kind=kind, target=target, attributes=attrs)
        )
    return tuple(destinations)


def _coerce_iterable(value: object) -> Iterable[object] | None:
    if isinstance(value, (list, tuple, set)):
        return value
    return None


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
