from __future__ import annotations

import csv
import json
import os
import time
import uuid
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fsspec
import google.auth
import numpy as np
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests  # type: ignore[import-untyped]
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.auth.transport import requests as google_requests
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore, storage
from google.oauth2 import id_token

from gcp_adapter.auth import authorize_request
from gcp_adapter.stores import abac_allowed, is_action_allowed
from retikon_core.audit import record_audit_log
from retikon_core.auth import AuthContext
from retikon_core.auth.rbac import (
    ACTION_DEV_GRAPH_OBJECT,
    ACTION_DEV_INDEX_BUILD,
    ACTION_DEV_INDEX_STATUS,
    ACTION_DEV_INGEST_STATUS,
    ACTION_DEV_LABEL_CATALOG,
    ACTION_DEV_MANIFEST,
    ACTION_DEV_OBJECT,
    ACTION_DEV_PARQUET_PREVIEW,
    ACTION_DEV_SNAPSHOT_RELOAD,
    ACTION_DEV_SNAPSHOT_STATUS,
    ACTION_DEV_UPLOAD,
    ACTION_DEV_VISUAL_LABELS,
)
from retikon_core.embeddings.stub import get_embedding_backend, get_image_text_embedder
from retikon_core.ingestion.idempotency import build_doc_id
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    apply_cors_middleware,
    build_health_response,
)
from retikon_core.storage.paths import (
    graph_root,
    join_uri,
    manifest_uri,
    normalize_bucket_uri,
)

SERVICE_NAME = "retikon-dev-console"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)

DEFAULT_RAW_PREFIX = "raw"
UPLOAD_FILE = File(...)
CATEGORY_FORM = Form(...)


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    name: str


@dataclass(frozen=True)
class LabelEntry:
    label: str
    category: str
    source: str
    source_id: str


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("DEV_CONSOLE_REQUIRE_ADMIN", default) == "1"


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(request=request, require_admin=_require_admin())


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _enforce_access(
    action: str,
    auth_context: AuthContext | None,
) -> None:
    base_uri = _audit_base_uri()
    if _rbac_enabled() and not is_action_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")
    if _abac_enabled() and not abac_allowed(auth_context, action, base_uri):
        raise HTTPException(status_code=403, detail="Forbidden")


def _audit_logging_enabled() -> bool:
    return os.getenv("AUDIT_LOGGING_ENABLED", "1") == "1"


def _schema_version() -> str:
    return os.getenv("SCHEMA_VERSION", "1")


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid.uuid4())


def _audit_base_uri() -> str:
    storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    if storage_backend == "local":
        local_root = os.getenv("LOCAL_GRAPH_ROOT")
        if local_root:
            return local_root
    bucket, prefix = _graph_settings()
    return graph_root(normalize_bucket_uri(bucket, scheme="gs"), prefix)


def _record_audit(
    *,
    request: Request,
    auth_context: AuthContext | None,
    action: str,
    decision: str,
    request_id: str,
) -> None:
    if not _audit_logging_enabled():
        return
    try:
        record_audit_log(
            base_uri=_audit_base_uri(),
            action=action,
            decision=decision,
            auth_context=auth_context,
            resource=request.url.path,
            request_id=request_id,
            pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
            schema_version=_schema_version(),
        )
    except Exception as exc:
        logger.warning(
            "Failed to record audit log",
            extra={"error_message": str(exc)},
        )


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


def _glob_files(pattern: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    if protocol in {"file", "local"}:
        return matches
    return [f"{protocol}://{match}" for match in matches]


def _manifest_uris() -> list[str]:
    bucket, prefix = _graph_settings()
    base_uri = graph_root(normalize_bucket_uri(bucket, scheme="gs"), prefix)
    manifest_glob = join_uri(base_uri, "manifests", "*", "manifest.json")
    return _glob_files(manifest_glob)


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


def _read_snapshot_report(snapshot_uri: str) -> dict[str, object] | None:
    meta_uri = f"{snapshot_uri}.json"
    fs, path = fsspec.core.url_to_fs(meta_uri)
    if not fs.exists(path):
        return None
    try:
        with fs.open(path, "rb") as handle:
            payload = json.loads(handle.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


_LABEL_CATALOG: list[LabelEntry] | None = None
_LABEL_EMBED_CACHE: dict[str, tuple[list[LabelEntry], np.ndarray]] = {}


def _query_service_url() -> str:
    raw = os.getenv("QUERY_SERVICE_URL") or os.getenv("QUERY_URL")
    if not raw:
        raise HTTPException(status_code=500, detail="Missing QUERY_SERVICE_URL")
    if raw.endswith("/query"):
        return raw[: -len("/query")]
    return raw.rstrip("/")


def _fetch_id_token(audience: str) -> str | None:
    env = os.getenv("ENV", "dev").lower()
    if env in {"dev", "local", "test"}:
        return None
    if audience.startswith(("http://localhost", "http://127.0.0.1")):
        return None
    request = google_requests.Request()
    return id_token.fetch_id_token(request, audience)


def _snapshot_reload_allow_sa() -> bool:
    return os.getenv("DEV_CONSOLE_SNAPSHOT_RELOAD_ALLOW_SA", "0") == "1"


def _parse_gs_uri(uri: str) -> ObjectRef:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path:
        raise HTTPException(status_code=400, detail="Invalid gs:// URI")
    bucket = parsed.netloc
    name = parsed.path.lstrip("/")
    return ObjectRef(bucket=bucket, name=name)


def _ensure_graph_uri(uri: str) -> None:
    bucket, prefix = _graph_settings()
    root = (
        graph_root(normalize_bucket_uri(bucket, scheme="gs"), prefix).rstrip("/")
        + "/"
    )
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


def _label_catalog_path() -> Path:
    override = os.getenv("LABEL_CATALOG_PATH")
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[1]
        / "retikon_core"
        / "labels"
        / "label_catalog.csv"
    )


def _load_label_catalog() -> list[LabelEntry]:
    global _LABEL_CATALOG
    if _LABEL_CATALOG is not None:
        return _LABEL_CATALOG
    path = _label_catalog_path()
    if not path.exists():
        raise HTTPException(status_code=500, detail="Missing label catalog")
    entries: list[LabelEntry] = []
    with path.open(newline="", encoding="ascii") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            label = (row.get("label") or "").strip()
            category = (row.get("category") or "").strip()
            source = (row.get("source") or "").strip()
            source_id = (row.get("source_id") or "").strip()
            if not label or not category:
                continue
            entries.append(
                LabelEntry(
                    label=label,
                    category=category,
                    source=source,
                    source_id=source_id,
                )
            )
    _LABEL_CATALOG = entries
    return entries


def _parse_rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_execution(executions: list[dict[str, object]]) -> dict[str, object] | None:
    latest = None
    latest_at = None
    for execution in executions:
        created_at = _parse_rfc3339(
            str(execution.get("createTime") or execution.get("startTime") or "")
        )
        if created_at is None:
            continue
        if latest_at is None or created_at > latest_at:
            latest = execution
            latest_at = created_at
    return latest


def _execution_completion(execution: dict[str, object]) -> tuple[str | None, str | None]:
    completion_time = execution.get("completionTime")
    succeeded = execution.get("succeededCount")
    failed = execution.get("failedCount") or execution.get("cancelledCount")
    task_count = execution.get("taskCount")
    if completion_time:
        if failed:
            return "FAILED", str(completion_time)
        if succeeded is not None and task_count is not None:
            try:
                if int(succeeded) >= int(task_count):
                    return "SUCCEEDED", str(completion_time)
            except (TypeError, ValueError):
                pass
        return "COMPLETED", str(completion_time)
    if execution.get("startTime"):
        return "RUNNING", None
    return "PENDING", None


def _label_embeddings(cache_key: str) -> tuple[list[LabelEntry], np.ndarray]:
    cached = _LABEL_EMBED_CACHE.get(cache_key)
    if cached is not None:
        return cached
    entries = _load_label_catalog()
    labels = [entry.label for entry in entries]
    try:
        embedder = get_image_text_embedder(512)
        vectors = embedder.encode(labels)
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    matrix = np.asarray(vectors, dtype=np.float32)
    _LABEL_EMBED_CACHE[cache_key] = (entries, matrix)
    return entries, matrix


def _image_vectors_for_media(
    *,
    media_asset_id: str,
    limit: int,
) -> list[dict[str, object]]:
    bucket, prefix = _graph_settings()
    base_uri = graph_root(normalize_bucket_uri(bucket, scheme="gs"), prefix)
    manifest_uri = join_uri(base_uri, "manifests", "*", "manifest.json")

    manifest_fs, manifest_path = fsspec.core.url_to_fs(manifest_uri)
    manifest_files = sorted(manifest_fs.glob(manifest_path))
    if not manifest_files:
        return []

    results: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for manifest_file in manifest_files:
        if limit > 0 and len(results) >= limit:
            break
        try:
            with manifest_fs.open(manifest_file, "r") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        image_core_uri = None
        image_vector_uri = None
        for item in manifest.get("files", []):
            uri = item.get("uri", "")
            if "/vertices/ImageAsset/core/" in uri:
                image_core_uri = uri
            elif "/vertices/ImageAsset/vector/" in uri:
                image_vector_uri = uri
        if not image_core_uri or not image_vector_uri:
            continue

        try:
            with fsspec.open(image_core_uri, "rb") as handle:
                core_table = pq.read_table(
                    handle,
                    columns=[
                        "id",
                        "timestamp_ms",
                        "thumbnail_uri",
                        "media_asset_id",
                    ],
                )
        except OSError:
            continue
        if core_table.num_rows == 0:
            continue
        mask = pc.equal(core_table["media_asset_id"], media_asset_id)
        mask = pc.fill_null(mask, False)
        if pc.sum(mask).as_py() == 0:
            continue
        filtered_core = core_table.filter(mask)
        if filtered_core.num_rows == 0:
            continue

        try:
            with fsspec.open(image_vector_uri, "rb") as handle:
                vector_table = pq.read_table(handle, columns=["clip_vector"])
        except OSError:
            continue
        if vector_table.num_rows != core_table.num_rows:
            continue

        filtered_vectors = vector_table.filter(mask).to_pylist()
        filtered_rows = filtered_core.to_pylist()
        for row, vec_row in zip(filtered_rows, filtered_vectors, strict=False):
            if limit > 0 and len(results) >= limit:
                break
            row_id = row.get("id")
            if isinstance(row_id, str) and row_id in seen_ids:
                continue
            vec = vec_row.get("clip_vector")
            if not isinstance(vec, list):
                continue
            if isinstance(row_id, str):
                seen_ids.add(row_id)
            results.append(
                {
                    "id": row_id,
                    "timestamp_ms": row.get("timestamp_ms"),
                    "thumbnail_uri": row.get("thumbnail_uri"),
                    "clip_vector": vec,
                }
            )
    return results


def _firestore_collection() -> str:
    return os.getenv("FIRESTORE_COLLECTION", "ingestion_events")


def _storage_client() -> storage.Client:
    return storage.Client()


def _firestore_client() -> firestore.Client:
    return firestore.Client()


def _forward_auth_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    header = (
        request.headers.get("authorization")
        or request.headers.get("x-forwarded-authorization")
        or request.headers.get("x-original-authorization")
    )
    if header:
        headers["authorization"] = header
    gateway_userinfo = request.headers.get("x-endpoint-api-userinfo")
    if gateway_userinfo:
        headers["x-endpoint-api-userinfo"] = gateway_userinfo
    return headers


@app.get("/health")
async def health() -> dict[str, str]:
    return build_health_response(SERVICE_NAME).model_dump()


@app.post("/dev/upload")
async def upload_file(
    request: Request,
    file: UploadFile = UPLOAD_FILE,
    category: str = CATEGORY_FORM,
) -> dict[str, object]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_UPLOAD, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.upload.create",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_INGEST_STATUS, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.ingest_status.read",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_MANIFEST, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.manifest.read",
        decision="allow",
        request_id=trace_id,
    )
    if not run_id and not manifest_uri_value:
        raise HTTPException(status_code=400, detail="run_id or manifest_uri required")
    if manifest_uri_value:
        _ensure_graph_uri(manifest_uri_value)
        uri = manifest_uri_value
    else:
        bucket, prefix = _graph_settings()
        uri = manifest_uri(
            graph_root(normalize_bucket_uri(bucket, scheme="gs"), prefix), run_id or ""
        )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_PARQUET_PREVIEW, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.parquet_preview.read",
        decision="allow",
        request_id=trace_id,
    )
    _ensure_graph_uri(path)
    return _preview_parquet(path, max(1, min(limit, 25)))


@app.get("/dev/label-catalog")
async def label_catalog(
    request: Request,
    categories: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_LABEL_CATALOG, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.label_catalog.read",
        decision="allow",
        request_id=trace_id,
    )
    entries = _load_label_catalog()
    selected = [entry for entry in entries]
    if categories:
        allow = {item.strip().lower() for item in categories.split(",") if item}
        selected = [entry for entry in selected if entry.category in allow]
    if limit is not None:
        selected = selected[: max(0, limit)]
    return {
        "count": len(selected),
        "labels": [
            {
                "label": entry.label,
                "category": entry.category,
                "source": entry.source,
                "source_id": entry.source_id,
            }
            for entry in selected
        ],
    }


@app.get("/dev/visual-labels")
async def visual_labels(
    request: Request,
    media_asset_id: str,
    top_k: int = 8,
    max_frames: int = 12,
    strategy: str = "max",
    categories: str | None = None,
) -> dict[str, object]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_VISUAL_LABELS, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.visual_labels.read",
        decision="allow",
        request_id=trace_id,
    )
    if not media_asset_id:
        raise HTTPException(status_code=400, detail="media_asset_id required")
    vectors = _image_vectors_for_media(
        media_asset_id=media_asset_id,
        limit=max(1, min(max_frames, 64)),
    )
    if not vectors:
        raise HTTPException(status_code=404, detail="No image vectors found")
    backend = get_embedding_backend()
    backend_key = f"{backend}:{os.getenv('USE_REAL_MODELS', '0')}"
    entries, matrix = _label_embeddings(backend_key)
    if matrix.size == 0:
        raise HTTPException(status_code=500, detail="Label embeddings unavailable")
    image_matrix = np.asarray(
        [row["clip_vector"] for row in vectors],
        dtype=np.float32,
    )
    if image_matrix.ndim != 2:
        raise HTTPException(status_code=500, detail="Invalid image vectors")
    scores = matrix @ image_matrix.T
    if strategy == "avg":
        score_vector = scores.mean(axis=1)
    else:
        score_vector = scores.max(axis=1)
    score_vector = np.clip(score_vector, 0.0, 1.0)

    def top_for_category(category: str) -> list[dict[str, object]]:
        items = [
            (idx, entry)
            for idx, entry in enumerate(entries)
            if entry.category == category
        ]
        if not items:
            return []
        scored = [
            {
                "label": entry.label,
                "score": float(score_vector[idx]),
                "source": entry.source,
            }
            for idx, entry in items
        ]
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[: max(1, min(top_k, 25))]

    allow_categories = (
        {item.strip().lower() for item in categories.split(",") if item}
        if categories
        else {"object", "scene", "action"}
    )
    payload = {
        "media_asset_id": media_asset_id,
        "backend": backend,
        "use_real_models": os.getenv("USE_REAL_MODELS") == "1",
        "strategy": strategy,
        "frame_count": len(vectors),
        "labels": {},
    }
    for category in ("object", "scene", "action"):
        if category in allow_categories:
            payload["labels"][category] = top_for_category(category)
    return payload


@app.get("/dev/object")
async def fetch_object(
    request: Request,
    uri: str,
) -> StreamingResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_OBJECT, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.object.read",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_GRAPH_OBJECT, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.graph_object.read",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_SNAPSHOT_STATUS, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.snapshot_status.read",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_INDEX_BUILD, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.index_build.create",
        decision="allow",
        request_id=trace_id,
    )
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_SNAPSHOT_RELOAD, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.snapshot_reload.create",
        decision="allow",
        request_id=trace_id,
    )
    base_url = _query_service_url()
    headers = _forward_auth_headers(request)
    if "x-endpoint-api-userinfo" not in headers and auth_context and auth_context.claims:
        headers["x-endpoint-api-userinfo"] = json.dumps(auth_context.claims)
    token = _fetch_id_token(base_url)
    if token and "authorization" not in headers and "x-endpoint-api-userinfo" not in headers:
        headers["authorization"] = f"Bearer {token}"
    resp = requests.post(
        f"{base_url}/admin/reload-snapshot",
        headers=headers,
    )
    if resp.status_code in {401, 403} and _snapshot_reload_allow_sa() and token:
        resp = requests.post(
            f"{base_url}/admin/reload-snapshot",
            headers={"authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 300:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.get("/dev/index-status")
async def index_status(request: Request) -> dict[str, object]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_DEV_INDEX_STATUS, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="dev.index_status.read",
        decision="allow",
        request_id=trace_id,
    )
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
    completion_status = latest.get("completionStatus") if isinstance(latest, dict) else None
    completion_time = latest.get("completionTimestamp") if isinstance(latest, dict) else None
    latest_name = latest.get("name") if isinstance(latest, dict) else None
    if not completion_time:
        executions_url = (
            f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job_name}/executions?pageSize=5"
        )
        executions_resp = session.get(executions_url)
        if executions_resp.status_code < 300:
            executions = executions_resp.json().get("executions", [])
            latest_exec = _latest_execution(executions)
            if latest_exec:
                completion_status, completion_time = _execution_completion(latest_exec)
                latest_name = latest_exec.get("name")
    manifest_count: int | None = None
    snapshot_manifest_count: int | None = None
    index_queue_length: int | None = None
    try:
        manifest_uris = _manifest_uris()
        manifest_count = len(manifest_uris)
        snapshot_uri = os.getenv("SNAPSHOT_URI")
        if snapshot_uri:
            report = _read_snapshot_report(snapshot_uri)
            if report:
                report_uris = report.get("manifest_uris")
                if isinstance(report_uris, list):
                    snapshot_manifest_count = len({str(uri) for uri in report_uris})
                else:
                    report_count = report.get("manifest_count")
                    if report_count is not None:
                        snapshot_manifest_count = int(report_count)
                if snapshot_manifest_count is not None:
                    index_queue_length = max(
                        0, manifest_count - snapshot_manifest_count
                    )
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        logger.warning(
            "Failed to compute index queue length",
            extra={"error_message": str(exc)},
        )
    return {
        "job_name": job_name,
        "region": region,
        "latest_execution": latest_name,
        "completion_status": completion_status,
        "completion_time": completion_time,
        "manifest_count": manifest_count,
        "snapshot_manifest_count": snapshot_manifest_count,
        "index_queue_length": index_queue_length,
    }


def _mount_static_ui() -> None:
    static_dir = Path(os.getenv("DEV_CONSOLE_STATIC_DIR", "/app/static"))
    if not static_dir.exists():
        return
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    logger.info("Static UI enabled", extra={"static_dir": str(static_dir)})


_mount_static_ui()
