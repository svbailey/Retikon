from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

import fsspec

from retikon_core.queue import QueuePublisher
from retikon_core.storage.paths import join_uri


@dataclass(frozen=True)
class TrainingSpec:
    dataset_id: str
    model_id: str
    epochs: int
    batch_size: int
    learning_rate: float
    labels: tuple[str, ...] | None


@dataclass(frozen=True)
class TrainingJob:
    id: str
    spec: TrainingSpec
    status: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    output: dict[str, object] | None
    metrics: dict[str, object] | None
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None


@dataclass(frozen=True)
class TrainingResult:
    status: str
    output: dict[str, object] | None = None
    metrics: dict[str, object] | None = None
    error: str | None = None


class TrainingExecutor(Protocol):
    def execute(self, *, job: TrainingJob) -> TrainingResult: ...


def training_jobs_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "training_jobs.json")


def load_training_jobs(base_uri: str) -> list[TrainingJob]:
    uri = training_jobs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("jobs", []) if isinstance(payload, dict) else []
    results: list[TrainingJob] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_job_from_dict(item))
    return results


def save_training_jobs(base_uri: str, jobs: Iterable[TrainingJob]) -> str:
    uri = training_jobs_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": [asdict(job) for job in jobs],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def create_training_job(
    *,
    dataset_id: str,
    model_id: str,
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    labels: Iterable[str] | None = None,
    status: str = "planned",
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
    output: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
) -> TrainingJob:
    now = datetime.now(timezone.utc).isoformat()
    spec = TrainingSpec(
        dataset_id=dataset_id,
        model_id=model_id,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        labels=_normalize_labels(labels),
    )
    return TrainingJob(
        id=str(uuid.uuid4()),
        spec=spec,
        status=status,
        created_at=now,
        updated_at=now,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        output=output,
        metrics=metrics,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
    )


def register_training_job(
    *,
    base_uri: str,
    dataset_id: str,
    model_id: str,
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    labels: Iterable[str] | None = None,
    status: str = "queued",
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
) -> TrainingJob:
    job = create_training_job(
        dataset_id=dataset_id,
        model_id=model_id,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        labels=labels,
        status=status,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
    )
    jobs = load_training_jobs(base_uri)
    jobs.append(job)
    save_training_jobs(base_uri, jobs)
    return job


def update_training_job(*, base_uri: str, job: TrainingJob) -> TrainingJob:
    jobs = load_training_jobs(base_uri)
    updated: list[TrainingJob] = []
    found = False
    for existing in jobs:
        if existing.id == job.id:
            updated.append(job)
            found = True
        else:
            updated.append(existing)
    if not found:
        updated.append(job)
    save_training_jobs(base_uri, updated)
    return job


def get_training_job(base_uri: str, job_id: str) -> TrainingJob | None:
    jobs = load_training_jobs(base_uri)
    return next((job for job in jobs if job.id == job_id), None)


def list_training_jobs(
    base_uri: str,
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[TrainingJob]:
    jobs = load_training_jobs(base_uri)
    if status:
        jobs = [job for job in jobs if job.status == status]
    if limit is not None:
        jobs = jobs[-limit:]
    return jobs


def mark_training_job_running(*, base_uri: str, job_id: str) -> TrainingJob:
    return _update_training_job(
        base_uri=base_uri,
        job_id=job_id,
        status="running",
        started_at=_now_iso(),
    )


def mark_training_job_completed(
    *,
    base_uri: str,
    job_id: str,
    output: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
) -> TrainingJob:
    return _update_training_job(
        base_uri=base_uri,
        job_id=job_id,
        status="completed",
        finished_at=_now_iso(),
        output=output,
        metrics=metrics,
    )


def mark_training_job_failed(
    *,
    base_uri: str,
    job_id: str,
    error: str,
) -> TrainingJob:
    return _update_training_job(
        base_uri=base_uri,
        job_id=job_id,
        status="failed",
        finished_at=_now_iso(),
        error=error,
    )


def mark_training_job_canceled(
    *,
    base_uri: str,
    job_id: str,
    reason: str | None = None,
) -> TrainingJob:
    return _update_training_job(
        base_uri=base_uri,
        job_id=job_id,
        status="canceled",
        finished_at=_now_iso(),
        error=reason,
    )


def execute_training_job(
    *,
    base_uri: str,
    job_id: str,
    executor: TrainingExecutor,
) -> TrainingJob:
    job = get_training_job(base_uri, job_id)
    if job is None:
        raise ValueError("Training job not found")
    running = mark_training_job_running(base_uri=base_uri, job_id=job_id)
    result = executor.execute(job=running)
    status = result.status.lower().strip()
    if status == "completed":
        return mark_training_job_completed(
            base_uri=base_uri,
            job_id=job_id,
            output=result.output,
            metrics=result.metrics,
        )
    if status == "canceled":
        return mark_training_job_canceled(
            base_uri=base_uri,
            job_id=job_id,
            reason=result.error,
        )
    error = result.error or "Training job failed"
    return mark_training_job_failed(
        base_uri=base_uri,
        job_id=job_id,
        error=error,
    )


def enqueue_training_job(
    *,
    publisher: QueuePublisher,
    topic: str,
    job: TrainingJob,
) -> str:
    payload = {"job_id": job.id}
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    return publisher.publish(topic=topic, data=data)


def _normalize_labels(labels: Iterable[object] | None) -> tuple[str, ...] | None:
    if not labels:
        return None
    cleaned = [str(label).strip() for label in labels if str(label).strip()]
    if not cleaned:
        return None
    deduped: list[str] = []
    for label in cleaned:
        if label not in deduped:
            deduped.append(label)
    return tuple(deduped)


def _job_from_dict(payload: dict[str, object]) -> TrainingJob:
    spec = payload.get("spec")
    return TrainingJob(
        id=str(payload.get("id")),
        spec=_spec_from_dict(spec if isinstance(spec, dict) else {}),
        status=str(payload.get("status", "queued")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        started_at=_coerce_optional_str(payload.get("started_at")),
        finished_at=_coerce_optional_str(payload.get("finished_at")),
        error=_coerce_optional_str(payload.get("error")),
        output=_coerce_dict(payload.get("output")),
        metrics=_coerce_dict(payload.get("metrics")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
    )


def _spec_from_dict(payload: dict[str, object]) -> TrainingSpec:
    return TrainingSpec(
        dataset_id=str(payload.get("dataset_id", "")),
        model_id=str(payload.get("model_id", "")),
        epochs=_coerce_int(payload.get("epochs")),
        batch_size=_coerce_int(payload.get("batch_size")),
        learning_rate=_coerce_float(payload.get("learning_rate")),
        labels=_normalize_labels(_coerce_iterable(payload.get("labels"))),
    )


def _coerce_iterable(value: object) -> Iterable[object] | None:
    if isinstance(value, (list, tuple, set)):
        return value
    return None


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _update_training_job(
    *,
    status: str,
    base_uri: str | None = None,
    job_id: str | None = None,
    job: TrainingJob | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
    output: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
) -> TrainingJob:
    if job is None:
        if base_uri is None or job_id is None:
            raise ValueError("Training job reference is required")
        job = get_training_job(base_uri, job_id)
        if job is None:
            raise ValueError("Training job not found")
    now = _now_iso()
    updated = TrainingJob(
        id=job.id,
        spec=job.spec,
        status=status,
        created_at=job.created_at,
        updated_at=now,
        started_at=started_at or job.started_at,
        finished_at=finished_at or job.finished_at,
        error=error if error is not None else job.error,
        output=output if output is not None else job.output,
        metrics=metrics if metrics is not None else job.metrics,
        org_id=job.org_id,
        site_id=job.site_id,
        stream_id=job.stream_id,
    )
    if base_uri is None:
        return updated
    return update_training_job(base_uri=base_uri, job=updated)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
