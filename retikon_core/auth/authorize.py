from __future__ import annotations

import secrets

from retikon_core.auth.store import find_api_key, load_api_keys
from retikon_core.auth.types import AuthContext
from retikon_core.errors import AuthError
from retikon_core.tenancy.types import TenantScope


def authorize_api_key(
    *,
    base_uri: str,
    raw_key: str | None,
    fallback_key: str | None = None,
    require: bool = True,
) -> AuthContext | None:
    if not raw_key:
        if require:
            raise AuthError("API key required")
        return None

    if fallback_key and secrets.compare_digest(raw_key, fallback_key):
        return AuthContext(
            api_key_id="legacy",
            scope=None,
            is_admin=True,
            actor_type="api_key",
            actor_id="legacy",
        )

    keys = load_api_keys(base_uri)
    match = find_api_key(raw_key, keys)
    if not match or not match.enabled:
        raise AuthError("Unauthorized")

    scope = TenantScope(
        org_id=match.org_id,
        site_id=match.site_id,
        stream_id=match.stream_id,
    )
    scope_value: TenantScope | None = None if scope.is_empty() else scope
    return AuthContext(
        api_key_id=match.id,
        scope=scope_value,
        is_admin=match.is_admin,
        actor_type="api_key",
        actor_id=match.id,
    )
