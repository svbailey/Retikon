from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Iterable

from fastapi import FastAPI

from gcp_adapter import (
    audit_service,
    chaos_service,
    data_factory_service,
    dev_console_service,
    edge_gateway_service,
    fleet_service,
    ingestion_service,
    privacy_service,
    query_service,
    webhook_service,
    workflow_service,
)
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    add_correlation_id_middleware,
    apply_cors_middleware,
    build_health_response,
)

SERVICE_NAME = "retikon-pro-monolith"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


def _optional_stream_ingest():
    try:
        from gcp_adapter import stream_ingest_service
    except Exception as exc:  # pragma: no cover - guarded by env in prod
        logger.warning(
            "Stream ingest disabled in monolith",
            extra={"error_message": str(exc)},
        )
        return None
    return stream_ingest_service


def _attach_routes(
    app: FastAPI,
    source_app: FastAPI,
    *,
    drop_paths: Iterable[str] = ("/health",),
) -> None:
    drop = set(drop_paths)
    for route in source_app.router.routes:
        path = getattr(route, "path", None)
        if path in drop:
            continue
        app.router.routes.append(route)


STREAM_INGEST = _optional_stream_ingest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with query_service.lifespan(app), audit_service.lifespan(app):
        if STREAM_INGEST is not None:
            await STREAM_INGEST._start_flush_loop()
        try:
            yield
        finally:
            if STREAM_INGEST is not None:
                await STREAM_INGEST._stop_flush_loop()


app = FastAPI(lifespan=lifespan)
apply_cors_middleware(app)
add_correlation_id_middleware(app)

_attach_routes(app, ingestion_service.app)
_attach_routes(app, query_service.app)
_attach_routes(app, audit_service.app)
_attach_routes(app, data_factory_service.app)
_attach_routes(app, privacy_service.app)
_attach_routes(app, workflow_service.app)
_attach_routes(app, chaos_service.app)
_attach_routes(app, fleet_service.app)
_attach_routes(app, edge_gateway_service.app)
_attach_routes(app, dev_console_service.app)
_attach_routes(app, webhook_service.app)
if STREAM_INGEST is not None:
    _attach_routes(app, STREAM_INGEST.app)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)
