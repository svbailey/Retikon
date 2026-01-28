import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from retikon_core.auth import AuthContext, authorize_api_key
from retikon_core.config import get_config
from retikon_core.errors import AuthError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.workflows import (
    WorkflowRun,
    WorkflowSpec,
    WorkflowStep,
    list_workflow_runs,
    load_workflows,
    register_workflow,
    register_workflow_run,
    update_workflow,
)

SERVICE_NAME = "retikon-workflows"

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


class WorkflowStepPayload(BaseModel):
    id: str | None = None
    name: str
    kind: str
    config: dict[str, object] | None = None
    retries: int | None = None
    timeout_seconds: int | None = None


class WorkflowRequest(BaseModel):
    name: str
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    schedule: str | None = None
    enabled: bool = True
    steps: list[WorkflowStepPayload] | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    steps: list[WorkflowStepPayload] | None = None


class WorkflowRunRequest(BaseModel):
    status: str | None = None
    finished_at: str | None = None
    error: str | None = None
    output: dict[str, object] | None = None
    triggered_by: str | None = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str | None
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    schedule: str | None
    enabled: bool
    steps: list[WorkflowStepPayload]
    created_at: str
    updated_at: str


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    output: dict[str, object] | None
    triggered_by: str | None


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
    return os.getenv("WORKFLOW_REQUIRE_ADMIN", default) == "1"


def _workflow_api_key() -> str | None:
    return os.getenv("WORKFLOW_API_KEY") or os.getenv("QUERY_API_KEY")


def _authorize(request: Request) -> AuthContext | None:
    raw_key = request.headers.get("x-api-key")
    try:
        context = authorize_api_key(
            base_uri=_get_config().graph_root_uri(),
            raw_key=raw_key,
            fallback_key=_workflow_api_key(),
            require=_api_key_required(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if _require_admin() and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def _get_config():
    return get_config()


def _step_from_payload(payload: WorkflowStepPayload) -> WorkflowStep:
    return WorkflowStep(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        kind=payload.kind,
        config=payload.config,
        retries=payload.retries,
        timeout_seconds=payload.timeout_seconds,
    )


def _workflow_response(workflow: WorkflowSpec) -> WorkflowResponse:
    steps = [
        WorkflowStepPayload(
            id=step.id,
            name=step.name,
            kind=step.kind,
            config=step.config,
            retries=step.retries,
            timeout_seconds=step.timeout_seconds,
        )
        for step in workflow.steps
    ]
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        org_id=workflow.org_id,
        site_id=workflow.site_id,
        stream_id=workflow.stream_id,
        schedule=workflow.schedule,
        enabled=workflow.enabled,
        steps=steps,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _run_response(run: WorkflowRun) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        output=run.output,
        triggered_by=run.triggered_by,
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


@app.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows_endpoint(request: Request) -> list[WorkflowResponse]:
    _authorize(request)
    workflows = load_workflows(_get_config().graph_root_uri())
    return [_workflow_response(workflow) for workflow in workflows]


@app.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    request: Request,
    payload: WorkflowRequest,
) -> WorkflowResponse:
    _authorize(request)
    steps = (
        tuple(_step_from_payload(step) for step in payload.steps)
        if payload.steps
        else ()
    )
    workflow = register_workflow(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        description=payload.description,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        schedule=payload.schedule,
        enabled=payload.enabled,
        steps=steps,
    )
    logger.info(
        "Workflow created",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.headers.get("x-correlation-id"),
            "workflow_id": workflow.id,
        },
    )
    return _workflow_response(workflow)


@app.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow_endpoint(
    request: Request,
    workflow_id: str,
    payload: WorkflowUpdateRequest,
) -> WorkflowResponse:
    _authorize(request)
    workflows = load_workflows(_get_config().graph_root_uri())
    existing = next((wf for wf in workflows if wf.id == workflow_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    now = datetime.now(timezone.utc).isoformat()
    steps = (
        tuple(_step_from_payload(step) for step in payload.steps)
        if payload.steps is not None
        else existing.steps
    )
    updated = WorkflowSpec(
        id=existing.id,
        name=payload.name or existing.name,
        description=payload.description
        if payload.description is not None
        else existing.description,
        org_id=payload.org_id if payload.org_id is not None else existing.org_id,
        site_id=payload.site_id if payload.site_id is not None else existing.site_id,
        stream_id=payload.stream_id
        if payload.stream_id is not None
        else existing.stream_id,
        schedule=payload.schedule
        if payload.schedule is not None
        else existing.schedule,
        enabled=payload.enabled if payload.enabled is not None else existing.enabled,
        steps=steps,
        created_at=existing.created_at,
        updated_at=now,
    )
    update_workflow(base_uri=_get_config().graph_root_uri(), workflow=updated)
    return _workflow_response(updated)


@app.get("/workflows/runs", response_model=list[WorkflowRunResponse])
async def list_runs(
    request: Request,
    workflow_id: str | None = None,
    limit: int | None = None,
) -> list[WorkflowRunResponse]:
    _authorize(request)
    runs = list_workflow_runs(
        _get_config().graph_root_uri(),
        workflow_id=workflow_id,
        limit=limit,
    )
    return [_run_response(run) for run in runs]


@app.post(
    "/workflows/{workflow_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=201,
)
async def create_run(
    request: Request,
    workflow_id: str,
    payload: WorkflowRunRequest,
) -> WorkflowRunResponse:
    _authorize(request)
    status = payload.status or "queued"
    run = register_workflow_run(
        base_uri=_get_config().graph_root_uri(),
        workflow_id=workflow_id,
        status=status,
        finished_at=payload.finished_at,
        error=payload.error,
        output=payload.output,
        triggered_by=payload.triggered_by,
    )
    return _run_response(run)
