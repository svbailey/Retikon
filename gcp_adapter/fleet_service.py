import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from retikon_core.auth import AuthContext, authorize_api_key
from retikon_core.config import get_config
from retikon_core.errors import AuthError
from retikon_core.fleet import (
    DeviceRecord,
    device_hardening,
    load_devices,
    plan_rollout,
    register_device,
    rollback_plan,
    update_device_status,
)
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-fleet"

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


class DeviceCreateRequest(BaseModel):
    name: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    tags: list[str] | None = None
    status: str = "unknown"
    firmware_version: str | None = None
    last_seen_at: str | None = None
    metadata: dict[str, object] | None = None


class DeviceStatusRequest(BaseModel):
    status: str
    last_seen_at: str | None = None


class DeviceResponse(BaseModel):
    id: str
    name: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    tags: list[str] | None = None
    status: str
    firmware_version: str | None = None
    last_seen_at: str | None = None
    metadata: dict[str, object] | None = None
    created_at: str
    updated_at: str


class RolloutRequest(BaseModel):
    stage_percentages: list[int] | None = None
    max_per_stage: int | None = Field(default=None, ge=1)
    status_filter: str | None = None


class RolloutStageResponse(BaseModel):
    stage: int
    percent: int
    target_count: int
    device_ids: list[str]


class RolloutResponse(BaseModel):
    total_devices: int
    stages: list[RolloutStageResponse]


class RollbackRequest(BaseModel):
    stage: int
    stage_percentages: list[int] | None = None
    max_per_stage: int | None = Field(default=None, ge=1)
    status_filter: str | None = None


class HardeningRequest(BaseModel):
    device_id: str


class HardeningResponse(BaseModel):
    status: str
    missing_controls: list[str]


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
    return os.getenv("FLEET_REQUIRE_ADMIN", default) == "1"


def _fleet_api_key() -> str | None:
    return os.getenv("FLEET_API_KEY") or os.getenv("QUERY_API_KEY")


def _authorize(request: Request) -> AuthContext | None:
    raw_key = request.headers.get("x-api-key")
    try:
        context = authorize_api_key(
            base_uri=_get_config().graph_root_uri(),
            raw_key=raw_key,
            fallback_key=_fleet_api_key(),
            require=_api_key_required(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    if _require_admin() and (context is None or not context.is_admin):
        raise HTTPException(status_code=403, detail="Forbidden")
    return context


def _get_config():
    return get_config()


def _device_response(device: DeviceRecord) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        org_id=device.org_id,
        site_id=device.site_id,
        stream_id=device.stream_id,
        tags=list(device.tags) if device.tags else None,
        status=device.status,
        firmware_version=device.firmware_version,
        last_seen_at=device.last_seen_at,
        metadata=device.metadata,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def _filtered_devices(
    devices: list[DeviceRecord],
    status_filter: str | None,
) -> list[DeviceRecord]:
    if not status_filter:
        return devices
    desired = status_filter.strip().lower()
    return [device for device in devices if device.status.lower() == desired]


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=os.getenv("RETIKON_VERSION", "dev"),
        commit=os.getenv("GIT_COMMIT", "unknown"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.get("/fleet/devices", response_model=list[DeviceResponse])
async def list_devices(request: Request) -> list[DeviceResponse]:
    _authorize(request)
    devices = load_devices(_get_config().graph_root_uri())
    return [_device_response(device) for device in devices]


@app.post("/fleet/devices", response_model=DeviceResponse, status_code=201)
async def create_device(
    request: Request,
    payload: DeviceCreateRequest,
) -> DeviceResponse:
    _authorize(request)
    device = register_device(
        base_uri=_get_config().graph_root_uri(),
        name=payload.name,
        org_id=payload.org_id,
        site_id=payload.site_id,
        stream_id=payload.stream_id,
        tags=payload.tags,
        status=payload.status,
        firmware_version=payload.firmware_version,
        last_seen_at=payload.last_seen_at,
        metadata=payload.metadata,
    )
    logger.info(
        "Device registered",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.headers.get("x-correlation-id"),
            "device_id": device.id,
        },
    )
    return _device_response(device)


@app.put("/fleet/devices/{device_id}/status", response_model=DeviceResponse)
async def update_status(
    request: Request,
    device_id: str,
    payload: DeviceStatusRequest,
) -> DeviceResponse:
    _authorize(request)
    updated = update_device_status(
        base_uri=_get_config().graph_root_uri(),
        device_id=device_id,
        status=payload.status,
        last_seen_at=payload.last_seen_at,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return _device_response(updated)


@app.post("/fleet/rollouts/plan", response_model=RolloutResponse)
async def plan_rollouts(
    request: Request,
    payload: RolloutRequest,
) -> RolloutResponse:
    _authorize(request)
    devices = load_devices(_get_config().graph_root_uri())
    devices = _filtered_devices(devices, payload.status_filter)
    plan = plan_rollout(
        devices,
        stage_percentages=payload.stage_percentages,
        max_per_stage=payload.max_per_stage,
    )
    return RolloutResponse(
        total_devices=plan.total_devices,
        stages=[
            RolloutStageResponse(
                stage=stage.stage,
                percent=stage.percent,
                target_count=stage.target_count,
                device_ids=list(stage.device_ids),
            )
            for stage in plan.stages
        ],
    )


@app.post("/fleet/rollouts/rollback", response_model=RolloutResponse)
async def rollback_rollout(
    request: Request,
    payload: RollbackRequest,
) -> RolloutResponse:
    _authorize(request)
    devices = load_devices(_get_config().graph_root_uri())
    devices = _filtered_devices(devices, payload.status_filter)
    plan = plan_rollout(
        devices,
        stage_percentages=payload.stage_percentages,
        max_per_stage=payload.max_per_stage,
    )
    rollback_ids = rollback_plan(plan, stage=payload.stage)
    return RolloutResponse(
        total_devices=len(rollback_ids),
        stages=[
            RolloutStageResponse(
                stage=payload.stage,
                percent=0,
                target_count=len(rollback_ids),
                device_ids=list(rollback_ids),
            )
        ],
    )


@app.post("/fleet/security/check", response_model=HardeningResponse)
async def hardening_check(
    request: Request,
    payload: HardeningRequest,
) -> HardeningResponse:
    _authorize(request)
    devices = load_devices(_get_config().graph_root_uri())
    match = next((device for device in devices if device.id == payload.device_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Device not found")
    result = device_hardening(match)
    return HardeningResponse(
        status=result.status,
        missing_controls=list(result.missing_controls),
    )
