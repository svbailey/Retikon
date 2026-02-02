import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gcp_adapter.auth import authorize_request
from gcp_adapter.stores import abac_allowed, get_control_plane_stores, is_action_allowed
from retikon_core.audit import record_audit_log
from retikon_core.auth import AuthContext
from retikon_core.auth.rbac import (
    ACTION_PRIVACY_POLICY_CREATE,
    ACTION_PRIVACY_POLICY_LIST,
    ACTION_PRIVACY_POLICY_UPDATE,
)
from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger
from retikon_core.privacy import PrivacyPolicy
from retikon_core.services.fastapi_scaffolding import (
    HealthResponse,
    apply_cors_middleware,
    build_health_response,
)

SERVICE_NAME = "retikon-privacy"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()
apply_cors_middleware(app)


class PrivacyPolicyRequest(BaseModel):
    name: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    modalities: list[str] | None = None
    contexts: list[str] | None = None
    redaction_types: list[str] | None = None
    enabled: bool = True
    status: str | None = None


class PrivacyPolicyUpdateRequest(BaseModel):
    name: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    modalities: list[str] | None = None
    contexts: list[str] | None = None
    redaction_types: list[str] | None = None
    enabled: bool | None = None
    status: str | None = None


class PrivacyPolicyResponse(BaseModel):
    id: str
    name: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    modalities: list[str] | None = None
    contexts: list[str] | None = None
    redaction_types: list[str] | None = None
    enabled: bool
    created_at: str
    updated_at: str
    status: str


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("PRIVACY_REQUIRE_ADMIN", default) == "1"


def _authorize(request: Request) -> AuthContext | None:
    return authorize_request(
        request=request,
        require_admin=_require_admin(),
    )


def _get_config():
    return get_config()


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


def _stores():
    return get_control_plane_stores(_get_config().graph_root_uri())


def _policy_response(policy: PrivacyPolicy) -> PrivacyPolicyResponse:
    return PrivacyPolicyResponse(
        id=policy.id,
        name=policy.name,
        org_id=policy.org_id,
        site_id=policy.site_id,
        stream_id=policy.stream_id,
        modalities=list(policy.modalities) if policy.modalities else None,
        contexts=list(policy.contexts) if policy.contexts else None,
        redaction_types=list(policy.redaction_types)
        if policy.redaction_types
        else None,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        status=policy.status,
    )


def _normalize_list(values: list[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    cleaned = [value.strip().lower() for value in values if value.strip()]
    if not cleaned:
        return None
    deduped: list[str] = []
    for item in cleaned:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return build_health_response(SERVICE_NAME)


@app.get("/privacy/policies", response_model=list[PrivacyPolicyResponse])
async def list_policies(request: Request) -> list[PrivacyPolicyResponse]:
    auth_context = _authorize(request)
    _enforce_access(ACTION_PRIVACY_POLICY_LIST, auth_context)
    trace_id = _request_id(request)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="privacy.policy.list",
        decision="allow",
        request_id=trace_id,
    )
    policies = _stores().privacy.load_policies()
    return [_policy_response(policy) for policy in policies]


@app.post(
    "/privacy/policies",
    response_model=PrivacyPolicyResponse,
    status_code=201,
)
async def create_policy(
    request: Request,
    payload: PrivacyPolicyRequest,
) -> PrivacyPolicyResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_PRIVACY_POLICY_CREATE, auth_context)
    trace_id = _request_id(request)
    policy = _stores().privacy.register_policy(
        name=payload.name,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        modalities=payload.modalities,
        contexts=payload.contexts,
        redaction_types=payload.redaction_types,
        enabled=payload.enabled,
        status=payload.status or "active",
    )
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="privacy.policy.create",
        decision="allow",
        request_id=trace_id,
    )
    logger.info(
        "Privacy policy created",
        extra={
            "request_id": trace_id,
            "correlation_id": request.headers.get("x-correlation-id"),
            "policy_id": policy.id,
        },
    )
    return _policy_response(policy)


@app.put("/privacy/policies/{policy_id}", response_model=PrivacyPolicyResponse)
async def update_policy(
    request: Request,
    policy_id: str,
    payload: PrivacyPolicyUpdateRequest,
) -> PrivacyPolicyResponse:
    auth_context = _authorize(request)
    _enforce_access(ACTION_PRIVACY_POLICY_UPDATE, auth_context)
    trace_id = _request_id(request)
    policies = _stores().privacy.load_policies()
    existing = next((policy for policy in policies if policy.id == policy_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    updated = PrivacyPolicy(
        id=existing.id,
        name=payload.name or existing.name,
        org_id=payload.org_id if payload.org_id is not None else existing.org_id,
        site_id=payload.site_id if payload.site_id is not None else existing.site_id,
        stream_id=payload.stream_id
        if payload.stream_id is not None
        else existing.stream_id,
        modalities=_normalize_list(payload.modalities)
        if payload.modalities is not None
        else existing.modalities,
        contexts=_normalize_list(payload.contexts)
        if payload.contexts is not None
        else existing.contexts,
        redaction_types=_normalize_list(payload.redaction_types)
        if payload.redaction_types is not None
        else existing.redaction_types,
        enabled=payload.enabled if payload.enabled is not None else existing.enabled,
        created_at=existing.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
        status=payload.status if payload.status is not None else existing.status,
    )
    _stores().privacy.update_policy(policy=updated)
    _record_audit(
        request=request,
        auth_context=auth_context,
        action="privacy.policy.update",
        decision="allow",
        request_id=trace_id,
    )
    return _policy_response(updated)
