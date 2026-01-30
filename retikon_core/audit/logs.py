from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from retikon_core.auth.types import AuthContext
from retikon_core.storage.paths import vertex_part_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet
from retikon_core.tenancy.types import TenantScope


@dataclass(frozen=True)
class AuditLogRecord:
    id: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    api_key_id: str | None
    actor_type: str | None
    actor_id: str | None
    action: str
    resource: str | None
    decision: str
    reason: str | None
    request_id: str | None
    created_at: datetime
    pipeline_version: str
    schema_version: str


def _resolve_scope(
    auth_context: AuthContext | None,
    scope: TenantScope | None,
) -> TenantScope | None:
    if scope is not None:
        return scope
    if auth_context is None:
        return None
    return auth_context.scope


def record_audit_log(
    *,
    base_uri: str,
    action: str,
    decision: str,
    pipeline_version: str,
    schema_version: str,
    auth_context: AuthContext | None = None,
    scope: TenantScope | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    resource: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    created_at: datetime | None = None,
) -> WriteResult:
    resolved_scope = _resolve_scope(auth_context, scope)
    if actor_type is None:
        actor_type = auth_context.actor_type if auth_context else "anonymous"
    if actor_id is None and auth_context is not None:
        actor_id = auth_context.actor_id or auth_context.api_key_id

    event = AuditLogRecord(
        id=str(uuid.uuid4()),
        org_id=resolved_scope.org_id if resolved_scope else None,
        site_id=resolved_scope.site_id if resolved_scope else None,
        stream_id=resolved_scope.stream_id if resolved_scope else None,
        api_key_id=auth_context.api_key_id if auth_context else None,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource=resource,
        decision=decision,
        reason=reason,
        request_id=request_id,
        created_at=created_at or datetime.now(timezone.utc),
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    schema = schema_for("AuditLog", "core")
    dest_uri = vertex_part_uri(base_uri, "AuditLog", "core", str(uuid.uuid4()))
    return write_parquet([asdict(event)], schema, dest_uri)
