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


def _normalize_event_types(event_types: Iterable[str] | None) -> tuple[str, ...] | None:
    if not event_types:
        return None
    items = [str(item).strip() for item in event_types if str(item).strip()]
    if not items:
        return None
    return tuple(items)


def _webhook_from_dict(payload: dict[str, object]) -> WebhookRegistration:
    return WebhookRegistration(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        url=str(payload.get("url", "")),
        secret=payload.get("secret") if payload.get("secret") else None,
        event_types=_normalize_event_types(payload.get("event_types")),
        enabled=bool(payload.get("enabled", True)),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        headers=(
            payload.get("headers")
            if isinstance(payload.get("headers"), dict)
            else None
        ),
        timeout_s=_coerce_float(payload.get("timeout_s")),
    )


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
