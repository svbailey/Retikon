from __future__ import annotations

import json
import os
from dataclasses import dataclass

import fsspec

from retikon_core.storage.paths import join_uri


@dataclass(frozen=True)
class IdentityProviderConfig:
    name: str
    issuer: str
    audience: str | None
    jwks_uri: str | None
    enabled: bool = True
    metadata: dict[str, str] | None = None


def _idp_config_uri(base_uri: str) -> str:
    override = os.getenv("IDP_CONFIG_URI")
    if override:
        return override
    return join_uri(base_uri, "control", "idp_config.json")


def load_idp_configs(base_uri: str) -> list[IdentityProviderConfig]:
    uri = _idp_config_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("providers", []) if isinstance(payload, dict) else []
    results: list[IdentityProviderConfig] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(
            IdentityProviderConfig(
                name=str(item.get("name", "")),
                issuer=str(item.get("issuer", "")),
                audience=_coerce_str(item.get("audience")),
                jwks_uri=_coerce_str(item.get("jwks_uri")),
                enabled=bool(item.get("enabled", True)),
                metadata=_coerce_dict(item.get("metadata")),
            )
        )
    return results


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _coerce_dict(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        result[str(key)] = str(item)
    return result or None
