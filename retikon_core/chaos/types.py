from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChaosStep:
    id: str
    name: str
    kind: str
    target: str | None
    percent: int | None
    duration_seconds: int | None
    jitter_ms: int | None
    metadata: dict[str, object] | None


@dataclass(frozen=True)
class ChaosPolicy:
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
    steps: tuple[ChaosStep, ...]
    created_at: str
    updated_at: str
    status: str = "active"


@dataclass(frozen=True)
class ChaosRun:
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
    created_at: str = ""
    updated_at: str = ""
