from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiKeyRecord:
    id: str
    name: str
    key_hash: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    status: str
    scopes: tuple[str, ...] | None
    last_used_at: str | None
    created_at: str
    updated_at: str
