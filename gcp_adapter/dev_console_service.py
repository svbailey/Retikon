from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import fsspec
import google.auth
import pyarrow.parquet as pq
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore, storage

from retikon_core.ingestion.idempotency import build_doc_id
from retikon_core.logging import configure_logging, get_logger
from retikon_core.storage.paths import graph_root, manifest_uri

SERVICE_NAME = "retikon-dev-console"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()

DEFAULT_RAW_PREFIX = "raw"
UPLOAD_FILE = File(...)
CATEGORY_FORM = Form(...)


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    name: str


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


def _require_api_key(request: Request) -> None:
    env = os.getenv("ENV", "dev").lower()
    key = os.getenv("DEV_CONSOLE_API_KEY") or os.getenv("QUERY_API_KEY")
    if not key:
        if env in {"dev", "local", "test"}:
            return
        raise HTTPException(status_code=500, detail="DEV_CONSOLE_API_KEY missing")
    header_key = request.headers.get("x-api-key")
    if not header_key or header_key != key:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _project_id() -> str:
    value = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
    if not value:
        raise HTTPException(status_code=500, detail="Missing PROJECT_ID")
    return value


def _graph_settings() -> tuple[str, str]:
    bucket = os.getenv("GRAPH_BUCKET")
    prefix = os.getenv("GRAPH_PREFIX")
    if not bucket or not prefix:
        raise HTTPException(status_code=500, detail="Missing GRAPH_BUCKET/GRAPH_PREFIX")
    return bucket, prefix


def _raw_bucket() -> str:
    bucket = os.getenv("RAW_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing RAW_BUCKET")
    return bucket


def _raw_prefix() -> str:
    return os.getenv("RAW_PREFIX", DEFAULT_RAW_PREFIX)


def _max_raw_bytes() -> int:
    return int(os.getenv("MAX_RAW_BYTES", "500000000"))


def _max_preview_bytes() -> int:
    return int(os.getenv("MAX_PREVIEW_BYTES", "5242880"))


def _query_service_url() -> str:
    raw = os.getenv("QUERY_SERVICE_URL") or os.getenv("QUERY_URL")
    if not raw:
        raise HTTPException(status_code=500, detail="Missing QUERY_SERVICE_URL")
    if raw.endswith("/query"):
        return raw[: -len("/query")]
    return raw.rstrip("/")


def _parse_gs_uri(uri: str) -> ObjectRef:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path:
        raise HTTPException(status_code=400, detail="Invalid gs:// URI")
    bucket = parsed.netloc
    name = parsed.path.lstrip("/")
    return ObjectRef(bucket=bucket, name=name)


def _ensure_graph_uri(uri: str) -> None:
    bucket, prefix = _graph_settings()
    root = graph_root(bucket, prefix).rstrip("/") + "/"
    if not uri.startswith(root):
        raise HTTPException(status_code=403, detail="Path outside graph prefix")


def _ensure_raw_uri(uri: str) -> None:
    bucket = _raw_bucket()
    if not uri.startswith(f"gs://{bucket}/"):
        raise HTTPException(status_code=403, detail="Path outside raw bucket")


def _format_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, list):
        if len(value) > 16:
            return {"length": len(value), "head": value[:8]}
        return value
    return value


def _preview_parquet(uri: str, limit: int) -> dict[str, object]:
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "rb") as handle:
        parquet = pq.ParquetFile(handle)
        batch_iter = parquet.iter_batches(batch_size=limit)
        try:
            batch = next(batch_iter)
        except StopIteration:
            return {"columns": [], "rows": [], "preview_count": 0}
    data = batch.to_pydict()
    columns = list(data.keys())
    rows = []
    for idx in range(len(batch)):
        row = {}
        for col in columns:
            row[col] = _format_value(data[col][idx])
        rows.append(row)
    return {
        "columns": columns,
        "rows": rows,
        "preview_count": len(rows),
        "row_count": parquet.metadata.num_rows if parquet.metadata else None,
    }


def _firestore_collection() -> str:
    return os.getenv("FIRESTORE_COLLECTION", "ingestion_events")


def _storage_client() -> storage.Client:
    return storage.Client()


def _firestore_client() -> firestore.Client:
    return firestore.Client()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": os.getenv("RETIKON_VERSION", "dev"),
        "commit": os.getenv("GIT_COMMIT", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.post("/dev/upload")
async def upload_file(
    request: Request,
    file: UploadFile = UPLOAD_FILE,
    category: str = CATEGORY_FORM,
) -> dict[str, object]:
    _require_api_key(request)
    raw_prefix = _raw_prefix().strip("/")
    bucket_name = _raw_bucket()
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"
    safe_name = os.path.basename(file.filename or "upload.bin")
    object_name = f"{raw_prefix}/{category}/{run_id}/{safe_name}"

    client = _storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_file(file.file, content_type=file.content_type)
    blob.reload()

    uri = f"gs://{bucket_name}/{object_name}"
    return {
        "uri": uri,
        "bucket": bucket_name,
        "name": object_name,
        "generation": str(blob.generation or ""),
        "size_bytes": blob.size,
        "content_type": blob.content_type,
        "run_id": run_id,
    }


@app.get("/dev/ingest-status")
async def ingest_status(
    request: Request,
    uri: str,
) -> dict[str, object]:
    _require_api_key(request)
    ref = _parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(ref.bucket).blob(ref.name)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Object not found")
    blob.reload()
    generation = str(blob.generation or "")
    doc_id = build_doc_id(ref.bucket, ref.name, generation)
    doc = _firestore_client().collection(_firestore_collection()).document(doc_id).get()
    data = doc.to_dict() if doc.exists else None
    return {
        "bucket": ref.bucket,
        "name": ref.name,
        "generation": generation,
        "doc_id": doc_id,
        "firestore": data,
        "status": (data or {}).get("status") if data else "MISSING",
    }


@app.get("/dev/manifest")
async def manifest(
    request: Request,
    run_id: str | None = None,
    manifest_uri_value: str | None = None,
) -> dict[str, object]:
    _require_api_key(request)
    if not run_id and not manifest_uri_value:
        raise HTTPException(status_code=400, detail="run_id or manifest_uri required")
    if manifest_uri_value:
        _ensure_graph_uri(manifest_uri_value)
        uri = manifest_uri_value
    else:
        bucket, prefix = _graph_settings()
        uri = manifest_uri(graph_root(bucket, prefix), run_id or "")
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    payload["manifest_uri"] = uri
    return payload


@app.get("/dev/parquet-preview")
async def parquet_preview(
    request: Request,
    path: str,
    limit: int = 5,
) -> dict[str, object]:
    _require_api_key(request)
    _ensure_graph_uri(path)
    return _preview_parquet(path, max(1, min(limit, 25)))


@app.get("/dev/object")
async def fetch_object(
    request: Request,
    uri: str,
) -> StreamingResponse:
    _require_api_key(request)
    _ensure_raw_uri(uri)
    ref = _parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(ref.bucket).blob(ref.name)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Object not found")
    blob.reload()
    if blob.size and blob.size > _max_preview_bytes():
        raise HTTPException(status_code=413, detail="Object too large for preview")
    stream = blob.open("rb")
    return StreamingResponse(
        stream,
        media_type=blob.content_type or "application/octet-stream",
    )


@app.get("/dev/graph-object")
async def fetch_graph_object(
    request: Request,
    uri: str,
) -> StreamingResponse:
    _require_api_key(request)
    _ensure_graph_uri(uri)
    ref = _parse_gs_uri(uri)
    client = _storage_client()
    blob = client.bucket(ref.bucket).blob(ref.name)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Object not found")
    blob.reload()
    if blob.size and blob.size > _max_preview_bytes():
        raise HTTPException(status_code=413, detail="Object too large for preview")
    stream = blob.open("rb")
    return StreamingResponse(
        stream,
        media_type=blob.content_type or "application/octet-stream",
    )


@app.get("/dev/snapshot-status")
async def snapshot_status(request: Request) -> dict[str, object]:
    _require_api_key(request)
    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if not snapshot_uri:
        raise HTTPException(status_code=500, detail="Missing SNAPSHOT_URI")
    meta_uri = f"{snapshot_uri}.json"
    fs, path = fsspec.core.url_to_fs(meta_uri)
    with fs.open(path, "rb") as handle:
        metadata = json.loads(handle.read().decode("utf-8"))
    return {
        "snapshot_uri": snapshot_uri,
        "metadata": metadata,
    }


@app.post("/dev/index-build")
async def index_build(request: Request) -> dict[str, object]:
    _require_api_key(request)
    job_name = os.getenv("INDEX_JOB_NAME")
    region = os.getenv("INDEX_JOB_REGION", os.getenv("REGION", "us-central1"))
    if not job_name:
        raise HTTPException(status_code=500, detail="Missing INDEX_JOB_NAME")
    project = _project_id()
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job_name}:run"
    resp = session.post(url, json={})
    if resp.status_code >= 300:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    payload = resp.json()
    return {
        "job_name": job_name,
        "region": region,
        "execution": payload.get("name"),
        "status": payload.get("done"),
    }


@app.post("/dev/snapshot-reload")
async def snapshot_reload(request: Request) -> dict[str, object]:
    _require_api_key(request)
    base_url = _query_service_url()
    api_key = os.getenv("DEV_CONSOLE_API_KEY") or os.getenv("QUERY_API_KEY")
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    resp = session.post(
        f"{base_url}/admin/reload-snapshot",
        headers={"x-api-key": api_key or ""},
    )
    if resp.status_code >= 300:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.get("/dev/index-status")
async def index_status(request: Request) -> dict[str, object]:
    _require_api_key(request)
    job_name = os.getenv("INDEX_JOB_NAME")
    region = os.getenv("INDEX_JOB_REGION", os.getenv("REGION", "us-central1"))
    if not job_name:
        raise HTTPException(status_code=500, detail="Missing INDEX_JOB_NAME")
    project = _project_id()
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job_name}"
    resp = session.get(url)
    if resp.status_code >= 300:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    payload = resp.json()
    status = payload.get("status", {})
    latest = status.get("latestCreatedExecution", {})
    return {
        "job_name": job_name,
        "region": region,
        "latest_execution": latest.get("name"),
        "completion_status": latest.get("completionStatus"),
        "completion_time": latest.get("completionTimestamp"),
    }
