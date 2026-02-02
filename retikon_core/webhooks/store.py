from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.storage.paths import join_uri
from retikon_core.webhooks.types import WebhookRegistration


def webhook_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "webhooks.json")


def load_webhooks(base_uri: str) -> list[WebhookRegistration]:
    uri = webhook_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("webhooks", []) if isinstance(payload, dict) else []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_webhook_from_dict(item))
    return results


def save_webhooks(base_uri: str, webhooks: Iterable[WebhookRegistration]) -> str:
    uri = webhook_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "webhooks": [asdict(hook) for hook in webhooks],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_webhook(
    *,
    base_uri: str,
    name: str,
    url: str,
    secret: str | None,
    event_types: Iterable[str] | None,
    enabled: bool,
    headers: dict[str, str] | None = None,
    timeout_s: float | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    status: str = "active",
) -> WebhookRegistration:
    now = datetime.now(timezone.utc).isoformat()
    registration = WebhookRegistration(
        id=str(uuid.uuid4()),
        name=name,
        url=url,
        secret=secret,
        event_types=_normalize_event_types(event_types),
        enabled=enabled,
        created_at=now,
        updated_at=now,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        status=status,
        headers=headers,
        timeout_s=timeout_s,
    )
    webhooks = load_webhooks(base_uri)
    webhooks.append(registration)
    save_webhooks(base_uri, webhooks)
    return registration


def update_webhook(
    *,
    base_uri: str,
    webhook: WebhookRegistration,
) -> WebhookRegistration:
    webhooks = load_webhooks(base_uri)
    updated = []
    for existing in webhooks:
        if existing.id == webhook.id:
            updated.append(webhook)
        else:
            updated.append(existing)
    save_webhooks(base_uri, updated)
    return webhook


def _normalize_event_types(
    event_types: Iterable[object] | None,
) -> tuple[str, ...] | None:
    if not event_types:
        return None
    items = [str(item).strip() for item in event_types if str(item).strip()]
    if not items:
        return None
    return tuple(items)


def _webhook_from_dict(payload: dict[str, object]) -> WebhookRegistration:
    raw_event_types = _coerce_iterable(payload.get("event_types"))
    return WebhookRegistration(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        url=str(payload.get("url", "")),
        secret=_coerce_optional_str(payload.get("secret")),
        event_types=_normalize_event_types(raw_event_types),
        enabled=bool(payload.get("enabled", True)),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        status=str(payload.get("status", "active")),
        headers=_coerce_headers(payload.get("headers")),
        timeout_s=_coerce_float(payload.get("timeout_s")),
    )


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_iterable(value: object) -> Iterable[object] | None:
    if isinstance(value, (list, tuple, set)):
        return value
    return None


def _coerce_headers(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        cleaned[str(key)] = str(item)
    return cleaned or None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
