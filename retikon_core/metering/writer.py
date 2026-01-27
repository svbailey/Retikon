from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from retikon_core.metering.types import UsageEvent
from retikon_core.storage.paths import vertex_part_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet
from retikon_core.tenancy.types import TenantScope


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
) -> WriteResult:
    event = UsageEvent(
        id=str(uuid.uuid4()),
        org_id=scope.org_id if scope else None,
        site_id=scope.site_id if scope else None,
        stream_id=scope.stream_id if scope else None,
        api_key_id=api_key_id,
        event_type=event_type,
        modality=modality,
        units=units,
        bytes=bytes_in,
        created_at=datetime.now(timezone.utc),
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    schema = schema_for("UsageEvent", "core")
    dest_uri = vertex_part_uri(base_uri, "UsageEvent", "core", str(uuid.uuid4()))
    return write_parquet([asdict(event)], schema, dest_uri)
