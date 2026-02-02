from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from google.cloud import firestore

from retikon_core.logging import get_logger
from retikon_core.metering import record_usage as record_usage_parquet
from retikon_core.storage.writer import WriteResult
from retikon_core.tenancy.types import TenantScope

logger = get_logger(__name__)


def _metering_firestore_enabled() -> bool:
    return os.getenv("METERING_FIRESTORE_ENABLED", "0") == "1"


def _collection_prefix() -> str:
    prefix = os.getenv("METERING_COLLECTION_PREFIX")
    if prefix is None:
        prefix = os.getenv("CONTROL_PLANE_COLLECTION_PREFIX", "")
    return prefix.strip()


def _collection_name() -> str:
    name = os.getenv("METERING_FIRESTORE_COLLECTION", "usage_events").strip()
    return name or "usage_events"


def _collection(client: firestore.Client) -> firestore.CollectionReference:
    prefix = _collection_prefix()
    name = _collection_name()
    if prefix:
        return client.collection(f"{prefix}{name}")
    return client.collection(name)


def _build_usage_payload(
    *,
    event_id: str,
    event_type: str,
    scope: TenantScope | None,
    api_key_id: str | None,
    modality: str | None,
    units: int | None,
    bytes_in: int | None,
    response_time_ms: int | None,
    tokens: int | None,
    pipeline_version: str,
    schema_version: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    token_value = tokens if tokens is not None else units
    payload: dict[str, object] = {
        "id": event_id,
        "org_id": scope.org_id if scope else None,
        "site_id": scope.site_id if scope else None,
        "stream_id": scope.stream_id if scope else None,
        "api_key_id": api_key_id,
        "event_type": event_type,
        "request_type": event_type,
        "modality": modality,
        "tokens": token_value,
        "bytes": bytes_in,
        "response_time": response_time_ms,
        "created_at": created_at.isoformat(),
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
    }
    return payload


def _write_firestore_event(payload: dict[str, object]) -> None:
    client = firestore.Client()
    collection = _collection(client)
    doc_id = str(payload.get("id") or uuid.uuid4())
    payload["id"] = doc_id
    collection.document(doc_id).set(payload)


def record_usage(
    *,
    base_uri: str,
    event_type: str,
    scope: TenantScope | None,
    api_key_id: str | None,
    modality: str | None,
    units: int | None,
    bytes_in: int | None,
    pipeline_version: str,
    schema_version: str,
    response_time_ms: int | None = None,
    tokens: int | None = None,
) -> WriteResult:
    result = record_usage_parquet(
        base_uri=base_uri,
        event_type=event_type,
        scope=scope,
        api_key_id=api_key_id,
        modality=modality,
        units=units,
        bytes_in=bytes_in,
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    if not _metering_firestore_enabled():
        return result
    event_id = str(uuid.uuid4())
    payload = _build_usage_payload(
        event_id=event_id,
        event_type=event_type,
        scope=scope,
        api_key_id=api_key_id,
        modality=modality,
        units=units,
        bytes_in=bytes_in,
        response_time_ms=response_time_ms,
        tokens=tokens,
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    try:
        _write_firestore_event(payload)
    except Exception as exc:
        logger.warning(
            "Failed to record usage to Firestore",
            extra={"error_message": str(exc)},
        )
    return result


def build_usage_payload_for_test(
    *,
    event_type: str,
    scope: TenantScope | None,
    api_key_id: str | None,
    modality: str | None,
    units: int | None,
    bytes_in: int | None,
    response_time_ms: int | None,
    tokens: int | None,
    pipeline_version: str,
    schema_version: str,
) -> dict[str, object]:
    event_id = str(uuid.uuid4())
    return _build_usage_payload(
        event_id=event_id,
        event_type=event_type,
        scope=scope,
        api_key_id=api_key_id,
        modality=modality,
        units=units,
        bytes_in=bytes_in,
        response_time_ms=response_time_ms,
        tokens=tokens,
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
