from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.storage.paths import join_uri


def model_registry_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "model_registry.json")


@dataclass(frozen=True)
class ModelRecord:
    id: str
    name: str
    version: str
    description: str | None
    task: str | None
    framework: str | None
    tags: tuple[str, ...] | None
    metrics: dict[str, object] | None
    created_at: str
    updated_at: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    status: str = "active"


def load_models(base_uri: str) -> list[ModelRecord]:
    uri = model_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("models", []) if isinstance(payload, dict) else []
    results: list[ModelRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_model_from_dict(item))
    return results


def save_models(base_uri: str, models: Iterable[ModelRecord]) -> str:
    uri = model_registry_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "models": [asdict(model) for model in models],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_model(
    *,
    base_uri: str,
    name: str,
    version: str,
    description: str | None = None,
    task: str | None = None,
    framework: str | None = None,
    tags: Iterable[str] | None = None,
    metrics: dict[str, object] | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    status: str = "active",
) -> ModelRecord:
    now = datetime.now(timezone.utc).isoformat()
    model = ModelRecord(
        id=str(uuid.uuid4()),
        name=name,
        version=version,
        description=description,
        task=task,
        framework=framework,
        tags=_normalize_list(tags),
        metrics=metrics,
        created_at=now,
        updated_at=now,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        status=status,
    )
    models = load_models(base_uri)
    models.append(model)
    save_models(base_uri, models)
    return model


def update_model(base_uri: str, model: ModelRecord) -> ModelRecord:
    models = load_models(base_uri)
    updated: list[ModelRecord] = []
    for existing in models:
        if existing.id == model.id:
            updated.append(model)
        else:
            updated.append(existing)
    save_models(base_uri, updated)
    return model


def _normalize_list(items: Iterable[object] | None) -> tuple[str, ...] | None:
    if not items:
        return None
    cleaned = [str(item).strip().lower() for item in items if str(item).strip()]
    if not cleaned:
        return None
    deduped: list[str] = []
    for item in cleaned:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def _model_from_dict(payload: dict[str, object]) -> ModelRecord:
    return ModelRecord(
        id=str(payload.get("id")),
        name=str(payload.get("name", "")),
        version=str(payload.get("version", "")),
        description=_coerce_optional_str(payload.get("description")),
        task=_coerce_optional_str(payload.get("task")),
        framework=_coerce_optional_str(payload.get("framework")),
        tags=_normalize_list(_coerce_iterable(payload.get("tags"))),
        metrics=_coerce_metrics(payload.get("metrics")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        org_id=_coerce_optional_str(payload.get("org_id")),
        site_id=_coerce_optional_str(payload.get("site_id")),
        stream_id=_coerce_optional_str(payload.get("stream_id")),
        status=str(payload.get("status", "active")),
    )


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_iterable(value: object) -> Iterable[object] | None:
    if isinstance(value, (list, tuple, set)):
        return value
    return None


def _coerce_metrics(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}
