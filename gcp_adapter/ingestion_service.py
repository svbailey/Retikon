import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-ingestion"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()


class CloudEvent(BaseModel):
    id: str
    type: str
    source: str
    specversion: str
    time: str | None = None
    subject: str | None = None
    data: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


class IngestResponse(BaseModel):
    status: str
    trace_id: str


def _correlation_id(header_value: str | None) -> str:
    if header_value:
        return header_value
    return str(uuid.uuid4())


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    corr = _correlation_id(request.headers.get("x-correlation-id"))
    request.state.correlation_id = corr
    response = await call_next(request)
    response.headers["x-correlation-id"] = corr
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    version = os.getenv("RETIKON_VERSION", "dev")
    commit = os.getenv("GIT_COMMIT", "unknown")
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=version,
        commit=commit,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest(
    request: Request,
    event: CloudEvent,
    x_request_id: str | None = Header(default=None),
) -> IngestResponse:
    try:
        _ = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    trace_id = x_request_id or str(uuid.uuid4())
    logger.info(
        "Received ingest event",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
        },
    )

    if event.data is None:
        raise HTTPException(status_code=400, detail="CloudEvent data is required")

    return IngestResponse(status="accepted", trace_id=trace_id)
