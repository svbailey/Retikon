from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


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


def create_training_job(
    *,
    dataset_id: str,
    model_id: str,
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    labels: Iterable[str] | None = None,
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
        status="planned",
        created_at=now,
        updated_at=now,
    )


def _normalize_labels(labels: Iterable[str] | None) -> tuple[str, ...] | None:
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
