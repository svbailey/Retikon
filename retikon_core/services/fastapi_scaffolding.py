from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


def cors_origins(
    *,
    raw: str | None = None,
    env: str | None = None,
    default_allow_all: bool = False,
) -> list[str]:
    raw_value = raw if raw is not None else os.getenv("CORS_ALLOW_ORIGINS", "")
    if raw_value:
        return [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    if default_allow_all:
        return ["*"]
    env_value = (env or os.getenv("ENV", "dev")).lower()
    if env_value in {"dev", "local", "test"}:
        return ["*"]
    return []


def apply_cors_middleware(
    app: FastAPI,
    *,
    allow_credentials: bool = False,
    allow_methods: list[str] | None = None,
    allow_headers: list[str] | None = None,
    raw_origins: str | None = None,
    env: str | None = None,
    default_allow_all: bool = False,
) -> list[str]:
    origins = cors_origins(
        raw=raw_origins,
        env=env,
        default_allow_all=default_allow_all,
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=allow_credentials,
            allow_methods=allow_methods or ["*"],
            allow_headers=allow_headers or ["*"],
        )
    return origins


def correlation_id(header_value: str | None) -> str:
    if header_value:
        return header_value
    return str(uuid.uuid4())


def add_correlation_id_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _add_correlation_id(request: Request, call_next):
        corr = correlation_id(request.headers.get("x-correlation-id"))
        request.state.correlation_id = corr
        response = await call_next(request)
        response.headers["x-correlation-id"] = corr
        return response


def build_health_response(
    service_name: str,
    *,
    status: str = "ok",
    version: str | None = None,
    commit: str | None = None,
) -> HealthResponse:
    return HealthResponse(
        status=status,
        service=service_name,
        version=version or os.getenv("RETIKON_VERSION", "dev"),
        commit=commit or os.getenv("GIT_COMMIT", "unknown"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
