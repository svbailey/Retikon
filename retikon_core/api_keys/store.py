from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.api_keys.types import ApiKeyRecord
from retikon_core.storage.paths import join_uri


def api_keys_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "api_keys.json")


def load_api_keys(base_uri: str) -> list[ApiKeyRecord]:
    uri = api_keys_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("api_keys", []) if isinstance(payload, dict) else []
    results: list[ApiKeyRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_api_key_from_dict(item))
    return results


def save_api_keys(base_uri: str, api_keys: Iterable[ApiKeyRecord]) -> str:
    uri = api_keys_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_keys": [asdict(key) for key in api_keys],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_api_key(
    *,
    base_uri: str,
    name: str,
    key_hash: str,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    status: str = "active",
    scopes: Iterable[str] | None = None,
    last_used_at: str | None = None,
) -> ApiKeyRecord:
    now = datetime.now(timezone.utc).isoformat()
    record = ApiKeyRecord(
        id=str(uuid.uuid4()),
        name=name,
        key_hash=key_hash,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        status=status,
        scopes=_normalize_list(scopes),
        last_used_at=last_used_at,
        created_at=now,
        updated_at=now,
    )
    api_keys = load_api_keys(base_uri)
    api_keys.append(record)
    save_api_keys(base_uri, api_keys)
    return record


def update_api_key(base_uri: str, api_key: ApiKeyRecord) -> ApiKeyRecord:
    api_keys = load_api_keys(base_uri)
    updated: list[ApiKeyRecord] = []
    for existing in api_keys:
        if existing.id == api_key.id:
            updated.append(api_key)
        else:
            updated.append(existing)
    save_api_keys(base_uri, updated)
    return api_key


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


def _api_key_from_dict(payload: dict[str, object]) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        key_hash=str(payload.get("key_hash", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        status=str(payload.get("status", "active")),
        scopes=_normalize_list(_coerce_iterable(payload.get("scopes"))),
        last_used_at=_coerce_optional_str(payload.get("last_used_at")),
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
