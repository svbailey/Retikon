from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retikon_core.workflows import (
    list_workflow_runs,
    load_workflows,
    register_workflow,
    register_workflow_run,
    update_workflow,
)
from retikon_core.workflows.types import WorkflowSpec, WorkflowStep


@pytest.mark.core
def test_workflow_roundtrip(tmp_path):
    step = WorkflowStep(
        id="step-1",
        name="Export",
        kind="export",
        config={"target": "s3"},
        retries=2,
        timeout_seconds=300,
    )
    workflow = register_workflow(
        base_uri=tmp_path.as_posix(),
        name="Daily export",
        description="Ship to data lake",
        schedule="0 2 * * *",
        steps=[step],
    )
    loaded = load_workflows(tmp_path.as_posix())
    assert loaded
    assert loaded[0].id == workflow.id
    assert loaded[0].steps[0].kind == "export"


@pytest.mark.core
def test_workflow_update(tmp_path):
    workflow = register_workflow(
        base_uri=tmp_path.as_posix(),
        name="Initial",
        steps=[],
    )
    updated = WorkflowSpec(
        id=workflow.id,
        name="Updated",
        description=workflow.description,
        org_id=workflow.org_id,
        site_id=workflow.site_id,
        stream_id=workflow.stream_id,
        schedule=workflow.schedule,
        enabled=workflow.enabled,
        steps=workflow.steps,
        created_at=workflow.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    update_workflow(base_uri=tmp_path.as_posix(), workflow=updated)
    loaded = load_workflows(tmp_path.as_posix())
    assert loaded[0].name == "Updated"


@pytest.mark.core
def test_workflow_runs(tmp_path):
    workflow = register_workflow(
        base_uri=tmp_path.as_posix(),
        name="Job",
        steps=[],
    )
    run = register_workflow_run(
        base_uri=tmp_path.as_posix(),
        workflow_id=workflow.id,
        status="running",
    )
    runs = list_workflow_runs(tmp_path.as_posix())
    assert runs
    assert runs[0].id == run.id
    assert runs[0].workflow_id == workflow.id
