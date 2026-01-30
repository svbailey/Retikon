from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

import jwt
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWK, PyJWKClient

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


JwtKey = (
    RSAPublicKey
    | EllipticCurvePublicKey
    | Ed25519PublicKey
    | Ed448PublicKey
    | PyJWK
    | str
    | bytes
)


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
    options: dict[str, object] = {}
    if config.required_claims:
        options["require"] = list(config.required_claims)
    issuers = _split_csv(config.issuer)
    audiences = _split_csv(config.audience)
    last_exc: jwt.PyJWTError | None = None
    for issuer in issuers or [None]:
        try:
            kwargs: dict[str, object] = {
                "key": key,
                "algorithms": list(algs),
                "leeway": config.leeway_seconds,
                "options": options,
            }
            if audiences:
                kwargs["audience"] = audiences
            if issuer:
                kwargs["issuer"] = issuer
            return jwt.decode(token, **kwargs)
        except jwt.PyJWTError as exc:
            last_exc = exc
            continue
    raise AuthError("Invalid JWT") from last_exc


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
) -> tuple[JwtKey, tuple[str, ...]]:
    if config.hs256_secret:
        return config.hs256_secret, ("HS256",)
    if config.public_key:
        return config.public_key, config.algorithms
    if config.jwks_uri:
        if _looks_like_x509(config.jwks_uri):
            return _load_x509_key(token, config.jwks_uri), config.algorithms
        try:
            jwk_client = PyJWKClient(config.jwks_uri)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            alg = _token_alg(token) or config.algorithms[0]
            return cast(JwtKey, signing_key.key), (alg,)
        except Exception as exc:
            raise AuthError("Failed to fetch JWKS") from exc
    raise AuthError("JWT verification not configured")


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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


def _looks_like_x509(uri: str) -> bool:
    return "/metadata/x509/" in uri


def _load_x509_key(token: str, jwks_uri: str) -> JwtKey:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise AuthError("JWT header missing kid")
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("JWT header invalid") from exc
    try:
        with urllib.request.urlopen(jwks_uri, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise AuthError("Failed to fetch x509 JWKS") from exc
    if not isinstance(payload, dict):
        raise AuthError("Invalid x509 JWKS payload")
    cert_pem = payload.get(kid)
    if not cert_pem:
        raise AuthError("JWT kid not found in x509 JWKS")
    try:
        cert = x509.load_pem_x509_certificate(str(cert_pem).encode("utf-8"))
        return cert.public_key()
    except Exception as exc:
        raise AuthError("Failed to parse x509 certificate") from exc


def _token_alg(token: str) -> str | None:
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        return None
    alg = header.get("alg")
    if not alg:
        return None
    return str(alg)
