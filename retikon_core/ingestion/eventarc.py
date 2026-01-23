from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from retikon_core.errors import ValidationError


@dataclass(frozen=True)
class GcsEvent:
    bucket: str
    name: str
    generation: str
    content_type: str | None
    size: int | None
    md5_hash: str | None
    crc32c: str | None

    @property
    def extension(self) -> str:
        if "." not in self.name:
            return ""
        return f".{self.name.rsplit('.', 1)[-1].lower()}"


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_cloudevent(payload: dict[str, Any]) -> GcsEvent:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValidationError("CloudEvent data is required")

    bucket = data.get("bucket")
    name = data.get("name")
    generation = data.get("generation")

    if not bucket or not name or not generation:
        raise ValidationError("CloudEvent data missing bucket, name, or generation")

    return GcsEvent(
        bucket=bucket,
        name=name,
        generation=str(generation),
        content_type=data.get("contentType"),
        size=_coerce_int(data.get("size")),
        md5_hash=data.get("md5Hash"),
        crc32c=data.get("crc32c"),
    )
