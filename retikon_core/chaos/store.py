from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.chaos.types import ChaosPolicy, ChaosRun, ChaosStep
from retikon_core.storage.paths import join_uri

_SAFE_STEP_KINDS: tuple[str, ...] = (
    "delay",
    "drop_percent",
    "retry_jitter",
    "rate_limit",
)


def chaos_policy_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "chaos_policies.json")


def chaos_runs_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "chaos_runs.json")


def chaos_enabled() -> bool:
    return os.getenv("CHAOS_ENABLED", "0") == "1"


def allowed_step_kinds() -> tuple[str, ...]:
    override = os.getenv("CHAOS_ALLOWED_STEPS")
    if override:
        items = [item.strip().lower() for item in override.split(",")]
        cleaned = [item for item in items if item]
        if cleaned:
            return tuple(cleaned)
    return _SAFE_STEP_KINDS


def max_percent_impact_limit() -> int:
    return int(os.getenv("CHAOS_MAX_PERCENT_IMPACT", "10"))


def max_duration_limit_minutes() -> int:
    return int(os.getenv("CHAOS_MAX_DURATION_MINUTES", "30"))


def load_chaos_policies(base_uri: str) -> list[ChaosPolicy]:
    uri = chaos_policy_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("policies", []) if isinstance(payload, dict) else []
    results: list[ChaosPolicy] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_policy_from_dict(item))
    return results


def save_chaos_policies(base_uri: str, policies: Iterable[ChaosPolicy]) -> str:
    uri = chaos_policy_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policies": [asdict(policy) for policy in policies],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_chaos_policy(
    *,
    base_uri: str,
    name: str,
    description: str | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    schedule: str | None = None,
    enabled: bool = True,
    max_duration_minutes: int | None = None,
    max_percent_impact: int | None = None,
    steps: Iterable[ChaosStep] | None = None,
) -> ChaosPolicy:
    now = datetime.now(timezone.utc).isoformat()
    policy = ChaosPolicy(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        schedule=schedule,
        enabled=enabled,
        max_duration_minutes=max_duration_minutes or max_duration_limit_minutes(),
        max_percent_impact=max_percent_impact or max_percent_impact_limit(),
        steps=tuple(steps) if steps else (),
        created_at=now,
        updated_at=now,
    )
    _validate_policy(policy)
    policies = load_chaos_policies(base_uri)
    policies.append(policy)
    save_chaos_policies(base_uri, policies)
    return policy


def update_chaos_policy(*, base_uri: str, policy: ChaosPolicy) -> ChaosPolicy:
    _validate_policy(policy)
    policies = load_chaos_policies(base_uri)
    updated: list[ChaosPolicy] = []
    for existing in policies:
        if existing.id == policy.id:
            updated.append(policy)
        else:
            updated.append(existing)
    save_chaos_policies(base_uri, updated)
    return policy


def load_chaos_runs(base_uri: str) -> list[ChaosRun]:
    uri = chaos_runs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("runs", []) if isinstance(payload, dict) else []
    results: list[ChaosRun] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_run_from_dict(item))
    return results


def save_chaos_runs(base_uri: str, runs: Iterable[ChaosRun]) -> str:
    uri = chaos_runs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runs": [asdict(run) for run in runs],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_chaos_run(
    *,
    base_uri: str,
    policy_id: str,
    status: str = "queued",
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
    summary: dict[str, object] | None = None,
    triggered_by: str | None = None,
) -> ChaosRun:
    now = datetime.now(timezone.utc).isoformat()
    run = ChaosRun(
        id=str(uuid.uuid4()),
        policy_id=policy_id,
        status=status,
        started_at=started_at or now,
        finished_at=finished_at,
        error=error,
        summary=summary,
        triggered_by=triggered_by,
    )
    runs = load_chaos_runs(base_uri)
    runs.append(run)
    save_chaos_runs(base_uri, runs)
    return run


def list_chaos_runs(
    base_uri: str,
    *,
    policy_id: str | None = None,
    limit: int | None = None,
) -> list[ChaosRun]:
    runs = load_chaos_runs(base_uri)
    if policy_id:
        runs = [run for run in runs if run.policy_id == policy_id]
    if limit is not None:
        runs = runs[-limit:]
    return runs


def filter_policies_by_scope(
    policies: Iterable[ChaosPolicy],
    *,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
) -> list[ChaosPolicy]:
    results = []
    for policy in policies:
        if policy.org_id and org_id and policy.org_id != org_id:
            continue
        if policy.site_id and site_id and policy.site_id != site_id:
            continue
        if policy.stream_id and stream_id and policy.stream_id != stream_id:
            continue
        results.append(policy)
    return results


def _validate_policy(policy: ChaosPolicy) -> None:
    errors: list[str] = []
    allowed = allowed_step_kinds()
    max_percent_limit = max_percent_impact_limit()
    max_duration_limit = max_duration_limit_minutes()

    if policy.max_percent_impact > max_percent_limit:
        errors.append(
            "max_percent_impact exceeds limit "
            f"({policy.max_percent_impact} > {max_percent_limit})"
        )
    if policy.max_duration_minutes > max_duration_limit:
        errors.append(
            "max_duration_minutes exceeds limit "
            f"({policy.max_duration_minutes} > {max_duration_limit})"
        )

    for step in policy.steps:
        if step.kind not in allowed:
            errors.append(f"unsupported step kind: {step.kind}")
        if step.percent is not None:
            if step.percent < 0 or step.percent > 100:
                errors.append(f"step percent out of range: {step.percent}")
            if step.percent > policy.max_percent_impact:
                errors.append(
                    "step percent exceeds policy max "
                    f"({step.percent} > {policy.max_percent_impact})"
                )
        if step.duration_seconds is not None:
            max_duration_seconds = policy.max_duration_minutes * 60
            if step.duration_seconds > max_duration_seconds:
                errors.append(
                    "step duration exceeds policy max "
                    f"({step.duration_seconds} > {max_duration_seconds})"
                )

    if errors:
        raise ValueError("; ".join(errors))


def _policy_from_dict(payload: dict[str, object]) -> ChaosPolicy:
    return ChaosPolicy(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        description=_coerce_optional_str(payload.get("description")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        schedule=_coerce_optional_str(payload.get("schedule")),
        enabled=bool(payload.get("enabled", True)),
        max_duration_minutes=_coerce_int(payload.get("max_duration_minutes"))
        or max_duration_limit_minutes(),
        max_percent_impact=_coerce_int(payload.get("max_percent_impact"))
        or max_percent_impact_limit(),
        steps=_normalize_steps(payload.get("steps")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )


def _run_from_dict(payload: dict[str, object]) -> ChaosRun:
    return ChaosRun(
        id=str(payload.get("id")),
        policy_id=str(payload.get("policy_id", "")),
        status=str(payload.get("status", "queued")),
        started_at=str(payload.get("started_at", "")),
        finished_at=_coerce_optional_str(payload.get("finished_at")),
        error=_coerce_optional_str(payload.get("error")),
        summary=_coerce_dict(payload.get("summary")),
        triggered_by=_coerce_optional_str(payload.get("triggered_by")),
    )


def _normalize_steps(value: object) -> tuple[ChaosStep, ...]:
    if not isinstance(value, list):
        return ()
    steps: list[ChaosStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        steps.append(_step_from_dict(item))
    return tuple(steps)


def _step_from_dict(payload: dict[str, object]) -> ChaosStep:
    return ChaosStep(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        kind=str(payload.get("kind", "")),
        target=_coerce_optional_str(payload.get("target")),
        percent=_coerce_int(payload.get("percent")),
        duration_seconds=_coerce_int(payload.get("duration_seconds")),
        jitter_ms=_coerce_int(payload.get("jitter_ms")),
        metadata=_coerce_dict(payload.get("metadata")),
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
