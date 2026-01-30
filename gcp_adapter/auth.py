from __future__ import annotations

import base64
import json
import os

from fastapi import HTTPException, Request

from gcp_adapter.jwt_auth import auth_context_from_claims, decode_jwt
from retikon_core.auth import authorize_api_key
from retikon_core.auth.types import AuthContext
from retikon_core.errors import AuthError


def authorize_request(
    *,
    request: Request,
    base_uri: str,
    fallback_key: str | None,
    require_api_key: bool,
    require_admin: bool = False,
) -> AuthContext | None:
    mode = _auth_mode()
    jwt_allowed = mode in {"jwt", "dual"}
    api_key_allowed = mode in {"api_key", "dual"}

    tokens = _extract_bearer_tokens(request) if jwt_allowed else []
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
        if context is None and not api_key_allowed:
            raise HTTPException(status_code=401, detail="Unauthorized") from last_exc
    elif jwt_allowed and _gateway_userinfo_enabled():
        context = _auth_context_from_gateway_userinfo(request)
    elif mode == "jwt":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if context is None and api_key_allowed:
        raw_key = request.headers.get("x-api-key")
        try:
            context = authorize_api_key(
                base_uri=base_uri,
                raw_key=raw_key,
                fallback_key=fallback_key,
                require=require_api_key,
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="Unauthorized") from exc

    if context is None and mode == "dual" and require_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if require_admin and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def _auth_mode() -> str:
    return os.getenv("AUTH_MODE", "api_key").strip().lower()


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


def _decode_gateway_userinfo(raw: str) -> dict[str, object] | None:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except Exception:
        decoded = raw
    try:
        return json.loads(decoded)
    except Exception:
        return None
