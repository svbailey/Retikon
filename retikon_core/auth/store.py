from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.auth.types import ApiKey
from retikon_core.storage.paths import join_uri


def api_key_registry_uri(base_uri: str) -> str:
    if base_uri.endswith(".json"):
        return base_uri
    return join_uri(base_uri, "control", "api_keys.json")


def resolve_registry_base(base_uri: str) -> str:
    override = os.getenv("API_KEY_REGISTRY_URI")
    return override or base_uri


def hash_key(raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return digest


def load_api_keys(base_uri: str) -> list[ApiKey]:
    uri = api_key_registry_uri(resolve_registry_base(base_uri))
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("api_keys", []) if isinstance(payload, dict) else []
    results: list[ApiKey] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_api_key_from_dict(item))
    return results


def save_api_keys(base_uri: str, keys: Iterable[ApiKey]) -> str:
    uri = api_key_registry_uri(resolve_registry_base(base_uri))
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "api_keys": [asdict(key) for key in keys],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_api_key(
    *,
    base_uri: str,
    name: str,
    raw_key: str,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    enabled: bool = True,
    is_admin: bool = False,
) -> ApiKey:
    now = datetime.now(timezone.utc).isoformat()
    key = ApiKey(
        id=str(uuid.uuid4()),
        name=name,
        key_hash=hash_key(raw_key),
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        enabled=enabled,
        is_admin=is_admin,
        created_at=now,
        updated_at=now,
    )
    keys = load_api_keys(base_uri)
    keys.append(key)
    save_api_keys(base_uri, keys)
    return key


def find_api_key(raw_key: str, keys: Iterable[ApiKey]) -> ApiKey | None:
    target_hash = hash_key(raw_key)
    for key in keys:
        if key.key_hash == target_hash:
            return key
    return None


def _api_key_from_dict(payload: dict[str, object]) -> ApiKey:
    return ApiKey(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        key_hash=str(payload.get("key_hash", "")),
        org_id=_coerce_str(payload.get("org_id")),
        site_id=_coerce_str(payload.get("site_id")),
        stream_id=_coerce_str(payload.get("stream_id")),
        enabled=bool(payload.get("enabled", True)),
        is_admin=bool(payload.get("is_admin", False)),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
