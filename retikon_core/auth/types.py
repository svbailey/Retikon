from __future__ import annotations

from dataclasses import dataclass

from retikon_core.tenancy.types import TenantScope


@dataclass(frozen=True)
class ApiKey:
    id: str
    name: str
    key_hash: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    enabled: bool
    is_admin: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AuthContext:
    api_key_id: str
    scope: TenantScope | None
    is_admin: bool = False
