import base64
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from retikon_core.auth import AuthContext, authorize_api_key
from retikon_core.config import get_config
from retikon_core.connectors import list_connectors
from retikon_core.data_factory import (
    add_annotation,
    create_dataset,
    create_training_job,
    list_annotations,
    list_datasets,
    load_models,
    register_model,
)
from retikon_core.errors import AuthError
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-data-factory"

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


class DatasetRequest(BaseModel):
    name: str
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    tags: list[str] | None = None
    size: int | None = None


class AnnotationRequest(BaseModel):
    dataset_id: str
    media_asset_id: str
    label: str
    value: str | None = None
    annotator: str | None = None
    status: str = "pending"
    qa_status: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None


class ModelRequest(BaseModel):
    name: str
    version: str
    description: str | None = None
    task: str | None = None
    framework: str | None = None
    tags: list[str] | None = None
    metrics: dict[str, object] | None = None


class TrainingRequest(BaseModel):
    dataset_id: str
    model_id: str
    epochs: int = 10
    batch_size: int = 16
    learning_rate: float = 1e-4
    labels: list[str] | None = None

    model_config = {"protected_namespaces": ()}


class ConnectorResponse(BaseModel):
    id: str
    name: str
    category: str
    tier: str
    edition: str
    direction: list[str]
    auth_methods: list[str]
    incremental: bool
    streaming: bool
    modalities: list[str]
    status: str
    notes: str | None = None


class OfficeConversionRequest(BaseModel):
    filename: str
    content_base64: str


class OfficeConversionResponse(BaseModel):
    status: str
    output_filename: str
    message: str | None = None


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


def _api_key_required() -> bool:
    env = os.getenv("ENV", "dev").lower()
    return env not in {"dev", "local", "test"}


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("DATA_FACTORY_REQUIRE_ADMIN", default) == "1"


def _data_factory_api_key() -> str | None:
    return os.getenv("DATA_FACTORY_API_KEY") or os.getenv("QUERY_API_KEY")


def _authorize(request: Request) -> AuthContext | None:
    raw_key = request.headers.get("x-api-key")
    try:
        context = authorize_api_key(
            base_uri=_get_config().graph_root_uri(),
            raw_key=raw_key,
            fallback_key=_data_factory_api_key(),
            require=_api_key_required(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if _require_admin() and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def _get_config():
    return get_config()


def _connector_response(item) -> ConnectorResponse:
    return ConnectorResponse(
        id=item.id,
        name=item.name,
        category=item.category,
        tier=item.tier,
        edition=item.edition,
        direction=list(item.direction),
        auth_methods=list(item.auth_methods),
        incremental=item.incremental,
        streaming=item.streaming,
        modalities=list(item.modalities),
        status=item.status,
        notes=item.notes,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=os.getenv("RETIKON_VERSION", "dev"),
        commit=os.getenv("GIT_COMMIT", "unknown"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.get("/data-factory/datasets")
async def get_datasets(request: Request) -> list[dict[str, Any]]:
    _authorize(request)
    return list_datasets(_get_config().graph_root_uri())


@app.post("/data-factory/datasets", status_code=201)
async def create_dataset_endpoint(
    request: Request,
    payload: DatasetRequest,
) -> dict[str, str]:
    _authorize(request)
    result = create_dataset(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        description=payload.description,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        tags=payload.tags,
        size=payload.size,
        pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
        schema_version=os.getenv("SCHEMA_VERSION", "1"),
    )
    logger.info(
        "Dataset created",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.headers.get("x-correlation-id"),
            "dataset_uri": result.uri,
        },
    )
    return {"uri": result.uri}


@app.get("/data-factory/annotations")
async def get_annotations(request: Request) -> list[dict[str, Any]]:
    _authorize(request)
    return list_annotations(_get_config().graph_root_uri())


@app.post("/data-factory/annotations", status_code=201)
async def create_annotation_endpoint(
    request: Request,
    payload: AnnotationRequest,
) -> dict[str, str]:
    _authorize(request)
    result = add_annotation(
        base_uri=_get_config().graph_root_uri(),
        dataset_id=payload.dataset_id,
        media_asset_id=payload.media_asset_id,
        label=payload.label,
        value=payload.value,
        annotator=payload.annotator,
        status=payload.status,
        qa_status=payload.qa_status,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        pipeline_version=os.getenv("RETIKON_VERSION", "dev"),
        schema_version=os.getenv("SCHEMA_VERSION", "1"),
    )
    logger.info(
        "Annotation created",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.headers.get("x-correlation-id"),
            "annotation_uri": result.uri,
        },
    )
    return {"uri": result.uri}


@app.get("/data-factory/models")
async def get_models(request: Request) -> list[dict[str, Any]]:
    _authorize(request)
    models = load_models(_get_config().graph_root_uri())
    return [model.__dict__ for model in models]


@app.post("/data-factory/models", status_code=201)
async def create_model_endpoint(
    request: Request,
    payload: ModelRequest,
) -> dict[str, Any]:
    _authorize(request)
    model = register_model(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        version=payload.version,
        description=payload.description,
        task=payload.task,
        framework=payload.framework,
        tags=payload.tags,
        metrics=payload.metrics,
    )
    logger.info(
        "Model registered",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.headers.get("x-correlation-id"),
            "model_id": model.id,
        },
    )
    return model.__dict__


@app.post("/data-factory/training", status_code=201)
async def create_training_endpoint(
    request: Request,
    payload: TrainingRequest,
) -> dict[str, Any]:
    _authorize(request)
    job = create_training_job(
        dataset_id=payload.dataset_id,
        model_id=payload.model_id,
        epochs=payload.epochs,
        batch_size=payload.batch_size,
        learning_rate=payload.learning_rate,
        labels=payload.labels,
    )
    return {
        "id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "spec": {
            "dataset_id": job.spec.dataset_id,
            "model_id": job.spec.model_id,
            "epochs": job.spec.epochs,
            "batch_size": job.spec.batch_size,
            "learning_rate": job.spec.learning_rate,
            "labels": list(job.spec.labels) if job.spec.labels else None,
        },
    }


@app.get("/data-factory/connectors", response_model=list[ConnectorResponse])
async def get_connectors(
    request: Request,
    edition: str | None = None,
    category: str | None = None,
    streaming: bool | None = None,
) -> list[ConnectorResponse]:
    _authorize(request)
    resolved = list_connectors(edition=edition, category=category, streaming=streaming)
    return [_connector_response(item) for item in resolved]


@app.post("/data-factory/ocr/connectors")
async def register_ocr_connector(request: Request) -> dict[str, str]:
    _authorize(request)
    return {"status": "ok"}


@app.post("/data-factory/convert-office", response_model=OfficeConversionResponse)
async def convert_office(
    request: Request,
    payload: OfficeConversionRequest,
) -> OfficeConversionResponse:
    _authorize(request)
    try:
        base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 payload") from exc
    output_name = f"{payload.filename}.pdf"
    return OfficeConversionResponse(
        status="stub",
        output_filename=output_name,
        message="Conversion pipeline not enabled in dev",
    )
