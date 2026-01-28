from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.fleet.types import DeviceRecord
from retikon_core.storage.paths import join_uri


def device_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "devices.json")


def load_devices(base_uri: str) -> list[DeviceRecord]:
    uri = device_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("devices", []) if isinstance(payload, dict) else []
    results: list[DeviceRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_device_from_dict(item))
    return results


def save_devices(base_uri: str, devices: Iterable[DeviceRecord]) -> str:
    uri = device_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "devices": [asdict(device) for device in devices],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_device(
    *,
    base_uri: str,
    name: str,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    tags: Iterable[str] | None = None,
    status: str = "unknown",
    firmware_version: str | None = None,
    last_seen_at: str | None = None,
    metadata: dict[str, object] | None = None,
) -> DeviceRecord:
    now = datetime.now(timezone.utc).isoformat()
    device = DeviceRecord(
        id=str(uuid.uuid4()),
        name=name,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        tags=_normalize_list(tags),
        status=status,
        firmware_version=firmware_version,
        last_seen_at=last_seen_at,
        metadata=metadata,
        created_at=now,
        updated_at=now,
    )
    devices = load_devices(base_uri)
    devices.append(device)
    save_devices(base_uri, devices)
    return device


def update_device(base_uri: str, device: DeviceRecord) -> DeviceRecord:
    devices = load_devices(base_uri)
    updated: list[DeviceRecord] = []
    for existing in devices:
        if existing.id == device.id:
            updated.append(device)
        else:
            updated.append(existing)
    save_devices(base_uri, updated)
    return device


def update_device_status(
    *,
    base_uri: str,
    device_id: str,
    status: str,
    last_seen_at: str | None = None,
) -> DeviceRecord | None:
    devices = load_devices(base_uri)
    updated: list[DeviceRecord] = []
    now = datetime.now(timezone.utc).isoformat()
    match: DeviceRecord | None = None
    for existing in devices:
        if existing.id == device_id:
            match = DeviceRecord(
                id=existing.id,
                name=existing.name,
                org_id=existing.org_id,
                site_id=existing.site_id,
                stream_id=existing.stream_id,
                tags=existing.tags,
                status=status,
                firmware_version=existing.firmware_version,
                last_seen_at=last_seen_at or now,
                metadata=existing.metadata,
                created_at=existing.created_at,
                updated_at=now,
            )
            updated.append(match)
        else:
            updated.append(existing)
    if match is None:
        return None
    save_devices(base_uri, updated)
    return match


def _normalize_list(items: Iterable[object] | None) -> tuple[str, ...] | None:
    if not items:
        return None
    cleaned = [str(item).strip().lower() for item in items if str(item).strip()]
    if not cleaned:
        return None
    deduped: list[str] = []
    for item in cleaned:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def _device_from_dict(payload: dict[str, object]) -> DeviceRecord:
    return DeviceRecord(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        tags=_normalize_list(_coerce_iterable(payload.get("tags"))),
        status=str(payload.get("status", "unknown")),
        firmware_version=_coerce_optional_str(payload.get("firmware_version")),
        last_seen_at=_coerce_optional_str(payload.get("last_seen_at")),
        metadata=_coerce_metadata(payload.get("metadata")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
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


def _coerce_metadata(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}
