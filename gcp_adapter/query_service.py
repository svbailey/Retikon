import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-query"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


class QueryRequest(BaseModel):
    query_text: str | None = None
    image_base64: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class QueryHit(BaseModel):
    modality: str
    uri: str
    snippet: str | None = None
    timestamp_ms: int | None = None
    score: float
    media_asset_id: str | None = None


class QueryResponse(BaseModel):
    results: list[QueryHit]


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


@app.post("/query", response_model=QueryResponse)
async def query(
    request: Request,
    payload: QueryRequest,
    x_request_id: str | None = Header(default=None),
) -> QueryResponse:
    try:
        _ = get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not payload.query_text and not payload.image_base64:
        raise HTTPException(
            status_code=400,
            detail="query_text or image_base64 is required",
        )

    trace_id = x_request_id or str(uuid.uuid4())
    logger.info(
        "Received query",
        extra={
            "request_id": trace_id,
            "correlation_id": request.state.correlation_id,
        },
    )

    return QueryResponse(results=[])
