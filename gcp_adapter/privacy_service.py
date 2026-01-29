import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from retikon_core.auth import AuthContext, authorize_api_key
from retikon_core.config import get_config
from retikon_core.errors import AuthError
from retikon_core.logging import configure_logging, get_logger
from retikon_core.privacy import (
    PrivacyPolicy,
    load_privacy_policies,
    register_privacy_policy,
    update_privacy_policy,
)
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


class PrivacyPolicyUpdateRequest(BaseModel):
    name: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    modalities: list[str] | None = None
    contexts: list[str] | None = None
    redaction_types: list[str] | None = None
    enabled: bool | None = None


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


def _api_key_required() -> bool:
    env = os.getenv("ENV", "dev").lower()
    return env not in {"dev", "local", "test"}


def _require_admin() -> bool:
    env = os.getenv("ENV", "dev").lower()
    default = "0" if env in {"dev", "local", "test"} else "1"
    return os.getenv("PRIVACY_REQUIRE_ADMIN", default) == "1"


def _privacy_api_key() -> str | None:
    return os.getenv("PRIVACY_API_KEY") or os.getenv("QUERY_API_KEY")


def _authorize(request: Request) -> AuthContext | None:
    raw_key = request.headers.get("x-api-key")
    try:
        context = authorize_api_key(
            base_uri=_get_config().graph_root_uri(),
            raw_key=raw_key,
            fallback_key=_privacy_api_key(),
            require=_api_key_required(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if _require_admin() and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def _get_config():
    return get_config()


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
    _authorize(request)
    policies = load_privacy_policies(_get_config().graph_root_uri())
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
    _authorize(request)
    policy = register_privacy_policy(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        modalities=payload.modalities,
        contexts=payload.contexts,
        redaction_types=payload.redaction_types,
        enabled=payload.enabled,
    )
    logger.info(
        "Privacy policy created",
        extra={
            "request_id": str(uuid.uuid4()),
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
    _authorize(request)
    base_uri = _get_config().graph_root_uri()
    policies = load_privacy_policies(base_uri)
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
    )
    update_privacy_policy(base_uri=base_uri, policy=updated)
    return _policy_response(updated)
