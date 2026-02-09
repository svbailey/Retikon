from __future__ import annotations

import base64
import json
import os

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from fastapi import HTTPException, Request

from retikon_core.auth.jwt import auth_context_from_claims, decode_jwt
from retikon_core.auth.types import AuthContext
from retikon_core.errors import AuthError


def authorize_request(
    *,
    request: Request,
    require_admin: bool = False,
) -> AuthContext | None:
    tokens = _extract_bearer_tokens(request)
    context: AuthContext | None = None
    if tokens:
        last_exc: AuthError | None = None
        for token in tokens:
            try:
                claims = decode_jwt(token)
                context = auth_context_from_claims(claims)
                break
            except AuthError as exc:
                last_exc = exc
                continue
        if context is None and _gateway_userinfo_enabled():
            context = _auth_context_from_gateway_userinfo(request)
        if context is None:
            raise HTTPException(status_code=401, detail="Unauthorized") from last_exc
    elif _gateway_userinfo_enabled():
        context = _auth_context_from_gateway_userinfo(request)
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if require_admin and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def authorize_internal_service_account(request: Request) -> AuthContext | None:
    allowed_sas = _split_csv(os.getenv("INTERNAL_AUTH_ALLOWED_SAS"))
    audiences = _split_csv(os.getenv("INTERNAL_AUTH_AUDIENCE"))
    if not allowed_sas:
        return None
    tokens = _extract_bearer_tokens(request)
    if not tokens:
        return None
    req = google_requests.Request()
    for token in tokens:
        for audience in audiences or [None]:
            claims = _verify_google_oidc(token, req, audience)
            if not claims:
                continue
            email = _coerce_str(claims.get("email"))
            if not email or email not in allowed_sas:
                continue
            if claims.get("email_verified") is False:
                continue
            return AuthContext(
                api_key_id=f"sa:{email}",
                scope=None,
                is_admin=True,
                actor_type="service_account",
                actor_id=email,
                email=email,
                roles=("admin",),
                groups=("admins",),
                claims=claims,
            )
    return None


def _extract_bearer_tokens(request: Request) -> list[str]:
    tokens: list[str] = []
    for header_name in (
        "authorization",
        "x-forwarded-authorization",
        "x-original-authorization",
    ):
        header = request.headers.get(header_name)
        token = _parse_bearer_token(header)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _parse_bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _verify_google_oidc(
    token: str,
    request: google_requests.Request,
    audience: str | None,
) -> dict[str, object] | None:
    try:
        return google_id_token.verify_oauth2_token(token, request, audience=audience)
    except Exception:
        return None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _gateway_userinfo_enabled() -> bool:
    return os.getenv("AUTH_GATEWAY_USERINFO", "0") == "1"


def _auth_context_from_gateway_userinfo(request: Request) -> AuthContext | None:
    raw = request.headers.get("x-endpoint-api-userinfo")
    if not raw:
        return None
    payload = _decode_gateway_userinfo(raw)
    if not payload:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return auth_context_from_claims(payload)
    except AuthError:
        return None


def _decode_gateway_userinfo(raw: str) -> object | None:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except Exception:
        decoded = raw
    try:
        return json.loads(decoded)
    except Exception:
        return _decode_jwt_payload(raw)


def _decode_jwt_payload(raw: str) -> object | None:
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None
