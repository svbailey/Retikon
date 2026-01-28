from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    name: str
    kind: str
    config: dict[str, object] | None
    retries: int | None
    timeout_seconds: int | None


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    description: str | None
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    schedule: str | None
    enabled: bool
    steps: tuple[WorkflowStep, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkflowRun:
    id: str
    workflow_id: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    output: dict[str, object] | None
    triggered_by: str | None
