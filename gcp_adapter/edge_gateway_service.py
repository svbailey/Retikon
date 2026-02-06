from __future__ import annotations

import mimetypes
import os
import uuid
from dataclasses import dataclass
from typing import Annotated

import fsspec
from google.cloud import storage
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from gcp_adapter.auth import authorize_request
from gcp_adapter.stores import abac_allowed, is_action_allowed
from retikon_core.auth import AuthContext
from retikon_core.auth.rbac import (
    ACTION_EDGE_BUFFER_PRUNE,
    ACTION_EDGE_BUFFER_REPLAY,
    ACTION_EDGE_BUFFER_STATUS,
    ACTION_EDGE_CONFIG_READ,
    ACTION_EDGE_CONFIG_UPDATE,
    ACTION_EDGE_UPLOAD,
)
from retikon_core.edge.buffer import BufferItem, EdgeBuffer
from retikon_core.edge.policies import AdaptiveBatchPolicy, BackpressurePolicy
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    apply_cors_middleware,
    build_health_response,
)
from retikon_core.storage.paths import graph_root, normalize_bucket_uri

SERVICE_NAME = "retikon-edge-gateway"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)


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


_FALLBACK_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rtf": "application/rtf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}


def _normalize_content_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower()


def _resolve_content_type(filename: str, content_type: str | None) -> str | None:
    normalized = _normalize_content_type(content_type)
    if normalized and normalized != "application/octet-stream":
        return normalized
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    _, ext = os.path.splitext(filename.lower())
    return _FALLBACK_CONTENT_TYPES.get(ext)


def _split_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError("Not a GCS URI")
    path = uri[5:]
    bucket, _, name = path.partition("/")
    if not bucket or not name:
        raise ValueError("Invalid GCS URI")
    return bucket, name


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


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(request=request, require_admin=False)


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _control_plane_base_uri() -> str:
    local_root = os.getenv("LOCAL_GRAPH_ROOT")
    if local_root:
        return local_root
    graph_bucket = os.getenv("GRAPH_BUCKET")
    graph_prefix = os.getenv("GRAPH_PREFIX", "")
    if not graph_bucket:
        raise HTTPException(status_code=500, detail="Missing GRAPH_BUCKET")
    return graph_root(normalize_bucket_uri(graph_bucket, scheme="gs"), graph_prefix)


def _enforce_access(
    action: str,
    auth_context: AuthContext | None,
) -> None:
    base_uri = _control_plane_base_uri()
    if _rbac_enabled() and not is_action_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")
    if _abac_enabled() and not abac_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")


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


def _write_to_store(
    payload: bytes,
    dest_uri: str,
    *,
    content_type: str | None,
    filename: str,
) -> int:
    if dest_uri.startswith("gs://"):
        bucket, name = _split_gs_uri(dest_uri)
        resolved = _resolve_content_type(filename, content_type)
        blob = storage.Client().bucket(bucket).blob(name)
        blob.upload_from_string(payload, content_type=resolved)
        return len(payload)
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
    content_type: str | None,
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
    bytes_written = _write_to_store(
        payload,
        dest_uri,
        content_type=content_type,
        filename=filename,
    )
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
            content_type=meta.get("content_type"),
        )
    except Exception as exc:
        logger.warning("Replay failed", extra={"error_message": str(exc)})
        return False
    return True


@app.get("/health")
async def health() -> dict[str, str]:
    return build_health_response(SERVICE_NAME).model_dump()


@app.get("/edge/config", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_CONFIG_READ, auth_context)
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
async def update_config(payload: ConfigUpdate, request: Request) -> ConfigResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_CONFIG_UPDATE, auth_context)
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
    return await get_config(request)


@app.get("/edge/buffer/status", response_model=BufferStatus)
async def buffer_status(request: Request) -> BufferStatus:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_BUFFER_STATUS, auth_context)
    stats = STATE.buffer.stats()
    return BufferStatus(
        count=stats.count,
        total_bytes=stats.total_bytes,
        oldest_age_s=stats.oldest_age_s,
        newest_age_s=stats.newest_age_s,
    )


@app.post("/edge/buffer/replay")
async def buffer_replay(request: Request) -> dict[str, int]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_BUFFER_REPLAY, auth_context)
    return STATE.buffer.replay(_replay_item)


@app.post("/edge/buffer/prune")
async def buffer_prune(request: Request) -> dict[str, int]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_BUFFER_PRUNE, auth_context)
    before = STATE.buffer.stats()
    STATE.buffer.prune()
    after = STATE.buffer.stats()
    return {"before": before.count, "after": after.count}


@app.post("/edge/upload", response_model=UploadResponse)
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    modality: Annotated[str, Form()],
    device_id: Annotated[str | None, Form()] = None,
    stream_id: Annotated[str | None, Form()] = None,
    site_id: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_EDGE_UPLOAD, auth_context)
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
            content_type=file.content_type,
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
