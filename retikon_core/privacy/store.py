from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.storage.paths import join_uri


def privacy_policy_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "privacy_policies.json")


def load_privacy_policies(base_uri: str) -> list[PrivacyPolicy]:
    uri = privacy_policy_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("policies", []) if isinstance(payload, dict) else []
    results: list[PrivacyPolicy] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_policy_from_dict(item))
    return results


def save_privacy_policies(
    base_uri: str,
    policies: Iterable[PrivacyPolicy],
) -> str:
    uri = privacy_policy_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policies": [asdict(policy) for policy in policies],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_privacy_policy(
    *,
    base_uri: str,
    name: str,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    modalities: Iterable[str] | None = None,
    contexts: Iterable[str] | None = None,
    redaction_types: Iterable[str] | None = None,
    enabled: bool = True,
) -> PrivacyPolicy:
    now = datetime.now(timezone.utc).isoformat()
    policy = PrivacyPolicy(
        id=str(uuid.uuid4()),
        name=name,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        modalities=_normalize_list(modalities),
        contexts=_normalize_list(contexts),
        redaction_types=_normalize_list(redaction_types) or ("pii",),
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    policies = load_privacy_policies(base_uri)
    policies.append(policy)
    save_privacy_policies(base_uri, policies)
    return policy


def update_privacy_policy(
    *,
    base_uri: str,
    policy: PrivacyPolicy,
) -> PrivacyPolicy:
    policies = load_privacy_policies(base_uri)
    updated: list[PrivacyPolicy] = []
    for existing in policies:
        if existing.id == policy.id:
            updated.append(policy)
        else:
            updated.append(existing)
    save_privacy_policies(base_uri, updated)
    return policy


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


def _policy_from_dict(payload: dict[str, object]) -> PrivacyPolicy:
    return PrivacyPolicy(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        modalities=_normalize_list(_coerce_iterable(payload.get("modalities"))),
        contexts=_normalize_list(_coerce_iterable(payload.get("contexts"))),
        redaction_types=_normalize_list(
            _coerce_iterable(payload.get("redaction_types"))
        ),
        enabled=bool(payload.get("enabled", True)),
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
