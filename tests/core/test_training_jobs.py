from __future__ import annotations

import pytest

from retikon_core.data_factory.training import (
    TrainingResult,
    execute_training_job,
    get_training_job,
    list_training_jobs,
    mark_training_job_completed,
    mark_training_job_failed,
    mark_training_job_running,
    register_training_job,
)


class _StubExecutor:
    def execute(self, *, job):
        return TrainingResult(
            status="completed",
            output={"ok": True},
            metrics={"loss": 0.1},
        )


@pytest.mark.core
def test_training_job_persistence(tmp_path):
    base_uri = tmp_path.as_posix()
    job = register_training_job(
        base_uri=base_uri,
        dataset_id="dataset-1",
        model_id="model-1",
        epochs=5,
        batch_size=8,
        learning_rate=1e-3,
        labels=["a", "b"],
    )
    assert job.status == "queued"
    jobs = list_training_jobs(base_uri)
    assert len(jobs) == 1
    assert jobs[0].spec.epochs == 5


@pytest.mark.core
def test_training_job_lifecycle_updates(tmp_path):
    base_uri = tmp_path.as_posix()
    job = register_training_job(
        base_uri=base_uri,
        dataset_id="dataset-2",
        model_id="model-2",
    )
    running = mark_training_job_running(base_uri=base_uri, job_id=job.id)
    assert running.status == "running"
    assert running.started_at is not None

    completed = mark_training_job_completed(
        base_uri=base_uri,
        job_id=job.id,
        output={"message": "done"},
        metrics={"accuracy": 0.95},
    )
    assert completed.status == "completed"
    assert completed.finished_at is not None
    assert completed.output == {"message": "done"}
    assert completed.metrics == {"accuracy": 0.95}


@pytest.mark.core
def test_training_job_execution(tmp_path):
    base_uri = tmp_path.as_posix()
    job = register_training_job(
        base_uri=base_uri,
        dataset_id="dataset-3",
        model_id="model-3",
    )
    updated = execute_training_job(
        base_uri=base_uri,
        job_id=job.id,
        executor=_StubExecutor(),
    )
    assert updated.status == "completed"
    assert updated.output == {"ok": True}


@pytest.mark.core
def test_training_job_failure(tmp_path):
    base_uri = tmp_path.as_posix()
    job = register_training_job(
        base_uri=base_uri,
        dataset_id="dataset-4",
        model_id="model-4",
    )
    failed = mark_training_job_failed(
        base_uri=base_uri,
        job_id=job.id,
        error="boom",
    )
    assert failed.status == "failed"
    assert failed.error == "boom"
    fetched = get_training_job(base_uri, job.id)
    assert fetched is not None
    assert fetched.status == "failed"
