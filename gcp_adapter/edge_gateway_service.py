from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fsspec
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from retikon_core.edge.buffer import BufferItem, EdgeBuffer
from retikon_core.edge.policies import AdaptiveBatchPolicy, BackpressurePolicy
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-edge-gateway"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()


class UploadResponse(BaseModel):
    status: str
    uri: str | None = None
    buffered: bool = False
    bytes_written: int | None = None
    device_id: str | None = None
    stream_id: str | None = None
    site_id: str | None = None
    modality: str | None = None
    trace_id: str


class BufferStatus(BaseModel):
    count: int
    total_bytes: int
    oldest_age_s: float | None
    newest_age_s: float | None


class ConfigResponse(BaseModel):
    buffer_dir: str
    buffer_max_bytes: int
    buffer_ttl_seconds: int
    batch_min: int
    batch_max: int
    low_watermark: int
    high_watermark: int
    backpressure_max_backlog: int
    backpressure_hard_limit: int


class ConfigUpdate(BaseModel):
    buffer_max_bytes: int | None = None
    buffer_ttl_seconds: int | None = None
    batch_min: int | None = None
    batch_max: int | None = None
    low_watermark: int | None = None
    high_watermark: int | None = None
    backpressure_max_backlog: int | None = None
    backpressure_hard_limit: int | None = None


@dataclass
class GatewayState:
    buffer: EdgeBuffer
    batch_policy: AdaptiveBatchPolicy
    backpressure: BackpressurePolicy


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    env = os.getenv("ENV", "dev").lower()
    if env in {"dev", "local", "test"}:
        return ["*"]
    return []


_cors = _cors_origins()
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _buffer_dir() -> str:
    return os.getenv("EDGE_BUFFER_DIR", "/tmp/retikon_edge_buffer")


def _buffer_max_bytes() -> int:
    return int(os.getenv("EDGE_BUFFER_MAX_BYTES", "2147483648"))


def _buffer_ttl_seconds() -> int:
    return int(os.getenv("EDGE_BUFFER_TTL_SECONDS", "86400"))


def _raw_prefix() -> str:
    return os.getenv("RAW_PREFIX", "raw").strip("/")


def _raw_bucket() -> str | None:
    return os.getenv("RAW_BUCKET")


def _raw_base_uri() -> str:
    override = os.getenv("EDGE_RAW_URI")
    if override:
        return override
    bucket = _raw_bucket()
    if not bucket:
        raise HTTPException(status_code=500, detail="RAW_BUCKET is required")
    return f"gs://{bucket}/{_raw_prefix()}"


def _max_raw_bytes() -> int:
    return int(os.getenv("MAX_RAW_BYTES", "500000000"))


def _force_buffer() -> bool:
    return os.getenv("EDGE_FORCE_BUFFER", "0") == "1"


def _init_state() -> GatewayState:
    buffer = EdgeBuffer(
        base_dir=_buffer_dir(),
        max_bytes=_buffer_max_bytes(),
        ttl_seconds=_buffer_ttl_seconds(),
    )
    batch_policy = AdaptiveBatchPolicy(
        min_batch=int(os.getenv("EDGE_BATCH_MIN", "1")),
        max_batch=int(os.getenv("EDGE_BATCH_MAX", "50")),
        low_watermark=int(os.getenv("EDGE_BACKLOG_LOW", "10")),
        high_watermark=int(os.getenv("EDGE_BACKLOG_HIGH", "100")),
        min_delay_ms=int(os.getenv("EDGE_BATCH_DELAY_MIN_MS", "0")),
        max_delay_ms=int(os.getenv("EDGE_BATCH_DELAY_MAX_MS", "2000")),
    )
    backpressure = BackpressurePolicy(
        max_backlog=int(os.getenv("EDGE_BACKPRESSURE_MAX", "1000")),
        hard_limit=int(os.getenv("EDGE_BACKPRESSURE_HARD", "2000")),
    )
    return GatewayState(
        buffer=buffer,
        batch_policy=batch_policy,
        backpressure=backpressure,
    )


STATE = _init_state()


def _object_path(
    *,
    modality: str,
    filename: str,
    device_id: str | None,
    stream_id: str | None,
    site_id: str | None,
) -> str:
    slug = uuid.uuid4().hex[:8]
    device = device_id or "unknown"
    stream = stream_id or "stream"
    site = site_id or "site"
    safe_name = filename.replace("/", "_")
    return f"{modality}/{site}/{device}/{stream}/{slug}_{safe_name}"


def _write_to_store(payload: bytes, dest_uri: str) -> int:
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    with fs.open(path, "wb") as handle:
        handle.write(payload)
    return len(payload)


def _store_payload(
    payload: bytes,
    *,
    filename: str,
    modality: str,
    device_id: str | None,
    stream_id: str | None,
    site_id: str | None,
) -> tuple[str, int]:
    base_uri = _raw_base_uri().rstrip("/")
    dest_path = _object_path(
        modality=modality,
        filename=filename,
        device_id=device_id,
        stream_id=stream_id,
        site_id=site_id,
    )
    dest_uri = f"{base_uri}/{dest_path}"
    bytes_written = _write_to_store(payload, dest_uri)
    return dest_uri, bytes_written


def _buffer_payload(
    payload: bytes,
    *,
    filename: str,
    content_type: str | None,
    modality: str,
    device_id: str | None,
    stream_id: str | None,
    site_id: str | None,
) -> BufferItem:
    metadata = {
        "filename": filename,
        "content_type": content_type,
        "modality": modality,
        "device_id": device_id,
        "stream_id": stream_id,
        "site_id": site_id,
    }
    return STATE.buffer.add_bytes(payload, metadata)


def _replay_item(item: BufferItem) -> bool:
    meta = item.metadata
    payload = item.read_bytes()
    try:
        _store_payload(
            payload,
            filename=meta.get("filename", "payload.bin"),
            modality=meta.get("modality", "unknown"),
            device_id=meta.get("device_id"),
            stream_id=meta.get("stream_id"),
            site_id=meta.get("site_id"),
        )
    except Exception as exc:
        logger.warning("Replay failed", extra={"error_message": str(exc)})
        return False
    return True


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": os.getenv("RETIKON_VERSION", "dev"),
        "commit": os.getenv("GIT_COMMIT", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/edge/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    return ConfigResponse(
        buffer_dir=_buffer_dir(),
        buffer_max_bytes=STATE.buffer.max_bytes,
        buffer_ttl_seconds=STATE.buffer.ttl_seconds,
        batch_min=STATE.batch_policy.min_batch,
        batch_max=STATE.batch_policy.max_batch,
        low_watermark=STATE.batch_policy.low_watermark,
        high_watermark=STATE.batch_policy.high_watermark,
        backpressure_max_backlog=STATE.backpressure.max_backlog,
        backpressure_hard_limit=STATE.backpressure.hard_limit,
    )


@app.post("/edge/config", response_model=ConfigResponse)
async def update_config(payload: ConfigUpdate) -> ConfigResponse:
    if payload.buffer_max_bytes is not None:
        STATE.buffer.max_bytes = payload.buffer_max_bytes
    if payload.buffer_ttl_seconds is not None:
        STATE.buffer.ttl_seconds = payload.buffer_ttl_seconds
    if payload.batch_min is not None:
        STATE.batch_policy = AdaptiveBatchPolicy(
            min_batch=payload.batch_min,
            max_batch=STATE.batch_policy.max_batch,
            low_watermark=STATE.batch_policy.low_watermark,
            high_watermark=STATE.batch_policy.high_watermark,
            min_delay_ms=STATE.batch_policy.min_delay_ms,
            max_delay_ms=STATE.batch_policy.max_delay_ms,
        )
    if payload.batch_max is not None:
        STATE.batch_policy = AdaptiveBatchPolicy(
            min_batch=STATE.batch_policy.min_batch,
            max_batch=payload.batch_max,
            low_watermark=STATE.batch_policy.low_watermark,
            high_watermark=STATE.batch_policy.high_watermark,
            min_delay_ms=STATE.batch_policy.min_delay_ms,
            max_delay_ms=STATE.batch_policy.max_delay_ms,
        )
    if payload.low_watermark is not None or payload.high_watermark is not None:
        STATE.batch_policy = AdaptiveBatchPolicy(
            min_batch=STATE.batch_policy.min_batch,
            max_batch=STATE.batch_policy.max_batch,
            low_watermark=payload.low_watermark or STATE.batch_policy.low_watermark,
            high_watermark=payload.high_watermark or STATE.batch_policy.high_watermark,
            min_delay_ms=STATE.batch_policy.min_delay_ms,
            max_delay_ms=STATE.batch_policy.max_delay_ms,
        )
    if payload.backpressure_max_backlog is not None:
        STATE.backpressure = BackpressurePolicy(
            max_backlog=payload.backpressure_max_backlog,
            hard_limit=STATE.backpressure.hard_limit,
        )
    if payload.backpressure_hard_limit is not None:
        STATE.backpressure = BackpressurePolicy(
            max_backlog=STATE.backpressure.max_backlog,
            hard_limit=payload.backpressure_hard_limit,
        )
    return await get_config()


@app.get("/edge/buffer/status", response_model=BufferStatus)
async def buffer_status() -> BufferStatus:
    stats = STATE.buffer.stats()
    return BufferStatus(
        count=stats.count,
        total_bytes=stats.total_bytes,
        oldest_age_s=stats.oldest_age_s,
        newest_age_s=stats.newest_age_s,
    )


@app.post("/edge/buffer/replay")
async def buffer_replay() -> dict[str, int]:
    return STATE.buffer.replay(_replay_item)


@app.post("/edge/buffer/prune")
async def buffer_prune() -> dict[str, int]:
    before = STATE.buffer.stats()
    STATE.buffer.prune()
    after = STATE.buffer.stats()
    return {"before": before.count, "after": after.count}


@app.post("/edge/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    modality: str = Form(...),
    device_id: str | None = Form(default=None),
    stream_id: str | None = Form(default=None),
    site_id: str | None = Form(default=None),
) -> UploadResponse:
    backlog = STATE.buffer.stats().count
    if not STATE.backpressure.should_accept(backlog):
        raise HTTPException(status_code=429, detail="Gateway backpressure active")
    payload = await file.read()
    if len(payload) > _max_raw_bytes():
        raise HTTPException(status_code=413, detail="Payload too large")

    trace_id = str(uuid.uuid4())
    try:
        if _force_buffer():
            raise RuntimeError("Forced buffering enabled")
        uri, bytes_written = _store_payload(
            payload,
            filename=file.filename or "payload.bin",
            modality=modality,
            device_id=device_id,
            stream_id=stream_id,
            site_id=site_id,
        )
        logger.info(
            "Edge upload stored",
            extra={
                "uri": uri,
                "bytes_written": bytes_written,
                "device_id": device_id,
                "stream_id": stream_id,
                "site_id": site_id,
            },
        )
        return UploadResponse(
            status="stored",
            uri=uri,
            buffered=False,
            bytes_written=bytes_written,
            device_id=device_id,
            stream_id=stream_id,
            site_id=site_id,
            modality=modality,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "Edge upload buffering",
            extra={"error_message": str(exc)},
        )
        _buffer_payload(
            payload,
            filename=file.filename or "payload.bin",
            content_type=file.content_type,
            modality=modality,
            device_id=device_id,
            stream_id=stream_id,
            site_id=site_id,
        )
        return UploadResponse(
            status="buffered",
            uri=None,
            buffered=True,
            bytes_written=len(payload),
            device_id=device_id,
            stream_id=stream_id,
            site_id=site_id,
            modality=modality,
            trace_id=trace_id,
        )
