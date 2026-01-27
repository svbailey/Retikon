from __future__ import annotations

import mimetypes
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from retikon_core.config import get_config
from retikon_core.errors import PermanentError
from retikon_core.ingestion.eventarc import GcsEvent
from retikon_core.ingestion.router import (
    _check_size,
    _ensure_allowed,
    _run_pipeline,
    _schema_version,
    pipeline_version,
)
from retikon_core.ingestion.types import IngestSource
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-local-ingestion"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV", "local"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str


class IngestRequest(BaseModel):
    path: str
    content_type: str | None = None


class IngestResponse(BaseModel):
    status: str
    modality: str
    manifest_uri: str | None = None
    media_asset_id: str | None = None
    trace_id: str


def _infer_modality(extension: str, config) -> str:
    if extension in config.allowed_doc_ext:
        return "document"
    if extension in config.allowed_image_ext:
        return "image"
    if extension in config.allowed_audio_ext:
        return "audio"
    if extension in config.allowed_video_ext:
        return "video"
    raise PermanentError(f"Unsupported extension: {extension}")


def _prefix_for_modality(modality: str) -> str:
    if modality == "document":
        return "docs"
    if modality == "image":
        return "images"
    if modality == "audio":
        return "audio"
    if modality == "video":
        return "videos"
    raise PermanentError(f"Unsupported modality: {modality}")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=os.getenv("RETIKON_VERSION", "dev"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(payload: IngestRequest) -> IngestResponse:
    config = get_config()
    trace_id = str(uuid.uuid4())

    path = Path(payload.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    extension = path.suffix.lower()
    if not extension:
        raise HTTPException(status_code=400, detail="File extension is required")

    content_type = payload.content_type
    if not content_type:
        content_type = mimetypes.guess_type(path.as_posix())[0]

    modality = _infer_modality(extension, config)
    object_name = f"raw/{_prefix_for_modality(modality)}/{path.name}"

    event = GcsEvent(
        bucket=config.raw_bucket or "local",
        name=object_name,
        generation="local",
        content_type=content_type,
        size=path.stat().st_size,
        md5_hash=None,
        crc32c=None,
    )

    try:
        _check_size(event, config)
        _ensure_allowed(event, config, modality)
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source = IngestSource(
        bucket=event.bucket,
        name=event.name,
        generation=event.generation,
        content_type=event.content_type,
        size_bytes=event.size,
        md5_hash=None,
        crc32c=None,
        local_path=str(path),
    )

    try:
        outcome = _run_pipeline(
            modality=modality,
            source=source,
            config=config,
            output_uri=config.graph_root_uri(),
            pipeline_version_value=pipeline_version(),
            schema_version=_schema_version(),
        )
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Local ingest completed",
        extra={
            "request_id": trace_id,
            "modality": modality,
            "media_asset_id": outcome.media_asset_id,
        },
    )

    return IngestResponse(
        status=outcome.status,
        modality=modality,
        manifest_uri=outcome.manifest_uri,
        media_asset_id=outcome.media_asset_id,
        trace_id=trace_id,
    )
