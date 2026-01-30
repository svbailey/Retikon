from __future__ import annotations

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

    token = _extract_bearer_token(request) if jwt_allowed else None
    context: AuthContext | None = None
    if token:
        try:
            claims = decode_jwt(token)
            context = auth_context_from_claims(claims)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="Unauthorized") from exc
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


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
