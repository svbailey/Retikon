from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UsageEvent:
    id: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    api_key_id: str | None
    event_type: str
    modality: str | None
    units: int | None
    bytes: int | None
    created_at: datetime
    pipeline_version: str
    schema_version: str
