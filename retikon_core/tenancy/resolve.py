from __future__ import annotations

from typing import Mapping

from retikon_core.tenancy.types import TenantScope

_METADATA_KEYS = {
    "org_id": ("org_id", "org", "tenant", "tenant_id"),
    "site_id": ("site_id", "site", "site_id"),
    "stream_id": ("stream_id", "stream", "stream_id"),
}


def scope_from_metadata(
    metadata: Mapping[str, object] | None,
    defaults: TenantScope | None = None,
) -> TenantScope:
    normalized = _normalize_metadata(metadata)
    default_scope = defaults or TenantScope()

    return TenantScope(
        org_id=_pick(normalized, _METADATA_KEYS["org_id"], default_scope.org_id),
        site_id=_pick(normalized, _METADATA_KEYS["site_id"], default_scope.site_id),
        stream_id=_pick(
            normalized,
            _METADATA_KEYS["stream_id"],
            default_scope.stream_id,
        ),
    )


def tenancy_fields(
    *,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    scope: TenantScope | None = None,
) -> dict[str, str | None]:
    if scope is not None:
        org_id = scope.org_id
        site_id = scope.site_id
        stream_id = scope.stream_id
    return {
        "org_id": org_id,
        "site_id": site_id,
        "stream_id": stream_id,
    }


def _normalize_metadata(metadata: Mapping[str, object] | None) -> dict[str, str]:
    if not metadata:
        return {}
    result: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        result[str(key).strip().lower()] = str(value).strip()
    return result


def _pick(
    metadata: Mapping[str, str],
    keys: tuple[str, ...],
    default: str | None,
) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value:
            return value
    return default
