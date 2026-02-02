import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gcp_adapter.auth import authorize_request
from retikon_core.audit import record_audit_log
from retikon_core.auth import AuthContext
from retikon_core.chaos import (
    ChaosPolicy,
    ChaosRun,
    ChaosStep,
    allowed_step_kinds,
    list_chaos_runs,
    load_chaos_policies,
    max_duration_limit_minutes,
    max_percent_impact_limit,
    register_chaos_policy,
    register_chaos_run,
    update_chaos_policy,
)
from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    apply_cors_middleware,
    build_health_response,
)

SERVICE_NAME = "retikon-chaos"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)


class ChaosStepPayload(BaseModel):
    id: str | None = None
    name: str
    kind: str
    target: str | None = None
    percent: int | None = None
    duration_seconds: int | None = None
    jitter_ms: int | None = None
    metadata: dict[str, object] | None = None


class ChaosPolicyRequest(BaseModel):
    name: str
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    schedule: str | None = None
    enabled: bool = True
    max_duration_minutes: int | None = None
    max_percent_impact: int | None = None
    steps: list[ChaosStepPayload] | None = None
    status: str | None = None


class ChaosPolicyUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    max_duration_minutes: int | None = None
    max_percent_impact: int | None = None
    steps: list[ChaosStepPayload] | None = None
    status: str | None = None


class ChaosRunRequest(BaseModel):
    status: str | None = None
    finished_at: str | None = None
    error: str | None = None
    summary: dict[str, object] | None = None
    triggered_by: str | None = None


class ChaosPolicyResponse(BaseModel):
    id: str
    name: str
    description: str | None
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    schedule: str | None
    enabled: bool
    max_duration_minutes: int
    max_percent_impact: int
    steps: list[ChaosStepPayload]
    created_at: str
    updated_at: str
    status: str


class ChaosRunResponse(BaseModel):
    id: str
    policy_id: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    summary: dict[str, object] | None
    triggered_by: str | None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("CHAOS_REQUIRE_ADMIN", default) == "1"


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=_require_admin(),
    )


def _get_config():
    return get_config()


def _audit_logging_enabled() -> bool:
    return os.getenv("AUDIT_LOGGING_ENABLED", "1") == "1"


def _schema_version() -> str:
    return os.getenv("SCHEMA_VERSION", "1")


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid.uuid4())


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
            base_uri=_get_config().graph_root_uri(),
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


def _step_from_payload(payload: ChaosStepPayload) -> ChaosStep:
    return ChaosStep(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        kind=payload.kind,
        target=payload.target,
        percent=payload.percent,
        duration_seconds=payload.duration_seconds,
        jitter_ms=payload.jitter_ms,
        metadata=payload.metadata,
    )


def _policy_response(policy: ChaosPolicy) -> ChaosPolicyResponse:
    steps = [
        ChaosStepPayload(
            id=step.id,
            name=step.name,
            kind=step.kind,
            target=step.target,
            percent=step.percent,
            duration_seconds=step.duration_seconds,
            jitter_ms=step.jitter_ms,
            metadata=step.metadata,
        )
        for step in policy.steps
    ]
    return ChaosPolicyResponse(
        id=policy.id,
        name=policy.name,
        description=policy.description,
        org_id=policy.org_id,
        site_id=policy.site_id,
        stream_id=policy.stream_id,
        schedule=policy.schedule,
        enabled=policy.enabled,
        max_duration_minutes=policy.max_duration_minutes,
        max_percent_impact=policy.max_percent_impact,
        steps=steps,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        status=policy.status,
    )


def _run_response(run: ChaosRun) -> ChaosRunResponse:
    return ChaosRunResponse(
        id=run.id,
        policy_id=run.policy_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        summary=run.summary,
        triggered_by=run.triggered_by,
        org_id=run.org_id,
        site_id=run.site_id,
        stream_id=run.stream_id,
        created_at=run.created_at or None,
        updated_at=run.updated_at or None,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/chaos/policies", response_model=list[ChaosPolicyResponse])
async def list_policies(request: Request) -> list[ChaosPolicyResponse]:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.policy.list",
        decision="allow",
        request_id=trace_id,
    )
    policies = load_chaos_policies(_get_config().graph_root_uri())
    return [_policy_response(policy) for policy in policies]


@app.post("/chaos/policies", response_model=ChaosPolicyResponse, status_code=201)
async def create_policy(
    request: Request,
    payload: ChaosPolicyRequest,
) -> ChaosPolicyResponse:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    steps = (
        tuple(_step_from_payload(step) for step in payload.steps)
        if payload.steps
        else ()
    )
    policy = register_chaos_policy(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        description=payload.description,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        schedule=payload.schedule,
        enabled=payload.enabled,
        max_duration_minutes=payload.max_duration_minutes,
        max_percent_impact=payload.max_percent_impact,
        steps=steps,
        status=payload.status or "active",
    )
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.policy.create",
        decision="allow",
        request_id=trace_id,
    )
    logger.info(
        "Chaos policy created",
        extra={
            "request_id": trace_id,
            "correlation_id": request.headers.get("x-correlation-id"),
            "policy_id": policy.id,
        },
    )
    return _policy_response(policy)


@app.put("/chaos/policies/{policy_id}", response_model=ChaosPolicyResponse)
async def update_policy(
    request: Request,
    policy_id: str,
    payload: ChaosPolicyUpdateRequest,
) -> ChaosPolicyResponse:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    policies = load_chaos_policies(_get_config().graph_root_uri())
    existing = next((policy for policy in policies if policy.id == policy_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    now = datetime.now(timezone.utc).isoformat()
    steps = (
        tuple(_step_from_payload(step) for step in payload.steps)
        if payload.steps is not None
        else existing.steps
    )
    updated = ChaosPolicy(
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
        max_duration_minutes=payload.max_duration_minutes
        if payload.max_duration_minutes is not None
        else existing.max_duration_minutes,
        max_percent_impact=payload.max_percent_impact
        if payload.max_percent_impact is not None
        else existing.max_percent_impact,
        steps=steps,
        created_at=existing.created_at,
        updated_at=now,
        status=payload.status if payload.status is not None else existing.status,
    )
    update_chaos_policy(base_uri=_get_config().graph_root_uri(), policy=updated)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.policy.update",
        decision="allow",
        request_id=trace_id,
    )
    return _policy_response(updated)


@app.get("/chaos/runs", response_model=list[ChaosRunResponse])
async def list_runs(
    request: Request,
    policy_id: str | None = None,
    limit: int | None = None,
) -> list[ChaosRunResponse]:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.run.list",
        decision="allow",
        request_id=trace_id,
    )
    runs = list_chaos_runs(
        _get_config().graph_root_uri(),
        policy_id=policy_id,
        limit=limit,
    )
    return [_run_response(run) for run in runs]


@app.post(
    "/chaos/policies/{policy_id}/runs",
    response_model=ChaosRunResponse,
    status_code=201,
)
async def create_run(
    request: Request,
    policy_id: str,
    payload: ChaosRunRequest,
) -> ChaosRunResponse:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    run = register_chaos_run(
        base_uri=_get_config().graph_root_uri(),
        policy_id=policy_id,
        status=payload.status or "queued",
        finished_at=payload.finished_at,
        error=payload.error,
        summary=payload.summary,
        triggered_by=payload.triggered_by,
    )
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.run.create",
        decision="allow",
        request_id=trace_id,
    )
    return _run_response(run)


@app.get("/chaos/config")
async def chaos_config(request: Request) -> dict[str, object]:
    auth_context = _authorize(request)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="chaos.config.read",
        decision="allow",
        request_id=trace_id,
    )
    return {
        "allowed_step_kinds": list(allowed_step_kinds()),
        "max_percent_impact": max_percent_impact_limit(),
        "max_duration_minutes": max_duration_limit_minutes(),
    }
