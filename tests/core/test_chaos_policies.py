from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retikon_core.chaos import (
    ChaosPolicy,
    ChaosStep,
    filter_policies_by_scope,
    list_chaos_runs,
    load_chaos_policies,
    register_chaos_policy,
    register_chaos_run,
    update_chaos_policy,
)


@pytest.mark.core
def test_chaos_policy_roundtrip(tmp_path):
    step = ChaosStep(
        id="step-1",
        name="Delay",
        kind="delay",
        target="query",
        percent=5,
        duration_seconds=60,
        jitter_ms=100,
        metadata=None,
    )
    policy = register_chaos_policy(
        base_uri=tmp_path.as_posix(),
        name="Delay queries",
        steps=[step],
    )
    loaded = load_chaos_policies(tmp_path.as_posix())
    assert loaded
    assert loaded[0].id == policy.id
    assert loaded[0].steps[0].kind == "delay"


@pytest.mark.core
def test_chaos_policy_update(tmp_path):
    policy = register_chaos_policy(
        base_uri=tmp_path.as_posix(),
        name="Initial",
        steps=[],
    )
    updated = ChaosPolicy(
        id=policy.id,
        name="Updated",
        description=policy.description,
        org_id=policy.org_id,
        site_id=policy.site_id,
        stream_id=policy.stream_id,
        schedule=policy.schedule,
        enabled=policy.enabled,
        max_duration_minutes=policy.max_duration_minutes,
        max_percent_impact=policy.max_percent_impact,
        steps=policy.steps,
        created_at=policy.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    update_chaos_policy(base_uri=tmp_path.as_posix(), policy=updated)
    loaded = load_chaos_policies(tmp_path.as_posix())
    assert loaded[0].name == "Updated"


@pytest.mark.core
def test_chaos_policy_guardrails(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAOS_MAX_PERCENT_IMPACT", "10")
    step = ChaosStep(
        id="step-2",
        name="Drop",
        kind="drop_percent",
        target="ingest",
        percent=20,
        duration_seconds=10,
        jitter_ms=None,
        metadata=None,
    )
    with pytest.raises(ValueError):
        register_chaos_policy(
            base_uri=tmp_path.as_posix(),
            name="Too much",
            steps=[step],
        )


@pytest.mark.core
def test_chaos_runs_roundtrip(tmp_path):
    policy = register_chaos_policy(
        base_uri=tmp_path.as_posix(),
        name="Run",
        steps=[],
    )
    run = register_chaos_run(
        base_uri=tmp_path.as_posix(),
        policy_id=policy.id,
        status="queued",
    )
    runs = list_chaos_runs(tmp_path.as_posix(), policy_id=policy.id)
    assert runs
    assert runs[0].id == run.id


@pytest.mark.core
def test_chaos_scope_filter(tmp_path):
    register_chaos_policy(
        base_uri=tmp_path.as_posix(),
        name="Org",
        org_id="org-1",
        steps=[],
    )
    register_chaos_policy(
        base_uri=tmp_path.as_posix(),
        name="Site",
        org_id="org-1",
        site_id="site-1",
        steps=[],
    )
    policies = load_chaos_policies(tmp_path.as_posix())
    scoped = filter_policies_by_scope(
        policies,
        org_id="org-1",
        site_id="site-1",
    )
    assert len(scoped) == 2
