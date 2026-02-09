import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gcp_adapter.auth import authorize_internal_service_account, authorize_request
from gcp_adapter.queue_pubsub import PubSubPublisher, parse_pubsub_push
from gcp_adapter.stores import abac_allowed, get_control_plane_stores, is_action_allowed
from retikon_core.audit import record_audit_log
from retikon_core.auth import AuthContext
from retikon_core.auth.rbac import (
    ACTION_WORKFLOWS_CREATE,
    ACTION_WORKFLOWS_LIST,
    ACTION_WORKFLOWS_RUN_CREATE,
    ACTION_WORKFLOWS_RUNS_LIST,
    ACTION_WORKFLOWS_SCHEDULE_TICK,
    ACTION_WORKFLOWS_UPDATE,
)
from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    apply_cors_middleware,
    build_health_response,
)
from retikon_core.workflows import (
    WorkflowRun,
    WorkflowSpec,
    WorkflowStep,
)

SERVICE_NAME = "retikon-workflows"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)


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
    status: str | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    steps: list[WorkflowStepPayload] | None = None
    status: str | None = None


class WorkflowRunRequest(BaseModel):
    execute: bool | None = None
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
    status: str


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    output: dict[str, object] | None
    triggered_by: str | None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ScheduleTickResponse(BaseModel):
    triggered: int
    skipped: int
    run_ids: list[str]


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("WORKFLOW_REQUIRE_ADMIN", default) == "1"


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=_require_admin(),
    )


def _authorize_internal(request: Request) -> AuthContext:
    context = authorize_internal_service_account(request)
    if context is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return context


def _authorize_tick(request: Request) -> AuthContext:
    try:
        return _authorize(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    return _authorize_internal(request)


def _get_config():
    return get_config()


def _stores(base_uri: str | None = None):
    if base_uri is None:
        base_uri = _get_config().graph_root_uri()
    return get_control_plane_stores(base_uri)


def _rbac_enabled() -> bool:
    return os.getenv("RBAC_ENFORCE", "0") == "1"


def _abac_enabled() -> bool:
    return os.getenv("ABAC_ENFORCE", "0") == "1"


def _enforce_access(
    action: str,
    auth_context: AuthContext | None,
) -> None:
    base_uri = _get_config().graph_root_uri()
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
        status=workflow.status,
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
        org_id=run.org_id,
        site_id=run.site_id,
        stream_id=run.stream_id,
        created_at=run.created_at or None,
        updated_at=run.updated_at or None,
    )


_queue_publisher: PubSubPublisher | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _run_mode() -> str:
    override = os.getenv("WORKFLOW_RUN_MODE")
    if override:
        return override.strip().lower()
    env = os.getenv("ENV", "dev").lower()
    return "inline" if env in {"dev", "local", "test"} else "queue"


def _queue_topic() -> str | None:
    return os.getenv("WORKFLOW_QUEUE_TOPIC")


def _dlq_topic() -> str | None:
    return os.getenv("WORKFLOW_DLQ_TOPIC")


def _queue_publisher_instance() -> PubSubPublisher:
    global _queue_publisher
    if _queue_publisher is None:
        _queue_publisher = PubSubPublisher()
    return _queue_publisher


def _enqueue_run(*, run: WorkflowRun, workflow: WorkflowSpec, reason: str) -> str:
    topic = _queue_topic()
    if not topic:
        raise RuntimeError("WORKFLOW_QUEUE_TOPIC is not configured")
    payload = {
        "workflow_id": workflow.id,
        "run_id": run.id,
        "triggered_by": run.triggered_by,
        "reason": reason,
    }
    message_id = _queue_publisher_instance().publish_json(topic=topic, payload=payload)
    logger.info(
        "Enqueued workflow run",
        extra={
            "workflow_id": workflow.id,
            "run_id": run.id,
            "message_id": message_id,
            "reason": reason,
        },
    )
    return message_id


def _publish_dlq(*, run: WorkflowRun, workflow: WorkflowSpec, error: str) -> str | None:
    topic = _dlq_topic()
    if not topic:
        return None
    payload = {
        "workflow_id": workflow.id,
        "run_id": run.id,
        "status": run.status,
        "error": error,
        "triggered_by": run.triggered_by,
        "finished_at": run.finished_at,
    }
    message_id = _queue_publisher_instance().publish_json(topic=topic, payload=payload)
    logger.warning(
        "Published workflow DLQ message",
        extra={
            "workflow_id": workflow.id,
            "run_id": run.id,
            "message_id": message_id,
        },
    )
    return message_id


def _cron_field_match(
    field: str,
    value: int,
    *,
    min_value: int,
    max_value: int,
) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        if step <= 0:
            return False
        return value % step == 0
    if "," in field:
        return any(
            _cron_field_match(
                part.strip(),
                value,
                min_value=min_value,
                max_value=max_value,
            )
            for part in field.split(",")
            if part.strip()
        )
    if field.isdigit():
        number = int(field)
        if number < min_value or number > max_value:
            return False
        return value == number
    return False


def _cron_matches(schedule: str, now: datetime) -> bool:
    parts = [part for part in schedule.split(" ") if part]
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    if not _cron_field_match(minute, now.minute, min_value=0, max_value=59):
        return False
    if not _cron_field_match(hour, now.hour, min_value=0, max_value=23):
        return False
    if not _cron_field_match(dom, now.day, min_value=1, max_value=31):
        return False
    if not _cron_field_match(month, now.month, min_value=1, max_value=12):
        return False
    python_dow = now.weekday()  # Mon=0..Sun=6
    cron_dow = (python_dow + 1) % 7  # Mon=1..Sun=0
    if dow == "7":
        dow = "0"
    return _cron_field_match(dow, cron_dow, min_value=0, max_value=6)


def _interval_seconds(schedule: str) -> float | None:
    raw = schedule.strip().lower()
    for prefix in ("every ", "interval "):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if not raw:
        return None
    unit = raw[-1]
    if unit not in {"s", "m", "h", "d"}:
        return None
    try:
        value = float(raw[:-1])
    except ValueError:
        return None
    if value <= 0:
        return None
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    return value * 86400


def _schedule_due(schedule: str, *, last_run: datetime | None, now: datetime) -> bool:
    interval = _interval_seconds(schedule)
    if interval is not None:
        if last_run is None:
            return True
        return (now - last_run).total_seconds() >= interval
    if schedule.startswith("@"):
        mapping = {
            "@hourly": 3600,
            "@daily": 86400,
            "@weekly": 604800,
        }
        interval_value = mapping.get(schedule)
        if interval_value is None:
            return False
        if last_run is None:
            return True
        return (now - last_run).total_seconds() >= interval_value
    if not _cron_matches(schedule, now):
        return False
    if last_run is None:
        return True
    last_minute = last_run.replace(second=0, microsecond=0)
    now_minute = now.replace(second=0, microsecond=0)
    return last_minute < now_minute


def _step_timeout(step: WorkflowStep) -> float:
    if step.timeout_seconds is not None:
        return float(step.timeout_seconds)
    default = os.getenv("WORKFLOW_STEP_TIMEOUT", "30")
    try:
        return float(default)
    except ValueError:
        return 30.0


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _coerce_mapping(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        result[str(key)] = str(item)
    return result


def _append_query_params(url: str, params: dict[str, object]) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query))
    for key, value in params.items():
        existing[str(key)] = str(value)
    query = urlencode(existing)
    return urlunparse(parsed._replace(query=query))


def _resolve_step_url(
    step: WorkflowStep,
    config: dict[str, object] | None,
) -> str | None:
    from_config = _coerce_str(config.get("url")) if config else None
    if from_config:
        return from_config
    kind = step.kind.lower()
    if kind == "ingest":
        return _coerce_str(os.getenv("WORKFLOW_INGEST_URL"))
    if kind == "export":
        return _coerce_str(os.getenv("WORKFLOW_EXPORT_URL"))
    if kind == "webhook":
        return _coerce_str(os.getenv("WORKFLOW_WEBHOOK_URL"))
    if kind == "http":
        return _coerce_str(os.getenv("WORKFLOW_HTTP_URL"))
    return None


def _default_step_method(step: WorkflowStep) -> str:
    if step.kind.lower() == "export":
        return "GET"
    return "POST"


def _execute_http_step(step: WorkflowStep) -> dict[str, object]:
    config = step.config or {}
    url = _resolve_step_url(step, config)
    if not url:
        raise ValueError(f"Missing URL for workflow step {step.id}")
    params = config.get("params")
    if isinstance(params, dict):
        url = _append_query_params(url, params)
    method = _coerce_str(config.get("method")) or _default_step_method(step)
    headers = _coerce_mapping(config.get("headers")) or {}
    auth_token = _coerce_str(config.get("auth_token")) or _coerce_str(
        os.getenv("WORKFLOW_AUTH_TOKEN")
    )
    auth_header = _coerce_str(config.get("auth_header"))
    if auth_token:
        header_name = auth_header or "Authorization"
        header_value = auth_token
        if header_name.lower() == "authorization" and not auth_token.lower().startswith(
            "bearer "
        ):
            header_value = f"Bearer {auth_token}"
        headers[header_name] = header_value
    body = config.get("payload")
    if body is None:
        body = config.get("body")
    data: bytes | None = None
    if body is not None and method.upper() not in {"GET", "HEAD"}:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            data = str(body).encode("utf-8")
    timeout = _step_timeout(step)
    request = UrlRequest(url, data=data, method=method.upper())
    for key, value in headers.items():
        request.add_header(key, value)
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {"status_code": status_code, "elapsed_ms": elapsed_ms, "url": url}
    except HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        raise RuntimeError(f"HTTP {exc.code} ({elapsed_ms}ms)") from exc
    except URLError as exc:
        raise RuntimeError(f"HTTP request failed: {exc.reason}") from exc


def _execute_step_once(step: WorkflowStep) -> dict[str, object]:
    kind = step.kind.lower()
    if kind == "delay":
        config = step.config or {}
        seconds = _coerce_float(config.get("seconds"))
        if seconds is None:
            seconds = _coerce_float(config.get("delay_seconds"))
        seconds = seconds or 0.0
        if seconds > 0:
            time.sleep(seconds)
        return {"delay_seconds": seconds}
    if kind in {"webhook", "http", "ingest", "export"}:
        return _execute_http_step(step)
    if kind == "noop":
        return {"status": "noop"}
    raise ValueError(f"Unsupported workflow step kind: {step.kind}")


def _step_retry_delay(step: WorkflowStep) -> float:
    config = step.config or {}
    delay = _coerce_float(config.get("retry_delay_seconds"))
    if delay is not None:
        return delay
    return 0.0


def _execute_step(step: WorkflowStep) -> dict[str, object]:
    retries = step.retries or 0
    attempts = 0
    delay = _step_retry_delay(step)
    while True:
        attempts += 1
        started_at = _now_iso()
        try:
            output = _execute_step_once(step)
            finished_at = _now_iso()
            return {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "status": "completed",
                "attempts": attempts,
                "started_at": started_at,
                "finished_at": finished_at,
                "output": output,
            }
        except Exception as exc:
            error = str(exc)
            finished_at = _now_iso()
            if attempts <= retries:
                if delay > 0:
                    time.sleep(delay)
                continue
            return {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "status": "failed",
                "attempts": attempts,
                "started_at": started_at,
                "finished_at": finished_at,
                "error": error,
            }


def _find_workflow(
    workflows: Iterable[WorkflowSpec],
    workflow_id: str,
) -> WorkflowSpec | None:
    return next(
        (workflow for workflow in workflows if workflow.id == workflow_id),
        None,
    )


def _find_run(runs: Iterable[WorkflowRun], run_id: str) -> WorkflowRun | None:
    return next((run for run in runs if run.id == run_id), None)


def _update_run(
    *,
    base_uri: str,
    run: WorkflowRun,
    status: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
    output: dict[str, object] | None = None,
) -> WorkflowRun:
    now = _now_iso()
    updated = WorkflowRun(
        id=run.id,
        workflow_id=run.workflow_id,
        status=status or run.status,
        started_at=started_at or run.started_at,
        finished_at=finished_at or run.finished_at,
        error=error if error is not None else run.error,
        output=output if output is not None else run.output,
        triggered_by=run.triggered_by,
        org_id=run.org_id,
        site_id=run.site_id,
        stream_id=run.stream_id,
        created_at=run.created_at,
        updated_at=now,
    )
    _stores(base_uri).workflows.update_workflow_run(run=updated)
    return updated


def _execute_workflow_run(
    *,
    base_uri: str,
    workflow: WorkflowSpec,
    run: WorkflowRun,
) -> WorkflowRun:
    if run.status in {"completed", "failed"}:
        return run
    running = _update_run(
        base_uri=base_uri,
        run=run,
        status="running",
        started_at=_now_iso(),
        finished_at=None,
        error=None,
    )
    step_results: list[dict[str, object]] = []
    error: str | None = None
    for step in workflow.steps:
        result = _execute_step(step)
        step_results.append(result)
        if result.get("status") != "completed":
            error = str(result.get("error") or "Step failed")
            break
    status = "completed" if error is None else "failed"
    finished = _update_run(
        base_uri=base_uri,
        run=running,
        status=status,
        finished_at=_now_iso(),
        error=error,
        output={"steps": step_results},
    )
    if status == "failed" and error:
        _publish_dlq(run=finished, workflow=workflow, error=error)
    return finished


def _runner_authorized(request: Request) -> None:
    _authorize_tick(request)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/workflows", response_model=list[WorkflowResponse])
async def list_workflows_endpoint(request: Request) -> list[WorkflowResponse]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_WORKFLOWS_LIST, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.list",
        decision="allow",
        request_id=trace_id,
    )
    workflows = _stores().workflows.load_workflows()
    return [_workflow_response(workflow) for workflow in workflows]


@app.post("/workflows", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    request: Request,
    payload: WorkflowRequest,
) -> WorkflowResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_WORKFLOWS_CREATE, auth_context)
    trace_id = _request_id(request)
    steps = (
        tuple(_step_from_payload(step) for step in payload.steps)
        if payload.steps
        else ()
    )
    workflow = _stores().workflows.register_workflow(
        name=payload.name,
        description=payload.description,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        schedule=payload.schedule,
        enabled=payload.enabled,
        steps=steps,
        status=payload.status or "active",
    )
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.create",
        decision="allow",
        request_id=trace_id,
    )
    logger.info(
        "Workflow created",
        extra={
            "request_id": trace_id,
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
    auth_context = _authorize(request)
    _enforce_access(ACTION_WORKFLOWS_UPDATE, auth_context)
    trace_id = _request_id(request)
    workflows = _stores().workflows.load_workflows()
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
        status=payload.status if payload.status is not None else existing.status,
    )
    _stores().workflows.update_workflow(workflow=updated)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.update",
        decision="allow",
        request_id=trace_id,
    )
    return _workflow_response(updated)


@app.get("/workflows/runs", response_model=list[WorkflowRunResponse])
async def list_runs(
    request: Request,
    workflow_id: str | None = None,
    limit: int | None = None,
) -> list[WorkflowRunResponse]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_WORKFLOWS_RUNS_LIST, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.runs.list",
        decision="allow",
        request_id=trace_id,
    )
    runs = _stores().workflows.list_workflow_runs(
        workflow_id=workflow_id,
        limit=limit,
    )
    return [_run_response(run) for run in runs]


@app.post("/workflows/schedule/tick", response_model=ScheduleTickResponse)
async def schedule_tick(
    request: Request,
    dry_run: bool = False,
) -> ScheduleTickResponse:
    auth_context = _authorize_tick(request)
    _enforce_access(ACTION_WORKFLOWS_SCHEDULE_TICK, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.schedule.tick",
        decision="allow",
        request_id=trace_id,
    )
    base_uri = _get_config().graph_root_uri()
    workflows = _stores(base_uri).workflows.load_workflows()
    runs = _stores(base_uri).workflows.load_workflow_runs()
    now = datetime.now(timezone.utc)
    active = {run.workflow_id for run in runs if run.status in {"queued", "running"}}
    last_run: dict[str, datetime] = {}
    for run in runs:
        parsed = _parse_iso(run.started_at)
        if parsed is None:
            continue
        existing = last_run.get(run.workflow_id)
        if existing is None or parsed > existing:
            last_run[run.workflow_id] = parsed

    triggered: list[str] = []
    skipped = 0
    for workflow in workflows:
        if not workflow.enabled or not workflow.schedule:
            continue
        if workflow.id in active:
            skipped += 1
            continue
        due = _schedule_due(
            workflow.schedule,
            last_run=last_run.get(workflow.id),
            now=now,
        )
        if not due:
            continue
        if dry_run:
            triggered.append(workflow.id)
            continue
        run = _stores(base_uri).workflows.register_workflow_run(
            workflow_id=workflow.id,
            status="queued",
            triggered_by="schedule",
            org_id=workflow.org_id,
            site_id=workflow.site_id,
            stream_id=workflow.stream_id,
        )
        if _run_mode() == "queue" and _queue_topic():
            _enqueue_run(run=run, workflow=workflow, reason="schedule")
        else:
            run = _execute_workflow_run(base_uri=base_uri, workflow=workflow, run=run)
        triggered.append(run.id)
    return ScheduleTickResponse(
        triggered=len(triggered),
        skipped=skipped,
        run_ids=triggered,
    )


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
    auth_context = _authorize(request)
    _enforce_access(ACTION_WORKFLOWS_RUN_CREATE, auth_context)
    trace_id = _request_id(request)
    base_uri = _get_config().graph_root_uri()
    workflows = _stores(base_uri).workflows.load_workflows()
    workflow = _find_workflow(workflows, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    status = payload.status or "queued"
    run = _stores(base_uri).workflows.register_workflow_run(
        workflow_id=workflow_id,
        status=status,
        finished_at=payload.finished_at,
        error=payload.error,
        output=payload.output,
        triggered_by=payload.triggered_by,
        org_id=workflow.org_id,
        site_id=workflow.site_id,
        stream_id=workflow.stream_id,
    )
    execute = payload.execute if payload.execute is not None else True
    if execute:
        if _run_mode() == "queue" and _queue_topic():
            _enqueue_run(run=run, workflow=workflow, reason="manual")
        else:
            run = _execute_workflow_run(base_uri=base_uri, workflow=workflow, run=run)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="workflows.run.create",
        decision="allow",
        request_id=trace_id,
    )
    return _run_response(run)


@app.post("/workflows/runner", response_model=WorkflowRunResponse)
async def workflow_runner(
    request: Request,
    body: dict[str, Any],
) -> WorkflowRunResponse:
    envelope = parse_pubsub_push(body)
    try:
        payload = json.loads(envelope.message.data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    _runner_authorized(request)
    workflow_id = _coerce_str(payload.get("workflow_id"))
    run_id = _coerce_str(payload.get("run_id"))
    if not workflow_id or not run_id:
        raise HTTPException(status_code=400, detail="Missing workflow_id or run_id")
    base_uri = _get_config().graph_root_uri()
    workflows = _stores(base_uri).workflows.load_workflows()
    runs = _stores(base_uri).workflows.load_workflow_runs()
    workflow = _find_workflow(workflows, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run = _find_run(runs, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    updated = _execute_workflow_run(base_uri=base_uri, workflow=workflow, run=run)
    return _run_response(updated)
