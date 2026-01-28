from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceRecord:
    id: str
    name: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    tags: tuple[str, ...] | None
    status: str
    firmware_version: str | None
    last_seen_at: str | None
    metadata: dict[str, object] | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RolloutStage:
    stage: int
    percent: int
    target_count: int
    device_ids: tuple[str, ...]


@dataclass(frozen=True)
class RolloutPlan:
    total_devices: int
    stages: tuple[RolloutStage, ...]


@dataclass(frozen=True)
class HardeningResult:
    status: str
    missing_controls: tuple[str, ...]
    details: dict[str, object] | None = None
