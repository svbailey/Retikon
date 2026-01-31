from __future__ import annotations

from dataclasses import dataclass

from retikon_core.tenancy.types import TenantScope


@dataclass(frozen=True)
class AuthContext:
    api_key_id: str
    scope: TenantScope | None
    is_admin: bool = False
    actor_type: str = "api_key"
    actor_id: str | None = None
    email: str | None = None
    roles: tuple[str, ...] | None = None
    groups: tuple[str, ...] | None = None
    claims: dict[str, object] | None = None
