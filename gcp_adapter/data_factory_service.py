import base64
import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gcp_adapter.auth import authorize_request
from gcp_adapter.office_conversion import (
    conversion_backend,
    conversion_mode,
    convert_office_bytes,
    create_job_record,
    decode_payload,
    enqueue_conversion,
    load_conversion_record,
    publish_conversion_dlq,
    save_conversion_record,
    update_job_record,
    validate_payload_size,
    write_conversion_output,
)
from gcp_adapter.queue_pubsub import PubSubPublisher, parse_pubsub_push
from retikon_core.auth import AuthContext
from retikon_core.config import get_config
from retikon_core.connectors import (
    list_connectors,
    load_ocr_connectors,
    register_ocr_connector,
)
from retikon_core.data_factory import (
    TrainingExecutor,
    TrainingJob,
    TrainingResult,
    add_annotation,
    create_dataset,
    execute_training_job,
    get_training_job,
    list_annotations,
    list_datasets,
    list_training_jobs,
    load_models,
    mark_training_job_failed,
    register_model,
    register_training_job,
)
from retikon_core.errors import PermanentError, RecoverableError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    apply_cors_middleware,
    build_health_response,
)

SERVICE_NAME = "retikon-data-factory"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)


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


class TrainingJobResponse(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    output: dict[str, object] | None = None
    metrics: dict[str, object] | None = None
    spec: dict[str, object]


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


class OcrConnectorRequest(BaseModel):
    name: str
    url: str
    auth_type: str = "none"
    auth_header: str | None = None
    token_env: str | None = None
    enabled: bool = True
    is_default: bool = False
    max_pages: int | None = None
    timeout_s: float | None = None
    notes: str | None = None


class OcrConnectorResponse(BaseModel):
    id: str
    name: str
    url: str
    auth_type: str
    auth_header: str | None = None
    token_env: str | None = None
    enabled: bool
    is_default: bool
    max_pages: int | None = None
    timeout_s: float | None = None
    notes: str | None = None
    created_at: str
    updated_at: str


class OfficeConversionRequest(BaseModel):
    filename: str
    content_base64: str
    queue: bool | None = None


class OfficeConversionResponse(BaseModel):
    status: str
    output_filename: str
    content_base64: str | None = None
    job_id: str | None = None
    output_uri: str | None = None
    message: str | None = None


class OfficeConversionJobResponse(BaseModel):
    id: str
    filename: str
    status: str
    output_uri: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("DATA_FACTORY_REQUIRE_ADMIN", default) == "1"


_training_queue_publisher: PubSubPublisher | None = None


def _training_run_mode() -> str:
    env = os.getenv("ENV", "dev").lower()
    default = "inline" if env in {"dev", "local", "test"} else "queue"
    return os.getenv("TRAINING_RUN_MODE", default).strip().lower()


def _training_queue_topic() -> str | None:
    return os.getenv("TRAINING_QUEUE_TOPIC")


def _training_dlq_topic() -> str | None:
    return os.getenv("TRAINING_DLQ_TOPIC")


def _training_runner_token() -> str | None:
    return os.getenv("TRAINING_RUNNER_TOKEN")


def _training_sim_seconds() -> float:
    raw = os.getenv("TRAINING_SIM_SECONDS", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _training_queue_publisher_instance() -> PubSubPublisher:
    global _training_queue_publisher
    if _training_queue_publisher is None:
        _training_queue_publisher = PubSubPublisher()
    return _training_queue_publisher


def _enqueue_training_job(job: TrainingJob, reason: str) -> str:
    topic = _training_queue_topic()
    if not topic:
        raise RuntimeError("TRAINING_QUEUE_TOPIC is not configured")
    payload: dict[str, Any] = {"job_id": job.id, "reason": reason}
    token = _training_runner_token()
    if token:
        payload["token"] = token
    publisher = _training_queue_publisher_instance()
    return publisher.publish_json(topic=topic, payload=payload)


def _publish_training_dlq(payload: dict[str, Any]) -> None:
    topic = _training_dlq_topic()
    if not topic:
        return
    publisher = _training_queue_publisher_instance()
    publisher.publish_json(topic=topic, payload=payload)


def _training_runner_authorized(request: Request, payload: dict[str, Any]) -> None:
    token = _training_runner_token()
    if token:
        payload_token = payload.get("token")
        if payload_token != token:
            raise HTTPException(status_code=403, detail="Forbidden")
        return
    _authorize(request)


def _training_job_response(job: TrainingJob) -> TrainingJobResponse:
    spec = {
        "dataset_id": job.spec.dataset_id,
        "model_id": job.spec.model_id,
        "epochs": job.spec.epochs,
        "batch_size": job.spec.batch_size,
        "learning_rate": job.spec.learning_rate,
        "labels": list(job.spec.labels) if job.spec.labels else None,
    }
    return TrainingJobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        output=job.output,
        metrics=job.metrics,
        spec=spec,
    )


class _StubTrainingExecutor(TrainingExecutor):
    def execute(self, *, job: TrainingJob) -> TrainingResult:
        delay = _training_sim_seconds()
        if delay > 0:
            time.sleep(delay)
        return TrainingResult(
            status="completed",
            output={"message": "stub"},
            metrics={"epochs": job.spec.epochs},
        )


def _execute_training_job_inline(job: TrainingJob) -> TrainingJob:
    return execute_training_job(
        base_uri=_get_config().graph_root_uri(),
        job_id=job.id,
        executor=_StubTrainingExecutor(),
    )

def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=_require_admin(),
    )


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


def _ocr_connector_response(item) -> OcrConnectorResponse:
    return OcrConnectorResponse(
        id=item.id,
        name=item.name,
        url=item.url,
        auth_type=item.auth_type,
        auth_header=item.auth_header,
        token_env=item.token_env,
        enabled=item.enabled,
        is_default=item.is_default,
        max_pages=item.max_pages,
        timeout_s=item.timeout_s,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


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
) -> TrainingJobResponse:
    _authorize(request)
    job = register_training_job(
        base_uri=_get_config().graph_root_uri(),
        dataset_id=payload.dataset_id,
        model_id=payload.model_id,
        epochs=payload.epochs,
        batch_size=payload.batch_size,
        learning_rate=payload.learning_rate,
        labels=payload.labels,
    )
    if _training_run_mode() == "queue" and _training_queue_topic():
        try:
            _enqueue_training_job(job, reason="manual")
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        job = _execute_training_job_inline(job)
    return _training_job_response(job)


@app.get("/data-factory/training/jobs", response_model=list[TrainingJobResponse])
async def list_training_jobs_endpoint(
    request: Request,
    status: str | None = None,
    limit: int | None = None,
) -> list[TrainingJobResponse]:
    _authorize(request)
    jobs = list_training_jobs(
        _get_config().graph_root_uri(),
        status=status,
        limit=limit,
    )
    return [_training_job_response(job) for job in jobs]


@app.get(
    "/data-factory/training/jobs/{job_id}",
    response_model=TrainingJobResponse,
)
async def get_training_job_endpoint(
    request: Request,
    job_id: str,
) -> TrainingJobResponse:
    _authorize(request)
    job = get_training_job(_get_config().graph_root_uri(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    return _training_job_response(job)


@app.post(
    "/data-factory/training/runner",
    response_model=TrainingJobResponse,
)
async def training_runner(
    request: Request,
    body: dict[str, Any],
) -> TrainingJobResponse:
    envelope = parse_pubsub_push(body)
    try:
        payload = json.loads(envelope.message.data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    _training_runner_authorized(request, payload)
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")
    base_uri = _get_config().graph_root_uri()
    job = get_training_job(base_uri, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    try:
        updated = _execute_training_job_inline(job)
    except Exception as exc:
        mark_training_job_failed(
            base_uri=base_uri,
            job_id=job_id,
            error=str(exc),
        )
        _publish_training_dlq(
            {
                "job_id": job_id,
                "error": str(exc),
            }
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _training_job_response(updated)


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
async def register_ocr_connector_endpoint(
    request: Request,
    payload: OcrConnectorRequest,
) -> OcrConnectorResponse:
    _authorize(request)
    try:
        connector = register_ocr_connector(
            base_uri=_get_config().graph_root_uri(),
            name=payload.name,
            url=payload.url,
            auth_type=payload.auth_type,
            auth_header=payload.auth_header,
            token_env=payload.token_env,
            enabled=payload.enabled,
            is_default=payload.is_default,
            max_pages=payload.max_pages,
            timeout_s=payload.timeout_s,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ocr_connector_response(connector)


@app.get("/data-factory/ocr/connectors", response_model=list[OcrConnectorResponse])
async def list_ocr_connectors(request: Request) -> list[OcrConnectorResponse]:
    _authorize(request)
    connectors = load_ocr_connectors(_get_config().graph_root_uri())
    return [_ocr_connector_response(item) for item in connectors]


@app.post("/data-factory/convert-office", response_model=OfficeConversionResponse)
async def convert_office(
    request: Request,
    payload: OfficeConversionRequest,
) -> OfficeConversionResponse:
    _authorize(request)
    if not _is_office_filename(payload.filename):
        raise HTTPException(status_code=400, detail="Unsupported filename extension")
    mode = _resolve_conversion_mode(payload.queue)
    if mode == "disabled":
        raise HTTPException(status_code=503, detail="Office conversion disabled")

    base_uri = _get_config().graph_root_uri()
    job = create_job_record(
        filename=payload.filename,
        content_base64=payload.content_base64,
        status="queued" if mode == "queue" else "processing",
    )
    save_conversion_record(base_uri, job)

    if mode == "queue":
        topic = os.getenv("OFFICE_CONVERSION_TOPIC", "")
        if not topic:
            raise HTTPException(
                status_code=500,
                detail="OFFICE_CONVERSION_TOPIC is required for queue mode",
            )
        try:
            enqueue_conversion(
                topic=topic,
                payload={
                    "job_id": job.id,
                    "filename": job.filename,
                    "content_base64": job.content_base64,
                },
            )
        except Exception as exc:
            failed = update_job_record(job, status="failed", error=str(exc))
            save_conversion_record(base_uri, failed)
            raise HTTPException(
                status_code=500,
                detail="Failed to enqueue conversion job",
            ) from exc
        return OfficeConversionResponse(
            status="queued",
            output_filename=_output_filename(payload.filename),
            job_id=job.id,
            output_uri=None,
            message="Job queued for conversion",
        )

    try:
        content = decode_payload(payload.content_base64)
        validate_payload_size(content)
        output_bytes = convert_office_bytes(
            filename=payload.filename,
            content=content,
            backend=conversion_backend(),
        )
        output_uri = write_conversion_output(base_uri, job.id, output_bytes)
        completed = update_job_record(job, status="completed", output_uri=output_uri)
        save_conversion_record(base_uri, completed)
        return OfficeConversionResponse(
            status="completed",
            output_filename=_output_filename(payload.filename),
            content_base64=base64.b64encode(output_bytes).decode("utf-8"),
            job_id=job.id,
            output_uri=output_uri,
        )
    except PermanentError as exc:
        failed = update_job_record(job, status="failed", error=str(exc))
        save_conversion_record(base_uri, failed)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RecoverableError as exc:
        failed = update_job_record(job, status="failed", error=str(exc))
        save_conversion_record(base_uri, failed)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/data-factory/convert-office/{job_id}",
    response_model=OfficeConversionJobResponse,
)
async def get_conversion_job(
    request: Request,
    job_id: str,
) -> OfficeConversionJobResponse:
    _authorize(request)
    job = load_conversion_record(_get_config().graph_root_uri(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Conversion job not found")
    return OfficeConversionJobResponse(
        id=job.id,
        filename=job.filename,
        status=job.status,
        output_uri=job.output_uri,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.post("/data-factory/convert-office/worker")
async def office_conversion_worker(request: Request) -> dict[str, str]:
    body = await request.json()
    envelope = parse_pubsub_push(body)
    payload = json.loads(envelope.message.data.decode("utf-8"))
    job_id = str(payload.get("job_id", "")).strip()
    filename = str(payload.get("filename", "")).strip()
    content_base64 = str(payload.get("content_base64", "")).strip()
    if not job_id or not filename or not content_base64:
        raise HTTPException(status_code=400, detail="Invalid conversion payload")
    if not _is_office_filename(filename):
        raise HTTPException(status_code=400, detail="Unsupported filename extension")

    base_uri = _get_config().graph_root_uri()
    job = load_conversion_record(base_uri, job_id)
    if job is None:
        job = create_job_record(
            filename=filename,
            content_base64=content_base64,
            status="processing",
        )
    else:
        job = update_job_record(job, status="processing")
    save_conversion_record(base_uri, job)

    try:
        content = decode_payload(content_base64)
        validate_payload_size(content)
        output_bytes = convert_office_bytes(
            filename=filename,
            content=content,
            backend=conversion_backend(),
        )
        output_uri = write_conversion_output(base_uri, job.id, output_bytes)
        completed = update_job_record(job, status="completed", output_uri=output_uri)
        save_conversion_record(base_uri, completed)
        return {"status": "ok"}
    except PermanentError as exc:
        failed = update_job_record(job, status="failed", error=str(exc))
        save_conversion_record(base_uri, failed)
        _publish_conversion_dlq(payload, str(exc))
        return {"status": "dlq"}
    except RecoverableError as exc:
        failed = update_job_record(job, status="failed", error=str(exc))
        save_conversion_record(base_uri, failed)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _resolve_conversion_mode(queue_override: bool | None) -> str:
    if queue_override is True:
        return "queue"
    if queue_override is False:
        return "inline"
    return conversion_mode()


def _output_filename(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    return f"{stem}.pdf"


def _publish_conversion_dlq(payload: dict[str, Any], error: str) -> None:
    topic = os.getenv("OFFICE_CONVERSION_DLQ_TOPIC")
    if not topic:
        return
    try:
        publish_conversion_dlq(
            topic=topic,
            payload={
                "error": error,
                "payload": payload,
                "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
    except Exception:
        logger.exception("Failed to publish office conversion DLQ message")


def _is_office_filename(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in {".doc", ".docx", ".ppt", ".pptx"}
