from __future__ import annotations

from typing import Any

from retikon_core.errors import ValidationError
from retikon_core.ingestion.storage_event import StorageEvent


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_cloudevent(payload: dict[str, Any]) -> StorageEvent:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValidationError("CloudEvent data is required")

    bucket = data.get("bucket")
    name = data.get("name")
    generation = data.get("generation")

    if not bucket or not name or not generation:
        raise ValidationError("CloudEvent data missing bucket, name, or generation")

    return StorageEvent(
        bucket=bucket,
        name=name,
        generation=str(generation),
        content_type=data.get("contentType"),
        size=_coerce_int(data.get("size")),
        md5_hash=data.get("md5Hash"),
        crc32c=data.get("crc32c"),
    )
