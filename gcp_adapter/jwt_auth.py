from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

from retikon_core.auth.types import AuthContext
from retikon_core.errors import AuthError
from retikon_core.tenancy.types import TenantScope


@dataclass(frozen=True)
class JwtConfig:
    issuer: str | None
    audience: str | None
    jwks_uri: str | None
    algorithms: tuple[str, ...]
    hs256_secret: str | None
    public_key: str | None
    required_claims: tuple[str, ...]
    claim_sub: str
    claim_email: str
    claim_roles: str
    claim_groups: str
    claim_org_id: str
    claim_site_id: str
    claim_stream_id: str
    admin_roles: tuple[str, ...]
    admin_groups: tuple[str, ...]
    leeway_seconds: int


def load_jwt_config() -> JwtConfig:
    return JwtConfig(
        issuer=_env_str("AUTH_ISSUER"),
        audience=_env_str("AUTH_AUDIENCE"),
        jwks_uri=_env_str("AUTH_JWKS_URI"),
        algorithms=_split_env("AUTH_JWT_ALGORITHMS", default="RS256"),
        hs256_secret=_env_str("AUTH_JWT_HS256_SECRET"),
        public_key=_env_str("AUTH_JWT_PUBLIC_KEY"),
        required_claims=_split_env("AUTH_REQUIRED_CLAIMS", default="sub"),
        claim_sub=os.getenv("AUTH_CLAIM_SUB", "sub"),
        claim_email=os.getenv("AUTH_CLAIM_EMAIL", "email"),
        claim_roles=os.getenv("AUTH_CLAIM_ROLES", "roles"),
        claim_groups=os.getenv("AUTH_CLAIM_GROUPS", "groups"),
        claim_org_id=os.getenv("AUTH_CLAIM_ORG_ID", "org_id"),
        claim_site_id=os.getenv("AUTH_CLAIM_SITE_ID", "site_id"),
        claim_stream_id=os.getenv("AUTH_CLAIM_STREAM_ID", "stream_id"),
        admin_roles=_split_env("AUTH_ADMIN_ROLES", default="admin"),
        admin_groups=_split_env("AUTH_ADMIN_GROUPS", default="admins"),
        leeway_seconds=int(os.getenv("AUTH_JWT_LEEWAY_SECONDS", "0")),
    )


def decode_jwt(token: str, *, config: JwtConfig | None = None) -> dict[str, Any]:
    config = config or load_jwt_config()
    key, algs = _resolve_key(token, config)
    if not key:
        raise AuthError("JWT verification not configured")
    options: dict[str, object] = {}
    if config.required_claims:
        options["require"] = list(config.required_claims)
    try:
        return jwt.decode(
            token,
            key=key,
            algorithms=list(algs),
            audience=config.audience,
            issuer=config.issuer,
            leeway=config.leeway_seconds,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid JWT") from exc


def auth_context_from_claims(
    claims: dict[str, Any],
    *,
    config: JwtConfig | None = None,
) -> AuthContext:
    config = config or load_jwt_config()
    sub = _coerce_str(claims.get(config.claim_sub))
    if not sub:
        raise AuthError("JWT missing subject")
    email = _coerce_str(claims.get(config.claim_email))
    roles = _coerce_list(claims.get(config.claim_roles))
    groups = _coerce_list(claims.get(config.claim_groups))
    org_id = _coerce_str(claims.get(config.claim_org_id))
    site_id = _coerce_str(claims.get(config.claim_site_id))
    stream_id = _coerce_str(claims.get(config.claim_stream_id))

    scope = TenantScope(org_id=org_id, site_id=site_id, stream_id=stream_id)
    scope_value = None if scope.is_empty() else scope
    is_admin = _is_admin(roles, groups, config)
    credential_id = f"jwt:{sub}"
    return AuthContext(
        api_key_id=credential_id,
        scope=scope_value,
        is_admin=is_admin,
        actor_type="jwt",
        actor_id=sub,
        email=email,
        roles=roles or None,
        groups=groups or None,
        claims=claims,
    )


def _resolve_key(
    token: str,
    config: JwtConfig,
) -> tuple[str | object | None, tuple[str, ...]]:
    if config.hs256_secret:
        return config.hs256_secret, ("HS256",)
    if config.public_key:
        return config.public_key, config.algorithms
    if config.jwks_uri:
        jwk_client = PyJWKClient(config.jwks_uri)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        alg = signing_key.algorithm or config.algorithms[0]
        return signing_key.key, (alg,)
    return None, config.algorithms


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_env(name: str, *, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(items)


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return tuple(parts)
    if isinstance(value, (list, tuple, set)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return tuple(dict.fromkeys(cleaned))
    return (str(value).strip(),) if str(value).strip() else ()


def _is_admin(
    roles: tuple[str, ...],
    groups: tuple[str, ...],
    config: JwtConfig,
) -> bool:
    if not roles and not groups:
        return False
    admin_roles = {item.lower() for item in config.admin_roles}
    admin_groups = {item.lower() for item in config.admin_groups}
    for role in roles:
        if role.lower() in admin_roles:
            return True
    for group in groups:
        if group.lower() in admin_groups:
            return True
    return False
