from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.storage.paths import join_uri
from retikon_core.workflows.types import WorkflowRun, WorkflowSpec, WorkflowStep


def workflow_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "workflows.json")


def workflow_runs_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "workflow_runs.json")


def load_workflows(base_uri: str) -> list[WorkflowSpec]:
    uri = workflow_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("workflows", []) if isinstance(payload, dict) else []
    results: list[WorkflowSpec] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_workflow_from_dict(item))
    return results


def save_workflows(base_uri: str, workflows: Iterable[WorkflowSpec]) -> str:
    uri = workflow_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "workflows": [asdict(workflow) for workflow in workflows],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_workflow(
    *,
    base_uri: str,
    name: str,
    description: str | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    schedule: str | None = None,
    enabled: bool = True,
    steps: Iterable[WorkflowStep] | None = None,
    status: str = "active",
) -> WorkflowSpec:
    now = datetime.now(timezone.utc).isoformat()
    workflow = WorkflowSpec(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        schedule=schedule,
        enabled=enabled,
        steps=tuple(steps) if steps else (),
        created_at=now,
        updated_at=now,
        status=status,
    )
    workflows = load_workflows(base_uri)
    workflows.append(workflow)
    save_workflows(base_uri, workflows)
    return workflow


def update_workflow(*, base_uri: str, workflow: WorkflowSpec) -> WorkflowSpec:
    workflows = load_workflows(base_uri)
    updated: list[WorkflowSpec] = []
    for existing in workflows:
        if existing.id == workflow.id:
            updated.append(workflow)
        else:
            updated.append(existing)
    save_workflows(base_uri, updated)
    return workflow


def load_workflow_runs(base_uri: str) -> list[WorkflowRun]:
    uri = workflow_runs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("runs", []) if isinstance(payload, dict) else []
    results: list[WorkflowRun] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_run_from_dict(item))
    return results


def save_workflow_runs(base_uri: str, runs: Iterable[WorkflowRun]) -> str:
    uri = workflow_runs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runs": [asdict(run) for run in runs],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_workflow_run(
    *,
    base_uri: str,
    workflow_id: str,
    status: str = "queued",
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
    output: dict[str, object] | None = None,
    triggered_by: str | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
) -> WorkflowRun:
    now = datetime.now(timezone.utc).isoformat()
    if org_id is None and site_id is None and stream_id is None:
        existing = _find_workflow(base_uri, workflow_id)
        if existing is not None:
            org_id = existing.org_id
            site_id = existing.site_id
            stream_id = existing.stream_id
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        status=status,
        started_at=started_at or now,
        finished_at=finished_at,
        error=error,
        output=output,
        triggered_by=triggered_by,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        created_at=now,
        updated_at=now,
    )
    runs = load_workflow_runs(base_uri)
    runs.append(run)
    save_workflow_runs(base_uri, runs)
    return run


def _find_workflow(base_uri: str, workflow_id: str) -> WorkflowSpec | None:
    workflows = load_workflows(base_uri)
    return next((workflow for workflow in workflows if workflow.id == workflow_id), None)


def update_workflow_run(*, base_uri: str, run: WorkflowRun) -> WorkflowRun:
    runs = load_workflow_runs(base_uri)
    updated: list[WorkflowRun] = []
    found = False
    for existing in runs:
        if existing.id == run.id:
            updated.append(run)
            found = True
        else:
            updated.append(existing)
    if not found:
        updated.append(run)
    save_workflow_runs(base_uri, updated)
    return run


def list_workflow_runs(
    base_uri: str,
    *,
    workflow_id: str | None = None,
    limit: int | None = None,
) -> list[WorkflowRun]:
    runs = load_workflow_runs(base_uri)
    if workflow_id:
        runs = [run for run in runs if run.workflow_id == workflow_id]
    if limit is not None:
        runs = runs[-limit:]
    return runs


def _workflow_from_dict(payload: dict[str, object]) -> WorkflowSpec:
    steps = _normalize_steps(payload.get("steps"))
    return WorkflowSpec(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        description=_coerce_optional_str(payload.get("description")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        schedule=_coerce_optional_str(payload.get("schedule")),
        enabled=bool(payload.get("enabled", True)),
        steps=steps,
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        status=str(payload.get("status", "active")),
    )


def _run_from_dict(payload: dict[str, object]) -> WorkflowRun:
    return WorkflowRun(
        id=str(payload.get("id")),
        workflow_id=str(payload.get("workflow_id", "")),
        status=str(payload.get("status", "queued")),
        started_at=str(payload.get("started_at", "")),
        finished_at=_coerce_optional_str(payload.get("finished_at")),
        error=_coerce_optional_str(payload.get("error")),
        output=_coerce_dict(payload.get("output")),
        triggered_by=_coerce_optional_str(payload.get("triggered_by")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )


def _normalize_steps(value: object) -> tuple[WorkflowStep, ...]:
    if not isinstance(value, list):
        return ()
    steps: list[WorkflowStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        steps.append(_step_from_dict(item))
    return tuple(steps)


def _step_from_dict(payload: dict[str, object]) -> WorkflowStep:
    return WorkflowStep(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        kind=str(payload.get("kind", "")),
        config=_coerce_dict(payload.get("config")),
        retries=_coerce_int(payload.get("retries")),
        timeout_seconds=_coerce_int(payload.get("timeout_seconds")),
    )


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
